"""
Solar Asset Performance Monitoring & Analysis
==============================================
Author: Vinayak Sonter
Purpose: Ingest, clean, merge, and analyze solar generation and weather data
         to calculate performance metrics, identify underperformance, and
         quantify lost energy and revenue impact.

Data Sources:
    - Plant 1 & 2 Generation Data (Kaggle - Solar Power Generation)
    - Plant 1 & 2 Weather Sensor Data (Kaggle)
    - NREL Rooftop PV Technical Potential (US)
"""

import pandas as pd
import numpy as np
import warnings
import os
from pathlib import Path

warnings.filterwarnings('ignore')

# ============================================================
# CONFIG
# ============================================================
# Paths are relative to the repo, so the script runs from any machine
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Datasets"
PPA_RATE = 40  # $/MWh — assumed Power Purchase Agreement rate
INTERVAL_HOURS = 0.25  # readings are every 15 minutes

# ============================================================
# STEP 1: DATA INGESTION & CLEANING
# ============================================================
print("=" * 60)
print("STEP 1: DATA INGESTION & CLEANING")
print("=" * 60)

# Load raw files
gen1 = pd.read_csv(os.path.join(DATA_DIR, "Plant_1_Generation_Data.csv"))
gen2 = pd.read_csv(os.path.join(DATA_DIR, "Plant_2_Generation_Data.csv"))
wx1 = pd.read_csv(os.path.join(DATA_DIR, "Plant_1_Weather_Sensor_Data.csv"))
wx2 = pd.read_csv(os.path.join(DATA_DIR, "Plant_2_Weather_Sensor_Data.csv"))

# Plant 1 DC_POWER is recorded 10x too high in the source file
# (DC/AC is about 10.2 there and about 1.02 in Plant 2), so scale it back.
gen1['DC_POWER'] = gen1['DC_POWER'] / 10

print(f"Loaded: Gen1={len(gen1)}, Gen2={len(gen2)}, Wx1={len(wx1)}, Wx2={len(wx2)}")

# Fix date formats — Plant 1 Gen uses DD-MM-YYYY, rest uses YYYY-MM-DD
gen1['DATE_TIME'] = pd.to_datetime(gen1['DATE_TIME'], format='%d-%m-%Y %H:%M')
gen2['DATE_TIME'] = pd.to_datetime(gen2['DATE_TIME'])
wx1['DATE_TIME'] = pd.to_datetime(wx1['DATE_TIME'])
wx2['DATE_TIME'] = pd.to_datetime(wx2['DATE_TIME'])

# Add date column for daily aggregation
for df in [gen1, gen2, wx1, wx2]:
    df['DATE'] = df['DATE_TIME'].dt.date
    df['HOUR'] = df['DATE_TIME'].dt.hour

# Add plant labels
gen1['PLANT_LABEL'] = 'Plant_1'
gen2['PLANT_LABEL'] = 'Plant_2'
wx1['PLANT_LABEL'] = 'Plant_1'
wx2['PLANT_LABEL'] = 'Plant_2'

# Combine both plants
gen_all = pd.concat([gen1, gen2], ignore_index=True)
wx_all = pd.concat([wx1, wx2], ignore_index=True)

print(f"Combined: Generation={len(gen_all)}, Weather={len(wx_all)}")
print(f"Date range: {gen_all['DATE_TIME'].min()} → {gen_all['DATE_TIME'].max()}")
print(f"Plants: {gen_all['PLANT_LABEL'].unique().tolist()}")
print(f"Total inverters: {gen_all['SOURCE_KEY'].nunique()}")
print("Step 1 complete.\n")

# ============================================================
# STEP 2: MERGE GENERATION + WEATHER
# ============================================================
print("=" * 60)
print("STEP 2: MERGE GENERATION + WEATHER")
print("=" * 60)

# Merge generation with weather on timestamp and plant
merged = pd.merge(
    gen_all,
    wx_all[['DATE_TIME', 'PLANT_ID', 'AMBIENT_TEMPERATURE', 'MODULE_TEMPERATURE', 'IRRADIATION']],
    on=['DATE_TIME', 'PLANT_ID'],
    how='left'
)

print(f"Merged rows: {len(merged)}")
print(f"Null check after merge:")
null_counts = merged[['AMBIENT_TEMPERATURE', 'MODULE_TEMPERATURE', 'IRRADIATION']].isnull().sum()
for col, count in null_counts.items():
    print(f"  {col}: {count} nulls ({count/len(merged)*100:.1f}%)")

# Forward fill weather data for minor gaps
merged[['AMBIENT_TEMPERATURE', 'MODULE_TEMPERATURE', 'IRRADIATION']] = \
    merged.groupby('PLANT_ID')[['AMBIENT_TEMPERATURE', 'MODULE_TEMPERATURE', 'IRRADIATION']].ffill()

