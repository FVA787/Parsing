#!/usr/bin/env python3
"""
Step 1: Raw extraction of DOM.RF declaration .xlsx files into JSON.

Single-pass architecture: walk every row once, building section_rows and units.
After the pass, use lookup functions to populate the output JSON.

Run modes:
    python3 extract_step1.py --sample        # 5 representative files only
    python3 extract_step1.py --files A B C   # named files (basenames or paths)
    python3 extract_step1.py --limit N       # process first N files
    python3 extract_step1.py                 # all files in input/
"""

import argparse
import datetime as dt
import json
import re
import sys
import traceback
from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output" / "001"

SAMPLE_GLOBS = [
    "0008_Жилой*obj66052*.xlsx",
    "0126_АХЕД*obj45298*.xlsx",
    "0175_ЖК*obj30640*.xlsx",
    "0613_СЕТ_obj62614.xlsx",
    "0388_Капитал*obj19620*.xlsx",
]

SECTION_HEADER_RE = re.compile(r"^(\d{1,2}\.\d{1,2})(?:\s*\((\d+)\))?(?:\s|$)")
SECTION_15_2_RE = re.compile(r"^15\.2(?:\s|\(|$)")
NEXT_MAJOR_AFTER_15_2_RE = re.compile(r"^(15\.[3-9]|1[6-9]\.|2\d\.)")
CODE_STRING_RE = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,4}$")

SINGLE_VALUE_FIELDS = {
    "name": "9.2.2",
    "developer": "1.1.2",
    "address_raw": "9.2.17",
    "subject": "9.2.3",
    "region": "9.2.8",
    "S_total": "9.2.21",
    "S_residential": "9.3.1",
    "S_non_residential": "9.3.2",
    "Price_plan": "18.1.1",
    "S_land": "12.3.2",
    "Start_period": "11.1.2",
    "Date_expert": "10.4.2",
    "material_walls": "9.2.22",
    "material_covering": "9.2.23",
    "energy_class": "9.2.24",
    "max_height": "13.2.3",
    "N_residential_rooms": "15.1.1",
    "N_non_residential_rooms": "15.1.2",
    "parking": "15.1.2.1",
    "other_rooms": "15.1.2.2",
    "other_info": "23.1.1",
}

UNIT_HEADER_LABELS = {
    "Условный номер": "conditional_number",
    "Назначение": "purpose",
    "Этаж расположения": "floor",
    "Номер подъезда": "entrance",
    "Общая жилая площадь": "living_area",
    "Общая площадь": "total_area",
    "Количество комнат": "rooms_count",
    "Высота потолков": "ceiling_height",
}
SORTED_UNIT_LABELS = sorted(UNIT_HEADER_LABELS.items(), key=lambda kv: -len(kv[0]))


def cell_to_str(value):
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    s = str(value)
    return s


def extract_id(filename):
    m = re.search(r"obj(\d+)", filename)
    return m.group(1) if m else None


def is_secondary_object(s):
    return bool(re.search(r"\(\d+\)$", s)) if s else False


def sanitize_filename(name):
    return re.sub(r"[^\w\-.]", "_", name)[:80]


def parse_title_block(text):
    if not text:
        return None, None
    m_num = re.search(r"№\s*(\S+)", text)
    m_date = re.search(r"от\s*(\d{1,2}\.\d{1,2}\.\d{4})", text)
    return (m_num.group(1) if m_num else None,
            m_date.group(1) if m_date else None)


def find_first(rows, section, occurrence=1):
    for r in rows:
        if r["section"] == section and r["occurrence"] == occurrence:
            return {
                "source_section": section,
                "value": r["value"],
            }
    return None


def find_all_section(rows, section):
    return [
        {
            "occurrence": r["occurrence"],
            "source_section": r["section"],
            "value": r["value"],
        }
        for r in rows
        if r["section"] == section
    ]


def find_all_in_group_starting_with(rows, prefix):
    return [
        {
            "occurrence": r["occurrence"],
            "source_section": r["section"],
            "value": r["value"],
        }
        for r in rows
        if r["section"].startswith(prefix)
    ]


