import os, json, uuid, requests
from datetime import datetime, timezone
from typing import List, Dict, Any
from google.cloud import bigquery

BQ_DATASET  = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE    = os.getenv("BQ_TABLE",   "swpc_alerts_raw")
SOURCE_URL  = os.getenv("SOURCE_URL", "https://services.swpc.noaa.gov/products/alerts.json")
SRC_TAG     = os.getenv("SRC_TAG",    "swpc")
REV_TS      = os.getenv("REV_TS",     "")  # heartbeat

def _utc_iso(s: str | None) -> str | None:
    if not s: return None
    s = s.replace("Z","+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        return None

def _rows_from_swpc(payload: Any) -> List[Dict[str,Any]]:
    """
    SWPC alerts.json is array-of-arrays: first row = headers.
    Example columns often include:
      issue_time, start_time, end_time, message, product_id, type, location, region, etc.
    We'll map what we find, safely.
    """
    rows: List[Dict[str,Any]] = []
    if not isinstance(payload, list) or not payload:
        return rows

    header = payload[0]
    if not isinstance(header, list):
        return rows

    # normalize header -> index lookup
    hidx = {str(h).strip(): i for i, h in enumerate(header)}

    def col(name: str, rec: list) -> str | None:
        i = hidx.get(name)
        if i is None or i >= len(rec): return None
        val = rec[i]
        return None if val in ("", None) else str(val)

    for rec in payload[1:]:
        if not isinstance(rec, list): continue
        issue_time = _utc_iso(col("issue_time", rec) or col("time_tag", rec))
        start_time = _utc_iso(col("start_time", rec))
        end_time   = _utc_iso(col("end_time", rec))
        message    = col("message", rec)
        product_id = col("product_id", rec) or col("pid", rec)
        ptype      = col("type", rec) or col("alert_type", rec)
        location   = col("location", rec) or col("region", rec)
        url        = col("url", rec)

        rid = f"swpc:{product_id}:{issue_time}" if product_id and issue_time else f"swpc:{uuid.uuid4()}"
        rows.append({
            "id": rid,
            "issue_time": issue_time,
            "start_time": start_time,
            "end_time": end_time,
            "message": message,
            "product_id": product_id,
            "product_type": ptype,
            "location": location,
            "url": url,
            "src": SRC_TAG,
            "raw": json.dumps(rec, ensure_ascii=False),
        })
    return rows

def handler(request):
    try:
        print(f"REV_TS={REV_TS} Fetching SWPC: {SOURCE_URL}")
        r = requests.get(SOURCE_URL, timeout=30)
        r.raise_for_status()
        payload = r.json()
        rows = _rows_from_swpc(payload)

        if not rows:
            return (json.dumps({"ok": True, "inserted": 0, "reason": "no_rows"}), 200, {"Content-Type":"application/json"})

        client = bigquery.Client()
        table_id = f"{client.project}.{BQ_DATASET}.{BQ_TABLE}"

        errors = client.insert_rows_json(table_id, rows)
        if errors:
            return (json.dumps({"ok": False, "errors": errors}), 200, {"Content-Type":"application/json"})
        return (json.dumps({"ok": True, "inserted": len(rows)}), 200, {"Content-Type":"application/json"})

    except requests.HTTPError as e:
        print(f"HTTP error fetching SWPC: {e}")
        return (json.dumps({"ok": False, "error": "http_error"}), 200, {"Content-Type":"application/json"})
    except Exception as e:
        print(f"Unhandled: {e}")
        return (json.dumps({"ok": False, "error": "exception"}), 200, {"Content-Type":"application/json"})
