#!/usr/bin/env python3
import re, sys, argparse, pandas as pd
from rapidfuzz import fuzz, process
import geonamescache as gc

STOP_LEAD = {
  "ok, since","okay, this","way, had","well, this","however, one",
  "buddhism, and","january, the","sights, smells","ufos, then"
}
PREP = r"(?:in|at|near|by|from|around|outside|inside|on)\s+"
TOKEN = r"[A-Z][\w\-\.'’]+"
CAND_PAT = re.compile(rf"\b{PREP}(({TOKEN})(?:\s+{TOKEN}){{0,3}}(?:,\s*{TOKEN}){{0,2}})\b")

def build_gazetteer():
    g = gc.GeonamesCache()

    # Countries
    countries = g.get_countries()  # { 'US': {... 'name','iso','iso3', ...}, ... }
    countries_by_name = {}
    for c in countries.values():
        nm = c.get('name')
        if nm: countries_by_name[nm] = ('', '', nm)
        for alt in filter(None, [c.get('iso3'), c.get('iso'), nm.replace('United States','USA') if nm else None, nm.replace('United States','US') if nm else None]):
            countries_by_name[alt] = ('', '', nm)

    # US states (handle both 'abbr' and 'code'; fall back to the dict key)
    us_states = g.get_us_states()  # e.g., {'al': {'name':'Alabama','code':'AL'}, ...}
    states_by_name = {}
    for key, s in us_states.items():
        name = s.get('name') or key.upper()
        abbr = s.get('abbr') or s.get('code') or key.upper()
        states_by_name[name] = ('', name, 'United States')
        states_by_name[abbr] = ('', name, 'United States')

    # Cities
    cities = g.get_cities()  # dict of city objects
    city_index = {}
    for _, c in cities.items():
        name = c.get('name')
        if not name: continue
        cc = c.get('countrycode')
        country_name = countries.get(cc, {}).get('name', cc)
        admin1 = c.get('admin1code') or ''
        city_index.setdefault(name, set()).add((name, admin1, country_name))
        # Alternate names
        alts = set()
        if c.get('asciiname'): alts.add(c['asciiname'])
        if isinstance(c.get('alternatenames'), list):
            alts.update([a for a in c['alternatenames'] if a])
        for alt in alts:
            city_index.setdefault(alt, set()).add((name, admin1, country_name))

    city_keys = list(city_index.keys())
    return city_index, city_keys, countries_by_name, states_by_name

CITY_INDEX, CITY_KEYS, COUNTRIES, STATES = build_gazetteer()

def clean_span(span: str) -> str:
    s = span.strip().strip(' .;:!?()[]{}\'"')
    s = re.sub(r"\s+", " ", s)
    return s

def is_junk(s: str) -> bool:
    return s.lower() in STOP_LEAD

def best_place_match(span: str, thresh=92):
    parts = [p.strip() for p in span.split(",") if p.strip()]
    cand = parts[0]
    admin = parts[1] if len(parts) > 1 else ""
    # as city
    match = process.extractOne(cand, CITY_KEYS, scorer=fuzz.WRatio, score_cutoff=thresh)
    city_hit = None
    if match:
        # take any canonical tuple for this key
        city_hit = next(iter(CITY_INDEX[match[0]]))
    # admin refinement
    country_hit = state_hit = None
    if admin:
        s2 = process.extractOne(admin, list(STATES.keys()), scorer=fuzz.WRatio, score_cutoff=thresh)
        if s2: state_hit = STATES[s2[0]]
        c2 = process.extractOne(admin, list(COUNTRIES.keys()), scorer=fuzz.WRatio, score_cutoff=thresh)
        if c2: country_hit = COUNTRIES[c2[0]]
    if city_hit:
        city, admin1, country = city_hit
        if state_hit:
            _, admin1_norm, country_norm = state_hit
            return f"{city}, {admin1_norm}, {country_norm}", 0.95
        if country_hit:
            _, _, country_norm = country_hit
            return f"{city}, {country_norm}", 0.93
        return f"{city}, {country}", 0.90
    if state_hit:
        _, admin1_norm, country_norm = state_hit
        return f"{admin1_norm}, {country_norm}", 0.88
    if country_hit:
        _, _, country_norm = country_hit
        return country_norm, 0.86
    return "", 0.0

