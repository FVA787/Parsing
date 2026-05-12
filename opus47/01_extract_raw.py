"""
Step 1: Raw extraction of DOM.RF declaration .xlsx files into JSON.

Outputs go to output/001/<basename>.json. No derivation, normalization, or
selection - everything is stored as raw text with source_section preserved,
and multi-occurrence sections are kept as arrays for later disambiguation.

Run modes:
    python3 01_extract_raw.py --sample        # 5 representative files only
    python3 01_extract_raw.py --files A B C   # named files (basenames or paths)
    python3 01_extract_raw.py                 # all files in input/
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
    "0002_Прокшино_*.xlsx",
    "0613_СЕТ_obj62614.xlsx",
    "0612_Оне_obj68245.xlsx",
    "0100_INDY Towers_*.xlsx",
    "0388_Капитал Тауэрс*.xlsx",
]

SECTION_HEADER_RE = re.compile(r"^(\d{1,2}\.\d{1,2})(?:\s*\((\d+)\))?(?:\s|$)")
SECTION_15_2_RE = re.compile(r"^15\.2(?:\s|\(|$)")
NEXT_MAJOR_AFTER_15_2_RE = re.compile(r"^(15\.[3-9]|1[6-9]\.|2\d\.)")
CODE_STRING_RE = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,4}$")

# Excel turns strings that look like dates ("9.2.10", "10.4.2") into datetime
# values when the cell's number_format follows a date-like template. To recover
# the original code we must read cell.number_format and apply the matching
# decode. The decoders below cover every format observed across the 615 files.
# Order matters: longer/more-specific tokens come first so "yy.m.d" doesn't
# accidentally match the "m.d.yy" branch.
DATE_FORMAT_DECODERS = [
    ("yy.m.d", lambda v: f"{v.year - 2000}.{v.month}.{v.day}"),
    ("d.m.yy", lambda v: f"{v.day}.{v.month}.{v.year - 2000}"),
    ("mm.d.yy", lambda v: f"{v.month}.{v.day}.{v.year - 2000}"),
    ("m.d.yy", lambda v: f"{v.month}.{v.day}.{v.year - 2000}"),
]
UNKNOWN_DATETIME_FORMATS = Counter()


def decode_code_cell(cell):
    """Return a canonical section-code string (e.g. "9.2.17") for cells that
    represent section codes; return None for everything else. Datetime cells
    are decoded back to codes via cell.number_format. 4-digit-year formats are
    treated as real dates (not codes) and rejected.
    """
    v = cell.value
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if CODE_STRING_RE.match(s) else None
    if isinstance(v, dt.datetime):
        fmt = (cell.number_format or "").lower()
        if "yyyy" in fmt:
            return None  # real date, not a code
        for token, decoder in DATE_FORMAT_DECODERS:
            if token in fmt:
                decoded = decoder(v)
                return decoded if CODE_STRING_RE.match(decoded) else None
        # Unknown format: log it once and try the most common decoding.
        UNKNOWN_DATETIME_FORMATS[fmt or "<empty>"] += 1
        decoded = f"{v.day}.{v.month}.{v.year - 2000}"
        return decoded if CODE_STRING_RE.match(decoded) else None
    return None

# Field names match intro.md exactly. Two intro.md fields share the name
# "other_rooms" (#28 from 15.1.2.2 and #30 from sum of 19.6.1.4); JSON cannot
# have duplicate keys, so the latter is renamed `other_rooms_19_6_1_4`.
TARGETED_FIELDS = [
    ("name",                    "9.2.2"),
    ("developer",               "1.1.2"),
    ("address",                 "9.2.17"),
    ("entity",                  "9.2.3"),
    ("region",                  "9.2.8"),
    ("S_total",                 "9.2.21"),
    ("S_residential",           "9.3.1"),
    ("S_non-residential",       "9.3.2"),
    ("Price_plan",              "18.1.1"),
    ("S_land",                  "12.3.2"),
    ("Start_period",            "11.1.2"),
    ("Date_expert",             "10.4.2"),
    ("material_walls",          "9.2.22"),
    ("material_covering",       "9.2.23"),
    ("energy_class",            "9.2.24"),
    ("max_height",              "13.2.3"),
    ("N_residential_rooms",     "15.1.1"),
    ("N_non-residential_rooms", "15.1.2"),
    ("parking",                 "15.1.2.1"),
    ("other_rooms",             "15.1.2.2"),
    ("other_info",              "23.1.1"),
]

UNIT_HEADER_LABELS = {
    "Условный номер":          "conditional_number",
    "Назначение":              "purpose",
    "Этаж расположения":       "floor",
    "Номер подъезда":          "entrance",
    "Общая жилая площадь":     "living_area",
    "Общая площадь":           "total_area",
    "Количество комнат":       "rooms_count",
    "Высота потолков":         "ceiling_height",
}
SORTED_UNIT_LABELS = sorted(UNIT_HEADER_LABELS.items(), key=lambda kv: -len(kv[0]))


_WHITESPACE_RUN_RE = re.compile(r"\s+")


def cell_to_str(value):
    """Convert any openpyxl value to a string. Newlines (\\n, \\r) inside
    cell text are replaced with single spaces and runs of whitespace are
    collapsed, so JSON output reads as clean single-line values without
    embedded \\n escapes.
    """
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
    if "\n" in s or "\r" in s or "\t" in s:
        s = _WHITESPACE_RUN_RE.sub(" ", s).strip()
    return s


def extract_id_from_filename(fn):
    m = re.search(r"obj(\d+)", fn)
    return m.group(1) if m else None


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
                "cell": r["value_cell"],
            }
    return None


def find_all_section(rows, section):
    return [
        {
            "occurrence": r["occurrence"],
            "source_section": r["section"],
            "value": r["value"],
            "cell": r["value_cell"],
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
            "cell": r["value_cell"],
        }
        for r in rows
        if r["section"].startswith(prefix)
    ]


def extract_one(path):
    """Single-pass extraction: walk every row once and partition into
    section-row records (subsection lookups) and unit-row records (15.2 table
    rows). Compatible with read_only=True for speed.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    title_block = None
    current_section = None
    current_occurrence = 1

    in_15_2 = False
    unit_col_map = {}      # 1-based column index -> field name
    table_occurrence = 0

    section_rows = []
    units = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=1), start=1):
        if not row:
            continue

        # First row: capture full title block text
        if row_idx == 1 and title_block is None:
            first = row[0]
            if hasattr(first, "value"):
                title_block = cell_to_str(first.value)

        # Index cells by column (1-based) for safe access regardless of tuple length.
        # In read-only mode, EmptyCell placeholders (no .column attribute) appear
        # for sparse cells; skip them since they carry no value anyway.
        col_to_cell = {c.column: c for c in row if hasattr(c, "column")}

        a_cell = col_to_cell.get(1)
        a_val = a_cell.value if a_cell else None
        a_str = a_val.strip() if isinstance(a_val, str) else ""

        # Section header detection
        is_15_2_header = bool(a_str) and SECTION_15_2_RE.match(a_str)
        next_major_after_15_2 = bool(a_str) and NEXT_MAJOR_AFTER_15_2_RE.match(a_str)

        m = SECTION_HEADER_RE.match(a_str) if a_str else None
        if m:
            current_section = m.group(1)
            current_occurrence = int(m.group(2)) if m.group(2) else 1
            if is_15_2_header:
                in_15_2 = True
                table_occurrence += 1
                unit_col_map = {}
            elif in_15_2 and next_major_after_15_2:
                in_15_2 = False
                unit_col_map = {}
            elif in_15_2:
                # Some other section starting with 15.x or earlier - shouldn't happen
                # given our header detection; defensive reset.
                in_15_2 = False
                unit_col_map = {}

        if in_15_2:
            # Inside the 15.2 block: either find the header or read a data row.
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

            # Data row: only keep purpose + total_area, which is what
            # script 2 needs to compute min_S_flat (filter to "Квартира" and
            # take the minimum total_area).
            purpose_col = unit_col_map.get("purpose")
            area_col = unit_col_map.get("total_area")
            purpose = cell_to_str(col_to_cell.get(purpose_col).value) if purpose_col and col_to_cell.get(purpose_col) else None
            area = cell_to_str(col_to_cell.get(area_col).value) if area_col and col_to_cell.get(area_col) else None
            if purpose or area:
                units.append({"purpose": purpose, "total_area": area})
            continue

        # Outside 15.2 - try to extract a regular subsection row.
        # Code cells live in different columns across files (observed: F, G, H,
        # I, J, K, L, M depending on the layout). Walk left-to-right and take
        # the first cell that decodes to a valid section code via
        # decode_code_cell (handles both string codes and datetime-corrupted
        # codes via cell.number_format).
        code_cell = None
        code_col = None
        inferred = None
        for idx in sorted(col_to_cell):
            if idx == 1 or idx > 20:
                continue
            cell = col_to_cell[idx]
            decoded = decode_code_cell(cell)
            if decoded is not None:
                code_cell = cell
                code_col = idx
                inferred = decoded
                break
        if code_cell is None:
            continue

        value_cell = None
        for idx in sorted(col_to_cell):
            if idx <= code_col:
                continue
            cell = col_to_cell[idx]
            if cell.value is not None:
                value_cell = cell
                break
        if value_cell is None:
            continue

        section_rows.append({
            "section": inferred,
            "section_group": current_section,
            "occurrence": current_occurrence,
            "value": cell_to_str(value_cell.value),
            "code_cell": code_cell.coordinate,
            "value_cell": value_cell.coordinate,
            "row": row_idx,
        })

    wb.close()

    n_decl, date_decl = parse_title_block(title_block)

    parsed = {
        "id": extract_id_from_filename(path.name),
        "N_declaration": n_decl,
        "date_declaration": date_decl,
    }
    # Insert the 21 single-section fields in intro.md order (with `address`
    # placed at #6 and `entity` at #11 to match the spec's numbering).
    for json_field, section in TARGETED_FIELDS:
        parsed[json_field] = find_first(section_rows, section)
        # Insert Finish_period right after Start_period (#19), and
        # min_S_flat / other_rooms_19_6_1_4 right after parking/other_rooms.
        if json_field == "Start_period":
            parsed["Finish_period"] = find_all_in_group_starting_with(section_rows, "17.1.")
        if json_field == "other_rooms":
            parsed["min_S_flat"] = units
            parsed["other_rooms_19_6_1_4"] = find_all_section(section_rows, "19.6.1.4")

    return {
        "source_file": path.name,
        "extracted_at": dt.datetime.now().isoformat(timespec="seconds"),
        "parsed_raw": parsed,
    }


