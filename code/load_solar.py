import pandas as pd
import mysql.connector

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",  # ← YOUR PASSWORD HERE
    database="solar_performance_db"
)
cursor = conn.cursor()
print("Connected!\n")

DATA_DIR = "/Users/vinayaksonter/Desktop/VinSonter/Solar/processed"

# Load each CSV into its table
tables = {
    "daily_plant_performance": f"{DATA_DIR}/daily_plant_performance.csv",
    "daily_inverter_performance": f"{DATA_DIR}/daily_inverter_performance.csv",
    "inverter_health_summary": f"{DATA_DIR}/inverter_health_summary.csv",
    "underperformance_alerts": f"{DATA_DIR}/underperformance_alerts.csv",
}

for table, filepath in tables.items():
    df = pd.read_csv(filepath)
    cols = [c for c in df.columns if c != 'id']
    placeholders = ', '.join(['%s'] * len(cols))
    col_names = ', '.join(cols)
    
    count = 0
    for _, row in df.iterrows():
        values = [None if pd.isna(v) else v for v in row[cols].values]
        cursor.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)
        count += 1
    
    conn.commit()
    print(f"{table}: {count} rows loaded")

# Verify
print("\n--- VERIFICATION ---")
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{table}: {cursor.fetchone()[0]} rows")

conn.close()
print("\nDone!")