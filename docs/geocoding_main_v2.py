"""
Project Sentinel — NLP Geocoding Pipeline
Cloud Run Job: extract place names from dream records and geocode them.

Corpora targeted:
  - archive_import  (~2,100 Reddit records)
  - archive_sddb    (~2,000 SDDb records)
NEXA corpus (34 records) is excluded — coordinates already corrected.

Outputs: updates hac_intake.hac_normalized.referred_lat_approx / referred_lon_approx
Checkpoint table: sentinel_geocoding.geocoding_checkpoint (resume-safe)
"""

import os
import json
import time
import logging
import hashlib
from typing import Optional

from google.cloud import bigquery, secretmanager
import anthropic

from extractor import extract_place_names, strip_reddit_title
from geocoder import geocode_place_names, GeocodingResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GCP_PROJECT       = os.environ.get("GCP_PROJECT", "synexis-project-sentinel")
BQ_DATASET        = os.environ.get("BQ_DATASET", "hac_intake")
BQ_TABLE          = os.environ.get("BQ_TABLE", "hac_normalized")
CHECKPOINT_DATASET= os.environ.get("CHECKPOINT_DATASET", "sentinel_geocoding")
CHECKPOINT_TABLE  = os.environ.get("CHECKPOINT_TABLE", "geocoding_checkpoint")
BATCH_SIZE        = int(os.environ.get("BATCH_SIZE", "50"))
ANTHROPIC_SECRET  = os.environ.get("ANTHROPIC_SECRET_NAME", "ANTHROPIC_API_KEY")
TARGET_CORPORA    = ["archive_import", "archive_sddb"]   # NEXA excluded
MAX_RECORDS       = int(os.environ.get("MAX_RECORDS", "0"))   # 0 = all


def get_anthropic_key() -> str:
    """Fetch Anthropic API key from GCP Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT}/secrets/{ANTHROPIC_SECRET}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8").strip()


def ensure_checkpoint_table(bq: bigquery.Client) -> None:
    """Create checkpoint table if it doesn't exist."""
    dataset_ref = bigquery.Dataset(f"{GCP_PROJECT}.{CHECKPOINT_DATASET}")
    try:
        bq.create_dataset(dataset_ref, exists_ok=True)
    except Exception:
        pass

    schema = [
        bigquery.SchemaField("submission_id",        "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("source_type",     "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("status",            "STRING",  mode="REQUIRED"),   # done|failed|no_place
        bigquery.SchemaField("extracted_places",  "STRING",  mode="NULLABLE"),   # JSON array
        bigquery.SchemaField("primary_place",     "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("geocode_source",    "STRING",  mode="NULLABLE"),   # nominatim|fallback|manual
        bigquery.SchemaField("lat",               "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("lon",               "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("geocode_confidence","FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("processed_at",      "TIMESTAMP", mode="REQUIRED"),
    ]
    table_ref = f"{GCP_PROJECT}.{CHECKPOINT_DATASET}.{CHECKPOINT_TABLE}"
    table = bigquery.Table(table_ref, schema=schema)
    bq.create_table(table, exists_ok=True)
    log.info("Checkpoint table ready: %s", table_ref)


def get_already_processed(bq: bigquery.Client) -> set[str]:
    """Return set of submission_ids already successfully processed."""
    query = f"""
        SELECT submission_id
        FROM `{GCP_PROJECT}.{CHECKPOINT_DATASET}.{CHECKPOINT_TABLE}`
        WHERE status IN ('done', 'no_place')
    """
    try:
        result = bq.query(query).result()
        ids = {row.submission_id for row in result}
        log.info("Resuming: %d records already processed", len(ids))
        return ids
    except Exception:
        return set()


def fetch_unprocessed_records(bq: bigquery.Client, done_ids: set[str]) -> list[dict]:
    """Fetch records needing geocoding from hac_normalized."""
    corpus_filter = ", ".join(f"'{c}'" for c in TARGET_CORPORA)
    query = f"""
        SELECT
            submission_id,
            source_type,
            llm_extracted_symbols,
            narrative_text
        FROM `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
        WHERE source_type IN ({corpus_filter})
          AND is_geophysical = TRUE
          AND is_dream_modality = TRUE
          AND (referred_lat_approx IS NULL OR referred_lon_approx IS NULL)
        ORDER BY source_type, submission_id
    """
    if MAX_RECORDS > 0:
        query += f"\nLIMIT {MAX_RECORDS}"

    rows = list(bq.query(query).result())
    # Filter already-done in memory (avoids NOT IN with huge list)
    records = [
        dict(row) for row in rows
        if row["submission_id"] not in done_ids
    ]
    log.info("Records to process: %d", len(records))
    return records


def write_checkpoint(bq: bigquery.Client, rows: list[dict]) -> None:
    """Upsert checkpoint rows. Uses INSERT + merge pattern via temp table."""
    if not rows:
        return
    table_ref = f"{GCP_PROJECT}.{CHECKPOINT_DATASET}.{CHECKPOINT_TABLE}"
    errors = bq.insert_rows_json(table_ref, rows)
    if errors:
        log.warning("Checkpoint insert errors: %s", errors[:3])


def bulk_update_bq_coordinates(bq: bigquery.Client, updates: list[dict]) -> None:
    """
    Batch-update referred_lat_approx / referred_lon_approx in hac_normalized.
    Uses load_table_from_json (avoids streaming buffer issues with temp tables).
    """
    if not updates:
        return

    import json as _json
    temp_table = f"{GCP_PROJECT}.{CHECKPOINT_DATASET}.geocoding_updates_tmp"
    schema = [
        bigquery.SchemaField("submission_id", "STRING"),
        bigquery.SchemaField("lat",           "FLOAT64"),
        bigquery.SchemaField("lon",           "FLOAT64"),
    ]
    table = bigquery.Table(temp_table, schema=schema)
    bq.delete_table(temp_table, not_found_ok=True)

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_TRUNCATE",
    )
    load_job = bq.load_table_from_json(updates, temp_table, job_config=job_config)
    load_job.result()  # wait for load to complete

    merge_sql = f"""
        MERGE `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}` T
        USING `{temp_table}` S
        ON T.submission_id = S.submission_id
        WHEN MATCHED THEN UPDATE SET
            T.referred_lat_approx = S.lat,
            T.referred_lon_approx = S.lon
    """
    bq.query(merge_sql).result()
    bq.delete_table(temp_table, not_found_ok=True)
    log.info("Updated %d records in BigQuery", len(updates))


def process_batch(
    records: list[dict],
    anthropic_client: anthropic.Anthropic,
) -> tuple[list[dict], list[dict]]:
    """
    Process one batch of records.
    Returns (checkpoint_rows, bq_update_rows).
    """
    from datetime import datetime, timezone

    checkpoint_rows = []
    bq_updates      = []
    now_ts          = datetime.now(timezone.utc).isoformat()

    for rec in records:
        submission_id     = rec["submission_id"]
        source_type = rec["source_type"]
        symbols_json  = rec.get("llm_extracted_symbols") or "{}"
        narrative     = rec.get("narrative_text") or ""
        source_name   = rec.get("source_name") or ""
        narrative     = strip_reddit_title(narrative, source_name)

        # ── 1. Extract place names via Claude ────────────────────────────────
        try:
            places = extract_place_names(
                anthropic_client,
                symbols_json=symbols_json,
                narrative_text=narrative,
            )
        except Exception as e:
            log.warning("[%s] extraction failed: %s", submission_id, e)
            checkpoint_rows.append({
                "submission_id":        submission_id,
                "source_type":    source_type,
                "status":           "failed",
                "extracted_places": None,
                "primary_place":    None,
                "geocode_source":   None,
                "lat":              None,
                "lon":              None,
                "geocode_confidence": None,
                "processed_at":     now_ts,
            })
            continue

        if not places:
            checkpoint_rows.append({
                "submission_id":        submission_id,
                "source_type":    source_type,
                "status":           "no_place",
                "extracted_places": "[]",
                "primary_place":    None,
                "geocode_source":   None,
                "lat":              None,
                "lon":              None,
                "geocode_confidence": None,
                "processed_at":     now_ts,
            })
            continue

        # ── 2. Geocode ────────────────────────────────────────────────────────
        geo: Optional[GeocodingResult] = geocode_place_names(places)

        if geo is None:
            checkpoint_rows.append({
                "submission_id":        submission_id,
                "source_type":    source_type,
                "status":           "no_place",
                "extracted_places": json.dumps(places),
                "primary_place":    places[0] if places else None,
                "geocode_source":   "failed",
                "lat":              None,
                "lon":              None,
                "geocode_confidence": None,
                "processed_at":     now_ts,
            })
            continue

        checkpoint_rows.append({
            "submission_id":          submission_id,
            "source_type":      source_type,
            "status":             "done",
            "extracted_places":   json.dumps(places),
            "primary_place":      geo.primary_place,
            "geocode_source":     geo.source,
            "lat":                geo.lat,
            "lon":                geo.lon,
            "geocode_confidence": geo.confidence,
            "processed_at":       now_ts,
        })
        bq_updates.append({
            "submission_id": submission_id,
            "lat":       geo.lat,
            "lon":       geo.lon,
        })

    return checkpoint_rows, bq_updates


def main():
    log.info("=== Project Sentinel NLP Geocoding Pipeline ===")
    log.info("GCP Project: %s  |  Target corpora: %s", GCP_PROJECT, TARGET_CORPORA)

    # ── Clients ───────────────────────────────────────────────────────────────
    bq = bigquery.Client(project=GCP_PROJECT)
    api_key = get_anthropic_key()
    anthropic_client = anthropic.Anthropic(api_key=api_key)

    # ── Setup ─────────────────────────────────────────────────────────────────
    ensure_checkpoint_table(bq)
    done_ids = get_already_processed(bq)
    records  = fetch_unprocessed_records(bq, done_ids)

    if not records:
        log.info("Nothing to process — all records already geocoded.")
        return

    # ── Batch loop ────────────────────────────────────────────────────────────
    total        = len(records)
    n_done       = 0
    n_geocoded   = 0
    n_no_place   = 0
    n_failed     = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = records[batch_start : batch_start + BATCH_SIZE]
        log.info(
            "Batch %d–%d / %d",
            batch_start + 1, min(batch_start + BATCH_SIZE, total), total,
        )

        cp_rows, bq_rows = process_batch(batch, anthropic_client)

        write_checkpoint(bq, cp_rows)
        bulk_update_bq_coordinates(bq, bq_rows)

        for r in cp_rows:
            if r["status"] == "done":    n_geocoded += 1
            elif r["status"] == "no_place": n_no_place += 1
            else:                           n_failed  += 1
        n_done += len(batch)

        log.info(
            "Progress: %d/%d  |  geocoded=%d  no_place=%d  failed=%d",
            n_done, total, n_geocoded, n_no_place, n_failed,
        )

        # Polite rate-limit pause between batches (Nominatim ToS: 1 req/sec)
        time.sleep(1)

    log.info(
        "=== Complete: %d processed, %d geocoded, %d no-place, %d failed ===",
        n_done, n_geocoded, n_no_place, n_failed,
    )


if __name__ == "__main__":
    main()
