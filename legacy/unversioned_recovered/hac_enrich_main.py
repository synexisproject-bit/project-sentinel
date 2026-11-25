#!/usr/bin/env python3
"""
hac-enrich batch job
Enriches unenriched records via Claude API.
Run explicitly or via Cloud Scheduler.

Environment variables:
  ANTHROPIC_API_KEY  — required
  ANTHROPIC_MODEL    — default: claude-haiku-4-5-20251001
  MAX_RECORDS        — max records to enrich per run (default: 500)
  SOURCE_FILTER      — optional source_type to restrict (e.g. archive_sddb)
  GEOPHYSICAL_KEYWORDS — optional pipe-separated keyword pre-filter

primary_domain taxonomy (aligned with NEXA corpus):
  precognitive_anticipatory  — perception of future events before they occur
  informational_nonlocal     — accessing non-future information beyond senses
  survival_afterdeath        — communication from deceased / ADC
  healing_biological         — recovery/remission via non-ordinary processes
  synchronicity              — meaningful coincidence without causal mechanism
  psychophysical             — mental influence on physical systems
  transcendent_mystical      — unity, ego dissolution, expanded consciousness
  other                      — anomalous but not fitting above
  non_anomalous              — ordinary dream/experience, no anomalous content
"""

import os
import json
import urllib.request
from datetime import datetime, timezone
from google.cloud import bigquery, storage

PROJECT_ID       = "synexis-project-sentinel"
NORMALIZED_TABLE = f"{PROJECT_ID}.hac_intake.hac_normalized"
ENRICHMENT_TABLE = f"{PROJECT_ID}.hac_intake.hac_enrichment"
EMBEDDINGS_BUCKET = f"{PROJECT_ID}-hac-embeddings"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

bq_client  = bigquery.Client(project=PROJECT_ID)
gcs_client = storage.Client(project=PROJECT_ID)

MAX_RECORDS   = int(os.environ.get("MAX_RECORDS", "500"))
MODEL         = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
SOURCE_FILTER = os.environ.get("SOURCE_FILTER", "")

VALID_DOMAINS = {
    "precognitive_anticipatory",
    "informational_nonlocal",
    "survival_afterdeath",
    "healing_biological",
    "synchronicity",
    "psychophysical",
    "transcendent_mystical",
    "other",
    "non_anomalous",
}

EXTRACTION_PROMPT = """You are analyzing a dream or noetic experience report submitted to a scientific research database. Extract structured signal features from the narrative text.

Respond with ONLY a valid JSON object, no preamble or markdown:

{
  "symbols": ["list", "of", "key", "imagery"],
  "dominant_emotion": "single word",
  "geophysical_imagery": true or false,
  "water_imagery": true or false,
  "destruction_imagery": true or false,
  "urgency_level": "low" or "medium" or "high",
  "scale_impression": "personal" or "local" or "regional" or "global",
  "primary_domain": "one of the exact strings listed below",
  "hazard_type": "one of: earthquake, tsunami, flood, volcanic, avalanche, landslide, multiple, none"
}

primary_domain must be exactly one of:
  "precognitive_anticipatory"  — perception of future events before they occur, including geophysical disasters, personal events, world events, or any anticipatory knowing
  "informational_nonlocal"     — accessing information beyond conventional sensory means that is NOT future-oriented (remote viewing of present/past events, telepathy, clairvoyance)
  "survival_afterdeath"        — apparent communication from a deceased person, visitation dream, experience suggesting continued consciousness after death
  "healing_biological"         — experiences involving recovery, remission, or biological change associated with non-ordinary processes
  "synchronicity"              — highly meaningful coincidence without clear causal mechanism
  "psychophysical"             — perceived mental influence on physical systems or external reality
  "transcendent_mystical"      — unity experience, ego dissolution, expanded consciousness, contact with divine or cosmic awareness
  "other"                      — anomalous experience not fitting any above category
  "non_anomalous"              — ordinary dream or experience with no apparent anomalous or precognitive content

geophysical_imagery should be true if the narrative contains imagery of earthquakes, tsunamis, floods, volcanoes, storms, wildfires, or large-scale natural disasters — whether named explicitly OR described implicitly (massive waves, shaking ground, walls of water, ash clouds, cities destroyed, earth opening up, sky turning dark).

hazard_type must be exactly one of:
  "earthquake"  — ground shaking, earth splitting, buildings collapsing from seismic activity
  "tsunami"     — massive ocean waves, walls of water, coastal inundation
  "flood"       — rising water, flooding rivers, inundation not from ocean waves
  "volcanic"    — eruption, lava, ash clouds, volcanic explosions
  "avalanche"   — snow, ice, or debris cascading down a mountain
  "landslide"   — earth, mud, or rock sliding or collapsing
  "multiple"    — clear imagery of more than one hazard type
  "none"        — no specific geophysical hazard imagery present

Narrative:
"""


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def fetch_unenriched_records():
    source_clause = (
        f"AND n.source_type = '{SOURCE_FILTER}'"
        if SOURCE_FILTER else ""
    )

    geophysical_keywords = os.environ.get("GEOPHYSICAL_KEYWORDS", "")
    if geophysical_keywords:
        keywords = [k.strip() for k in geophysical_keywords.replace(",", "|").split("|")]
        kw_clauses = " OR ".join(
            [f"LOWER(n.narrative_text) LIKE '%{k}%'" for k in keywords]
        )
        keyword_clause = f"AND ({kw_clauses})"
    else:
        keyword_clause = ""

    query = f"""
    SELECT n.submission_id, n.narrative_text, n.source_type
    FROM `{NORMALIZED_TABLE}` n
    LEFT JOIN `{ENRICHMENT_TABLE}` e ON n.submission_id = e.submission_id
    WHERE e.submission_id IS NULL
      AND n.narrative_text IS NOT NULL
      AND LENGTH(n.narrative_text) > 50
      {source_clause}
      {keyword_clause}
    ORDER BY n.submitted_at_utc ASC
    LIMIT {MAX_RECORDS}
    """
    rows = list(bq_client.query(query).result())
    log(f"Found {len(rows)} unenriched records (limit: {MAX_RECORDS})")
    return rows


