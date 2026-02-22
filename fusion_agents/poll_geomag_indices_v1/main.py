import os, json, requests
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
TABLE   = os.environ.get("BQ_TABLE",   "geomag_indices_raw")
URL     = os.environ.get("SOURCE_URL")
SRC_TAG = os.environ.get("SRC_TAG", "swpc")
bq = bigquery.Client(project=PROJECT)

def _ts(s):
    if s is None: return None
    try:
        s2 = s.replace("Z","+00:00").replace(" ", "T")
        if "T" not in s2:
            s2 = s2 + "T00:00:00+00:00"
        return datetime.fromisoformat(s2).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        return None

def _num(x):
    try:
        return float(x)
    except Exception:
        return None

def handler(request=None):
    r = requests.get(URL, headers={"User-Agent":"Synexis-Project-Sentinel"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        for key in ("data","items","values","records"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    rows = []
    for it in (data or []):
        ts  = it.get("time_tag") or it.get("time") or it.get("timestamp") or it.get("date_time")
        kp  = it.get("kp") or it.get("Kp") or it.get("kp_index")
        dst = it.get("dst") or it.get("DST")
        ap  = it.get("ap") or it.get("Ap") or it.get("ap_index")
        bz  = it.get("bz") or it.get("Bz") or it.get("b_z")
        rows.append({
            "ts": _ts(ts),
            "kp": _num(kp),
            "dst": _num(dst),
            "ap": _num(ap),
            "bz": _num(bz),
            "src": SRC_TAG,
            "raw": json.dumps(it, ensure_ascii=False),
        })
    if not rows: return ("ok", 200)
    bq.load_table_from_json(rows, f"{PROJECT}.{DATASET}.{TABLE}").result()
    return ("ok", 200)
