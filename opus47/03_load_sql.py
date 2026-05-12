"""
Step 3: load cleaned JSONs from output/002/ into a SQLite database
(output/003/dom_rf.db) with two tables:

- Declaration_info     — one row per unique project id (id, name, N_declaration, date_declaration)
- Current_declaration  — full latest version per project (31 fields)

Field type choices were sized against the actual data ranges in output/002/:
  id: 7531..70846 unique           → INTEGER PRIMARY KEY
  area / money / min_S_flat        → NUMERIC (largest seen: 238.6e9 ₽ — fits 64-bit double easily)
  counts                           → INTEGER (largest seen: 3235)
  dates                            → TEXT (ISO 8601, 10 chars; SQLite stores DATE as TEXT)
  free text (name 476, address 388, material_walls 1080, other_info 3308) → TEXT (no length cap in SQLite)

JSON → SQL column-name mapping (intro.md → instruction.md):
  entity              → subject
  S_non-residential   → S_non_residential
  N_non-residential_rooms → N_non_residential_rooms

Run:
    python3 03_load_sql.py
    python3 03_load_sql.py --db /path/to/custom.db
"""

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "output" / "002"
DEFAULT_DB = ROOT / "output" / "003" / "dom_rf.db"

DECLARATION_INFO_DDL = """
CREATE TABLE Declaration_info (
    id               BIGINT PRIMARY KEY,
    name             TEXT NOT NULL,
    N_declaration    TEXT NOT NULL,
    date_declaration DATE NOT NULL
)
"""

CURRENT_DECLARATION_DDL = """
CREATE TABLE Current_declaration (
    id                      BIGINT PRIMARY KEY REFERENCES Declaration_info(id),
    N_declaration           TEXT NOT NULL,
    date_declaration        DATE NOT NULL,
    name                    TEXT NOT NULL,
    developer               TEXT,
    city                    TEXT,
    district                TEXT,
    street                  TEXT,
    land_plot               TEXT,
    building                TEXT,
    subject                 TEXT,
    region                  TEXT,
    S_total                 NUMERIC,
    S_residential           NUMERIC,
    S_non_residential       NUMERIC,
    Price_plan              NUMERIC,
    S_land                  NUMERIC,
    Start_period            DATE,
    Finish_period           TEXT,
    Date_expert             DATE,
    material_walls          TEXT,
    material_covering       TEXT,
    energy_class            TEXT,
    max_height              TEXT,
    N_residential_rooms     INTEGER,
    N_non_residential_rooms INTEGER,
    parking                 INTEGER,
    other_rooms             INTEGER,
    min_S_flat              NUMERIC,
    other_rooms_19_6_1_4    NUMERIC,
    other_info              TEXT
)
"""

# JSON keys that need to be renamed before insertion.
JSON_TO_SQL_RENAMES = {
    "entity": "subject",
    "S_non-residential": "S_non_residential",
    "N_non-residential_rooms": "N_non_residential_rooms",
}

CURRENT_COLUMNS = [
    "id", "N_declaration", "date_declaration", "name", "developer",
    "city", "district", "street", "land_plot", "building",
    "subject", "region",
    "S_total", "S_residential", "S_non_residential", "Price_plan", "S_land",
    "Start_period", "Finish_period", "Date_expert",
    "material_walls", "material_covering", "energy_class", "max_height",
    "N_residential_rooms", "N_non_residential_rooms", "parking", "other_rooms",
    "min_S_flat", "other_rooms_19_6_1_4", "other_info",
]
INFO_COLUMNS = ["id", "name", "N_declaration", "date_declaration"]


def to_sql_row(rec, columns):
    """Map a cleaned-JSON record onto an ordered tuple matching the SQL column list."""
    out = []
    for col in columns:
        # If a JSON key needs to be renamed, look it up under the original.
        json_key = next((j for j, s in JSON_TO_SQL_RENAMES.items() if s == col), col)
        out.append(rec.get(json_key))
    return tuple(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"path to SQLite db (default: {DEFAULT_DB})")
    parser.add_argument("--input", default=str(INPUT_DIR),
                        help=f"path to cleaned JSON dir (default: {INPUT_DIR})")
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
        print(f"Removed existing db at {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    cur = conn.cursor()
    cur.execute(DECLARATION_INFO_DDL)
    cur.execute(CURRENT_DECLARATION_DDL)
    print(f"Created tables in {db_path}")

    json_files = sorted(Path(args.input).glob("*.json"))
    print(f"Loading {len(json_files)} JSON file(s) from {args.input}")

    info_inserted = 0
    current_inserted = 0
    skipped = []

    for jf in json_files:
        rec = json.loads(jf.read_text(encoding="utf-8"))
        if rec.get("id") is None:
            skipped.append((jf.name, "no id"))
            continue
        # Declaration_info
        info_row = to_sql_row(rec, INFO_COLUMNS)
        try:
            cur.execute(
                f"INSERT INTO Declaration_info ({', '.join(INFO_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(INFO_COLUMNS))})",
                info_row,
            )
            info_inserted += 1
        except sqlite3.IntegrityError as e:
            skipped.append((jf.name, f"info insert: {e}"))
            continue

        # Current_declaration
        cur_row = to_sql_row(rec, CURRENT_COLUMNS)
        try:
            cur.execute(
                f"INSERT INTO Current_declaration ({', '.join(CURRENT_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(CURRENT_COLUMNS))})",
                cur_row,
            )
            current_inserted += 1
        except sqlite3.IntegrityError as e:
            skipped.append((jf.name, f"current insert: {e}"))
            continue

    conn.commit()
    conn.close()

    print()
    print(f"Inserted {info_inserted} rows into Declaration_info")
    print(f"Inserted {current_inserted} rows into Current_declaration")
    if skipped:
        print(f"Skipped {len(skipped)} files:")
        for n, why in skipped[:20]:
            print(f"  {n}: {why}")


if __name__ == "__main__":
    main()
