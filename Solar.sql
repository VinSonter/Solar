USE solar_performance_db;
SELECT plant_label,
       ROUND(SUM(total_ac_kwh), 1) AS total_energy_kwh,
       ROUND(AVG(avg_performance_ratio), 3) AS avg_pr,
       ROUND(SUM(total_lost_kwh), 1) AS total_lost_kwh,
       ROUND(SUM(total_lost_revenue), 2) AS lost_revenue
FROM daily_plant_performance
GROUP BY plant_label;


SELECT plant_label, source_key,
       ROUND(avg_pr, 3) AS performance_ratio,
       underperforming_days,
       ROUND(total_lost_kwh, 1) AS lost_kwh,
       ROUND(total_lost_revenue, 2) AS lost_revenue
FROM inverter_health_summary
ORDER BY avg_pr ASC
LIMIT 5;




SELECT plant_label, source_key,
       COUNT(*) AS alert_count,
       ROUND(AVG(performance_ratio), 3) AS avg_pr_when_failing,
       ROUND(SUM(lost_kwh), 1) AS total_lost_kwh
FROM underperformance_alerts
GROUP BY plant_label, source_key
ORDER BY total_lost_kwh DESC
LIMIT 10;



SELECT plant_label,
       ROUND(SUM(total_lost_kwh), 1) AS total_lost_kwh
FROM daily_plant_performance
GROUP BY plant_label;



