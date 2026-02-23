import os, json, requests
from datetime import datetime, timezone
from flask import Flask, request
from google.cloud import bigquery

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
BQ_DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.environ.get("BQ_TABLE", "nws_cap_alerts_raw")

app = Flask(__name__)

def poll():
    now = datetime.now(timezone.utc).isoformat()
    try:
        r = requests.get(
            "https://api.weather.gov/alerts/active",
            timeout=45,
            headers={"User-Agent": "synexis-project-sentinel/1.0 (synexisproject@gmail.com)"}
        )
        r.raise_for_status()
        data = r.json()
        features = data.get("features", []) or []

        filtered = [f for f in features
                   if (f.get("properties", {}) or {}).get("severity")
                   in ("Extreme", "Severe")]

        if not filtered:
            return {"ok": True, "inserted": 0, "reason": "no_severe_alerts"}

        rows = []
        for f in filtered[:100]:
            p = f.get("properties", {}) or {}
            geo = f.get("geometry") or {}
            lat, lon = None, None
            if geo.get("type") == "Point":
                coords = geo.get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
            rows.append({
                "id": p.get("id") or f.get("id"),
                "event": p.get("event"),
                "headline": p.get("headline"),
                "sender": p.get("senderName"),
                "severity": p.get("severity"),
                "urgency": p.get("urgency"),
                "certainty": p.get("certainty"),
                "area": p.get("areaDesc"),
                "effective": p.get("effective"),
                "onset": p.get("onset"),
                "expires": p.get("expires"),
                "sent": p.get("sent"),
                "status": p.get("status"),
                "category": p.get("category"),
                "response": p.get("response"),
                "instruction": p.get("instruction"),
                "description": p.get("description"),
                "url": p.get("@id"),
                "latitude": lat,
                "longitude": lon,
                "src": "nws-cap",
                "src_tag": "nws-cap",
                "source_url": "https://api.weather.gov/alerts/active",
                "raw": json.dumps(f, ensure_ascii=False),
                "ingested_at": now,
            })

        client = bigquery.Client(project=PROJECT)
        table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
        errors = client.insert_rows_json(table_id, rows)
        if errors:
            return {"ok": False, "errors": str(errors[:3])}
        return {"ok": True, "inserted": len(rows)}

    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/", methods=["GET", "POST"])
@app.route("/run", methods=["GET", "POST"])
def run():
    result = poll()
    return json.dumps(result), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
