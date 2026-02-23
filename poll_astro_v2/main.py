import os, json, ephem
from datetime import datetime, timezone
from flask import Flask, request
from google.cloud import bigquery
import math

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
BQ_DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.environ.get("BQ_TABLE", "astro_daily_raw")

app = Flask(__name__)

def moon_phase_name(phase_pct):
    if phase_pct < 0.03 or phase_pct > 0.97: return "New Moon"
    elif phase_pct < 0.22: return "Waxing Crescent"
    elif phase_pct < 0.28: return "First Quarter"
    elif phase_pct < 0.47: return "Waxing Gibbous"
    elif phase_pct < 0.53: return "Full Moon"
    elif phase_pct < 0.72: return "Waning Gibbous"
    elif phase_pct < 0.78: return "Last Quarter"
    else: return "Waning Crescent"

def poll():
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    obs = ephem.Observer()
    obs.date = now.strftime("%Y/%m/%d %H:%M:%S")

    moon = ephem.Moon(obs)
    sun = ephem.Sun(obs)
    mercury = ephem.Mercury(obs)
    venus = ephem.Venus(obs)
    mars = ephem.Mars(obs)
    jupiter = ephem.Jupiter(obs)
    saturn = ephem.Saturn(obs)

    phase_pct = moon.phase / 100.0
    phase_name = moon_phase_name(phase_pct)

    # Moon distance in km
    moon_dist_km = moon.earth_distance * 149597870.7

    # Next full and new moon
    next_full = ephem.next_full_moon(obs.date)
    next_new = ephem.next_new_moon(obs.date)
    prev_full = ephem.previous_full_moon(obs.date)

    # Is moon near perigee? (within 10% of closest approach ~356,500 km)
    is_supermoon = moon_dist_km < 370000

    row = {
        "observed_at": now_iso,
        "moon_phase_pct": round(float(moon.phase), 4),
        "moon_phase_name": phase_name,
        "moon_distance_km": round(moon_dist_km, 1),
        "moon_is_supermoon": is_supermoon,
        "moon_ra": str(moon.ra),
        "moon_dec": str(moon.dec),
        "sun_ra": str(sun.ra),
        "sun_dec": str(sun.dec),
        "mercury_phase": round(float(mercury.phase), 4),
        "venus_phase": round(float(venus.phase), 4),
        "mars_phase": round(float(mars.phase), 4),
        "jupiter_phase": round(float(jupiter.phase), 4),
        "saturn_phase": round(float(saturn.phase), 4),
        "next_full_moon": str(ephem.Date(next_full)),
        "next_new_moon": str(ephem.Date(next_new)),
        "prev_full_moon": str(ephem.Date(prev_full)),
        "src": "ephem-calculated",
        "ingested_at": now_iso,
    }

    client = bigquery.Client(project=PROJECT)
    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        return {"ok": False, "errors": str(errors)}
    return {"ok": True, "inserted": 1, "phase": phase_name, "moon_pct": round(float(moon.phase), 1)}

@app.route("/", methods=["GET", "POST"])
@app.route("/run", methods=["GET", "POST"])
def run():
    result = poll()
    return json.dumps(result), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