def write_json(out_path, data):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        files = files[: args.limit]

    print(f"Processing {len(files)} file(s) -> {OUTPUT_DIR}", flush=True)

    missing_counter = Counter()
    error_files = []
    ok = 0

    for i, path in enumerate(files, 1):
        try:
            data = extract_one(path)
            out_path = OUTPUT_DIR / (path.stem + ".json")
            write_json(out_path, data)
            ok += 1

            parsed = data["parsed_raw"]
            for k, v in parsed.items():
                if v is None or v == [] or (isinstance(v, dict) and v.get("value") in (None, "")):
                    missing_counter[k] += 1

            if i % 25 == 0 or i == len(files):
                print(f"  [{i}/{len(files)}] {path.name}", flush=True)
        except Exception as e:
            error_files.append((path.name, repr(e)))
            print(f"  ERROR on {path.name}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

    print()
    print(f"Wrote {ok}/{len(files)} JSON files.")
    if error_files:
        print(f"Errors: {len(error_files)}")
        for n, e in error_files[:20]:
            print(f"  {n}: {e}")
    if missing_counter:
        print("Missing-field counts:")
        for k, v in missing_counter.most_common():
            print(f"  {v:4d}  {k}")
    if UNKNOWN_DATETIME_FORMATS:
        print("Datetime cells with unrecognised number_format (decoded as d.m.yy):")
        for fmt, n in UNKNOWN_DATETIME_FORMATS.most_common():
            print(f"  {n:4d}  {fmt!r}")


if __name__ == "__main__":
    main()
