USE solar_performance_db;

-- Q1: Plant Performance Comparison
SELECT '--- Q1: PLANT PERFORMANCE COMPARISON ---' AS '';
SELECT plant_label,
       ROUND(SUM(total_ac_kwh), 1) AS total_energy_kwh,
       ROUND(AVG(avg_performance_ratio), 3) AS avg_pr,
       ROUND(SUM(total_lost_kwh), 1) AS total_lost_kwh,
       ROUND(SUM(total_lost_revenue), 2) AS lost_revenue_usd
FROM daily_plant_performance
GROUP BY plant_label;

-- Q2: Top 10 Worst Inverters
SELECT '--- Q2: TOP 10 WORST INVERTERS ---' AS '';
SELECT plant_label, source_key,
       ROUND(avg_pr, 3) AS performance_ratio,
       underperforming_days,
       ROUND(total_lost_kwh, 1) AS lost_kwh,
       ROUND(total_lost_revenue, 2) AS lost_revenue_usd
FROM inverter_health_summary
ORDER BY avg_pr ASC
LIMIT 10;

-- Q3: Daily Production Trend
SELECT '--- Q3: DAILY PRODUCTION TREND ---' AS '';
SELECT date, plant_label,
       ROUND(total_ac_kwh, 1) AS ac_kwh,
       ROUND(avg_performance_ratio, 3) AS pr,
       underperforming_inverters AS underperf_inv
FROM daily_plant_performance
ORDER BY date, plant_label;

-- Q4: Underperformance Alerts by Inverter
SELECT '--- Q4: ALERT SUMMARY BY INVERTER ---' AS '';
SELECT plant_label, source_key,
       COUNT(*) AS alert_count,
       ROUND(AVG(performance_ratio), 3) AS avg_pr_when_failing,
       ROUND(SUM(lost_kwh), 1) AS total_lost_kwh,
       ROUND(SUM(lost_revenue_usd), 2) AS total_lost_revenue
FROM underperformance_alerts
GROUP BY plant_label, source_key
ORDER BY total_lost_kwh DESC;

-- Q5: Temperature Impact on Performance
SELECT '--- Q5: TEMPERATURE vs PERFORMANCE ---' AS '';
SELECT ROUND(avg_module_temp, 0) AS temp_celsius,
       ROUND(AVG(avg_performance_ratio), 3) AS avg_pr,
       COUNT(*) AS observation_days
FROM daily_plant_performance
GROUP BY temp_celsius
ORDER BY temp_celsius;

-- Q6: Weekly Performance Summary
SELECT '--- Q6: WEEKLY PERFORMANCE ---' AS '';
SELECT plant_label,
       YEARWEEK(date) AS week,
       ROUND(AVG(avg_performance_ratio), 3) AS weekly_pr,
       ROUND(SUM(total_lost_kwh), 1) AS weekly_lost_kwh,
       SUM(underperforming_inverters) AS total_alerts
FROM daily_plant_performance
GROUP BY plant_label, YEARWEEK(date)
ORDER BY plant_label, week;

-- Q7: Best vs Worst Day per Plant
SELECT '--- Q7: BEST vs WORST DAY PER PLANT ---' AS '';
SELECT plant_label, date,
       ROUND(total_ac_kwh, 1) AS ac_kwh,
       ROUND(avg_performance_ratio, 3) AS pr,
       'Best Day' AS type
FROM daily_plant_performance d1
WHERE total_ac_kwh = (SELECT MAX(total_ac_kwh) FROM daily_plant_performance d2 WHERE d2.plant_label = d1.plant_label)
UNION ALL
SELECT plant_label, date,
       ROUND(total_ac_kwh, 1) AS ac_kwh,
       ROUND(avg_performance_ratio, 3) AS pr,
       'Worst Day' AS type
FROM daily_plant_performance d1
WHERE total_ac_kwh = (SELECT MIN(total_ac_kwh) FROM daily_plant_performance d2 WHERE d2.plant_label = d1.plant_label)
ORDER BY plant_label, type;

-- Q8: Inverter DC-AC Conversion Efficiency
SELECT '--- Q8: INVERTER DC-AC CONVERSION EFFICIENCY ---' AS '';
SELECT plant_label, source_key,
       ROUND(avg_dc_ac_ratio, 3) AS dc_ac_efficiency,
       ROUND(avg_pr, 3) AS performance_ratio
FROM inverter_health_summary
ORDER BY dc_ac_efficiency ASC
LIMIT 10: