import os
import re
import math
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import requests
from flask import Flask, request, jsonify
from google.cloud import bigquery
import google.auth

app = Flask(__name__)

# ----------------------------
# Config
# ----------------------------
SRC_TAG = "gcp-egg"

BASE_URL = os.getenv("GCP_EGG_BASE_URL", "https://global-mind.org/data/eggsummary")
BQ_DATASET = os.getenv("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.getenv("BQ_TABLE", "gcp_egg_raw")

# Process safety
MAX_DAYS_PER_RUN = int(os.getenv("MAX_DAYS_PER_RUN", "7"))
LAG_DAYS = int(os.getenv("LAG_DAYS", "0"))  # you can keep 0 for now

PROJECT = os.getenv("PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""


def _resolve_project() -> str:
    proj = PROJECT
    if not proj:
        proj = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""
    if not proj:
        # ADC fallback (Cloud Run friendly)
        try:
            _, proj = google.auth.default()
        except Exception:
            proj = ""
    if not proj:
        raise RuntimeError("Project id not found (set PROJECT or rely on ADC / GOOGLE_CLOUD_PROJECT).")
    return proj


def _table_fq() -> str:
    proj = _resolve_project()
    return f"{proj}.{BQ_DATASET}.{BQ_TABLE}"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _build_daily_url(d: date) -> str:
    # Example: https://global-mind.org/data/eggsummary/2026/basketdata-2026-01-01.csv.gz
    return f"{BASE_URL}/{d.year}/basketdata-{d.isoformat()}.csv.gz"


def _fetch_gz(url: str) -> bytes:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        raise FileNotFoundError(url)
    r.raise_for_status()
    return r.content


def _parse_gcp_daily_to_aggregate(gz_bytes: bytes, d: date) -> Dict[str, Any]:
    # Decode gz -> text
    try:
        raw_csv = gzip.decompress(gz_bytes).decode("utf-8", errors="replace")
    except Exception as e:
        return {
            "id": f"gcp_day_{d.isoformat()}",
            "egg_id": None,
            "zscore": None,
            "deviation": None,
            "network_mean": None,
            "variance": None,
            "eggs_reporting": None,
            "status": "decode_error",
            "sent": datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat(),
            "url": _build_daily_url(d),
            "src": SRC_TAG,
            "raw": f"decode_error: {e}",
        }

    # eggs_reporting metadata line example:
    # 11,1,9,"Eggs reporting"
    m = re.search(r'11,1,(\d+),"Eggs reporting"', raw_csv)
    eggs_reporting = int(m.group(1)) if m else None

    # start/end unix in metadata (optional, for raw/debug)
    m2 = re.search(r'11,2,(\d+),"Start time"', raw_csv)
    start_unix = int(m2.group(1)) if m2 else None
    m3 = re.search(r'11,3,(\d+),"End time"', raw_csv)
    end_unix = int(m3.group(1)) if m3 else None

    vals: List[float] = []
    # Data lines start with 13, <unix>, , <v1>,<v2>...
    for line in raw_csv.splitlines():
        if not line.startswith("13,"):
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        for p in parts[3:]:
            p = p.strip().strip('"')
            if p == "" or p.lower() == "nan":
                continue
            try:
                vals.append(float(p))
            except Exception:
                continue

    if not vals:
        return {
            "id": f"gcp_day_{d.isoformat()}",
            "egg_id": "NETWORK_DAILY",
            "zscore": None,
            "deviation": None,
            "network_mean": None,
            "variance": None,
            "eggs_reporting": eggs_reporting,
            "status": "no_data",
            "sent": datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat(),
            "url": _build_daily_url(d),
            "src": SRC_TAG,
            "raw": f"no_numeric_vals eggs={eggs_reporting} start={start_unix} end={end_unix}",
        }

    n = len(vals)
    mean = sum(vals) / n
    var = sum((x - mean) ** 2 for x in vals) / n
    std = math.sqrt(var) if var > 0 else 0.0
    z = (mean / std) if std > 0 else None

    return {
        "id": f"gcp_day_{d.isoformat()}",
        "egg_id": "NETWORK_DAILY",
        "zscore": float(z) if z is not None else None,
        "deviation": None,
        "network_mean": float(mean),
        "variance": float(var),
        "eggs_reporting": eggs_reporting,
        "status": "ok",
        "sent": datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat(),
        "url": _build_daily_url(d),
        "src": SRC_TAG,
        "raw": f"nvals={n} eggs={eggs_reporting} start={start_unix} end={end_unix}",
    }


def _already_inserted(bq: bigquery.Client, row_id: str) -> bool:
    q = f"SELECT 1 FROM `{_table_fq()}` WHERE id = @id LIMIT 1"
    job = bq.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", row_id)]
        ),
    )
    return any(True for _ in job.result())


def _insert_one(bq: bigquery.Client, row: Dict[str, Any]) -> int:
    if not row:
        return 0
    rid = row.get("id")
    if not rid:
        raise RuntimeError("Row missing id")
    # Hard dedupe (authoritative)
    if _already_inserted(bq, rid):
        return 0
    # Still include insertId to help if retries happen
    errors = bq.insert_rows_json(_table_fq(), [row], row_ids=[rid])
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors[:3]}{'...' if len(errors)>3 else ''}")
    return 1


def handler_v2(req) -> Dict[str, Any]:
    args = req.args or {}
    max_days = int(args.get("max_days", MAX_DAYS_PER_RUN))

    # Parse start/end
    start_s = args.get("start")
    end_s = args.get("end")

    today_utc = _utc_today()
    safe_end = today_utc - timedelta(days=1 + max(0, LAG_DAYS))

    if start_s and end_s:
        start_d = date.fromisoformat(start_s)
        end_d = date.fromisoformat(end_s)
    else:
        # Default to safe_end only (single day) to keep behavior predictable
        start_d = safe_end
        end_d = safe_end

    if end_d > safe_end:
        end_d = safe_end
    if start_d > end_d:
        start_d = end_d

    # Clamp to max_days
    span = (end_d - start_d).days + 1
    if span > max_days:
        end_d = start_d + timedelta(days=max_days - 1)

    bq = bigquery.Client()

    inserted = 0
    skipped = 0
    processed = 0

    d = start_d
    while d <= end_d:
        processed += 1
        url = _build_daily_url(d)
        try:
            gz = _fetch_gz(url)
            agg = _parse_gcp_daily_to_aggregate(gz, d)
            n = _insert_one(bq, agg)
            if n == 1:
                inserted += 1
            else:
                skipped += 1
        except FileNotFoundError:
            # upstream missing file, stop early
            break
        d += timedelta(days=1)

    return {
        "ok": True,
        "inserted": inserted,
        "skipped": skipped,
        "days_processed": processed,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
    }


@app.route("/")
def root():
    try:
        out = handler_v2(request)
        return jsonify(out), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
