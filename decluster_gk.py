import math
from google.cloud import bigquery
from datetime import timedelta

PROJECT = "synexis-project-sentinel"
CLIENT = bigquery.Client(project=PROJECT)

def gk_windows(mag):
    """Gardner-Knopoff (1974) distance and time windows."""
    dist_km = 10 ** (0.1238 * mag + 0.983)
    if mag < 6.5:
        time_days = 10 ** (0.5409 * mag - 0.547)
    else:
        time_days = 10 ** (0.032 * mag + 2.7389)
    return dist_km, time_days

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

print("Loading master_earthquakes...")
query = """
SELECT event_id as id, time, latitude, longitude, magnitude
FROM `synexis-project-sentinel.sentinel_groundtruth.master_earthquakes`
WHERE magnitude IS NOT NULL AND latitude IS NOT NULL AND longitude IS NOT NULL
ORDER BY time ASC
"""
df = CLIENT.query(query).to_dataframe()
print(f"Loaded {len(df)} events")

# Sort by time ascending
df = df.sort_values("time").reset_index(drop=True)
is_mainshock = [True] * len(df)

print("Running Gardner-Knopoff declustering...")
for i in range(len(df)):
    if not is_mainshock[i]:
        continue
    mag = df.at[i, "magnitude"]
    lat = df.at[i, "latitude"]
    lon = df.at[i, "longitude"]
    t = df.at[i, "time"]
    dist_km, time_days = gk_windows(mag)

    for j in range(i + 1, len(df)):
        tj = df.at[j, "time"]
        dt = (tj - t).total_seconds() / 86400.0
        if dt > time_days:
            break
        if not is_mainshock[j]:
            continue
        latj = df.at[j, "latitude"]
        lonj = df.at[j, "longitude"]
        d = haversine_km(lat, lon, latj, lonj)
        if d <= dist_km:
            is_mainshock[j] = False

    if i % 1000 == 0:
        removed = sum(1 for x in is_mainshock if not x)
        print(f"  Processed {i}/{len(df)}, aftershocks removed so far: {removed}")

df["is_mainshock"] = is_mainshock
mainshocks = df[df["is_mainshock"]].copy()
print(f"\nDeclustering complete:")
print(f"  Total events: {len(df)}")
print(f"  Mainshocks: {len(mainshocks)}")
print(f"  Aftershocks removed: {len(df) - len(mainshocks)}")

# Check Tohoku/Maule/Sumatra survival
tohoku = mainshocks[
    (mainshocks.latitude.between(35,42)) &
    (mainshocks.longitude.between(140,147)) &
    (mainshocks.time.astype(str).str[:10] >= "2011-03-11") &
    (mainshocks.time.astype(str).str[:10] <= "2012-03-11") &
    (mainshocks.magnitude >= 6.5)
]
maule = mainshocks[
    (mainshocks.latitude.between(-40,-33)) &
    (mainshocks.longitude.between(-76,-70)) &
    (mainshocks.time.astype(str).str[:10] >= "2010-02-27") &
    (mainshocks.time.astype(str).str[:10] <= "2011-02-27") &
    (mainshocks.magnitude >= 6.5)
]
sumatra = mainshocks[
    (mainshocks.latitude.between(2,6)) &
    (mainshocks.longitude.between(94,98)) &
    (mainshocks.time.astype(str).str[:10] >= "2004-12-26") &
    (mainshocks.time.astype(str).str[:10] <= "2005-12-26") &
    (mainshocks.magnitude >= 6.5)
]
print(f"\nAftershock sequence survivors (M6.5+):")
print(f"  Tohoku window: {len(tohoku)} remaining (was 14)")
print(f"  Maule window: {len(maule)} remaining (was 10)")
print(f"  Sumatra window: {len(sumatra)} remaining (was 4)")

# Load to BQ
print("\nLoading to BQ...")
schema = [
    bigquery.SchemaField("id", "STRING"),
    bigquery.SchemaField("time", "TIMESTAMP"),
    bigquery.SchemaField("latitude", "FLOAT64"),
    bigquery.SchemaField("longitude", "FLOAT64"),
    bigquery.SchemaField("magnitude", "FLOAT64"),
    bigquery.SchemaField("is_mainshock", "BOOL"),
]
table_id = f"{PROJECT}.sentinel_groundtruth.master_earthquakes_declustered"
table = bigquery.Table(table_id, schema=schema)
table = CLIENT.create_table(table, exists_ok=True)

rows = []
for _, row in df.iterrows():
    rows.append({
        "id": str(row["id"]) if row["id"] else None,
        "time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "magnitude": float(row["magnitude"]),
        "is_mainshock": bool(row["is_mainshock"]),
    })

chunk_size = 5000
total = 0
for i in range(0, len(rows), chunk_size):
    chunk = rows[i:i+chunk_size]
    errors = CLIENT.insert_rows_json(table, chunk)
    if errors:
        print(f"Errors chunk {i//chunk_size}: {errors[:2]}")
    else:
        total += len(chunk)
        print(f"  Loaded {total}/{len(rows)}")

print(f"Done. {total} rows loaded to {table_id}")
