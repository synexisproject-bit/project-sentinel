import os, json, time, requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from google.cloud import bigquery
from flask import Response

# ---------- config ----------
BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE   = os.getenv("BQ_TABLE",   "usgs_quakes_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson")
SRC_TAG    = os.getenv("SRC_TAG",    "usgs")
REV_TS     = os.getenv("REV_TS",     "")

bq_client = bigquery.Client()

def _ms_to_rfc3339(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms/1000, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def handler(_request) -> Response:
    try:
        print(f"REV_TS={REV_TS} Fetching USGS feed: {SOURCE_URL}")
        r = requests.get(SOURCE_URL, timeout=20)
        r.raise_for_status()
        data = r.json()
        feats = data.get("features", [])
        print(f"Fetch ok; features: {len(feats)}")

        rows: List[Dict[str, Any]] = []
        row_ids: List[str] = []

        for f in feats:
            props = f.get("properties", {}) or {}
            geom  = f.get("geometry", {}) or {}
            coords = geom.get("coordinates") or [None, None, None]  # [lon, lat, depth]

            rid = f.get("id") or props.get("code") or str(props.get("time") or "")
            if not rid:
                continue

            row = {
                "id": rid,
                "mag": props.get("mag"),
                "place": props.get("place"),
                "time": _ms_to_rfc3339(props.get("time")),
                "updated": _ms_to_rfc3339(props.get("updated")),
                "tz": props.get("tz"),
                "url": props.get("url"),
                "detail": props.get("detail"),
                "felt": props.get("felt"),
                "cdi": props.get("cdi"),
                "mmi": props.get("mmi"),
                "alert": props.get("alert"),
                "status": props.get("status"),
                "tsunami": props.get("tsunami"),
                "sig": props.get("sig"),
                "net": props.get("net"),
                "code": props.get("code"),
                "ids": props.get("ids"),
                "sources": props.get("sources"),
                "types": props.get("types"),
                "nst": props.get("nst"),
                "dmin": props.get("dmin"),
                "rms": props.get("rms"),
                "gap": props.get("gap"),
                "magType": props.get("magType"),
                "type": props.get("type"),
                "longitude": coords[0] if len(coords) > 0 else None,
                "latitude":  coords[1] if len(coords) > 1 else None,
                "depth":     coords[2] if len(coords) > 2 else None,
                "src": SRC_TAG,
                "raw": json.dumps(f, separators=(",", ":"), ensure_ascii=False),
            }
            rows.append(row)
            row_ids.append(rid)

        if not rows:
            return Response(json.dumps({"ok": True, "inserted": 0, "reason": "no_features"}), mimetype="application/json")

        table_ref = f"{bq_client.project}.{BQ_DATASET}.{BQ_TABLE}"
        errors = bq_client.insert_rows_json(table_ref, rows, row_ids=row_ids)  # idempotent
        if errors:
            print(f"BigQuery insert errors: {errors}")
            return Response(json.dumps({"ok": False, "errors": errors}), mimetype="application/json", status=500)

        return Response(json.dumps({"ok": True, "inserted": len(rows)}), mimetype="application/json")

    except requests.HTTPError as e:
        print(f"HTTP error fetching USGS feed: {e}")
        return Response(json.dumps({"ok": False, "error": "http", "detail": str(e)}), mimetype="application/json", status=502)
    except Exception as e:
        print("Unhandled exception:", repr(e))
        return Response(json.dumps({"ok": False, "error": "exception", "detail": repr(e)}), mimetype="application/json", status=500)
