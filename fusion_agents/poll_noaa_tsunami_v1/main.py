import os, json, requests, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
TABLE   = os.environ.get("BQ_TABLE",   "tsunami_alerts_raw")
URL     = os.environ.get("SOURCE_URL")
bq = bigquery.Client(project=PROJECT)

def _ts(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        return None

NS = {'atom':'http://www.w3.org/2005/Atom','cap':'urn:oasis:names:tc:emergency:cap:1.1'}

def handler(request=None):
    print(f"Fetching tsunami feed: {URL}")
    r = requests.get(URL, headers={"User-Agent":"Synexis-Project-Sentinel"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    rows = []
    for entry in root.findall('atom:entry', NS):
        id_ = (entry.findtext('atom:id', default='', namespaces=NS) or "").strip()
        title = (entry.findtext('atom:title', default='', namespaces=NS) or "").strip()
        updated = (entry.findtext('atom:updated', default='', namespaces=NS) or "").strip()
        link_el = entry.find('atom:link', NS)
        url = link_el.get('href') if link_el is not None else None
        rows.append({
            "id": id_ or url,
            "headline": title,
            "description": None,
            "severity": None,
            "urgency": None,
            "region": None,
            "latitude": None,
            "longitude": None,
            "polygon": None,
            "sent": _ts(updated),
            "effective": None,
            "expires": None,
            "url": url,
            "src": "tsunami-noaa",
            "raw": json.dumps({"entry_xml": ET.tostring(entry, encoding="unicode")}, ensure_ascii=False)
        })
    if not rows: return ("ok", 200)
    bq.load_table_from_json(rows, f"{PROJECT}.{DATASET}.{TABLE}").result()
    return ("ok", 200)
