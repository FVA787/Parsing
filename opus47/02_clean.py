"""
Step 2: clean / normalize the raw JSONs in output/001/ and write SQL-ready
JSONs to output/002/.

Deterministic for everything that's predictable (label stripping, number
parsing, date conversion, min_S_flat filter, sum of 19.6.1.4). LLM-assisted
for the two fields where Russian text is variable enough to break regex:
address parsing and Finish_period selection.

Run modes:
    python3 02_clean.py --sample           # 5 representative files
    python3 02_clean.py --files A B ...    # specific basenames
    python3 02_clean.py                    # all files in output/001/
    python3 02_clean.py --force            # overwrite existing output/002 files
"""

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "output" / "001"
OUTPUT_DIR = ROOT / "output" / "002"

SAMPLE_BASENAMES = [
    "0002_Прокшино_27629523_obj67507-pd77-003240.json",
    "0613_СЕТ_obj62614.json",
    "0612_Оне_obj68245.json",
    "0100_INDY Towers_ИНДИ Тауэрз_36573245_obj65452-pd77-003186.json",
    "0388_Капитал Тауэрс _Capital Towers_00408594_obj19620-pd77-000770.json",
]

UNIT_TOKENS = ["руб.", "руб", "кв.м", "кв. м", "кв.метр",
               "м²", "м2", "м.", "²"]

EMPTY_ADDRESS = {"city": None, "district": None, "street": None,
                 "land_plot": None, "building": None}


# ─── Deterministic helpers ────────────────────────────────────────────────

def strip_label(s):
    """'Label: Value' → 'Value'. Falls back to original if no ': ' found."""
    if s is None:
        return None
    i = s.find(": ")
    return s[i + 2:].strip() if i >= 0 else s.strip()


def text_value(field):
    """Pull the {value} out of a {source_section, value, cell} dict and
    strip the label prefix. Returns None for missing fields."""
    if not field or not isinstance(field, dict):
        return None
    return strip_label(field.get("value"))


_ABSENT_RE = re.compile(r"отсутству", re.IGNORECASE)


def parse_number(s):
    """Extract a float from a (possibly labeled, possibly unit-suffixed)
    Russian-formatted number string. Returns None if no number is parseable.

    Accepted: '11 214 564 000,00 руб.', '17439.3 м2', '682', '0', '—'.
    Phrases like 'отсутствуют' / 'отсутствует' return 0.0 (the spec
    explicitly asserts the counted area / amount is zero).
    """
    if s is None:
        return None
    text = strip_label(s)
    if text is None or text == "":
        return None
    if _ABSENT_RE.search(text):
        return 0.0
    for unit in UNIT_TOKENS:
        text = text.replace(unit, "")
    # Keep only digits, dots, commas, minus
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text or text in ("-", ".", ","):
        return None
    text = text.replace(",", ".")
    # If multiple dots, keep only the last one as decimal separator.
    parts = text.split(".")
    if len(parts) > 2:
        text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(s):
    """Like parse_number but returns int. Treats 'отсутствуют' / 'не предусмотрено' /
    'отсутствуют' phrases as 0 — these declarations explicitly assert that the
    counted item is absent (e.g. 'Жилые помещения отсутствуют')."""
    if s is None:
        return None
    if isinstance(s, str) and _ABSENT_RE.search(s):
        return 0
    n = parse_number(s)
    if n is None:
        return None
    try:
        return int(n)
    except (ValueError, OverflowError):
        return None


def parse_date(s):
    """DD.MM.YYYY → YYYY-MM-DD. Returns None if no date pattern is found."""
    if s is None:
        return None
    text = strip_label(s)
    if text is None:
        return None
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def find_min_kvartira(units):
    """Return the minimum total_area among units whose purpose contains
    'квартир' (case-insensitive). Returns None if no eligible unit found."""
    if not units:
        return None
    areas = []
    for u in units:
        purpose = (u.get("purpose") or "").lower()
        if "квартир" not in purpose:
            continue
        area_str = u.get("total_area")
        if area_str is None:
            continue
        try:
            areas.append(float(str(area_str).replace(",", ".")))
        except ValueError:
            continue
    return min(areas) if areas else None


