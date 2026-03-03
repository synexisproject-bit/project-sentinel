import requests, re
from datetime import date
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
TABLE_ID = f"{PROJECT}.sentinel_features.env_daily"
TMP_TABLE = f"{PROJECT}.sentinel_features._xray_tmp"
client = bigquery.Client(project=PROJECT)

BASE_URL = "https://www.ngdc.noaa.gov/stp/space-weather/solar-data/solar-features/solar-flares/x-rays/goes/xrs/"
FLARE_CLASS_RANK = {'A': 1, 'B': 2, 'C': 3, 'M': 4, 'X': 5}

YEAR_FILES = {y: f"goes-xrs-report_{y}.txt" for y in range(2001, 2017)}
YEAR_FILES[2017] = "goes-xrs-report_2017-ytd.txt"

def parse_url(url, year):
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return {}
    daily = {}
    for line in r.text.splitlines():
        line = line.strip()
        if not line: continue
        try:
            yy = line[5:7]
            mm = line[7:9]
            dd = line[9:11]
            if not (yy.isdigit() and mm.isdigit() and dd.isdigit()): continue
            full_year = 2000 + int(yy) if int(yy) < 50 else 1900 + int(yy)
            if full_year != year: continue
            d = date(full_year, int(mm), int(dd))
        except: continue
        flux_match = re.search(r'(\d+\.\d+E[+-]\d+)', line)
        # Match any GOES satellite designation: GOES, G15, G16, G17, G18 etc
        class_match = re.search(r'\s([ABCMX])\s+(\d+)\s+G(?:OES|\d+)', line)
        if not flux_match or not class_match: continue
        flux = float(flux_match.group(1))
        flare_class = class_match.group(1)
        if d not in daily:
            daily[d] = {'xray_max': flux, 'xray_class_max': flare_class,
                        'has_m_flare': 0, 'has_x_flare': 0}
        else:
            if flux > daily[d]['xray_max']:
                daily[d]['xray_max'] = flux
            if FLARE_CLASS_RANK.get(flare_class, 0) > FLARE_CLASS_RANK.get(daily[d]['xray_class_max'], 0):
                daily[d]['xray_class_max'] = flare_class
        if flare_class == 'M': daily[d]['has_m_flare'] = 1
        if flare_class == 'X': daily[d]['has_x_flare'] = 1
    return daily

def update_env_daily(rows):
    if not rows: return 0
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("day", "DATE"),
            bigquery.SchemaField("xray_max", "FLOAT64"),
            bigquery.SchemaField("xray_class_max", "STRING"),
            bigquery.SchemaField("has_m_flare", "INT64"),
            bigquery.SchemaField("has_x_flare", "INT64"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    job = client.load_table_from_json(rows, TMP_TABLE, job_config=job_config)
    job.result()
    client.query(f"""
    MERGE `{TABLE_ID}` T USING `{TMP_TABLE}` S ON T.day = S.day
    WHEN MATCHED THEN UPDATE SET
      T.xray_max = S.xray_max,
      T.xray_class_max = S.xray_class_max,
      T.has_m_flare = S.has_m_flare,
      T.has_x_flare = S.has_x_flare
    """).result()
    return len(rows)

total = 0
for year, filename in YEAR_FILES.items():
    print(f"Processing {year}...", end=" ", flush=True)
    try:
        url = f"{BASE_URL}{filename}"
        daily = parse_url(url, year)
        if not daily:
            print("no data."); continue
        rows = [{"day": d.isoformat(), "xray_max": v['xray_max'],
                 "xray_class_max": v['xray_class_max'],
                 "has_m_flare": v['has_m_flare'],
                 "has_x_flare": v['has_x_flare']}
                for d, v in sorted(daily.items())]
        updated = update_env_daily(rows)
        total += updated
        x_days = sum(1 for v in daily.values() if v['has_x_flare'])
        print(f"{updated} days, {x_days} X-flare days.")
    except Exception as e:
        print(f"ERROR: {e}")

try:
    client.delete_table(TMP_TABLE)
except: pass

print(f"\nDone. Total days updated: {total}")
