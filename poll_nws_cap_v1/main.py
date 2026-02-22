import os
import json
import requests
from google.cloud import bigquery
from google.auth import default as google_auth_default

VERSION = "nws-cap-v1.2"
NWS_URL = os.environ.get("NWS_CAP_URL", "https://api.weather.gov/alerts/active")

def _resolve_project_id():
    # Try env first, then ADC, as a last resort let BQ client resolve
    p = (os.environ.get("PROJECT_ID")
         or os.environ.get("GCP_PROJECT")
         or os.environ.get("GOOGLE_CLOUD_PROJECT"))
    if p:
        return p
    try:
        creds, proj = google_auth_default()
        if proj:
            return proj
    except Exception:
        pass
    try:
        return bigquery.Client().project
    except Exception:
        return None

def _iso_to_rfc3339(s: str):
    if not s:
        return None
    # NWS returns RFC3339 already; keep simple & permissive
    return s

def _centroid_from_geojson_geometry(geom):
    """Compute centroid (lat, lon) purely from basic GeoJSON structures (no shapely)."""
    if not geom or "type" not in geom or "coordinates" not in geom:
        return (None, None)
    t = geom["type"]
    c = geom["coordinates"]
    pts = []
    try:
        if t == "Point":
            pts = [tuple(c)]
        elif t in ("MultiPoint", "LineString"):
            pts = [tuple(p) for p in c]
        elif t in ("MultiLineString", "Polygon"):
            pts = [tuple(p) for p in (c[0] if t == "Polygon" else sum(c, []))]
        elif t == "MultiPolygon":
            for poly in c:
                if poly and poly[0]:
                    pts.extend(tuple(p) for p in poly[0])
    except Exception:
        return (None, None)
    if not pts:
        return (None, None)
    lons, lats = zip(*pts)
    return (sum(lats)/len(lats), sum(lons)/len(lons))

def handler(request=None):
    # Do everything inside the request so imports never crash the container.
    try:
        project = _resolve_project_id()
        dataset = os.environ.get("BQ_DATASET", "sentinel_raw")
        table   = os.environ.get("BQ_TABLE",   "cap_alerts_raw")

        if not project:
            # Log clearly for debugging
            print(json.dumps({"version": VERSION, "stage": "error", "reason": "No project resolved"}))
            return ("missing project id", 500)

        print(json.dumps({"version": VERSION, "stage": "start", "project": project}))

        # Create client lazily here (not at import time)
        bq = bigquery.Client(project=project)

        # Fetch active alerts
        r = requests.get(
            NWS_URL,
            timeout=25,
            headers={"User-Agent": "synexis-nws-cap/1.0 (contact: synexisproject@gmail.com)"}
        )
        r.raise_for_status()
        data = r.json()
        feats = data.get("features", []) or []

        rows = []
        for f in feats:
            p = f.get("properties", {}) or {}
            lat, lon = _centroid_from_geojson_geometry(f.get("geometry"))
            rows.append({
                "id": p.get("id") or f.get("id"),
                "event": p.get("event"),
                "headline": p.get("headline"),
                "description": p.get("description"),
                "severity": p.get("severity"),
                "urgency": p.get("urgency"),
                "certainty": p.get("certainty"),
                "effective": _iso_to_rfc3339(p.get("effective")),
                "expires": _iso_to_rfc3339(p.get("expires")),
                "area_desc": p.get("areaDesc"),
                "centroid_lat": lat,
                "centroid_lon": lon,
                "regions": p.get("affectedZones") or [],
                "raw_json": json.dumps(f, ensure_ascii=False),
                "src": "nws-cap",
            })

        # No rows? return ok (this keeps healthcheck happy and logs helpful)
        if not rows:
            print(json.dumps({"version": VERSION, "stage": "done", "inserted": 0}))
            return ("ok", 200)

        table_ref = bigquery.TableReference.from_string(f"{project}.{dataset}.{table}")
        job = bq.load_table_from_json(
            rows, table_ref,
            job_config=bigquery.LoadJobConfig(
                write_disposition="WRITE_APPEND",
                schema=[
                    bigquery.SchemaField("id","STRING"),
                    bigquery.SchemaField("event","STRING"),
                    bigquery.SchemaField("headline","STRING"),
                    bigquery.SchemaField("description","STRING"),
                    bigquery.SchemaField("severity","STRING"),
                    bigquery.SchemaField("urgency","STRING"),
                    bigquery.SchemaField("certainty","STRING"),
                    bigquery.SchemaField("effective","TIMESTAMP"),
                    bigquery.SchemaField("expires","TIMESTAMP"),
                    bigquery.SchemaField("area_desc","STRING"),
                    bigquery.SchemaField("centroid_lat","FLOAT"),
                    bigquery.SchemaField("centroid_lon","FLOAT"),
                    bigquery.SchemaField("regions","STRING","REPEATED"),
                    bigquery.SchemaField("raw_json","STRING"),
                    bigquery.SchemaField("src","STRING"),
                    bigquery.SchemaField("_ingested_at","TIMESTAMP"),
                ]
            )
        )
        job.result()
        print(json.dumps({"version": VERSION, "stage": "done", "inserted": len(rows)}))
        return ("ok", 200)

    except Exception as e:
        # Never crash the container; log the error and return 500 to caller.
        print(json.dumps({"version": VERSION, "stage": "exception", "error": str(e)}))
        return ("error", 500)
