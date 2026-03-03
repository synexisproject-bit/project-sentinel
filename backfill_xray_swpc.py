import re, os, tarfile, io, subprocess
from datetime import date
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
TABLE_ID = f"{PROJECT}.sentinel_features.env_daily"
TMP_TABLE = f"{PROJECT}.sentinel_features._xray_tmp"
client = bigquery.Client(project=PROJECT)

FLARE_CLASS_RANK = {'A': 1, 'B': 2, 'C': 3, 'M': 4, 'X': 5}

def fetch_tar(year):
    url = f"ftp://ftp.swpc.noaa.gov/pub/warehouse/{year}/{year}_events.tar.gz"
    result = subprocess.run(['curl', '-s', '--max-time', '120', url],
                          capture_output=True)
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout

def parse_events_file(content):
    daily = {}
    date_match = re.search(r':Date:\s+(\d{4})\s+(\d{2})\s+(\d{2})', content)
    if not date_match:
        return {}
    try:
        d = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
    except:
        return {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(':'): continue
        if 'XRA' not in line or '1-8A' not in line: continue
        flux_match = re.search(r'(\d+\.\d+E[+-]\d+)', line)
        class_match = re.search(r'\s([ABCMX])(\d+\.\d+)\s', line)
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

def process_year(year):
    data = fetch_tar(year)
    if not data:
        return {}
    all_daily = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.name.endswith('events.txt'): continue
            f = tar.extractfile(member)
            if not f: continue
            content = f.read().decode('utf-8', errors='ignore')
            day_daily = parse_events_file(content)
            for d, v in day_daily.items():
                if d.year != year: continue
                if d not in all_daily:
                    all_daily[d] = v
                else:
                    if v['xray_max'] > all_daily[d]['xray_max']:
                        all_daily[d]['xray_max'] = v['xray_max']
                    if FLARE_CLASS_RANK.get(v['xray_class_max'], 0) > FLARE_CLASS_RANK.get(all_daily[d]['xray_class_max'], 0):
                        all_daily[d]['xray_class_max'] = v['xray_class_max']
                    if v['has_m_flare']: all_daily[d]['has_m_flare'] = 1
                    if v['has_x_flare']: all_daily[d]['has_x_flare'] = 1
    return all_daily

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
for year in range(2018, 2027):
    print(f"Processing {year}...", end=" ", flush=True)
    try:
        daily = process_year(year)
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
