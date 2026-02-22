import os
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, List

import requests
from google.cloud import bigquery
from lxml import etree

# ---------- Config ----------
BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.getenv("BQ_TABLE", "tsunami_alerts_raw")
SOURCE_URL = os.getenv("SOURCE_URL", "https://www.tsunami.gov/events/xml/PAAQCAP.xml")
SRC_TAG = os.getenv("SRC_TAG", "tsunami-noaa")
REV_TS = os.getenv("REV_TS", "")  # used only to force a new revision
INSERT_HEARTBEAT_ON_EMPTY = os.getenv("INSERT_HEARTBEAT_ON_EMPTY", "true").lower() == "true"

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SEC", "20"))

# ---------- Helpers ----------
def _xn(node, expr: str):
    """Namespace-agnostic XPath using local-name(). Returns list of elements/values."""
    return node.xpath(expr)

def _xt(node, expr: str) -> Optional[str]:
    """Get text/value for the first XPath result, or None."""
    if node is None:
        return None
    r = node.xpath(expr)
    if not r:
        return None
    v = r[0]
    if isinstance(v, etree._Element):
        return (v.text or "").strip() or None
    return (str(v).strip() or None)

def _parse_iso8601(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None

def _first_latlon_from_polygon(poly: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """CAP polygon is 'lat,lon lat,lon ...' — return first pair as floats if present."""
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

def _heartbeat_row(now_utc: datetime) -> dict:
    ts = now_utc.isoformat().replace("+00:00", "Z")
    return {
        "id": f"heartbeat-{ts}",
        "headline": "No active tsunami alerts (heartbeat)",
        "description": None,
        "severity": None,
        "urgency": None,
        "region": None,
        "latitude": None,
        "longitude": None,
        "polygon": None,
        "sent": ts,
        "effective": ts,
        "expires": ts,
        "url": SOURCE_URL,
        "src": SRC_TAG,
        "raw": "{}",
        "_ingested_at": ts,
    }

def _entry_to_row(entry: etree._Element, now_utc: datetime) -> Optional[dict]:
    """Map one Atom <entry> (wrapping a CAP <alert>) to a BigQuery row."""
    # Atom basics
    entry_id = _xt(entry, ".//*[local-name()='id']/text()")
    updated = _xt(entry, ".//*[local-name()='updated']/text()")  # may be unused, but harmless
    title = _xt(entry, ".//*[local-name()='title']/text()")
    link = _xt(entry, ".//*[local-name()='link']/@href") or entry_id

    # Try to find inline CAP payload
    cap_alert = None
    contents = _xn(entry, ".//*[local-name()='content']/*[local-name()='alert']")
    if contents:
        cap_alert = contents[0]
    else:
        # Sometimes CAP XML is text inside <content>
        cap_text = _xt(entry, ".//*[local-name()='content']/text()")
        if cap_text:
            try:
                tmp = etree.fromstring(cap_text.encode("utf-8"))
                if tmp is not None and tmp.tag and tmp.tag.lower().endswith("alert"):
                    cap_alert = tmp
            except Exception:
                cap_alert = None

    # As a loose fallback, grab any descendant named 'alert'
    if cap_alert is None:
        maybe = _xn(entry, ".//*[local-name()='alert']")
        if maybe:
            cap_alert = maybe[0]

    # Extract CAP fields (namespace-agnostic)
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
    now_str = now_utc.isoformat().replace("+00:00", "Z")
    row = {
        "id": entry_id or link or (headline or f"unknown-{now_str}"),
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
        "url": link or SOURCE_URL,
        "src": SRC_TAG,
        "raw": etree.tostring(entry, encoding="unicode"),
        "_ingested_at": now_str,
    }
    return row

def _fetch_feed(url: str) -> bytes:
    print(f"REV_TS={REV_TS} Fetching tsunami CAP feed: {url}")
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.content

def _parse_atom(xml_bytes: bytes) -> List[etree._Element]:
    # Robust XML parser
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    print(f"Root tag: {root.tag}, nsmap: {root.nsmap}")
    # Find entries regardless of namespaces
    entries = root.xpath(".//*[local-name()='entry']")
    return [e for e in entries if isinstance(e, etree._Element)]

def _insert_rows_bq(rows: List[dict]) -> None:
    client = bigquery.Client()
    table_ref = f"{client.project}.{BQ_DATASET}.{BQ_TABLE}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        # errors is a list; surface it clearly
        raise RuntimeError(f"BigQuery insert errors: {errors}")

# ---------- Cloud Function entry ----------
def handler(request):
    try:
        now_utc = datetime.now(timezone.utc)

        xml_bytes = _fetch_feed(SOURCE_URL)
        print(f"Fetch ok {len(xml_bytes)} bytes; first 120 chars: {repr(xml_bytes[:120])}")

        entries = _parse_atom(xml_bytes)
        rows: List[dict] = []

        for e in entries:
            row = _entry_to_row(e, now_utc)
            if row:
                rows.append(row)

        if not rows:
            if INSERT_HEARTBEAT_ON_EMPTY:
                rows = [_heartbeat_row(now_utc)]
                print("No entries in feed; inserting heartbeat row to advance freshness.")
            else:
                return (
                    json.dumps({"ok": True, "inserted": 0, "reason": "no_entries"}),
                    200,
                    {"Content-Type": "application/json"},
                )

        _insert_rows_bq(rows)

        return (
            json.dumps({"ok": True, "inserted": len(rows)}),
            200,
            {"Content-Type": "application/json"},
        )

    except requests.HTTPError as e:
        msg = f"HTTP error fetching feed: {getattr(e.response, 'status_code', 'unknown')} {str(e)}"
        print(msg)
        return json.dumps({"ok": False, "error": msg}), 502, {"Content-Type": "application/json"}
    except Exception as e:
        msg = f"Unhandled error: {type(e).__name__}: {str(e)}"
        print(msg)
        return json.dumps({"ok": False, "error": msg}), 500, {"Content-Type": "application/json"}
