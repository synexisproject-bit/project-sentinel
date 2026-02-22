import os
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, List

import requests
from google.cloud import bigquery
from lxml import etree

# --------- Config ---------
BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.getenv("BQ_TABLE", "tsunami_alerts_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://www.tsunami.gov/events/xml/PAAQCAP.xml")
SRC_TAG = os.getenv("SRC_TAG", "tsunami-noaa")
REV_TS = os.getenv("REV_TS", "")  # used only to force a new revision

# --------- Helpers ---------
def _xn(node, expr: str):
    """Namespace-agnostic XPath using local-name(). Returns list of elements."""
    return node.xpath(expr)

def _xt(node, expr: str) -> Optional[str]:
    """Text helper (first match)."""
    r = node.xpath(expr)
    if not r:
        return None
    if isinstance(r[0], etree._Element):
        return (r[0].text or "").strip() or None
    # attribute or string result
    v = str(r[0]).strip()
    return v or None

def _parse_iso8601(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        # normalize to RFC3339 if needed
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def _first_latlon_from_polygon(poly: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Given CAP polygon string 'lat,lon lat,lon ...', return first pair as floats."""
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

def _entry_to_row(entry: etree._Element, now_utc: datetime) -> Optional[dict]:
    """Map one Atom entry (wrapping a CAP alert) to a BigQuery row."""
    # Atom basics
    entry_id = _xt(entry, ".//*[local-name()='id']/text()")
    updated = _xt(entry, ".//*[local-name()='updated']/text()")
    title = _xt(entry, ".//*[local-name()='title']/text()")
    link = _xt(entry, ".//*[local-name()='link']/@href") or _xt(entry, ".//*[local-name()='id']/text()")

    # CAP payload: prefer inline <content> that contains <alert>
    # 1) inline CAP:
    cap_alert = None
    contents = _xn(entry, ".//*[local-name()='content']/*[local-name()='alert']")
    if contents:
        cap_alert = contents[0]
    else:
        # 2) sometimes Atom uses <entry><content>CAP-XML-as-text</content>
        # try parsing that inner text as XML
        cap_text = _xt(entry, ".//*[local-name()='content']/text()")
        if cap_text:
            try:
                tmp = etree.fromstring(cap_text.encode("utf-8"))
                if tmp is not None and tmp.tag and tmp.tag.lower().endswith("alert"):
                    cap_alert = tmp
            except Exception:
                cap_alert = None

    # If still no inline CAP, we could follow link, but most NOAA tsunami entries are inline.
    if cap_alert is None:
        # As a fallback, try to find any descendant named alert
        maybe = _xn(entry, ".//*[local-name()='alert']")
        if maybe:
            cap_alert = maybe[0]

    # Pull CAP fields safely (namespace-agnostic)
    headline = _xt(cap_alert, ".//*[local-name()='headline']/text()") if cap_alert is not None else title
    description = _xt(cap_alert, ".//*[local-name()='description']/text()") if cap_alert is not None else None
    severity = _xt(cap_alert, ".//*[local-name()='severity']/text()") if cap_alert is not None else None
    urgency = _xt(cap_alert, ".//*[local-name()='urgency']/text()") if cap_alert is not None else None
    area = _xn(cap_alert, ".//*[local-name()='area']") if cap_alert is not None else []
    region = _xt(area[0], ".//*[local-name()='areaDesc']/text()") if area else None
    polygon = _xt(area[0], ".//*[local-name()='polygon']/text()") if area else None

    sent = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='sent']/text()") if cap_alert is not None else None)
    effective = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='effective']/text()") if cap_alert is not None else None)
    expires = _parse_iso8601(_xt(cap_alert, ".//*[local-name()='expires']/text()") if cap_alert is not None else None)

    lat, lon = _first_latlon_from_polygon(polygon)

    # Build row
    row = {
        "id": entry_id or link or (headline or "unknown"),
        "headline": headline,
        "description": description,
        "severity": severity,
        "urgency": urgency,
        "region": region,
        "latitude": lat,
        "longitude": lon,
        "polygon": polygon,
        "sent": sent,
        "effective": effective,
        "expires": expires,
        "url": link,
        "src": SRC_TAG,
        "raw": etree.tostring(entry, encoding="unicode"),
        "_ingested_at": now_utc.isoformat().replace("+00:00", "Z"),
    }
    return row

# --------- HTTP Entry Point ---------
def handler(request):
    now_utc = datetime.now(timezone.utc)

    try:
        print(f"REV_TS={REV_TS} Fetching tsunami CAP feed: {SOURCE_URL}")
        r = requests.get(SOURCE_URL, timeout=30)
        r.raise_for_status()
        xml = r.content
    except Exception as e:
        return (json.dumps({"ok": False, "error": f"fetch_failed: {e}"}), 500, {"Content-Type": "application/json"})

    try:
        root = etree.fromstring(xml)

        # Atom feed entries are usually under //entry
        entries = root.xpath(".//*[local-name()='entry']")
        rows: List[dict] = []

        for entry in entries:
            row = _entry_to_row(entry, now_utc)
            if row and row.get("id"):
                rows.append(row)

        # No entries? Return OK but empty (feed can be quiet)
        if not rows:
            return (json.dumps({"ok": True, "inserted": 0, "reason": "no_entries"}), 200, {"Content-Type": "application/json"})

        client = bigquery.Client()
        table_id = f"{client.project}.{BQ_DATASET}.{BQ_TABLE}"

        errors = client.insert_rows_json(table_id, rows, skip_invalid_rows=True, ignore_unknown_values=True)
        if errors:
            # flatten errors for easier debugging
            return (json.dumps({"ok": False, "errors": errors}), 500, {"Content-Type": "application/json"})

        return (json.dumps({"ok": True, "inserted": len(rows)}), 200, {"Content-Type": "application/json"})

    except Exception as e:
        # surface parsing issues
        return (json.dumps({"ok": False, "error": f"parse_or_bq_failed: {e}"}), 500, {"Content-Type": "application/json"})
