# Solar Asset Performance Monitoring & Analysis

## Dashboard

### Plant Comparison
![Plant Comparison](processed/panel1_plant_comparison.png)

![Daily Production](processed/panel2_daily_production.png)

![Inverter Health](processed/panel3_inverter_health.png)

![Lost Energy](processed/panel4_lost_energy_revenue.png)

![Weather Impact](processed/panel5_weather_vs_production.png)

## Overview:

Built a solar asset performance monitoring system that ingests generation and weather data from two solar plants (44 inverters), calculates performance metrics, identifies underperforming equipment, and quantifies lost energy and revenue impact. The project simulates what an Asset Performance Data Analyst does at a solar O&M company — monitoring assets, validating data, flagging issues, and reporting findings to stakeholders.

## Business Questions Answered

1. Are our solar assets producing what they should?
2. Which inverters are underperforming and by how much?
3. How much energy and revenue are we losing?
4. How does weather affect production?
5. Which equipment needs immediate maintenance attention?

## Key Findings

| Metric | Plant 1 | Plant 2 |
|--------|---------|---------|
| Total Energy | 5,293 kWh | 4,084 kWh |
| Underperformance Events | 6 | 226 |
| Lost Energy | 13.5 kWh | 548.1 kWh |
| Lost Revenue | $0.54 | $21.92 |
| Worst Inverter PR | 0.908 | 0.697 |

Plant 2 has systemic inverter issues — 226 underperformance events across 34 days. The three worst inverters (Quc1TzYxW2pYoWX, Et9kgGMDl729KT4, LYwnQax7tkwH5Cb) are producing 70-81% of expected output and need immediate field inspection. Plant 1's trend slope (268 kWh per unit irradiance) is more than double Plant 2's (122), confirming Plant 2 converts sunlight to energy far less efficiently.

## Data Sources

| Dataset | Source | Records |
|---------|--------|---------|
| Plant 1 & 2 Generation Data | Kaggle — Solar Power Generation | 136,476 |
| Plant 1 & 2 Weather Sensor Data | Kaggle | 6,441 |
| Rooftop PV Technical Potential | NREL | 5,132 |

## Pipeline Architecture

```
Raw CSVs (Generation + Weather)
    ↓
Step 1: Data Ingestion & Cleaning (Python)
    • Standardize date formats
    • Combine both plants
    • Add helper columns
    ↓
Step 2: Merge Generation + Weather (Python)
    • Join on timestamp and plant ID
    • Forward fill minor gaps
    • Filter to daylight hours
    ↓
Step 3: Feature Engineering (Python)
    • Performance Ratio per inverter
    • Lost Energy (kWh)
    • Revenue Impact ($40/MWh PPA rate)
    • Status flags (Underperforming/Normal/Over-performing)
    • Inverter Health Ranking
    • DC-AC Conversion Efficiency
    • Rolling 7-day Performance Ratio
    ↓
Step 4: Data Quality Checks (Python)
    • 8 automated QA checks — all passed
    ↓
Step 5: MySQL Database (4 tables, 1,808 rows)
    ↓
Step 6: SQL Analysis (8 analytical queries)
    ↓
Step 7: Dashboard (5 panels in Matplotlib)
```

## Database Schema

MySQL database `solar_performance_db` with 4 tables:

| Table | Description | Rows |
|-------|-------------|------|
| `daily_plant_performance` | Daily aggregated metrics per plant | 68 |
| `daily_inverter_performance` | Daily metrics per inverter | 1,464 |
| `inverter_health_summary` | Overall health score per inverter | 44 |
| `underperformance_alerts` | Every underperformance event flagged | 232 |

## QA Checks

| Check | Result |
|-------|--------|
| Row count validation | PASS |
| No negative AC power | PASS |
| Performance ratio in bounds (0-3) | PASS |
| No future dates | PASS |
| Both plants present | PASS |
| All 44 inverters reporting | PASS |
| Temperature in bounds (10-80°C) | PASS |
| Lost energy non-negative | PASS |

## Sample SQL Queries

**Plant performance comparison:**
```sql
SELECT plant_label,
       ROUND(SUM(total_ac_kwh), 1) AS total_energy_kwh,
       ROUND(SUM(total_lost_kwh), 1) AS total_lost_kwh,
       ROUND(SUM(total_lost_revenue), 2) AS lost_revenue_usd
FROM daily_plant_performance
GROUP BY plant_label;
```

**Top 5 worst inverters:**
```sql
SELECT plant_label, source_key,
       ROUND(avg_pr, 3) AS performance_ratio,
       underperforming_days,
       ROUND(total_lost_kwh, 1) AS lost_kwh
FROM inverter_health_summary
ORDER BY avg_pr ASC
LIMIT 5;
```

**Alert summary by inverter:**
```sql
SELECT plant_label, source_key,
       COUNT(*) AS alert_count,
       ROUND(AVG(performance_ratio), 3) AS avg_pr_when_failing,
       ROUND(SUM(lost_kwh), 1) AS total_lost_kwh
FROM underperformance_alerts
GROUP BY plant_label, source_key
ORDER BY total_lost_kwh DESC;
```

## Tech Stack

- **Python** — Pandas, NumPy, Matplotlib
- **MySQL** — Database design, schema creation, analytical queries
- **SQL** — Complex queries, aggregations, window functions, trend analysis
- **Google Colab** — Data processing and visualization
- **Git/GitHub** — Version control and documentation

## How to Run

### 1. Run the Pipeline (Google Colab or local)
```bash
source ~/ds_env/bin/activate
python3 solar_pipeline.py
```

### 2. Create MySQL Database
```bash
mysql -u root -p -e "CREATE DATABASE solar_performance_db;"
```

### 3. Create Tables and Load Data
```bash
mysql -u root -p solar_performance_db < solar_queries.sql
python3 load_solar.py
```

### 4. Run Analytical Queries
```bash
mysql -u root -p < solar_queries.sql > query_results.txt
```

## Project Structure

```
Solar/
├── solar_pipeline.py              # Main Python ETL pipeline
├── load_solar.py                  # MySQL data loader
├── solar_queries.sql              # 8 analytical SQL queries
├── query_results.txt              # Query output documentation
├── Plant_1_Generation_Data.csv    # Raw data
├── Plant_2_Generation_Data.csv
├── Plant_1_Weather_Sensor_Data.csv
├── Plant_2_Weather_Sensor_Data.csv
├── processed/
│   ├── daily_plant_performance.csv
│   ├── daily_inverter_performance.csv
│   ├── inverter_health_summary.csv
│   ├── underperformance_alerts.csv
│   ├── panel1_plant_comparison.png
│   ├── panel2_daily_production.png
│   ├── panel3_inverter_health.png
│   ├── panel4_lost_energy_revenue.png
│   └── panel5_weather_vs_production.png
└── README.md
```

## Author

**Vinayak Sonter**
MS in Data Science — University of Massachusetts Dartmouth