def extract_value_from_row(col_to_cell, code_col):
    for idx in sorted(col_to_cell):
        if idx <= code_col:
            continue
        cell = col_to_cell[idx]
        if cell.value is not None:
            raw = cell_to_str(cell.value)
            if raw and ":\n" in raw:
                return raw.split("\n", 1)[1].strip()
            return raw
    return None


def process_file(filepath, filename):
    obj_id = extract_id(filename)
    if obj_id is None:
        return None, f"Cannot extract ID from filename: {filename}"

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    title_block = None
    current_section = None
    current_occurrence = 1
    sub_counter = 0

    in_15_2 = False
    unit_col_map = {}

    section_rows = []
    apartments = []
    apt_note = None

    for row_idx, row in enumerate(ws.iter_rows(min_row=1), start=1):
        if not row:
            continue

        if row_idx == 1 and title_block is None:
            first = row[0]
            if hasattr(first, "value") and first.value is not None:
                title_block = cell_to_str(first.value)

        col_to_cell = {c.column: c for c in row if hasattr(c, "column")}

        a_cell = col_to_cell.get(1)
        a_val = a_cell.value if a_cell else None
        a_str = a_val.strip() if isinstance(a_val, str) else ""

        is_15_2_header = bool(a_str) and SECTION_15_2_RE.match(a_str)
        next_major_after_15_2 = bool(a_str) and NEXT_MAJOR_AFTER_15_2_RE.match(a_str)

        m = SECTION_HEADER_RE.match(a_str) if a_str else None
        if m:
            current_section = m.group(1)
            current_occurrence = int(m.group(2)) if m.group(2) else 1
            sub_counter = 0
            if is_15_2_header:
                in_15_2 = True
                unit_col_map = {}
            elif in_15_2 and next_major_after_15_2:
                in_15_2 = False
                unit_col_map = {}
            elif in_15_2:
                in_15_2 = False
                unit_col_map = {}

        if in_15_2:
            if not unit_col_map:
                mapping = {}
                for cell in row:
                    if cell.value is None:
                        continue
                    v = str(cell.value).strip()
                    for label, field in SORTED_UNIT_LABELS:
                        if label in v and field not in mapping:
                            mapping[field] = cell.column
                            break
                if "conditional_number" in mapping and "total_area" in mapping:
                    unit_col_map = mapping
                continue

            apt = {}
            has_any = False
            for fn, ci in unit_col_map.items():
                c = col_to_cell.get(ci)
                cv = c.value if c else None
                if cv is not None:
                    if isinstance(cv, float) and cv == int(cv):
                        apt[fn] = str(int(cv))
                    else:
                        apt[fn] = str(cv).strip()
                    has_any = True
                else:
                    apt[fn] = None
            if has_any:
                apartments.append(apt)
            else:
                in_15_2 = False
                unit_col_map = {}
            continue

        code_cell = None
        code_col = None
        for idx in sorted(col_to_cell):
            if idx == 1 or idx > 20:
                continue
            cell = col_to_cell[idx]
            v = cell.value
            if v is None:
                continue
            if isinstance(v, str) and CODE_STRING_RE.match(v.strip()):
                code_cell = cell
                code_col = idx
                break
            if isinstance(v, dt.datetime):
                code_cell = cell
                code_col = idx
                break
        if code_cell is None:
            continue

        value = extract_value_from_row(col_to_cell, code_col)
        if value is None:
            continue

        if current_section is None:
            continue

        sub_counter += 1
        cv = code_cell.value
        inferred = None
        if isinstance(cv, str) and CODE_STRING_RE.match(cv.strip()):
            inferred = cv.strip()
        if inferred is None:
            inferred = f"{current_section}.{sub_counter}"

        if is_secondary_object(inferred):
            continue

        section_rows.append({
            "section": inferred,
            "section_group": current_section,
            "occurrence": current_occurrence,
            "value": value,
            "row": row_idx,
        })

    wb.close()

    n_decl, date_decl = parse_title_block(title_block)

    if not section_rows:
        return None, f"No section rows found in {filename}"

    parsed_raw = {}

    for field_name, target_sec in SINGLE_VALUE_FIELDS.items():
        parsed_raw[field_name] = find_first(section_rows, target_sec)

    finish_entries = find_all_in_group_starting_with(section_rows, "17.1.")
    parsed_raw["Finish_period"] = finish_entries

    if apt_note:
        parsed_raw["residential_units_raw"] = {
            "source_section": "15.2.1",
            "value": apartments,
            "note": apt_note,
        }
    else:
        parsed_raw["residential_units_raw"] = {
            "source_section": "15.2.1",
            "value": apartments,
        }

    loan_entries = find_all_section(section_rows, "19.6.1.4")
    parsed_raw["loan_amounts_19_6_1_4_raw"] = loan_entries

    return {
        "source_file": filename,
        "id": obj_id,
        "N_declaration": n_decl,
        "date_declaration": date_decl,
        "parsed_raw": parsed_raw,
    }, None