def sum_loans(loan_array):
    """Sum every parseable 19.6.1.4 value. Returns None if no values found."""
    if not loan_array:
        return None
    total = 0.0
    any_found = False
    for entry in loan_array:
        n = parse_number(entry.get("value"))
        if n is not None:
            total += n
            any_found = True
    return total if any_found else None


# ─── LLM-assisted helpers ─────────────────────────────────────────────────

_MOSCOW_RE = re.compile(r"москв", re.IGNORECASE)


def fallback_city_from_entity(entity_text):
    """If the AI couldn't read a city from the address, derive one from
    section 9.2.3 (entity), which is always something like 'Город Москва' /
    'ГОРОД МОСКВА' / 'Московская область'.
    """
    if not entity_text:
        return None
    s = entity_text.strip()
    # 'Город Москва' → 'Москва', 'г Москва' → 'Москва'
    s = re.sub(r"^(?:Город|ГОРОД|г\.?|Г\.?)\s+", "", s).strip()
    if not s:
        return None
    return s.title() if s.isupper() else s


def parse_address_via_llm(address_text, entity_text):
    addr_out = dict(EMPTY_ADDRESS)
    err = None
    if address_text:
        try:
            result = llm.call_prompt_json(
                "01_address",
                {"ADDRESS": address_text},
                max_tokens=200,
            )
            for k in EMPTY_ADDRESS:
                addr_out[k] = result.get(k)
        except Exception as e:
            err = repr(e)
    # City fallback: when the address didn't mention Moscow but the entity does.
    if addr_out["city"] is None and entity_text and _MOSCOW_RE.search(entity_text):
        addr_out["city"] = "Москва"
    elif addr_out["city"] is None and entity_text:
        addr_out["city"] = fallback_city_from_entity(entity_text)
    return addr_out, err


def select_finish_period_via_llm(fp_array):
    """Returns (date_string_or_None, warning_or_None)."""
    if not fp_array:
        return None, None
    events = [e for e in fp_array if e.get("source_section") == "17.1.1"]
    dates = [e for e in fp_array if e.get("source_section") == "17.1.2"]
    if not events or not dates:
        return None, "no 17.1.1/17.1.2 entries"
    # Build numbered events list (label-stripped for clarity)
    text = "\n".join(
        f"{i + 1}. {strip_label(e.get('value'))}"
        for i, e in enumerate(events)
    )
    try:
        result = llm.call_prompt_json(
            "02_finish_period",
            {"EVENTS": text},
            max_tokens=64,
        )
        idx = result.get("index") if isinstance(result, dict) else None
        if idx is None:
            return None, "no commissioning event found"
        if not (1 <= idx <= len(dates)):
            return None, f"index {idx} out of range (1..{len(dates)})"
        return strip_label(dates[idx - 1].get("value")), None
    except Exception as e:
        return None, repr(e)


# ─── Per-file processing ─────────────────────────────────────────────────