def call_anthropic(narrative_text):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    payload = {
        "model": MODEL,
        "max_tokens": 600,
        "messages": [{
            "role": "user",
            "content": EXTRACTION_PROMPT + narrative_text[:2000]
        }]
    }
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        text = result["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())


def store_extraction(submission_id, extraction):
    try:
        bucket = gcs_client.bucket(EMBEDDINGS_BUCKET)
        blob = bucket.blob(f"extractions/{submission_id}.json")
        blob.upload_from_string(
            json.dumps({
                "submission_id": submission_id,
                "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
                "extraction": extraction
            }),
            content_type="application/json"
        )
        return f"gs://{EMBEDDINGS_BUCKET}/extractions/{submission_id}.json"
    except Exception as e:
        log(f"  GCS store warning for {submission_id}: {str(e)[:80]}")
        return None


def write_enrichment_row(submission_id, extraction, embedding_uri):
    """Write to hac_enrichment table."""
    row = {
        "submission_id":         submission_id,
        "enriched_at_utc":       datetime.now(timezone.utc).isoformat(),
        "llm_extracted_symbols": json.dumps(extraction.get("symbols", [])),
        "llm_extracted_emotion": extraction.get("dominant_emotion", ""),
        "embedding_uri":         embedding_uri,
        "geophysical_imagery":   extraction.get("geophysical_imagery", False),
        "water_imagery":         extraction.get("water_imagery", False),
        "destruction_imagery":   extraction.get("destruction_imagery", False),
        "urgency_level":         extraction.get("urgency_level", ""),
        "scale_impression":      extraction.get("scale_impression", ""),
        "hazard_type":           extraction.get("hazard_type", "none"),
    }
    errors = bq_client.insert_rows_json(ENRICHMENT_TABLE, [row])
    if errors:
        raise Exception(f"BigQuery insert errors: {errors}")


def update_normalized_domain(submission_id, extraction):
    """
    Write primary_domain and is_geophysical back to hac_normalized.
    primary_domain uses the NEXA-aligned 9-value taxonomy.
    """
    domain = extraction.get("primary_domain", "")
    if domain not in VALID_DOMAINS:
        domain = "other"

    is_geo = bool(extraction.get("geophysical_imagery", False))

    query = f"""
    UPDATE `{NORMALIZED_TABLE}`
    SET
      primary_domain = @domain,
      is_geophysical = @is_geo
    WHERE submission_id = @sid
      AND (primary_domain IS NULL
           OR primary_domain = 'precognitive'
           OR primary_domain NOT IN (
             'precognitive_anticipatory','informational_nonlocal',
             'survival_afterdeath','healing_biological',
             'synchronicity','psychophysical',
             'transcendent_mystical','other','non_anomalous'
           ))
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("domain", "STRING", domain),
        bigquery.ScalarQueryParameter("is_geo",  "BOOL",   is_geo),
        bigquery.ScalarQueryParameter("sid",     "STRING", submission_id),
    ])
    try:
        bq_client.query(query, job_config=cfg).result()
    except Exception as e:
        log(f"  domain update warning for {submission_id}: {str(e)[:80]}")


def main():
    log("=== hac-enrich batch job starting ===")
    log(f"Model: {MODEL} | Max: {MAX_RECORDS} | "
        f"Source: '{SOURCE_FILTER or 'all'}' | "
        f"Keywords: '{os.environ.get('GEOPHYSICAL_KEYWORDS','none')}'")

    records = fetch_unenriched_records()
    if not records:
        log("No unenriched records found — nothing to do")
        return

    enriched = 0
    failed   = 0

    for i, record in enumerate(records):
        submission_id = record.submission_id
        narrative     = record.narrative_text

        try:
            extraction    = call_anthropic(narrative)
            embedding_uri = store_extraction(submission_id, extraction)
            write_enrichment_row(submission_id, extraction, embedding_uri)
            update_normalized_domain(submission_id, extraction)
            enriched += 1
            if enriched % 50 == 0:
                log(f"Progress: {enriched} enriched, {failed} failed "
                    f"of {i+1} processed")
        except Exception as e:
            failed += 1
            log(f"Error on {submission_id}: {str(e)[:100]}")
            if failed > 10:
                log("Too many failures — stopping to prevent runaway costs")
                break

    log(f"=== Complete: {enriched} enriched, {failed} failed "
        f"of {len(records)} records ===")
    estimated_cost = enriched * 0.00112
    log(f"Estimated API cost this run: ${estimated_cost:.2f}")


if __name__ == "__main__":
    main()
