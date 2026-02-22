import os, json, hashlib, requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from google.cloud import bigquery

BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE   = os.getenv("BQ_TABLE",   "swpc_solar_alerts_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://services.swpc.noaa.gov/products/alerts.json")
SRC_TAG    = os.getenv("SRC_TAG",    "swpc")
REV_TS     = os.getenv("REV_TS",     "")  # bump to force new revision

def _to_ts(s: Optional[str]) -> Optional[str]:
    if not s: return None
    try:
        # Try ISO first
        dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        pass
    try:
        # Try epoch seconds
        sec = float(s)
        dt = datetime.fromtimestamp(sec, tz=timezone.utc)
        return dt.isoformat().replace("+00:00","Z")
    except Exception:
        return None

def _hash_id(parts: List[str]) -> str:
    h = hashlib.sha1(("||".join([p or "" for p in parts])).encode("utf-8")).hexdigest()
    return f"swpc_{h}"

def _normalize_rows(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts either:
      - list of lists with first row = headers (SWPC canonical format), or
      - list of dicts (fallback)
    Returns list of normalized dicts with our target columns.
    """
    out = []

    # Case 1: list-of-lists with header row
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        headers = [str(h) for h in payload[0]]
        for row in payload[1:]:
            if not isinstance(row, list): continue
            d = { headers[i]: (row[i] if i < len(row) else None) for i in range(len(headers)) }

            # Common SWPC columns (best-effort; varies by alert)
            issue  = d.get("issue_datetime") or d.get("issueTime") or d.get("issue_unix_time")
            expire = d.get("expires_datetime") or d.get("expiresTime") or d.get("expires_unix_time")
            msg    = d.get("message") or d.get("summary") or d.get("msg") or d.get("product_text")
            sev    = d.get("severity") or d.get("priority") or d.get("alert_severity")
            atype  = d.get("type") or d.get("alert") or d.get("product_id") or d.get("event")
            prod   = d.get("product_id") or d.get("product") or d.get("pid")
            area   = d.get("area") or d.get("region") or d.get("geo")

            row_id = _hash_id([str(d.get("id") or ""), str(d.get("product_id") or ""), str(d.get("issue_unix_time") or ""), str(msg or "")])

            out.append({
                "id": row_id,
                "product_id": (prod or atype) or "unknown",
                "alert_type": atype,
                "severity": sev,
                "message": msg,
                "area": area,
                "issue_time": _to_ts(issue),
                "expires_time": _to_ts(expire),
                "url": SOURCE_URL,
                "src": SRC_TAG,
                "raw": json.dumps(d, ensure_ascii=False),
            })
        return out

    # Case 2: list-of-dicts
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        for d in payload:
            issue  = d.get("issue_datetime") or d.get("issueTime") or d.get("issue_unix_time")
            expire = d.get("expires_datetime") or d.get("expiresTime") or d.get("expires_unix_time")
            msg    = d.get("message") or d.get("summary") or d.get("msg") or d.get("product_text")
            sev    = d.get("severity") or d.get("priority") or d.get("alert_severity")
            atype  = d.get("type") or d.get("alert") or d.get("product_id") or d.get("event")
            prod   = d.get("product_id") or d.get("product") or d.get("pid")
            area   = d.get("area") or d.get("region") or d.get("geo")

            row_id = _hash_id([str(d.get("id") or ""), str(d.get("product_id") or ""), str(d.get("issue_unix_time") or ""), str(msg or "")])

            out.append({
                "id": row_id,
                "product_id": (prod or atype) or "unknown",
                "alert_type": atype,
                "severity": sev,
                "message": msg,
                "area": area,
                "issue_time": _to_ts(issue),
                "expires_time": _to_ts(expire),
                "url": SOURCE_URL,
                "src": SRC_TAG,
                "raw": json.dumps(d, ensure_ascii=False),
            })
        return out

    # fallback: unknown format
    return []

def handler(_request):
    try:
        print(f"REV_TS={REV_TS} Fetching SWPC feed: {SOURCE_URL}")
        r = requests.get(SOURCE_URL, timeout=20)
        r.raise_for_status()
        payload = r.json()
        rows = _normalize_rows(payload)

        if not rows:
            return (json.dumps({"ok": True, "inserted": 0, "reason": "no_rows"}), 200, {"Content-Type":"application/json"})

        client = bigquery.Client()
        table_id = f"{client.project}.{BQ_DATASET}.{BQ_TABLE}"
        errors = client.insert_rows_json(table_id, rows, ignore_unknown_values=True)
        if errors:
            print("BigQuery insert errors:", errors)
            return (json.dumps({"ok": False, "errors": errors}), 200, {"Content-Type":"application/json"})
        return (json.dumps({"ok": True, "inserted": len(rows)}), 200, {"Content-Type":"application/json"})
    except requests.HTTPError as e:
        print("HTTP error fetching feed:", str(e))
        return (json.dumps({"ok": False, "error": "http_error"}), 200, {"Content-Type":"application/json"})
    except Exception as e:
        print("Exception:", repr(e))
        return (json.dumps({"ok": False, "error": "exception"}), 200, {"Content-Type":"application/json"})