def select_files(args):
    if args.files:
        out = []
        for f in args.files:
            p = Path(f)
            if not p.is_absolute() and not p.exists():
                p = INPUT_DIR / f
            if p.is_dir():
                out.extend(sorted(p.glob("*.xlsx")))
            else:
                out.append(p)
        return out
    if args.sample:
        out = []
        for pattern in SAMPLE_GLOBS:
            matches = sorted(p for p in INPUT_DIR.glob(pattern) if not p.name.startswith("~$"))
            if not matches:
                print(f"WARN: no match for sample pattern {pattern}", file=sys.stderr)
            out.extend(matches[:1])
        return out
    return sorted(p for p in INPUT_DIR.glob("*.xlsx") if not p.name.startswith("~$"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    files = select_files(args)
    if args.limit:
        files = files[:args.limit]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Processing {len(files)} file(s) -> {OUTPUT_DIR}", flush=True)

    missing_counter = Counter()
    error_files = []
    ok = 0

    for i, path in enumerate(files, 1):
        try:
            result, error = process_file(path, path.name)
            if error:
                error_files.append((path.name, error))
                print(f"  [{i}/{len(files)}] ERROR: {path.name}: {error}", flush=True)
                continue

            obj_id = result["id"]
            sanitized = sanitize_filename(path.stem)
            out_name = f"{obj_id}_{sanitized}.json"
            out_path = OUTPUT_DIR / out_name

            n_fields = sum(
                1 for v in result["parsed_raw"].values()
                if isinstance(v, dict) and v.get("value") is not None
            )
            ru = result["parsed_raw"].get("residential_units_raw", {})
            n_apt = len(ru.get("value", [])) if isinstance(ru.get("value"), list) else 0
            n_loans = len(result["parsed_raw"].get("loan_amounts_19_6_1_4_raw", []))

            print(
                f"  [{i}/{len(files)}] {path.name[:50]} id={obj_id} "
                f"fields={n_fields} apts={n_apt} loans={n_loans}",
                flush=True,
            )

            with out_path.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            ok += 1

            parsed = result["parsed_raw"]
            for k, v in parsed.items():
                if v is None or v == []:
                    missing_counter[k] += 1
                elif isinstance(v, dict) and v.get("value") in (None, ""):
                    missing_counter[k] += 1

        except Exception as e:
            error_files.append((path.name, repr(e)))
            print(f"  [{i}/{len(files)}] EXCEPTION: {path.name}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

    print()
    print(f"Wrote {ok}/{len(files)} JSON files.")
    if error_files:
        print(f"Errors: {len(error_files)}")
        for n, e in error_files[:20]:
            print(f"  {n}: {e}")
        if len(error_files) > 20:
            print(f"  ... and {len(error_files) - 20} more")
    if missing_counter:
        print("Missing-field counts:")
        for k, v in missing_counter.most_common():
            print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