def clean_one(raw):
    """Transform one parsed_raw record into the cleaned record."""
    pr = raw["parsed_raw"]
    warnings = []

    # Address parsing - one LLM call. Skip if no address present.
    address_text = text_value(pr.get("address"))
    entity_text = text_value(pr.get("entity"))
    addr_parts, addr_err = parse_address_via_llm(address_text, entity_text)
    if addr_err:
        warnings.append(f"address LLM: {addr_err}")

    # Finish_period selection - one LLM call. Skip if no events.
    fp_value, fp_err = select_finish_period_via_llm(pr.get("Finish_period") or [])
    if fp_err:
        warnings.append(f"Finish_period: {fp_err}")

    out = {
        "source_file": raw.get("source_file"),
        "id": int(pr["id"]) if pr.get("id") and str(pr["id"]).isdigit() else pr.get("id"),
        "N_declaration": pr.get("N_declaration"),
        "date_declaration": parse_date(pr.get("date_declaration")),
        "name": text_value(pr.get("name")),
        "developer": text_value(pr.get("developer")),
        "address": address_text,
        "city": addr_parts.get("city"),
        "district": addr_parts.get("district"),
        "street": addr_parts.get("street"),
        "land_plot": addr_parts.get("land_plot"),
        "building": addr_parts.get("building"),
        "entity": text_value(pr.get("entity")),
        "region": text_value(pr.get("region")),
        "S_total": parse_number(pr.get("S_total", {}).get("value") if pr.get("S_total") else None),
        "S_residential": parse_number(pr.get("S_residential", {}).get("value") if pr.get("S_residential") else None),
        "S_non-residential": parse_number(pr.get("S_non-residential", {}).get("value") if pr.get("S_non-residential") else None),
        "Price_plan": parse_number(pr.get("Price_plan", {}).get("value") if pr.get("Price_plan") else None),
        "S_land": parse_number(pr.get("S_land", {}).get("value") if pr.get("S_land") else None),
        "Start_period": parse_date(pr.get("Start_period", {}).get("value") if pr.get("Start_period") else None),
        "Finish_period": fp_value,
        "Date_expert": parse_date(pr.get("Date_expert", {}).get("value") if pr.get("Date_expert") else None),
        "material_walls": text_value(pr.get("material_walls")),
        "material_covering": text_value(pr.get("material_covering")),
        "energy_class": text_value(pr.get("energy_class")),
        "max_height": text_value(pr.get("max_height")),
        "N_residential_rooms": parse_int(pr.get("N_residential_rooms", {}).get("value") if pr.get("N_residential_rooms") else None),
        "N_non-residential_rooms": parse_int(pr.get("N_non-residential_rooms", {}).get("value") if pr.get("N_non-residential_rooms") else None),
        "parking": parse_int(pr.get("parking", {}).get("value") if pr.get("parking") else None),
        "other_rooms": parse_int(pr.get("other_rooms", {}).get("value") if pr.get("other_rooms") else None),
        "min_S_flat": find_min_kvartira(pr.get("min_S_flat") or []),
        "other_rooms_19_6_1_4": sum_loans(pr.get("other_rooms_19_6_1_4") or []),
        "other_info": text_value(pr.get("other_info")),
    }
    if warnings:
        out["_warnings"] = warnings
    return out


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
                out.extend(sorted(p.glob("*.json")))
            elif p.exists():
                out.append(p)
            else:
                print(f"WARN: not found: {f}", file=sys.stderr)
        return out
    if args.sample:
        out = []
        for name in SAMPLE_BASENAMES:
            p = INPUT_DIR / name
            if p.exists():
                out.append(p)
            else:
                print(f"WARN: sample missing: {name}", file=sys.stderr)
        return out
    return sorted(INPUT_DIR.glob("*.json"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true",
                        help="re-process files that already have an output JSON")
    args = parser.parse_args()

    files = select_files(args)
    if args.limit:
        files = files[: args.limit]

    print(f"Processing {len(files)} file(s) -> {OUTPUT_DIR}", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ok = 0
    skipped = 0
    errors = []
    null_counts = Counter()
    warn_counts = Counter()
    t0 = time.time()

    for i, in_path in enumerate(files, 1):
        out_path = OUTPUT_DIR / in_path.name
        if out_path.exists() and not args.force:
            skipped += 1
            continue
        try:
            raw = json.loads(in_path.read_text(encoding="utf-8"))
            cleaned = clean_one(raw)
            write_json(out_path, cleaned)
            ok += 1

            for k, v in cleaned.items():
                if k == "_warnings":
                    for w in v:
                        warn_counts[w[:60]] += 1
                    continue
                if v is None:
                    null_counts[k] += 1

            if i % 25 == 0 or i == len(files):
                elapsed = time.time() - t0
                rate = ok / elapsed if elapsed > 0 else 0
                eta = (len(files) - i) / rate if rate > 0 else 0
                print(f"  [{i}/{len(files)}] {in_path.name[:60]}  "
                      f"({rate:.1f} files/s, ETA {eta:.0f}s)", flush=True)
        except Exception as e:
            errors.append((in_path.name, repr(e)))
            print(f"  ERROR {in_path.name}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

    print()
    print(f"Wrote {ok}/{len(files)} JSON files. Skipped {skipped} (already exist).")
    if errors:
        print(f"Errors: {len(errors)}")
        for n, e in errors[:20]:
            print(f"  {n}: {e}")
    if null_counts:
        print("Null-value counts per field:")
        for k, v in null_counts.most_common():
            print(f"  {v:4d}  {k}")
    if warn_counts:
        print("Warning counts:")
        for k, v in warn_counts.most_common():
            print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
