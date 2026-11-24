"""Load the processed CSVs into MySQL (solar_performance_db).

Clears the four tables first, so it is safe to run again after the
pipeline is re-run. Asks for the MySQL password instead of storing it.
"""
from getpass import getpass
from pathlib import Path

import mysql.connector
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "processed"

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password=getpass("MySQL password: "),
    database="solar_performance_db",
)
cursor = conn.cursor()
print("Connected!\n")

tables = [
    "daily_plant_performance",
    "daily_inverter_performance",
    "inverter_health_summary",
    "underperformance_alerts",
]

for table in tables:
    df = pd.read_csv(DATA_DIR / f"{table}.csv")
    cols = [c for c in df.columns if c != "id"]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)

    cursor.execute(f"DELETE FROM {table}")
    rows = [
        tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in row)
        for row in df[cols].itertuples(index=False, name=None)
    ]
    cursor.executemany(
        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", rows
    )
    conn.commit()
    print(f"{table}: {len(rows)} rows loaded")

print("\n--- VERIFICATION ---")
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{table}: {cursor.fetchone()[0]} rows")

conn.close()
print("\nDone!")