def extract_place(text: str):
    if not isinstance(text, str) or not text:
        return ("", "", 0.0)
    best_norm, best_span, best_conf = "", "", 0.0
    for m in CAND_PAT.finditer(text):
        raw = clean_span(m.group(1))
        if not raw or is_junk(raw) or not re.match(r"^[A-Z]", raw):
            continue
        norm, conf = best_place_match(raw, thresh=92)
        if conf > best_conf:
            best_conf, best_norm, best_span = conf, norm, raw
    return (best_span, best_norm, best_conf)

REL_PATTERNS = [
    (re.compile(r"\b(last night|yesterday)\b", re.I), pd.Timedelta(days=1)),
    (re.compile(r"\b(\d+)\s+days?\s+ago\b", re.I), "days"),
    (re.compile(r"\b(\d+)\s+weeks?\s+ago\b", re.I), "weeks"),
    (re.compile(r"\b(\d+)\s+months?\s+ago\b", re.I), "months"),
    (re.compile(r"\b(\d+)\s+years?\s+ago\b", re.I), "years"),
    (re.compile(r"\blast (week|month|year)\b", re.I), "last_unit"),
]

def anchor_time(row):
    text = row["description"]
    start = pd.to_datetime(row["start_date"], errors="coerce")
    explicit = pd.to_datetime(pd.Series(re.findall(
        r"\b(?:\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s*\d{4}|\w+\s+\d{4}|\d{4})\b", str(text)
    )), errors="coerce").dropna()
    if len(explicit):
        return explicit.iloc[0], "high", "explicit_date"
    t = str(text or "")
    for pat, kind in REL_PATTERNS:
        m = pat.search(t)
        if m is not None and pd.notnull(start):
            if kind == pd.Timedelta(days=1):
                return (start - kind, "medium", m.group(1))
            if kind in ("days","weeks","months","years"):
                n = int(m.group(1))
                delta = pd.DateOffset(**{kind: n})
                return (start - delta, "medium", f"{n}_{kind}_ago")
            if kind == "last_unit":
                unit = m.group(1).lower()
                if unit == "week":  return (start - pd.DateOffset(weeks=1), "medium", "last_week")
                if unit == "month": return (start - pd.DateOffset(months=1), "medium", "last_month")
                if unit == "year":  return (start - pd.DateOffset(years=1), "medium", "last_year")
    if "dream" in t.lower() and pd.notnull(start):
        return start, "low_dream_proxy", "dream_fallback"
    return pd.NaT, "none", ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    args = ap.parse_args()

    df = pd.read_excel(args.src)
    cols = {c: re.sub(r"\s+", " ", str(c)).strip().lower() for c in df.columns}
    df.columns = [cols[c] for c in df.columns]
    desc_col = [c for c in df.columns if "describe" in c][:1]
    if not desc_col:
        print("Could not find description column (header contains 'describe').", file=sys.stderr); sys.exit(1)
    desc_col = desc_col[0]

    out = pd.DataFrame()
    out["respondent_id"] = df.get("respondent id", df.get("respondent_id"))
    out["start_date"] = pd.to_datetime(df.get("start date", df.get("start_date")), errors="coerce")
    out["end_date"]   = pd.to_datetime(df.get("end date", df.get("end_date")), errors="coerce")
    out["description"]= df[desc_col].astype(str)

    anchored = out.apply(anchor_time, axis=1, result_type="expand")
    out["inferred_event_date"] = anchored[0]
    out["time_anchor_confidence"] = anchored[1]
    out["time_anchor_evidence"]   = anchored[2]

    spans, norms, quals = [], [], []
    for txt in out["description"]:
        span, norm, q = extract_place(txt)
        spans.append(span); norms.append(norm); quals.append(q)
    out["location_span"] = spans
    out["location_normalized"] = norms
    out["location_quality"] = quals
    out.loc[out["location_quality"] < 0.90, ["location_span","location_normalized","location_quality"]] = ["","",""]

    out.to_csv(args.out, index=False)
    print(f"✅ Wrote {args.out} with {len(out)} rows.")
if __name__ == "__main__":
    main()
