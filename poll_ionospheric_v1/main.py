import os, json, requests
from datetime import datetime, timezone
from flask import Flask, request
from google.cloud import bigquery

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
BQ_DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.environ.get("BQ_TABLE", "ionospheric_raw")

app = Flask(__name__)

def get_bq_client():
    return bigquery.Client(project=PROJECT)

def ensure_table(client):
    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    schema = [
        bigquery.SchemaField("observed_at", "TIMESTAMP"),
        bigquery.SchemaField("source", "STRING"),
        bigquery.SchemaField("xray_short", "FLOAT"),
        bigquery.SchemaField("xray_long", "FLOAT"),
        bigquery.SchemaField("electron_flux", "FLOAT"),
        bigquery.SchemaField("kp_index", "FLOAT"),
        bigquery.SchemaField("dst_index", "FLOAT"),
        bigquery.SchemaField("raw", "STRING"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP"),
    ]
    try:
        client.get_table(table_id)
    except Exception:
        client.create_table(bigquery.Table(table_id, schema=schema), exists_ok=True)

def poll():
    client = get_bq_client()
    ensure_table(client)
    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    # X-ray flux — primary ionospheric disturbance indicator
    try:
        xray = requests.get(
            "https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json",
            timeout=30, headers={"User-Agent": "synexis-project-sentinel/1.0"}
        ).json()
        if isinstance(xray, list) and xray:
            last = xray[-1]
            rows.append({
                "observed_at": last.get("time_tag"),
                "source": "noaa-swpc-xray",
                "xray_short": float(last.get("flux", 0) or 0),
                "xray_long": float(last.get("flux", 0) or 0),
                "electron_flux": None,
                "kp_index": None,
                "dst_index": None,
                "raw": json.dumps(last),
                "ingested_at": now,
            })
    except Exception as e:
        print(f"X-ray fetch error: {e}")

    # Electron flux — ionospheric charging indicator
    try:
        eflux = requests.get(
            "https://services.swpc.noaa.gov/json/goes/primary/electrons-1-day.json",
            timeout=30, headers={"User-Agent": "synexis-project-sentinel/1.0"}
        ).json()
        if isinstance(eflux, list) and eflux:
            last = eflux[-1]
            rows.append({
                "observed_at": last.get("time_tag"),
                "source": "noaa-swpc-electrons",
                "xray_short": None,
                "xray_long": None,
                "electron_flux": float(last.get("flux", 0) or 0),
                "kp_index": None,
                "dst_index": None,
                "raw": json.dumps(last),
                "ingested_at": now,
            })
    except Exception as e:
        print(f"Electron flux fetch error: {e}")

    if not rows:
        return {"ok": True, "inserted": 0, "reason": "no_rows"}

    errors = client.insert_rows_json(table_id, rows)
    if errors:
        return {"ok": False, "errors": str(errors)}
    return {"ok": True, "inserted": len(rows)}

@app.route("/", methods=["GET", "POST"])
@app.route("/run", methods=["GET", "POST"])
def run():
    result = poll()
    return json.dumps(result), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
