import os, json, requests
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
TABLE   = os.environ.get("BQ_TABLE",   "water_iv_raw")
URL     = os.environ.get("SOURCE_URL")
bq = bigquery.Client(project=PROJECT)

def _ts(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        return None

def _f(v):
    try:
        return float(v)
    except Exception:
        return None

def handler(request=None):
    r = requests.get(URL, headers={"User-Agent":"Synexis-Project-Sentinel"}, timeout=45)
    r.raise_for_status()
    data = r.json()
    series = (data.get("value", {}) or {}).get("timeSeries", []) if isinstance(data, dict) else []
    rows = []
    for ts in series:
        source_info = ts.get("sourceInfo", {}) or {}
        site_code = None
        site_name = source_info.get("siteName")
        if isinstance(source_info.get("siteCode"), list) and source_info["siteCode"]:
            site_code = source_info["siteCode"][0].get("value")
        loc = source_info.get("geoLocation", {}) or {}
        geo = loc.get("geogLocation", {}) or {}
        lat = geo.get("latitude"); lon = geo.get("longitude")
        variable = ts.get("variable", {}) or {}
        param_code = None
        if isinstance(variable.get("variableCode"), list) and variable["variableCode"]:
            param_code = variable["variableCode"][0].get("value")
        unit = ((variable.get("unit") or {}).get("unitCode")) if variable.get("unit") else None
        points = (ts.get("values", [{}])[0] or {}).get("value", []) if ts.get("values") else []
        for p in points:
            val = _f(p.get("value")); tss = _ts(p.get("dateTime"))
            if tss is None: continue
            rows.append({
                "site_code": site_code, "site_name": site_name, "parameter": param_code,
                "value": val, "unit": unit, "ts": tss,
                "longitude": _f(lon), "latitude": _f(lat),
                "src": "usgs_water", "raw": json.dumps(ts, ensure_ascii=False)
            })
    if not rows: return ("ok", 200)
    bq.load_table_from_json(rows, f"{PROJECT}.{DATASET}.{TABLE}").result()
    return ("ok", 200)