# Drop remaining nulls (if any)
before = len(merged)
merged = merged.dropna(subset=['IRRADIATION'])
after = len(merged)
print(f"Dropped {before - after} rows with missing irradiation")
print("Step 2 complete.\n")

# ============================================================
# STEP 3: FEATURE ENGINEERING
# ============================================================
print("=" * 60)
print("STEP 3: FEATURE ENGINEERING")
print("=" * 60)

# --- 3a: Performance Ratio (per 15-min interval per inverter) ---
# PR = Actual AC Power / (Irradiance * nominal capacity factor)
# Since we don't have exact inverter capacity, we use relative PR

# Filter to daylight hours only (irradiation > 0)
daylight = merged[merged['IRRADIATION'] > 0].copy()
print(f"Daylight records: {len(daylight)} out of {len(merged)} total")

# Calculate DC to AC conversion efficiency per inverter
daylight['DC_AC_RATIO'] = np.where(
    daylight['DC_POWER'] > 0,
    daylight['AC_POWER'] / daylight['DC_POWER'],
    0
)

# Normalized yield per unit irradiation
daylight['YIELD_PER_IRRADIANCE'] = daylight['AC_POWER'] / daylight['IRRADIATION']

# --- 3b: Daily aggregation per inverter ---
daily_inverter = daylight.groupby(['DATE', 'PLANT_LABEL', 'PLANT_ID', 'SOURCE_KEY']).agg(
    total_dc_kwh=('DC_POWER', 'sum'),
    total_ac_kwh=('AC_POWER', 'sum'),
    daily_yield=('DAILY_YIELD', 'max'),
    avg_irradiance=('IRRADIATION', 'mean'),
    total_irradiance=('IRRADIATION', 'sum'),
    avg_ambient_temp=('AMBIENT_TEMPERATURE', 'mean'),
    avg_module_temp=('MODULE_TEMPERATURE', 'mean'),
    avg_dc_ac_ratio=('DC_AC_RATIO', 'mean'),
    records_count=('AC_POWER', 'count')
).reset_index()

# Power readings are in kW. A 15-minute reading of X kW is X * 0.25 kWh.
daily_inverter['total_dc_kwh'] = daily_inverter['total_dc_kwh'] * INTERVAL_HOURS
daily_inverter['total_ac_kwh'] = daily_inverter['total_ac_kwh'] * INTERVAL_HOURS

print(f"Daily inverter records: {len(daily_inverter)}")

# --- 3c: Performance Ratio per inverter ---
# This is a relative ratio: each inverter's daily energy against the plant's
# daily average. It ranks inverters within a plant. It is not the IEC
# performance ratio, which needs nameplate capacity (not in this dataset),
# and by construction it averages to 1.0 across a plant.
plant_daily_avg = daily_inverter.groupby(['DATE', 'PLANT_LABEL']).agg(
    plant_avg_ac=('total_ac_kwh', 'mean')
).reset_index()

daily_inverter = daily_inverter.merge(plant_daily_avg, on=['DATE', 'PLANT_LABEL'])
daily_inverter['performance_ratio'] = np.where(
    daily_inverter['plant_avg_ac'] > 0,
    daily_inverter['total_ac_kwh'] / daily_inverter['plant_avg_ac'],
    0
)

# --- 3d: Status flags ---
daily_inverter['status'] = daily_inverter['performance_ratio'].apply(
    lambda x: 'Underperforming' if x < 0.85
    else ('Over-performing' if x > 1.15 else 'Normal')
)

# --- 3e: Lost energy calculation ---
daily_inverter['lost_kwh'] = np.where(
    daily_inverter['status'] == 'Underperforming',
    daily_inverter['plant_avg_ac'] - daily_inverter['total_ac_kwh'],
    0
)

# Revenue impact
daily_inverter['lost_revenue_usd'] = daily_inverter['lost_kwh'] / 1000 * PPA_RATE

# --- 3f: Daily plant-level summary ---
daily_plant = daily_inverter.groupby(['DATE', 'PLANT_LABEL', 'PLANT_ID']).agg(
    total_ac_kwh=('total_ac_kwh', 'sum'),
    total_dc_kwh=('total_dc_kwh', 'sum'),
    avg_irradiance=('avg_irradiance', 'mean'),
    avg_ambient_temp=('avg_ambient_temp', 'mean'),
    avg_module_temp=('avg_module_temp', 'mean'),
    avg_performance_ratio=('performance_ratio', 'mean'),
    underperforming_inverters=('status', lambda x: (x == 'Underperforming').sum()),
    total_lost_kwh=('lost_kwh', 'sum'),
    total_lost_revenue=('lost_revenue_usd', 'sum'),
    inverter_count=('SOURCE_KEY', 'nunique')
).reset_index()

