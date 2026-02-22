import os, json, time, requests
from datetime import datetime, timezone
from typing import List, Dict, Any
from google.cloud import bigquery

BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.getenv("BQ_TABLE", "nws_cap_alerts_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update")
SRC_TAG    = os.getenv("SRC_TAG", "nws-cap")
REV_TS     = os.getenv("REV_TS", "")  # to force new revisions

_session = requests.Session()
_session.headers.update({
    "User-Agent": "synexis-sentinel (bigquery-ingestor)",
    "Accept": "application/geo+json,application/json"
})

def _to_ts(s: Any):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def _row_from_feature(feat: Dict[str, Any]) -> Dict[str, Any]:
    props = feat.get("properties", {}) or {}
    geom  = feat.get("geometry", {}) or {}
    coords = None
    if geom and geom.get("type") == "Point" and geom.get("coordinates"):
        # NWS returns [lon, lat]
        try:
            lon, lat = geom["coordinates"][:2]
            coords = (float(lat), float(lon))
        except Exception:
            coords = None

    row = {
        "id": props.get("id") or feat.get("id"),
        "event": props.get("event"),
        "headline": props.get("headline"),
        "sender": props.get("senderName"),
        "severity": props.get("severity"),
        "urgency": props.get("urgency"),
        "certainty": props.get("certainty"),
        "area": (props.get("areaDesc") or None),
        "effective": _to_ts(props.get("effective")),
        "onset": _to_ts(props.get("onset")),
        "expires": _to_ts(props.get("expires")),
        "sent": _to_ts(props.get("sent")),
        "status": props.get("status"),
        "category": props.get("category"),
        "response": props.get("response"),
        "instruction": props.get("instruction"),
        "description": props.get("description"),
        "url": props.get("url") or props.get("@id") or feat.get("id"),
        "latitude": coords[0] if coords else None,
        "longitude": coords[1] if coords else None,
        "src": SRC_TAG,
        "raw": json.dumps(feat, separators=(",", ":")),
    }
    # id is required for de-dupe; if missing, fall back
    if not row["id"]:
        row["id"] = f"{row['event'] or 'alert'}-{row['sent'] or time.time()}"
    return row

def _fetch_all(url: str) -> List[Dict[str, Any]]:
    out = []
    while url:
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        feats = (data.get("features") or [])
        out.extend(feats)
        # try Link header (RFC 5988) for next page
        next_url = None
        link = r.headers.get("Link") or r.headers.get("link")
        if link and 'rel="next"' in link:
            try:
                # format: <URL>; rel="next", <URL2>; rel="something"
                parts = [p.strip() for p in link.split(",")]
                for p in parts:
                    if 'rel="next"' in p:
                        # between < and >
                        start = p.find("<") + 1
                        end = p.find(">")
                        if start > 0 and end > start:
                            next_url = p[start:end]
                            break
            except Exception:
                next_url = None
        url = next_url
        if len(out) >= 2000:  # safety cap
            break
    return out

def handler(request):
    print(f"REV_TS={REV_TS} Fetching NWS alerts: {SOURCE_URL}")
    try:
        feats = _fetch_all(SOURCE_URL)
        print(f"Fetched {len(feats)} features")
        now = datetime.now(timezone.utc)

        rows = [_row_from_feature(f) for f in feats]
        if not rows:
            return (json.dumps({"ok": True, "inserted": 0, "reason": "no_rows"}), 200, {"Content-Type":"application/json"})

        bq = bigquery.Client()
        table = f"{BQ_DATASET}.{BQ_TABLE}"
        errors = bq.insert_rows_json(table, rows, ignore_unknown_values=True)
        if errors:
            print("BigQuery insert errors", errors)
            return (json.dumps({"ok": False, "errors": errors}), 200, {"Content-Type":"application/json"})
        return (json.dumps({"ok": True, "inserted": len(rows)}), 200, {"Content-Type":"application/json"})
    except requests.HTTPError as e:
        print("HTTP error fetching feed", e, getattr(e, "response", None).text if getattr(e, "response", None) else "")
        return (json.dumps({"ok": False, "error": "http_error"}), 200, {"Content-Type":"application/json"})
    except Exception as e:
        print("Unhandled error", repr(e))
        return (json.dumps({"ok": False, "error": "exception"}), 200, {"Content-Type":"application/json"})
