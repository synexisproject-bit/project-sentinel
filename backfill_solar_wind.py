import requests
from datetime import datetime, timezone, date, timedelta
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
TABLE_ID = f"{PROJECT}.sentinel_features.env_daily"
TMP_TABLE = f"{PROJECT}.sentinel_features._sw_tmp"
client = bigquery.Client(project=PROJECT)

def fetch_var(year, var_num):
    url = (f"https://omniweb.gsfc.nasa.gov/cgi/nx1.cgi"
           f"?activity=retrieve&res=hourly&spacecraft=omni2"
           f"&start_date={year}0101&end_date={year}1231&vars={var_num}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    daily = {}
    for line in r.text.splitlines():
        parts = line.strip().split()
        if len(parts) != 4:
            continue
        # All first 3 columns must be integers (year, doy, hour)
        try:
            yr, doy, hr = int(parts[0]), int(parts[1]), int(parts[2])
            val = float(parts[3])
        except (ValueError, IndexError):
            continue
        # Must be a plausible year
        if yr < 1990 or yr > 2030:
            continue
        # Skip fill values
        if val in (9999., 99999., 999999., 9999.99, 99999.9, 9999.990, 99999.900):
            continue
        if abs(val) > 9000:
            continue
        d = date(yr, 1, 1) + timedelta(days=doy - 1)
        if d not in daily:
            daily[d] = []
        daily[d].append(val)
    return daily

def process_year(year):
    print(f"Fetching solar wind for {year}...", end=" ", flush=True)
    speed = fetch_var(year, 24)
    density = fetch_var(year, 23)
    bz = fetch_var(year, 16)
    all_days = set(speed.keys()) | set(density.keys()) | set(bz.keys())
    rows = []
    for d in sorted(all_days):
        row = {"day": d.isoformat()}
        row["sw_speed_mean"] = round(sum(speed[d])/len(speed[d]), 2) if d in speed and speed[d] else None
        row["sw_density_mean"] = round(sum(density[d])/len(density[d]), 4) if d in density and density[d] else None
        row["sw_bz_min"] = round(min(bz[d]), 2) if d in bz and bz[d] else None
        rows.append(row)
    return rows

def update_env_daily(rows):
    if not rows:
        return 0
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("day", "DATE"),
            bigquery.SchemaField("sw_speed_mean", "FLOAT64"),
            bigquery.SchemaField("sw_density_mean", "FLOAT64"),
            bigquery.SchemaField("sw_bz_min", "FLOAT64"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    job = client.load_table_from_json(rows, TMP_TABLE, job_config=job_config)
    job.result()
    merge_sql = f"""
    MERGE `{TABLE_ID}` T
    USING `{TMP_TABLE}` S
    ON T.day = S.day
    WHEN MATCHED THEN UPDATE SET
      T.sw_speed_mean = S.sw_speed_mean,
      T.sw_density_mean = S.sw_density_mean,
      T.sw_bz_min = S.sw_bz_min
    """
    client.query(merge_sql).result()
    return len(rows)

total = 0
current_year = datetime.now().year
for year in range(2001, current_year + 1):
    try:
        rows = process_year(year)
        updated = update_env_daily(rows)
        total += updated
        print(f"{updated} days updated.")
    except Exception as e:
        print(f"ERROR: {e}")

try:
    client.delete_table(TMP_TABLE)
except:
    pass

print(f"\nDone. Total days updated: {total}")
