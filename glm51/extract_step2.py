#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "output", "001")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "002")
CACHE_PATH = os.path.join(BASE_DIR, "output", "llm_cache.json")
PROMPT_01 = os.path.join(BASE_DIR, "prompts", "01_address_parse.txt")
PROMPT_02 = os.path.join(BASE_DIR, "prompts", "02_developer_clean.txt")
LLM_URL = "http://95.84.168.248:1234/v1/chat/completions"
LLM_MODEL = "local-model"


def parse_date(value):
    if not value:
        return None
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", str(value))
    if not m:
        return None
    d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    return f"{y}-{mo}-{d}"


def parse_numeric(value):
    if not value:
        return None
    s = str(value)
    s = re.sub(r"\s*руб\.?\s*$", "", s)
    s = re.sub(r"\s*м[2²]\s*$", "", s)
    s = re.sub(r"\s*кв\.м\s*$", "", s)
    s = re.sub(r"\s*м\b", "", s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_integer(value):
    if not value:
        return None
    s = str(value).strip()
    if "отсутствуют" in s.lower() or "не указано" in s.lower():
        return None
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", ".")
    try:
        f = float(s)
        return int(f) if f == int(f) else int(f)
    except (ValueError, TypeError):
        return None


def select_finish_period(finish_entries):
    if not finish_entries:
        return None, []
    occ_map = {}
    for e in finish_entries:
        occ = e.get("occurrence")
        sec = e.get("source_section", "")
        val = e.get("value", "")
        if occ not in occ_map:
            occ_map[occ] = {}
        if sec == "17.1.1":
            occ_map[occ]["desc"] = val
        elif sec == "17.1.2":
            occ_map[occ]["date"] = val

    for occ in sorted(occ_map.keys()):
        desc = occ_map[occ].get("desc") or ""
        if "ввод в эксплуатацию" in desc.lower() or "получение разрешения на ввод" in desc.lower():
            return occ_map[occ].get("date"), finish_entries

    all_dates = [occ_map[o].get("date") for o in sorted(occ_map.keys()) if "date" in occ_map[o]]
    return (all_dates[-1] if all_dates else None), finish_entries


def compute_min_s_flat(units):
    if not units:
        return None, None
    flats = []
    for u in units:
        purpose = u.get("purpose") or ""
        if "квартира" in purpose.lower():
            area = parse_numeric(u.get("total_area"))
            if area is not None:
                flats.append((area, u))
    if not flats:
        return None, None
    min_flat = min(flats, key=lambda x: x[0])
    return min_flat[0], {
        "purpose": min_flat[1].get("purpose"),
        "total_area": min_flat[1].get("total_area"),
        "conditional_number": min_flat[1].get("conditional_number"),
    }


def sum_loan_amounts(loan_entries):
    if not loan_entries:
        return None, []
    parsed = []
    for e in loan_entries:
        v = e.get("value", "")
        if not v or "руб" not in v:
            continue
        val = parse_numeric(v)
        if val is not None:
            parsed.append(val)
    total = sum(parsed) if parsed else None
    return total, parsed


def get_raw_value(data, key):
    field = data.get("parsed_raw", {}).get(key)
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return field


def llm_call(system_prompt, user_content, max_tokens=200, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.post(
                LLM_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return text
        except Exception as ex:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  LLM error after {retries} attempts: {ex}", file=sys.stderr)
                return None


def parse_address_response(text):
    if not text:
        return {"city": None, "district": None, "street": None, "land_plot": None, "building": None}
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
        return {
            "city": result.get("city"),
            "district": result.get("district"),
            "street": result.get("street"),
            "land_plot": result.get("land_plot"),
            "building": result.get("building"),
        }
    except json.JSONDecodeError:
        print(f"  Failed to parse address JSON: {text[:100]}", file=sys.stderr)
        return {"city": None, "district": None, "street": None, "land_plot": None, "building": None}


def process_deterministic(data):
    pr = data.get("parsed_raw", {})
    raw = data

    date_decl = parse_date(raw.get("date_declaration"))
    start_period = parse_date(get_raw_value(raw, "Start_period"))
    date_expert_raw = get_raw_value(raw, "Date_expert")
    date_expert = parse_date(date_expert_raw)

    s_total = parse_numeric(get_raw_value(raw, "S_total"))
    s_residential = parse_numeric(get_raw_value(raw, "S_residential"))
    s_non_residential = parse_numeric(get_raw_value(raw, "S_non_residential"))
    price_plan = parse_numeric(get_raw_value(raw, "Price_plan"))
    s_land = parse_numeric(get_raw_value(raw, "S_land"))

    n_res = parse_integer(get_raw_value(raw, "N_residential_rooms"))
    n_non_res = parse_integer(get_raw_value(raw, "N_non_residential_rooms"))
    parking = parse_integer(get_raw_value(raw, "parking"))
    other_rooms = parse_integer(get_raw_value(raw, "other_rooms"))

    finish_raw = pr.get("Finish_period", [])
    finish_value, finish_all = select_finish_period(finish_raw)

    units_raw = pr.get("residential_units_raw", {})
    units = units_raw.get("value", []) if isinstance(units_raw, dict) else []
    min_s_flat, min_s_flat_source = compute_min_s_flat(units)

    loan_raw = pr.get("loan_amounts_19_6_1_4_raw", [])
    loan_sum, loan_parsed = sum_loan_amounts(loan_raw)

    obj_id = raw.get("id")
    try:
        obj_id = int(obj_id)
    except (ValueError, TypeError):
        pass

    result = {
        "source_file": raw.get("source_file"),
        "id": obj_id,
        "N_declaration": raw.get("N_declaration"),
        "date_declaration": date_decl,
        "Declaration_info": {
            "id": obj_id,
            "name": get_raw_value(raw, "name"),
            "N_declaration": raw.get("N_declaration"),
            "date_declaration": date_decl,
        },
        "Current_declaration": {
            "id": obj_id,
            "N_declaration": raw.get("N_declaration"),
            "date_declaration": date_decl,
            "name": get_raw_value(raw, "name"),
            "developer": None,
            "city": None,
            "district": None,
            "street": None,
            "land_plot": None,
            "building": None,
            "subject": get_raw_value(raw, "subject"),
            "region": get_raw_value(raw, "region"),
            "S_total": s_total,
            "S_residential": s_residential,
            "S_non_residential": s_non_residential,
            "Price_plan": price_plan,
            "S_land": s_land,
            "Start_period": start_period,
            "Finish_period": finish_value,
            "Date_expert": date_expert,
            "material_walls": get_raw_value(raw, "material_walls"),
            "material_covering": get_raw_value(raw, "material_covering"),
            "energy_class": get_raw_value(raw, "energy_class"),
            "max_height": get_raw_value(raw, "max_height"),
            "N_residential_rooms": n_res,
            "N_non_residential_rooms": n_non_res,
            "parking": parking,
            "other_rooms": other_rooms,
            "min_S_flat": min_s_flat,
            "other_rooms_19_6_1_4": loan_sum,
            "other_info": get_raw_value(raw, "other_info"),
        },
        "debug": {
            "address_raw": get_raw_value(raw, "address_raw"),
            "developer_raw": get_raw_value(raw, "developer"),
            "address_llm_response": None,
            "developer_llm_response": None,
            "loan_amounts_parsed": loan_parsed,
            "min_S_flat_source": min_s_flat_source,
            "Finish_period_selected": None,
            "Finish_period_all": finish_all,
        },
    }

    if finish_value:
        for e in finish_raw:
            if e.get("source_section") == "17.1.2" and e.get("value") == finish_value:
                result["debug"]["Finish_period_selected"] = {
                    "occurrence": e.get("occurrence"),
                    "value": finish_value,
                }
                break
        if result["debug"]["Finish_period_selected"] is None:
            result["debug"]["Finish_period_selected"] = {"value": finish_value}

    return result


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"addresses": {}, "developers": {}}
    return {"addresses": {}, "developers": {}}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Step 2: Process 001 JSON → 002 JSON")
    parser.add_argument("--sample", action="store_true", help="Process only 5 files")
    parser.add_argument("--files", nargs="+", help="Specific filenames to process")
    parser.add_argument("--limit", type=int, help="Process first N files")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM calls, use cache only")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.json")))

    if args.files:
        target_names = {os.path.basename(f) for f in args.files}
        all_files = [f for f in all_files if os.path.basename(f) in target_names]
    elif args.sample:
        all_files = all_files[:5]
    elif args.limit:
        all_files = all_files[: args.limit]

    if not all_files:
        print("No files to process.")
        return

    print(f"Processing {len(all_files)} files...")

    all_data = []
    for fpath in all_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_data.append(data)
        except Exception as ex:
            print(f"  Skipping malformed file {os.path.basename(fpath)}: {ex}", file=sys.stderr)

    results = []
    for i, data in enumerate(all_data):
        try:
            result = process_deterministic(data)
            results.append(result)
        except Exception as ex:
            print(f"  Error processing {data.get('source_file', '?')}: {ex}", file=sys.stderr)

    if not args.no_llm:
        cache = load_cache()
        addr_prompt = open(PROMPT_01, "r", encoding="utf-8").read().strip()
        dev_prompt = open(PROMPT_02, "r", encoding="utf-8").read().strip()

        unique_addrs = {}
        unique_devs = {}
        for r in results:
            ar = r["debug"]["address_raw"]
            if ar:
                unique_addrs[ar] = True
            dr = r["debug"]["developer_raw"]
            if dr:
                unique_devs[dr] = True

        new_addrs = [a for a in unique_addrs if a not in cache["addresses"]]
        new_devs = [d for d in unique_devs if d not in cache["developers"]]

        print(f"Unique addresses: {len(unique_addrs)} total, {len(new_addrs)} new")
        print(f"Unique developers: {len(unique_devs)} total, {len(new_devs)} new")

        for idx, addr in enumerate(new_addrs):
            resp = llm_call(addr_prompt, addr, max_tokens=200)
            cache["addresses"][addr] = resp
            parsed = parse_address_response(resp)
            if (idx + 1) % 25 == 0 or idx == len(new_addrs) - 1:
                print(f"  Addresses: {idx + 1}/{len(new_addrs)}")
            time.sleep(0.05)

        for idx, dev in enumerate(new_devs):
            resp = llm_call(dev_prompt, dev, max_tokens=100)
            cache["developers"][dev] = resp.strip() if resp else None
            if (idx + 1) % 25 == 0 or idx == len(new_devs) - 1:
                print(f"  Developers: {idx + 1}/{len(new_devs)}")
            time.sleep(0.05)

        save_cache(cache)

    cache = load_cache()

    for r in results:
        ar = r["debug"]["address_raw"]
        dr = r["debug"]["developer_raw"]

        addr_resp = cache["addresses"].get(ar) if ar else None
        addr_parsed = parse_address_response(addr_resp) if addr_resp else {
            "city": None, "district": None, "street": None, "land_plot": None, "building": None
        }
        r["Current_declaration"]["city"] = addr_parsed["city"]
        r["Current_declaration"]["district"] = addr_parsed["district"]
        r["Current_declaration"]["street"] = addr_parsed["street"]
        r["Current_declaration"]["land_plot"] = addr_parsed["land_plot"]
        r["Current_declaration"]["building"] = addr_parsed["building"]
        r["debug"]["address_llm_response"] = addr_resp

        dev_clean = cache["developers"].get(dr) if dr else None
        r["Current_declaration"]["developer"] = dev_clean
        r["debug"]["developer_llm_response"] = dev_clean

    saved = 0
    for r in results:
        src = r.get("source_file", "")
        stem = os.path.splitext(src)[0] if src else str(r.get("id", "unknown"))
        out_path = os.path.join(OUTPUT_DIR, stem + ".json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            saved += 1
        except Exception as ex:
            print(f"  Error writing {out_path}: {ex}", file=sys.stderr)

        if saved % 25 == 0 and saved > 0:
            print(f"  Saved {saved}/{len(results)} files")

    null_counts = {}
    for r in results:
        cd = r.get("Current_declaration", {})
        for k, v in cd.items():
            if v is None:
                null_counts[k] = null_counts.get(k, 0) + 1

    print(f"\nDone. Processed {len(results)} files, saved {saved} to {OUTPUT_DIR}")
    if null_counts:
        print("Fields with null values:")
        for k in sorted(null_counts):
            print(f"  {k}: {null_counts[k]}/{len(results)}")


if __name__ == "__main__":
    main()
