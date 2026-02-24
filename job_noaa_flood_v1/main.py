import os, json, requests
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
BQ_DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.environ.get("BQ_TABLE", "noaa_flood_raw")

def run():
    now = datetime.now(timezone.utc).isoformat()
    print(f"Starting NOAA flood job at {now}")
    rows = []

    try:
        print("Fetching NOAA NWPS gauges...")
        r = requests.get(
            "https://api.water.noaa.gov/nwps/v1/gauges",
            timeout=120,
            headers={"User-Agent": "synexis-project-sentinel/1.0"}
        )
        r.raise_for_status()
        data = r.json()
        gauges = data.get("gauges", []) or []
        print(f"Fetched {len(gauges)} gauges.")

        flood_categories = {"minor_flooding", "moderate_flooding", "major_flooding"}
        flooding = [g for g in gauges
                   if (g.get("status", {}) or {}).get("observed", {}).get("floodCategory")
                   in flood_categories]

        # If no active flooding use top 25 as baseline heartbeat
        target = flooding if flooding else gauges[:25]
        print(f"Processing {len(target)} gauges ({len(flooding)} actively flooding).")

        for g in target:
            obs = (g.get("status", {}) or {}).get("observed", {}) or {}
            fcast = (g.get("status", {}) or {}).get("forecast", {}) or {}
            rows.append({
                "site_id": g.get("lid"),
                "site_name": g.get("name"),
                "state": (g.get("state", {}) or {}).get("abbreviation"),
                "latitude": g.get("latitude"),
                "longitude": g.get("longitude"),
                "observed_stage": obs.get("primary") if obs.get("primary") != -999 else None,
                "observed_stage_unit": obs.get("primaryUnit"),
                "observed_flow": obs.get("secondary") if obs.get("secondary") != -999 else None,
                "flood_category": obs.get("floodCategory"),
                "forecast_category": fcast.get("floodCategory"),
                "valid_time": obs.get("validTime"),
                "src": "noaa-nwps",
                "raw": json.dumps(g, ensure_ascii=False),
                "ingested_at": now,
            })

    except Exception as e:
        print(f"ERROR fetching gauges: {e}")
        raise

    if not rows:
        print("No rows to insert.")
        return

    client = bigquery.Client(project=PROJECT)
    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        print(f"BigQuery errors: {errors[:3]}")
        raise Exception(f"BQ insert failed: {errors[:3]}")

    print(f"Successfully inserted {len(rows)} rows into {table_id}")

if __name__ == "__main__":
    run()