daily_plant['DATE'] = pd.to_datetime(daily_plant['DATE'])

# Rolling 7-day performance ratio
daily_plant['rolling_7d_pr'] = daily_plant.groupby('PLANT_LABEL')['avg_performance_ratio'].transform(
    lambda x: x.rolling(7, min_periods=1).mean()
)

print(f"Daily plant records: {len(daily_plant)}")

# --- 3g: Inverter health ranking ---
inverter_health = daily_inverter.groupby(['PLANT_LABEL', 'SOURCE_KEY']).agg(
    avg_pr=('performance_ratio', 'mean'),
    min_pr=('performance_ratio', 'min'),
    underperforming_days=('status', lambda x: (x == 'Underperforming').sum()),
    total_lost_kwh=('lost_kwh', 'sum'),
    total_lost_revenue=('lost_revenue_usd', 'sum'),
    avg_dc_ac_ratio=('avg_dc_ac_ratio', 'mean')
).reset_index()

inverter_health['health_rank'] = inverter_health.groupby('PLANT_LABEL')['avg_pr'].rank(ascending=True)
inverter_health = inverter_health.sort_values(['PLANT_LABEL', 'health_rank'])

print(f"Inverter health records: {len(inverter_health)}")

# --- 3h: Alerts ---
alerts = daily_inverter[daily_inverter['status'] == 'Underperforming'][
    ['DATE', 'PLANT_LABEL', 'PLANT_ID', 'SOURCE_KEY', 'performance_ratio', 
     'total_ac_kwh', 'plant_avg_ac', 'lost_kwh', 'lost_revenue_usd', 'status']
].copy()
alerts['DATE'] = pd.to_datetime(alerts['DATE'])

print(f"Underperformance alerts: {len(alerts)}")

feature_summary = {
    'performance_ratio': 'Inverter daily energy / plant daily average (relative, not IEC PR)',
    'status': 'Underperforming (<0.85), Normal (0.85-1.15), Over-performing (>1.15)',
    'lost_kwh': 'Shortfall vs plant average for underperforming inverters',
    'lost_revenue_usd': 'Lost kWh * PPA rate ($40/MWh)',
    'dc_ac_ratio': 'DC to AC conversion efficiency',
    'yield_per_irradiance': 'AC output normalized by solar irradiance',
    'rolling_7d_pr': '7-day rolling average performance ratio',
    'health_rank': 'Inverter ranking within plant (1 = worst)'
}

print("\nFeatures engineered:")
for feat, desc in feature_summary.items():
    print(f"  {feat}: {desc}")
print("Step 3 complete.\n")

# ============================================================
# STEP 4: DATA QUALITY / QA CHECKS
# ============================================================
print("=" * 60)
print("STEP 4: DATA QUALITY CHECKS")
print("=" * 60)

qa_results = []

# Check 1: Row counts
check = "Row count — daily_inverter"
expected_approx = 22 * 34 * 2  # 22 inverters * 34 days * 2 plants
actual = len(daily_inverter)
status = "PASS" if actual > expected_approx * 0.9 else "WARN"
qa_results.append((check, f"Expected ~{expected_approx}, got {actual}", status))

# Check 2: No negative power values
check = "No negative AC power"
neg_count = (daily_inverter['total_ac_kwh'] < 0).sum()
status = "PASS" if neg_count == 0 else "FAIL"
qa_results.append((check, f"{neg_count} negative values", status))

# Check 3: Performance ratio bounds
check = "Performance ratio within bounds (0-3)"
out_of_bounds = ((daily_inverter['performance_ratio'] < 0) | (daily_inverter['performance_ratio'] > 3)).sum()
status = "PASS" if out_of_bounds == 0 else "WARN"
qa_results.append((check, f"{out_of_bounds} out of bounds", status))

# Check 4: No future dates
check = "No future dates"
future = (pd.to_datetime(daily_inverter['DATE']) > pd.Timestamp.now()).sum()
status = "PASS" if future == 0 else "FAIL"
qa_results.append((check, f"{future} future dates", status))

# Check 5: Both plants represented
check = "Both plants present"
plants = daily_inverter['PLANT_LABEL'].nunique()
status = "PASS" if plants == 2 else "FAIL"
qa_results.append((check, f"{plants} plants found", status))

# Check 6: All inverters reporting
check = "All 44 inverters reporting"
inv_count = daily_inverter['SOURCE_KEY'].nunique()
status = "PASS" if inv_count == 44 else "WARN"
qa_results.append((check, f"{inv_count} inverters found", status))

