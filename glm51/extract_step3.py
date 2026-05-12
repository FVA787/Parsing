#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from glob import glob


DECLARATION_INFO_COLUMNS = [
    "id", "name", "N_declaration", "date_declaration"
]

CURRENT_DECLARATION_COLUMNS = [
    "id", "N_declaration", "date_declaration", "name", "developer", "city",
    "district", "street", "land_plot", "building", "subject", "region",
    "S_total", "S_residential", "S_non_residential", "Price_plan", "S_land",
    "Start_period", "Finish_period", "Date_expert", "material_walls",
    "material_covering", "energy_class", "max_height", "N_residential_rooms",
    "N_non_residential_rooms", "parking", "other_rooms", "min_S_flat",
    "other_rooms_19_6_1_4", "other_info"
]

NUMERIC_FIELDS_2 = {
    "S_total", "S_residential", "S_non_residential", "Price_plan", "S_land",
    "min_S_flat", "other_rooms_19_6_1_4"
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS Declaration_info (
    id BIGINT PRIMARY KEY,
    name TEXT,
    N_declaration TEXT,
    date_declaration DATE
);

CREATE TABLE IF NOT EXISTS Current_declaration (
    id BIGINT PRIMARY KEY,
    N_declaration TEXT,
    date_declaration DATE,
    name TEXT,
    developer TEXT,
    city TEXT,
    district TEXT,
    street TEXT,
    land_plot TEXT,
    building TEXT,
    subject TEXT,
    region TEXT,
    S_total NUMERIC(18, 2),
    S_residential NUMERIC(18, 2),
    S_non_residential NUMERIC(18, 2),
    Price_plan NUMERIC(18, 2),
    S_land NUMERIC(18, 2),
    Start_period DATE,
    Finish_period TEXT,
    Date_expert DATE,
    material_walls TEXT,
    material_covering TEXT,
    energy_class TEXT,
    max_height TEXT,
    N_residential_rooms INTEGER,
    N_non_residential_rooms INTEGER,
    parking INTEGER,
    other_rooms INTEGER,
    min_S_flat NUMERIC(18, 2),
    other_rooms_19_6_1_4 NUMERIC(18, 2),
    other_info TEXT
);
"""


def round_numeric(value):
    if value is not None:
        return round(value, 2)
    return None


def extract_row(data_dict, columns):
    row = []
    for col in columns:
        val = data_dict.get(col)
        if col in NUMERIC_FIELDS_2:
            val = round_numeric(val)
        row.append(val)
    return tuple(row)


def main():
    parser = argparse.ArgumentParser(description="Load 002 JSON files into SQLite")
    parser.add_argument("--db", default="output/domrf_declarations.sqlite", help="Database path")
    parser.add_argument("--limit", type=int, default=None, help="Process first N files only")
    args = parser.parse_args()

    db_path = args.db
    json_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "002")

    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Deleted existing database: {db_path}")

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    files = sorted(glob(os.path.join(json_dir, "*.json")))
    if args.limit:
        files = files[: args.limit]

    print(f"Found {len(files)} JSON files in {json_dir}")

    di_sql = f"INSERT OR REPLACE INTO Declaration_info ({', '.join(DECLARATION_INFO_COLUMNS)}) VALUES ({', '.join('?' * len(DECLARATION_INFO_COLUMNS))})"
    cd_sql = f"INSERT OR REPLACE INTO Current_declaration ({', '.join(CURRENT_DECLARATION_COLUMNS)}) VALUES ({', '.join('?' * len(CURRENT_DECLARATION_COLUMNS))})"

    di_rows = []
    cd_rows = []
    errors = 0

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            di_data = data.get("Declaration_info", {})
            cd_data = data.get("Current_declaration", {})
            if di_data:
                di_rows.append(extract_row(di_data, DECLARATION_INFO_COLUMNS))
            if cd_data:
                cd_rows.append(extract_row(cd_data, CURRENT_DECLARATION_COLUMNS))
        except Exception as e:
            errors += 1
            print(f"  ERROR processing {os.path.basename(fpath)}: {e}")

    cur.executemany(di_sql, di_rows)
    cur.executemany(cd_sql, cd_rows)
    conn.commit()

    print(f"\nInserted: Declaration_info={len(di_rows)}, Current_declaration={len(cd_rows)}")
    if errors:
        print(f"Errors: {errors}")

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    def q(label, sql):
        cur.execute(sql)
        row = cur.fetchone()
        print(f"{label}: {row[0]}")

    q("1. Declaration_info count", "SELECT COUNT(*) FROM Declaration_info")
    q("2. Current_declaration count", "SELECT COUNT(*) FROM Current_declaration")
    q("3. Current_declaration with city", "SELECT COUNT(*) FROM Current_declaration WHERE city IS NOT NULL")
    q("4. Current_declaration with developer", "SELECT COUNT(*) FROM Current_declaration WHERE developer IS NOT NULL")

    def sample_rows(table, columns):
        cur.execute(f"SELECT MIN(id), MAX(id), COUNT(*) FROM {table}")
        mn, mx, cnt = cur.fetchone()
        print(f"\nSample rows from {table} (min={mn}, max={mx}, count={cnt}):")
        if cnt == 0:
            print("  (no rows)")
            return
        if cnt == 1:
            cur.execute(f"SELECT * FROM {table}")
            for r in cur.fetchall():
                print(f"  {dict(zip(columns, r))}")
            return
        if cnt == 2:
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            for r in cur.fetchall():
                print(f"  {dict(zip(columns, r))}")
            return
        mid_id = mn + (mx - mn) // 2
        for position, pid in [("first", mn), ("middle", mid_id), ("last", mx)]:
            cur.execute(f"SELECT * FROM {table} WHERE id >= ? ORDER BY id LIMIT 1", (pid,))
            r = cur.fetchone()
            if r:
                print(f"  [{position}] {dict(zip(columns, r))}")

    sample_rows("Declaration_info", DECLARATION_INFO_COLUMNS)
    sample_rows("Current_declaration", CURRENT_DECLARATION_COLUMNS)

    cur.execute("SELECT MIN(id), MAX(id) FROM Declaration_info")
    row = cur.fetchone()
    print(f"\n6. Declaration_info id range: {row[0]} .. {row[1]}")

    cur.execute("SELECT MIN(S_total), MAX(S_total), ROUND(AVG(S_total),2) FROM Current_declaration WHERE S_total IS NOT NULL")
    row = cur.fetchone()
    print(f"7. S_total: min={row[0]}, max={row[1]}, avg={row[2]}")

    cur.execute("SELECT MIN(Price_plan), MAX(Price_plan) FROM Current_declaration WHERE Price_plan IS NOT NULL")
    row = cur.fetchone()
    print(f"8. Price_plan: min={row[0]}, max={row[1]}")

    q("9. Current_declaration with N_residential_rooms", "SELECT COUNT(*) FROM Current_declaration WHERE N_residential_rooms IS NOT NULL")
    q("10. Current_declaration with min_S_flat", "SELECT COUNT(*) FROM Current_declaration WHERE min_S_flat IS NOT NULL")

    cur.execute("SELECT COUNT(*) FROM Current_declaration WHERE S_total IS NOT NULL AND S_residential IS NOT NULL AND S_total < S_residential")
    print(f"11. Rows where S_total < S_residential: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM Current_declaration WHERE Price_plan IS NOT NULL AND Price_plan < 0")
    print(f"12. Rows where Price_plan < 0: {cur.fetchone()[0]}")

    conn.close()
    print(f"\nDatabase saved to: {db_path}")


if __name__ == "__main__":
    main()
