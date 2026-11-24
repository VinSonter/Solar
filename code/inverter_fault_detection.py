"""
Inverter Fault Detection & Fix-First List
=========================================
Author: Vinayak Sonter

Question this answers:
    On a site with many inverters, which exact inverter should the field
    crew go to first, what is wrong with it, and what is it costing?

Method (peer comparison):
    Every inverter in a plant sits under the same sky. At each 15-minute
    reading, each inverter is compared with the median of the inverters
    in the same plant that are producing at that moment. A cloud lowers
    all of them together, so it is not flagged. One inverter dropping
    while its peers hold is flagged.

Fault types:
    Outage   - output is zero while peers are producing
    Derate   - output is below 75% of peers
    Chronic  - inverter runs steadily below peers over the whole period
    Data gap - inverter stopped reporting (loss unknown, so not priced)

Run from anywhere:
    python3 code/inverter_fault_detection.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Datasets"
OUT_DIR = ROOT / "processed"
PLOT_DIR = ROOT / "Output_Plots"

INTERVAL_HOURS = 0.25        # readings are every 15 minutes
PPA_RATE = 40                # $/MWh, assumed contract price
DAYLIGHT_MIN_KW = 50         # peers must be producing at least this much
MIN_PEERS = 5                # need this many producing peers for a baseline
OUTAGE_RATIO = 0.01          # at or below 1% of peers counts as zero
DERATE_RATIO = 0.75          # below 75% of peers counts as a derate
MIN_EVENT_INTERVALS = 2      # ignore blips shorter than 30 minutes
CHRONIC_RATIO = 0.95         # median output below 95% of peers = chronic
SHARED_OUTAGE_COUNT = 5      # this many down together suggests a shared cause


# ------------------------------------------------------------
# STEP 1: LOAD
# ------------------------------------------------------------
def load_generation():
    """AC_POWER in the source files is in kW. 15-min kW x 0.25 h = kWh."""
    g1 = pd.read_csv(DATA_DIR / "Plant_1_Generation_Data.csv")
    g2 = pd.read_csv(DATA_DIR / "Plant_2_Generation_Data.csv")
    g1["DATE_TIME"] = pd.to_datetime(g1["DATE_TIME"], format="%d-%m-%Y %H:%M")
    g2["DATE_TIME"] = pd.to_datetime(g2["DATE_TIME"])
    g1["PLANT"] = "Plant_1"
    g2["PLANT"] = "Plant_2"
    # Plant 1 DC_POWER is recorded 10x too high in the source file
    # (DC/AC is about 10.2 there and about 1.02 in Plant 2).
    g1["DC_POWER"] = g1["DC_POWER"] / 10
    return pd.concat([g1, g2], ignore_index=True)


# ------------------------------------------------------------
# STEP 2: PEER BASELINE AND STATE PER READING
# ------------------------------------------------------------
def classify_plant(gen, plant):
    """Return one row per inverter per daylight reading with its state."""
    ac = gen[gen["PLANT"] == plant].pivot_table(
        index="DATE_TIME", columns="SOURCE_KEY", values="AC_POWER"
    )
    producing = ac.where(ac > 0)
    baseline = producing.median(axis=1)
    n_producing = producing.notna().sum(axis=1)
    daylight = (baseline >= DAYLIGHT_MIN_KW) & (n_producing >= MIN_PEERS)

    ac = ac[daylight]
    baseline = baseline[daylight]
    ratio = ac.div(baseline, axis=0)

    state = pd.DataFrame("normal", index=ac.index, columns=ac.columns)
    state = state.mask(ratio < DERATE_RATIO, "derate")
    state = state.mask(ratio <= OUTAGE_RATIO, "outage")
    state = state.mask(ac.isna(), "gap")

    def melt(df, name):
        return df.reset_index().melt(
            id_vars="DATE_TIME", var_name="inverter", value_name=name
        )

    long = melt(ac, "ac_kw")
    long["ratio"] = melt(ratio, "ratio")["ratio"]
    long["state"] = melt(state, "state")["state"]
    long["baseline_kw"] = long["DATE_TIME"].map(baseline)
    long["plant"] = plant
    # daylight sequence number, so an event can run across a night
    seq = pd.Series(np.arange(len(ac.index)), index=ac.index)
    long["seq"] = long["DATE_TIME"].map(seq)
    down_together = (state == "outage").sum(axis=1)
    long["down_together"] = long["DATE_TIME"].map(down_together)
    return long


# ------------------------------------------------------------
# STEP 3: READINGS -> EVENTS
# ------------------------------------------------------------
def build_events(readings):
    """Group consecutive flagged readings into events."""
    r = readings.sort_values(["plant", "inverter", "seq"]).copy()
    new_run = (
        (r["state"] != r["state"].shift())
        | (r["inverter"] != r["inverter"].shift())
        | (r["seq"] != r["seq"].shift() + 1)
    )
    r["run_id"] = new_run.cumsum()
    r["shortfall_kwh"] = (
        (r["baseline_kw"] - r["ac_kw"].fillna(0)).clip(lower=0) * INTERVAL_HOURS
    )

    flagged = r[r["state"] != "normal"]
    events = flagged.groupby("run_id").agg(
        plant=("plant", "first"),
        inverter=("inverter", "first"),
        fault_type=("state", "first"),
        start=("DATE_TIME", "min"),
        end=("DATE_TIME", "max"),
        intervals=("seq", "size"),
        avg_pct_of_peers=("ratio", lambda x: 100 * x.mean()),
        lost_kwh=("shortfall_kwh", "sum"),
        peak_down_together=("down_together", "max"),
    ).reset_index(drop=True)

    events = events[events["intervals"] >= MIN_EVENT_INTERVALS].copy()
    events["daylight_hours"] = events["intervals"] * INTERVAL_HOURS
    events["lost_mwh"] = events["lost_kwh"] / 1000
    # a data gap has no measured output, so its loss is unknown, not zero
    is_gap = events["fault_type"] == "gap"
    events.loc[is_gap, ["lost_mwh", "avg_pct_of_peers"]] = np.nan
    events["lost_usd"] = events["lost_mwh"] * PPA_RATE
    last_reading = r.groupby("plant")["DATE_TIME"].max()
    events["ongoing_at_end"] = events["end"] == events["plant"].map(last_reading)
    events["shared_outage"] = (
        (events["fault_type"] == "outage")
        & (events["peak_down_together"] >= SHARED_OUTAGE_COUNT)
    )
    events["fault_type"] = events["fault_type"].replace({"gap": "data gap"})

    # keep the event id on each reading so chronic loss can skip event time
    kept = set(flagged.loc[flagged["run_id"].isin(
        flagged.groupby("run_id").size().loc[lambda s: s >= MIN_EVENT_INTERVALS].index
    ), "run_id"])
    r["in_event"] = r["run_id"].isin(kept)

    cols = ["plant", "inverter", "fault_type", "start", "end", "daylight_hours",
            "avg_pct_of_peers", "lost_mwh", "lost_usd", "peak_down_together",
            "shared_outage", "ongoing_at_end"]
    return events[cols].sort_values("lost_usd", ascending=False), r


# ------------------------------------------------------------
# STEP 4: FIX-FIRST LIST (one row per inverter)
# ------------------------------------------------------------
SUGGESTED_CHECK = {
    "outage": "Repeated zero output: pull the fault log, check breaker and grid-side trips",
    "derate": "Partial output: check for failed strings, blown fuses, or shading",
    "chronic": "Steadily below peers: check string currents, soiling, and module condition",
    "data gap": "Not reporting: check the logger and communications before sending a crew",
    "none": "No action",
}
SHARED_CHECK = ("Goes down together with 5+ other inverters: look upstream first "
                "(grid voltage trips, export limit, feeder or transformer)")


def build_priority(events, readings):
    rows = []
    for (plant, inv), r in readings.groupby(["plant", "inverter"]):
        ev = events[(events["plant"] == plant) & (events["inverter"] == inv)]
        by_type = ev.groupby("fault_type")

        def hours(t):
            return by_type.get_group(t)["daylight_hours"].sum() if t in by_type.groups else 0.0

        def mwh(t):
            return by_type.get_group(t)["lost_mwh"].sum() if t in by_type.groups else 0.0

        on = r[(r["ac_kw"] > 0) & (~r["in_event"])]
        pct_when_on = 100 * on["ratio"].median()
        # chronic loss = net shortfall while running, outside any event
        chronic_mwh = 0.0
        if pct_when_on < 100 * CHRONIC_RATIO:
            net = (on["baseline_kw"] - on["ac_kw"]).sum() * INTERVAL_HOURS / 1000
            chronic_mwh = max(net, 0.0)

        losses = {"outage": mwh("outage"), "derate": mwh("derate"), "chronic": chronic_mwh}
        total_mwh = sum(losses.values())
        if total_mwh > 0:
            primary = max(losses, key=losses.get)
        elif hours("data gap") > 0:
            primary = "data gap"
        else:
            primary = "none"

        reported = r[r["state"] != "gap"]
        outages = ev[ev["fault_type"] == "outage"]
        out_hours = outages["daylight_hours"].sum()
        shared_pct = (100 * outages.loc[outages["shared_outage"], "daylight_hours"].sum()
                      / out_hours) if out_hours else 0.0
        check = SUGGESTED_CHECK[primary]
        if primary == "outage" and shared_pct >= 50:
            check = SHARED_CHECK
        rows.append({
            "plant": plant,
            "inverter": inv,
            "primary_issue": primary,
            "outage_events": len(outages),
            "outage_hours": hours("outage"),
            "shared_outage_pct": shared_pct,
            "derate_hours": hours("derate"),
            "data_gap_hours": hours("data gap"),
            "availability_pct": 100 * (reported["state"] != "outage").mean(),
            "pct_of_peers_when_on": pct_when_on,
            "lost_mwh_outage": losses["outage"],
            "lost_mwh_derate": losses["derate"],
            "lost_mwh_chronic": losses["chronic"],
            "lost_mwh": total_mwh,
            "lost_usd": total_mwh * PPA_RATE,
            "last_event_end": ev["end"].max() if len(ev) else pd.NaT,
            "ongoing_at_end": bool(ev["ongoing_at_end"].any()) if len(ev) else False,
            "suggested_check": check,
        })
    p = pd.DataFrame(rows).sort_values("lost_usd", ascending=False).reset_index(drop=True)
    p.insert(0, "priority", p.index + 1)
    return p


# ------------------------------------------------------------
# STEP 5: QA CHECKS
# ------------------------------------------------------------
def run_qa(gen, readings, events, priority):
    checks = []

    def add(name, ok, detail):
        checks.append((name, "PASS" if ok else "FAIL", detail))

    # energy from 15-min kW readings should match the plant's own daily meter
    g = gen.copy()
    g["date"] = g["DATE_TIME"].dt.date
    daily = g.groupby(["SOURCE_KEY", "date"]).agg(
        integ=("AC_POWER", lambda x: x.sum() * INTERVAL_HOURS),
        meter=("DAILY_YIELD", "max"),
    )
    full_days = daily[daily["meter"] > 0]
    med_ratio = (full_days["integ"] / full_days["meter"]).median()
    add("Units: integrated kWh vs DAILY_YIELD", 0.9 < med_ratio < 1.1,
        f"median ratio {med_ratio:.3f}")
    add("All 44 inverters analysed", priority["inverter"].nunique() == 44,
        f"{priority['inverter'].nunique()} inverters")
    add("No negative losses", (events["lost_mwh"].fillna(0) >= 0).all()
        and (priority["lost_mwh"] >= 0).all(), "min loss >= 0")
    add("Event start <= end", (events["start"] <= events["end"]).all(), "all events")
    dup = events.duplicated(["inverter", "start"]).sum()
    add("No duplicate events", dup == 0, f"{dup} duplicates")
    produced = readings["ac_kw"].sum() * INTERVAL_HOURS / 1000
    lost = priority["lost_mwh"].sum()
    add("Loss is a sane share of production", 0 <= lost < produced,
        f"lost {lost:,.0f} MWh vs produced {produced:,.0f} MWh")
    add("Data gaps are not priced",
        events.loc[events["fault_type"] == "data gap", "lost_usd"].isna().all(),
        "gap loss left blank")

    print(f"\n{'Check':<42}{'Status':<8}Detail")
    print("-" * 85)
    for name, status, detail in checks:
        print(f"{name:<42}{status:<8}{detail}")
    passed = sum(s == "PASS" for _, s, _ in checks)
    print(f"\n{passed}/{len(checks)} checks passed")
    return passed == len(checks)


# ------------------------------------------------------------
# STEP 6: ONE-PAGE VISUAL
# ------------------------------------------------------------
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
PEER_GREY = "#a3a29c"
GAP_GREY = "#d9d8d3"
SEQ = LinearSegmentedColormap.from_list(
    "seq_blue", ["#f3f3f0", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
)


def make_figure(readings, priority, events, path):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9,
        "text.color": INK, "axes.labelcolor": INK_2,
        "xtick.color": INK_2, "ytick.color": INK_2,
        "axes.edgecolor": GRID, "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
    })
    fig = plt.figure(figsize=(17, 11))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.25, 1], height_ratios=[1.15, 1],
                          left=0.10, right=0.975, top=0.845, bottom=0.07,
                          wspace=0.30, hspace=0.36)

    total_mwh = priority["lost_mwh"].sum()
    total_usd = priority["lost_usd"].sum()
    top5_share = 100 * priority.head(5)["lost_usd"].sum() / total_usd
    days = readings["DATE_TIME"].dt.date.nunique()
    out = events[events["fault_type"] == "outage"]
    shared_share = (100 * out.loc[out["shared_outage"], "daylight_hours"].sum()
                    / out["daylight_hours"].sum())
    fig.text(0.10, 0.955, "Which inverter to fix first", fontsize=20,
             fontweight="bold", ha="left")
    fig.text(0.10, 0.918,
             f"44 inverters, 2 plants, {days} days.  About {total_mwh:,.0f} MWh lost "
             f"(\\${total_usd:,.0f} at \\${PPA_RATE}/MWh).  The top 5 inverters account for "
             f"{top5_share:.0f}% of it.",
             fontsize=11.5, color=INK_2, ha="left")
    fig.text(0.10, 0.892,
             f"{shared_share:.0f}% of outage hours happen while {SHARED_OUTAGE_COUNT}+ inverters "
             "are down together, which points to a shared upstream cause.  "
             "Method: each inverter vs the median of its producing peers, every 15 min.  "
             "Public dataset, not Standard Solar data.",
             fontsize=9.5, color=INK_2, ha="left")

    # ---- Panel A: inverter x day heatmap of lost MWh ----
    ax = fig.add_subplot(gs[:, 0])
    r = readings.copy()
    r["date"] = r["DATE_TIME"].dt.normalize()
    flagged = r[r["in_event"] & r["state"].isin(["outage", "derate"])]
    lost = (flagged.groupby(["inverter", "date"])["shortfall_kwh"].sum() / 1000).unstack()
    gap = (r[r["state"] == "gap"].groupby(["inverter", "date"]).size()
           * INTERVAL_HOURS).unstack()
    order = priority.sort_values(["plant", "lost_usd"], ascending=[True, False])
    dates = pd.date_range(r["date"].min(), r["date"].max(), freq="D")
    lost = lost.reindex(index=order["inverter"], columns=dates).fillna(0)
    gap = gap.reindex(index=order["inverter"], columns=dates).fillna(0)

    vmax = np.ceil(lost.values.max())
    im = ax.imshow(lost.values, aspect="auto", cmap=SEQ, vmin=0, vmax=vmax,
                   interpolation="nearest")
    # white gaps between cells
    ax.set_xticks(np.arange(-0.5, len(dates), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(order), 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.2)
    ax.tick_params(which="minor", length=0)
    # data gap days (4+ daylight hours missing): hatched grey
    for i, j in zip(*np.where(gap.values >= 4)):
        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=GAP_GREY,
                                   edgecolor=INK_2, hatch="////", linewidth=0))
    n_p1 = int((order["plant"] == "Plant_1").sum())
    ax.axhline(n_p1 - 0.5, color=INK, linewidth=1)
    labels = [f"{inv}" for inv in order["inverter"]]
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(labels, fontsize=7.5, family="DejaVu Sans Mono")
    tick_idx = list(range(0, len(dates), 4))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([dates[i].strftime("%b %d") for i in tick_idx], fontsize=8)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    n_all = len(order)
    for name, mid in [("Plant 1", n_p1 / 2), ("Plant 2", n_p1 + (n_all - n_p1) / 2)]:
        # imshow draws row 0 at the top
        ax.text(-0.215, 1 - mid / n_all, name, transform=ax.transAxes, rotation=90,
                va="center", ha="center", fontsize=10, fontweight="bold")
    ax.set_title("Lost energy per inverter per day",
                 loc="left", fontsize=11.5, fontweight="bold", pad=10)
    cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.025,
                      pad=0.045, aspect=40)
    cb.set_label("MWh lost that day", fontsize=8.5)
    cb.outline.set_visible(False)
    ax.legend(handles=[Patch(facecolor=GAP_GREY, hatch="////", edgecolor=INK_2,
                             linewidth=0, label="Not reporting (loss unknown)")],
              loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False,
              fontsize=8.5)

    # ---- Panel B: fix-first list ----
    ax = fig.add_subplot(gs[0, 1])
    top = priority.head(10).iloc[::-1]
    y = np.arange(len(top))
    ax.barh(y, top["lost_usd"], color=BLUE, height=0.62)
    ax.set_yticks(y)
    ax.set_yticklabels(top["inverter"], fontsize=8, family="DejaVu Sans Mono")
    xmax = top["lost_usd"].max()
    for yi, (_, row) in zip(y, top.iterrows()):
        note = (f"\\${row['lost_usd']:,.0f}   {row['primary_issue']}, "
                f"{row['outage_hours']:.0f} h down")
        ax.text(row["lost_usd"] + xmax * 0.015, yi, note, va="center",
                fontsize=8.3, color=INK)
    ax.set_xlim(0, xmax * 1.62)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"\\${v:,.0f}"))
    ax.set_xticks([t for t in ax.get_xticks() if t <= xmax * 1.05])
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(f"Fix-first list: top 10 by lost revenue over {days} days",
                 loc="left", fontsize=11.5, fontweight="bold", pad=10)

    # ---- Panel C: worst inverter vs peers on its worst day ----
    ax = fig.add_subplot(gs[1, 1])
    worst = priority.iloc[0]
    wr = r[r["inverter"] == worst["inverter"]]
    worst_day = wr.groupby("date")["shortfall_kwh"].sum().idxmax()
    d = wr[wr["date"] == worst_day].sort_values("DATE_TIME")
    hrs = d["DATE_TIME"].dt.hour + d["DATE_TIME"].dt.minute / 60
    ax.fill_between(hrs, d["ac_kw"].fillna(0), d["baseline_kw"],
                    where=d["baseline_kw"] > d["ac_kw"].fillna(0),
                    color=BLUE, alpha=0.12, linewidth=0)
    ax.plot(hrs, d["baseline_kw"], color=PEER_GREY, linewidth=2)
    ax.plot(hrs, d["ac_kw"], color=BLUE, linewidth=2)
    peak_i = d["baseline_kw"].values.argmax()
    ax.annotate("Peer median", (hrs.iloc[peak_i], d["baseline_kw"].iloc[peak_i]),
                xytext=(0, 8), textcoords="offset points", ha="center",
                fontsize=8.5, color=INK_2)
    day_loss = d["shortfall_kwh"].sum() / 1000
    ax.text(0.5, 0.06, f"{worst['inverter']} (blue): {day_loss:.1f} MWh lost this day",
            transform=ax.transAxes, ha="center", fontsize=9.5, color=INK)
    ax.set_ylim(0, d["baseline_kw"].max() * 1.15)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("AC power (kW)")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.set_title(f"What a flag looks like: the #1 inverter on "
                 f"{pd.Timestamp(worst_day).strftime('%b %d, %Y')}",
                 loc="left", fontsize=11.5, fontweight="bold", pad=10)

    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main():
    OUT_DIR.mkdir(exist_ok=True)
    PLOT_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("INVERTER FAULT DETECTION")
    print("=" * 60)
    gen = load_generation()
    print(f"Loaded {len(gen):,} readings, {gen['SOURCE_KEY'].nunique()} inverters")

    readings = pd.concat(
        [classify_plant(gen, p) for p in ["Plant_1", "Plant_2"]], ignore_index=True
    )
    print(f"Daylight inverter-readings checked: {len(readings):,}")

    events, readings = build_events(readings)
    priority = build_priority(events, readings)

    print("\nEvents by type:")
    summary = events.groupby(["plant", "fault_type"]).agg(
        events=("inverter", "size"),
        hours=("daylight_hours", "sum"),
        lost_mwh=("lost_mwh", "sum"),
    ).round(1)
    print(summary.to_string())

    for plant, pr in priority.groupby("plant"):
        print(f"\n{plant}: {pr['lost_mwh'].sum():,.1f} MWh lost, "
              f"${pr['lost_usd'].sum():,.0f} at ${PPA_RATE}/MWh")
        print(f"  outage {pr['lost_mwh_outage'].sum():,.1f} | "
              f"derate {pr['lost_mwh_derate'].sum():,.1f} | "
              f"chronic {pr['lost_mwh_chronic'].sum():,.1f} MWh")
    out = events[events["fault_type"] == "outage"]
    if len(out):
        shared = out.loc[out["shared_outage"], "daylight_hours"].sum()
        print(f"\nOutage hours with {SHARED_OUTAGE_COUNT}+ inverters down together: "
              f"{100 * shared / out['daylight_hours'].sum():.0f}%")
        o = readings[(readings["state"] == "outage") & readings["in_event"]]
        midday = o["DATE_TIME"].dt.hour.between(10, 13).mean()
        print(f"Outage readings between 10:00 and 14:00: {100 * midday:.0f}%")

    print("\nFIX-FIRST LIST (top 10)")
    show = priority.head(10)[["priority", "plant", "inverter", "primary_issue",
                              "outage_events", "outage_hours", "availability_pct",
                              "pct_of_peers_when_on", "lost_mwh", "lost_usd"]]
    print(show.round(1).to_string(index=False))

    ok = run_qa(gen, readings, events, priority)

    events.round({"daylight_hours": 2, "avg_pct_of_peers": 1, "lost_mwh": 3, "lost_usd": 2}).to_csv(OUT_DIR / "fault_events.csv", index=False)
    priority.round(3 if False else {c: 2 for c in priority.select_dtypes("float").columns}).to_csv(OUT_DIR / "fix_first_list.csv", index=False)
    fig_path = PLOT_DIR / "panel7_fix_first.png"
    make_figure(readings, priority, events, fig_path)
    print(f"\nSaved: processed/fault_events.csv ({len(events)} events)")
    print(f"Saved: processed/fix_first_list.csv ({len(priority)} inverters)")
    print(f"Saved: Output_Plots/{fig_path.name}")
    if not ok:
        raise SystemExit("QA failed, check the table above")


if __name__ == "__main__":
    main()