# Check 7: Temperature sanity
check = "Temperature within bounds (10-80°C)"
temp_issues = ((daily_inverter['avg_module_temp'] < 10) | (daily_inverter['avg_module_temp'] > 80)).sum()
status = "PASS" if temp_issues == 0 else "WARN"
qa_results.append((check, f"{temp_issues} out of bounds", status))

# Check 8: Lost energy is non-negative
check = "Lost energy >= 0"
neg_lost = (daily_inverter['lost_kwh'] < 0).sum()
status = "PASS" if neg_lost == 0 else "FAIL"
qa_results.append((check, f"{neg_lost} negative values", status))

# Check 9: Units — integrated energy should match the plant's own daily meter
check = "Units match DAILY_YIELD meter"
with_meter = daily_inverter[(daily_inverter['daily_yield'] > 0) & (daily_inverter['PLANT_LABEL'] == 'Plant_1')]
unit_ratio = (with_meter['total_ac_kwh'] / with_meter['daily_yield']).median()
status = "PASS" if 0.9 < unit_ratio < 1.1 else "FAIL"
qa_results.append((check, f"median ratio {unit_ratio:.3f}", status))

print(f"\n{'Check':<45} {'Result':<35} {'Status'}")
print("-" * 90)
for check, result, status in qa_results:
    marker = "✓" if status == "PASS" else "⚠" if status == "WARN" else "✗"
    print(f"{marker} {check:<44} {result:<35} {status}")

passed = sum(1 for _, _, s in qa_results if s == "PASS")
print(f"\n{passed}/{len(qa_results)} checks passed")
print("Step 4 complete.\n")

# ============================================================
# STEP 5: SUMMARY STATISTICS
# ============================================================
print("=" * 60)
print("STEP 5: KEY FINDINGS")
print("=" * 60)

for plant in ['Plant_1', 'Plant_2']:
    p = daily_plant[daily_plant['PLANT_LABEL'] == plant]
    inv = daily_inverter[daily_inverter['PLANT_LABEL'] == plant]
    
    print(f"\n  {plant}:")
    print(f"  Total AC Energy: {p['total_ac_kwh'].sum() / 1000:,.1f} MWh")
    print(f"  Avg Daily Production: {p['total_ac_kwh'].mean() / 1000:,.1f} MWh/day")
    print(f"  Avg Irradiance: {p['avg_irradiance'].mean():.3f} kW/m²")
    print(f"  Avg Module Temp: {p['avg_module_temp'].mean():.1f}°C")
    print(f"  Total Lost Energy: {inv['lost_kwh'].sum() / 1000:,.1f} MWh")
    print(f"  Total Lost Revenue: ${inv['lost_revenue_usd'].sum():,.0f}")
    print(f"  Underperformance Events: {(inv['status'] == 'Underperforming').sum()}")
    
    # Top 3 worst inverters
    worst = inverter_health[inverter_health['PLANT_LABEL'] == plant].head(3)
    print(f"  Top 3 worst inverters:")
    for _, row in worst.iterrows():
        print(f"    {row['SOURCE_KEY']}: PR={row['avg_pr']:.3f}, Lost={row['total_lost_kwh'] / 1000:.1f} MWh, "
              f"Underperforming {row['underperforming_days']:.0f} days")

print("\nStep 5 complete.\n")

# ============================================================
# STEP 6: EXPORT TO CSV (for MySQL and Tableau)
# ============================================================
print("=" * 60)
print("STEP 6: EXPORT")
print("=" * 60)

output_dir = ROOT / "processed"
os.makedirs(output_dir, exist_ok=True)

daily_plant.to_csv(os.path.join(output_dir, "daily_plant_performance.csv"), index=False)
daily_inverter.to_csv(os.path.join(output_dir, "daily_inverter_performance.csv"), index=False)
inverter_health.to_csv(os.path.join(output_dir, "inverter_health_summary.csv"), index=False)
alerts.to_csv(os.path.join(output_dir, "underperformance_alerts.csv"), index=False)

print(f"Exported to {output_dir}:")
print(f"  daily_plant_performance.csv: {len(daily_plant)} rows")
print(f"  daily_inverter_performance.csv: {len(daily_inverter)} rows")
print(f"  inverter_health_summary.csv: {len(inverter_health)} rows")
print(f"  underperformance_alerts.csv: {len(alerts)} rows")
print("Step 6 complete.\n")

print("=" * 60)
print("PIPELINE COMPLETE")
print("=" * 60)
print(f"Total records processed: {len(gen_all) + len(wx_all):,}")
print(f"Output tables: 4")
print("Next: python3 code/inverter_fault_detection.py, then python3 code/make_dashboard.py")