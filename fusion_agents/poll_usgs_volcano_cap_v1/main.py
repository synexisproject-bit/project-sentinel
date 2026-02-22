import os
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, List

import requests
from google.cloud import bigquery
from lxml import etree

# --------- Config via env ---------
BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.getenv("BQ_TABLE", "volcano_alerts_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://volcanoes.usgs.gov/hans-public/api/volcano/getCapElevated")
SRC_TAG    = os.getenv("SRC_TAG", "usgs-volcano")
REV_TS     = os.getenv("REV_TS", "")  # just to force fresh revisions on deploy

# --------- Helpers ---------
def _xn(node, expr: str):
    """Namespace-agnostic XPath using local-name()."""
    return node.xpath(expr)

def _xt(node, expr: str) -> Optional[str]:
    """Return text for the first match, or None."""
    if node is None:
        return None
    r = node.xpath(expr)
    if not r:
        return None
    if isinstance(r[0], etree._Element):
        t = (r[0].text or "").strip()
        return t or None
    # attribute or string result
    return (str(r[0]).strip() or None)

def _parse_iso8601(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        # normalize “Z” and ensure RFC3339
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def _first_latlon_from_polygon(poly: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """CAP polygon: 'lat,lon lat,lon ...' → first pair"""
    if not poly:
        return None, None
    try:
        pts = poly.split()
        if not pts:
            return None, None
        lat_str, lon_str = pts[0].split(",")
        return float(lat_str), float(lon_str)
    except Exception:
        return None, None

def _entry_to_row(entry: etree._Element) -> Optional[dict]:
    """
    Map one Atom <entry> (wrapping CAP <alert>) → row for volcano_alerts_raw.
    Target schema (from your table):
      id,event,headline,sender,severity,urgency,certainty,status,volcano,area,polygon,
      latitude,longitude,sent,effective,expires,url,src,raw
    """
    # Atom basics
    entry_id = _xt(entry, ".//*[local-name()='id']/text()")
    updated  = _xt(entry, ".//*[local-name()='updated']/text()")
    title    = _xt(entry, ".//*[local-name()='title']/text()")
    link     = _xt(entry, ".//*[local-name()='link']/@href") or entry_id

    # Inline CAP alert (prefer)
    cap_alert = None
    contents = _xn(entry, ".//*[local-name()='content']/*[local-name()='alert']")
    if contents:
        cap_alert = contents[0]
    else:
        # sometimes content may contain raw CAP text
        cap_text = _xt(entry, ".//*[local-name()='content']/text()")
        if cap_text:
            try:
                tmp = etree.fromstring(cap_text.encode("utf-8"))
                if tmp is not None and tmp.tag and tmp.tag.lower().endswith("alert"):
                    cap_alert = tmp
            except Exception:
                cap_alert = None

    if cap_alert is None:
        # last resort: any descendant named alert
        maybe = _xn(entry, ".//*[local-name()='alert']")
        if maybe:
            cap_alert = maybe[0]

    # CAP fields (namespace-agnostic)
    event       = _xt(cap_alert, ".//*[local-name()='event']/text()") if cap_alert is not None else None
    headline    = _xt(cap_alert, ".//*[local-name()='headline']/text()") if cap_alert is not None else title
    sender      = _xt(cap_alert, ".//*[local-name()='sender']/text()") if cap_alert is not None else None
    severity    = _xt(cap_alert, ".//*[local-name()='severity']/text()") if cap_alert is not None else None
    urgency     = _xt(cap_alert, ".//*[local-name()='urgency']/text()") if cap_alert is not None else None
    certainty   = _xt(cap_alert, ".//*[local-name()='certainty']/text()") if cap_alert is not None else None
    status      = _xt(cap_alert, ".//*[local-name()='status']/text()") if cap_alert is not None else None

    # Some volcano feeds include a volcano name inside <areaDesc> or <parameter>
    area_nodes  = _xn(cap_alert, ".//*[local-name()='area']") if cap_alert is not None else []
    area_desc   = _xt(area_nodes[0], ".//*[local-name()='areaDesc']/text()") if area_nodes else None
    polygon     = _xt(area_nodes[0], ".//*[local-name()='polygon']/text()") if area_nodes else None
    lat, lon    = _first_latlon_from_polygon(polygon)

    # Opportunistic volcano name (best-effort)
    volcano     = None
    if area_desc:
        # simple heuristic: often like "Volcano: X" or just volcano name
        volcano = area_desc

    sent        = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='sent']/text()") if cap_alert is not None else None)
    effective   = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='effective']/text()") if cap_alert is not None else None)
    expires     = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='expires']/text()") if cap_alert is not None else None)

    row = {
        "id": entry_id or link or (headline or "unknown"),
        "event": event,
        "headline": headline,
        "sender": sender,
        "severity": severity,
        "urgency": urgency,
        "certainty": certainty,
        "status": status,
        "volcano": volcano,
        "area": area_desc,
        "polygon": polygon,
        "latitude": lat,
        "longitude": lon,
        "sent": sent,
        "effective": effective,
        "expires": expires,
        "url": link,
        "src": SRC_TAG,
        "raw": etree.tostring(entry, encoding="unicode"),
    }
    return row

def _insert_rows(rows: List[dict]) -> dict:
    client = bigquery.Client()
    table_id = f"{client.project}.{BQ_DATASET}.{BQ_TABLE}"
    errors = client.insert_rows_json(table_id, rows, ignore_unknown_values=True)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "inserted": len(rows)}

# --------- Cloud Function entrypoint ---------
def handler(request):
    now = datetime.now(timezone.utc)
    print(f"REV_TS={REV_TS} Fetching volcano CAP/Atom feed: {SOURCE_URL}")

    try:
        r = requests.get(SOURCE_URL, timeout=20)
        r.raise_for_status()
        content = r.content
        print(f"Fetch ok {len(content)} bytes; first 120: {content[:120]!r}")
    except Exception as e:
        print(f"HTTP error fetching feed: {e}")
        return (json.dumps({"ok": False, "error": "http_error"}), 200, {"Content-Type": "application/json"})

    # Try XML parse (CAP/Atom). If JSON, you can extend later.
    rows: List[dict] = []
    try:
        root = etree.fromstring(content)
        entries = root.xpath(".//*[local-name()='entry']")
        print(f"Root tag: {root.tag}, entries found: {len(entries)}")

        for e in entries:
            row = _entry_to_row(e)
            if row:
                rows.append(row)
    except Exception as e:
        print(f"XML parse path failed: {e}")
        rows = []  # ensure list

    # If nothing parsed → HEARTBEAT
    if not rows:
        hb_row = {
            "id": f"heartbeat-{now.isoformat().replace(':','').replace('.','')}",
            "event": "HEARTBEAT",
            "headline": "No active volcano alerts (heartbeat)",
            "sender": "system",
            "severity": None,
            "urgency": None,
            "certainty": None,
            "status": "Actual",
            "volcano": None,
            "area": None,
            "polygon": None,
            "latitude": None,
            "longitude": None,
            "sent": now.isoformat().replace("+00:00", "Z"),
            "effective": None,
            "expires": None,
            "url": SOURCE_URL,
            "src": SRC_TAG,
            "raw": "{}",
        }
        rows = [hb_row]
        print("No entries parsed; inserting heartbeat row.")

    result = _insert_rows(rows)
    print(f"Insert result: {result}")
    return (json.dumps(result), 200, {"Content-Type": "application/json"})
