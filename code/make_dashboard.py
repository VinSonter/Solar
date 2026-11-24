"""
Dashboard panels 1-6 and KPI scorecard
======================================
Author: Vinayak Sonter

Reads the CSVs in processed/ and writes the PNG panels to Output_Plots/.
Run after Solar.py and inverter_fault_detection.py:

    python3 code/Solar.py
    python3 code/inverter_fault_detection.py
    python3 code/make_dashboard.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "processed"
PLOTS = ROOT / "Output_Plots"

PPA_RATE = 40    # $/MWh, assumed
SREC_RATE = 70   # $/MWh, assumed

INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
PLANT_COLOR = {"Plant_1": "#2a78d6", "Plant_2": "#eb6834"}
PLANT_NAME = {"Plant_1": "Plant 1", "Plant_2": "Plant 2"}
STATUS_COLOR = {"On Target": "#0ca30c", "Monitor": "#fab219",
                "Needs Attention": "#d03b3b", "---": "#a3a29c"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": GRID, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.titleweight": "bold", "axes.titlesize": 11.5, "axes.titlelocation": "left",
})


def clean(ax, grid="y"):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(PLOTS / name, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved Output_Plots/{name}")


def title(fig, text, sub=None):
    fig.suptitle(text, x=0.01, ha="left", fontsize=15, fontweight="bold", y=1.04)
    if sub:
        fig.text(0.01, 0.955, sub, ha="left", fontsize=10, color=INK_2)


# ------------------------------------------------------------
# LOAD
# ------------------------------------------------------------
daily_plant = pd.read_csv(DATA / "daily_plant_performance.csv", parse_dates=["DATE"])
daily_inv = pd.read_csv(DATA / "daily_inverter_performance.csv", parse_dates=["DATE"])
health = pd.read_csv(DATA / "inverter_health_summary.csv")
alerts = pd.read_csv(DATA / "underperformance_alerts.csv", parse_dates=["DATE"])
fix = pd.read_csv(DATA / "fix_first_list.csv")
events = pd.read_csv(DATA / "fault_events.csv", parse_dates=["start", "end"])
plants = ["Plant_1", "Plant_2"]

# ------------------------------------------------------------
# PANEL 1: PLANT COMPARISON
# ------------------------------------------------------------
produced = daily_plant.groupby("PLANT_LABEL")["total_ac_kwh"].sum() / 1000
lost = fix.groupby("plant")["lost_mwh"].sum()
flagged = daily_plant.groupby("PLANT_LABEL")["underperforming_inverters"].mean()

fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
title(fig, "Plant comparison", "34 days, 22 inverters per plant")
for ax, (series, label, fmt) in zip(axes, [
    (produced, "Energy produced (MWh)", "{:,.0f}"),
    (lost, "Energy lost to faults (MWh)", "{:,.0f}"),
    (flagged, "Inverters below 85% of plant average, per day", "{:.1f}"),
]):
    vals = [series[p] for p in plants]
    ax.bar([PLANT_NAME[p] for p in plants], vals,
           color=[PLANT_COLOR[p] for p in plants], width=0.5)
    for i, v in enumerate(vals):
        ax.text(i, v + max(vals) * 0.02, fmt.format(v), ha="center", fontweight="bold")
    ax.set_ylim(0, max(vals) * 1.15)
    ax.set_title(label)
    clean(ax)
fig.tight_layout()
save(fig, "panel1_plant_comparison.png")

# ------------------------------------------------------------
# PANEL 2: DAILY PRODUCTION
# ------------------------------------------------------------
fig, ax = plt.subplots(figsize=(15, 4.5))
title(fig, "Daily AC production")
for p in plants:
    d = daily_plant[daily_plant["PLANT_LABEL"] == p]
    ax.plot(d["DATE"], d["total_ac_kwh"] / 1000, color=PLANT_COLOR[p], linewidth=2,
            marker="o", markersize=4, label=PLANT_NAME[p])
    ax.annotate(PLANT_NAME[p], (d["DATE"].iloc[-1], d["total_ac_kwh"].iloc[-1] / 1000),
                xytext=(8, 0), textcoords="offset points", va="center", color=INK)
ax.set_ylabel("MWh per day")
ax.set_ylim(0, None)
ax.legend(frameon=False, loc="lower left", ncol=2)
clean(ax)
fig.tight_layout()
save(fig, "panel2_daily_production.png")

# ------------------------------------------------------------
# PANEL 3: INVERTER HEALTH
# ------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(15, 7), sharex=True)
title(fig, "Inverter health: daily energy vs plant average",
      "1.00 = plant average. Dashed line = 0.85 flag threshold.")
for ax, p in zip(axes, plants):
    d = health[health["PLANT_LABEL"] == p].sort_values("avg_pr", ascending=False)
    ax.barh(d["SOURCE_KEY"], d["avg_pr"], color=PLANT_COLOR[p], height=0.65)
    for y, v in enumerate(d["avg_pr"]):
        ax.text(v + 0.008, y, f"{v:.2f}", va="center", fontsize=8)
    ax.axvline(0.85, color=INK, linestyle="--", linewidth=1)
    ax.set_xlim(0.5, 1.2)
    ax.set_title(PLANT_NAME[p])
    ax.tick_params(axis="y", labelsize=8)
    for lab in ax.get_yticklabels():
        lab.set_family("DejaVu Sans Mono")
    clean(ax, grid="x")
fig.tight_layout()
save(fig, "panel3_inverter_health.png")

# ------------------------------------------------------------
# PANEL 4: WHERE THE LOST ENERGY WENT
# ------------------------------------------------------------
out = events[events["fault_type"] == "outage"]
causes = pd.Series({
    "Outage, 5+ inverters\ndown together": out["lost_mwh_shared"].sum(),
    "Outage, fewer than 5\ndown together": out["lost_mwh"].sum() - out["lost_mwh_shared"].sum(),
    "Derate\n(below 75% of peers)": fix["lost_mwh_derate"].sum(),
    "Chronic\n(steadily below peers)": fix["lost_mwh_chronic"].sum(),
})
fig, ax = plt.subplots(figsize=(11, 4.5))
title(fig, "Where the lost energy went",
      f"Both plants, {causes.sum():,.0f} MWh in total, priced at ${PPA_RATE}/MWh".replace("$", r"\$"))
ax.bar(causes.index, causes.values, color=PLANT_COLOR["Plant_1"], width=0.5)
for i, v in enumerate(causes.values):
    ax.text(i, v + causes.max() * 0.02,
            f"{v:,.0f} MWh\n" + r"\$" + f"{v * PPA_RATE:,.0f}", ha="center", fontweight="bold")
ax.set_ylim(0, causes.max() * 1.22)
ax.set_ylabel("MWh lost")
clean(ax)
fig.tight_layout()
save(fig, "panel4_lost_energy_revenue.png")

# ------------------------------------------------------------
# PANEL 5: WEATHER VS PRODUCTION
# ------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5.5))
title(fig, "Irradiance vs daily production",
      "Each dot is one day. Plant 2 gets similar sun and produces less.")
for p in plants:
    d = daily_plant[daily_plant["PLANT_LABEL"] == p]
    x, y = d["avg_irradiance"], d["total_ac_kwh"] / 1000
    ax.scatter(x, y, color=PLANT_COLOR[p], s=55, edgecolors=SURFACE, linewidths=1.5,
               label=PLANT_NAME[p], zorder=3)
    slope, intercept = np.polyfit(x, y, 1)
    xs = np.linspace(x.min(), x.max(), 50)
    ax.plot(xs, slope * xs + intercept, color=PLANT_COLOR[p], linewidth=1.5, alpha=0.6)
ax.set_xlabel("Average daylight irradiance (kW/m²)")
ax.set_ylabel("MWh per day")
ax.legend(frameon=False, loc="upper left")
clean(ax, grid="both")
fig.tight_layout()
save(fig, "panel5_weather_vs_production.png")

# ------------------------------------------------------------
# PANEL 6: KPI SCORECARD
# ------------------------------------------------------------
def status(actual, target, higher_is_better=True):
    if higher_is_better:
        return ("On Target" if actual >= target
                else "Monitor" if actual >= target * 0.97 else "Needs Attention")
    return ("On Target" if actual <= target
            else "Monitor" if actual <= target * 1.2 else "Needs Attention")


total_produced = produced.sum()
total_lost = fix["lost_mwh"].sum()
availability = fix["availability_pct"].mean()
lost_share = 100 * total_lost / (total_produced + total_lost)
inverter_days = len(daily_inv)
expected_days = fix["inverter"].nunique() * daily_plant["DATE"].nunique()
flag_rate = 100 * len(alerts) / inverter_days
completeness = 100 * inverter_days / expected_days
repeat_rate = 100 * (fix["outage_events"] >= 3).mean()
worst = fix.loc[fix["pct_of_peers_when_on"].idxmin()]

kpis = [
    ("Inverter availability (daylight)", f"{availability:.1f}%", "98%", status(availability, 98)),
    ("Energy lost to faults", f"{lost_share:.1f}% ({total_lost:,.0f} MWh)", "<2%",
     status(lost_share, 2, False)),
    ("Inverter-days below 85% of plant avg", f"{flag_rate:.1f}%", "<5%", status(flag_rate, 5, False)),
    ("Data completeness", f"{completeness:.1f}%", "99%", status(completeness, 99)),
    ("Inverters with 3+ outage events", f"{repeat_rate:.0f}%", "<10%", status(repeat_rate, 10, False)),
    ("Worst inverter vs peers when running",
     f"{worst['pct_of_peers_when_on']:.0f}% ({worst['inverter']})", ">95%",
     status(worst["pct_of_peers_when_on"], 95)),
    (f"Lost revenue, PPA at ${PPA_RATE}/MWh (assumed)", f"${total_lost * PPA_RATE:,.0f}", "---", "---"),
    (f"Lost revenue, SREC at ${SREC_RATE}/MWh (assumed)", f"${total_lost * SREC_RATE:,.0f}", "---", "---"),
    ("Total revenue impact", f"${total_lost * (PPA_RATE + SREC_RATE):,.0f}", "---", "---"),
]
kpi_df = pd.DataFrame(kpis, columns=["KPI", "Actual", "Target", "Status"])
kpi_df.to_csv(DATA / "kpi_scorecard.csv", index=False)
print(kpi_df.to_string(index=False))

fig, ax = plt.subplots(figsize=(12, 5.2))
title(fig, "Portfolio KPI scorecard", "2 plants, 44 inverters, May 15 to Jun 17, 2020")
ax.axis("off")
cols = [0.0, 0.47, 0.76, 0.86]
for x, head in zip(cols, ["KPI", "Actual", "Target", "Status"]):
    ax.text(x, 1.0, head, fontweight="bold", color=INK_2, transform=ax.transAxes, va="top")
row_h = 0.1
for i, (name, actual, target, stat) in enumerate(kpis):
    y = 0.9 - i * row_h
    ax.plot([0, 1], [y + row_h * 0.35, y + row_h * 0.35], color=GRID, linewidth=0.8,
            transform=ax.transAxes, clip_on=False)
    esc = lambda t: t.replace("$", r"\$")
    ax.text(cols[0], y, esc(name), transform=ax.transAxes, va="center")
    ax.text(cols[1], y, esc(actual), transform=ax.transAxes, va="center", fontweight="bold")
    ax.text(cols[2], y, target, transform=ax.transAxes, va="center", color=INK_2)
    if stat != "---":
        ax.scatter([cols[3] + 0.008], [y], s=90, color=STATUS_COLOR[stat],
                   transform=ax.transAxes, clip_on=False)
        ax.text(cols[3] + 0.025, y, stat, transform=ax.transAxes, va="center")
save(fig, "panel6_kpi_dashboard.png")
