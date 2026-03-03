import requests
from datetime import datetime, timezone, date, timedelta
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
TABLE_ID = f"{PROJECT}.sentinel_features.env_daily"
client = bigquery.Client(project=PROJECT)

def fetch_year_kp(year):
    start = f"{year}0101"
    end = f"{year}1231"
    url = (f"https://omniweb.gsfc.nasa.gov/cgi/nx1.cgi"
           f"?activity=retrieve&res=hourly&spacecraft=omni2"
           f"&start_date={start}&end_date={end}&vars=38")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    daily = {}
    for line in r.text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].isdigit():
            yr, doy, hr, kp_raw = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            if kp_raw == 999:
                continue
            kp = kp_raw / 10.0
            d = date(yr, 1, 1) + timedelta(days=doy - 1)
            if d not in daily:
                daily[d] = []
            daily[d].append(kp)
    rows = []
    for d, vals in daily.items():
        rows.append({
            "day": d.isoformat(),
            "kp_max": max(vals),
            "kp_mean": round(sum(vals) / len(vals), 4),
        })
    return rows

def update_env_daily(rows):
    if not rows:
        return 0
    # Load into temp table then merge
    tmp_table = f"{PROJECT}.sentinel_features._kp_tmp"
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("day", "DATE"),
            bigquery.SchemaField("kp_max", "FLOAT64"),
            bigquery.SchemaField("kp_mean", "FLOAT64"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    job = client.load_table_from_json(rows, tmp_table, job_config=job_config)
    job.result()
    
    merge_sql = f"""
    MERGE `{TABLE_ID}` T
    USING `{tmp_table}` S
    ON T.day = S.day
    WHEN MATCHED THEN UPDATE SET
      T.kp_max = S.kp_max,
      T.kp_mean = S.kp_mean
    """
    client.query(merge_sql).result()
    return len(rows)

total = 0
current_year = datetime.now().year
for year in range(2001, current_year + 1):
    print(f"Fetching Kp for {year}...", end=" ", flush=True)
    try:
        rows = fetch_year_kp(year)
        updated = update_env_daily(rows)
        total += updated
        print(f"{updated} days updated.")
    except Exception as e:
        print(f"ERROR: {e}")

# Clean up temp table
try:
    client.delete_table(f"{PROJECT}.sentinel_features._kp_tmp")
except:
    pass

print(f"\nDone. Total days updated: {total}")
