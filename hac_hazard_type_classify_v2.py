#!/usr/bin/env python3
"""
hac_hazard_type_classify_v2.py

Improved targeted re-enrichment to populate hazard_type field.
Key improvements over v1:
  - Batch BQ updates (write all at end, not one per record)
  - Retry with exponential backoff on API failures
  - Higher error threshold (50 consecutive, not 20 total)
  - Resume-safe (skips already-classified records)

Usage:
  python3 hac_hazard_type_classify_v2.py
  python3 hac_hazard_type_classify_v2.py --dry-run
  python3 hac_hazard_type_classify_v2.py --limit 500
  python3 hac_hazard_type_classify_v2.py --batch-size 1000
"""

import argparse
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT_ID    = "synexis-project-sentinel"
ENRICHMENT    = f"{PROJECT_ID}.hac_intake.hac_enrichment"
NORMALIZED    = f"{PROJECT_ID}.hac_intake.hac_normalized"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL         = "claude-haiku-4-5-20251001"

VALID_HAZARD_TYPES = {
    'earthquake', 'tsunami', 'flood', 'volcanic',
    'avalanche', 'landslide', 'multiple', 'none'
}

# Normalization map for common LLM variations
HAZARD_NORMALIZE = {
    'volcanic eruption': 'volcanic',
    'eruption':          'volcanic',
    'volcano':           'volcanic',
    'mudslide':          'landslide',
    'mudflow':           'landslide',
    'debris flow':       'landslide',
    'debris avalanche':  'landslide',
    'flash flood':       'flood',
    'flooding':          'flood',
    'river flood':       'flood',
    'coastal flood':     'flood',
    'snow avalanche':    'avalanche',
    'tidal wave':        'tsunami',
    'seismic':           'earthquake',
    'tremor':            'earthquake',
    'earth shaking':     'earthquake',
}

bq = bigquery.Client(project=PROJECT_ID)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


HAZARD_PROMPT = """Classify this dream/vision report for a geophysical hazard research database.

Respond with ONLY valid JSON (no markdown, no backticks):
{{"hazard_type": "<value>", "confidence": "high/medium/low", "reasoning": "<one sentence max 80 chars>"}}

hazard_type must be exactly one of:
  "earthquake"  - ground shaking, earth splitting, seismic collapse
  "tsunami"     - massive ocean waves, walls of water, coastal inundation
  "flood"       - rising water, rivers overflowing, inland flooding
  "volcanic"    - eruption, lava, ash clouds, volcanic explosions
  "avalanche"   - snow/ice sliding down mountain, buried in snow
  "landslide"   - earth/mud/rock sliding, mudslide, hillside collapse
  "multiple"    - two or more distinct hazard types clearly present
  "none"        - geophysical-adjacent but no specific hazard matches

Choose the MOST SPECIFIC single type. Use "multiple" only when two distinct types are clearly present.

Report:
{narrative}"""


def call_anthropic_with_retry(narrative, symbols, max_retries=3):
    """Call Anthropic API with exponential backoff retry."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    # Build context with symbols if available
    context = narrative[:1500]
    if symbols and symbols not in ('["nan"]', '[]', ''):
        context = f"Extracted imagery: {symbols[:200]}\n\nDream narrative: {narrative[:1200]}"

    prompt = HAZARD_PROMPT.format(narrative=context)

    payload = {
        "model": MODEL,
        "max_tokens": 120,
        "messages": [{"role": "user", "content": prompt}]
    }

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                ANTHROPIC_URL,
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

                # Robust JSON extraction - find first { ... } block
                import re
                match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if match:
                    text = match.group(0)

                return json.loads(text)

        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s
                log(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code >= 500:  # Server error
                wait = (2 ** attempt) * 2
                log(f"    Server error {e.code}, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
        except (json.JSONDecodeError, KeyError) as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise ValueError(f"JSON parse failed after {max_retries} attempts: {e}")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise

    raise ValueError(f"Failed after {max_retries} attempts")


def fetch_records(limit=None):
    """Fetch geophysical records with null hazard_type."""
    limit_clause = f"LIMIT {limit}" if limit else ""
    query = f"""
    SELECT n.submission_id, n.narrative_text, n.source_type,
           e.llm_extracted_symbols
    FROM `{NORMALIZED}` n
    JOIN `{ENRICHMENT}` e USING (submission_id)
    WHERE n.is_geophysical = TRUE
      AND (n.is_duplicate IS NULL OR n.is_duplicate = FALSE)
      AND n.normalized_status NOT IN ('date_unreliable')
      AND e.hazard_type IS NULL
      AND n.narrative_text IS NOT NULL
      AND LENGTH(n.narrative_text) > 50
    ORDER BY n.submitted_at_utc ASC
    {limit_clause}
    """
    rows = list(bq.query(query).result())
    log(f"Found {len(rows)} records needing hazard_type classification")
    return rows


def batch_update_bq(classified, dry_run=False):
    """
    Write all classifications to BQ in one efficient batch operation.
    Uses a temp table + MERGE for efficiency.
    """
    if not classified:
        log("No classifications to write")
        return 0

    if dry_run:
        log(f"DRY RUN — would write {len(classified)} classifications")
        return len(classified)

    # Build UPDATE statements in batches using CASE WHEN
    # BQ doesn't support multi-row UPDATE efficiently, so we use
    # a temp table approach
    log(f"Writing {len(classified)} classifications to BQ...")

    # Write in chunks of 500 using individual updates batched together
    # via a VALUES-based subquery
    chunk_size = 500
    total_written = 0

    for i in range(0, len(classified), chunk_size):
        chunk = classified[i:i+chunk_size]

        # Build a VALUES list for the MERGE
        values = ", ".join(
            f"('{sid}', '{ht}')"
            for sid, ht in chunk
        )

        query = f"""
        UPDATE `{ENRICHMENT}` e
        SET e.hazard_type = updates.hazard_type
        FROM (
            SELECT submission_id, hazard_type
            FROM UNNEST([
                STRUCT('placeholder' AS submission_id, 'none' AS hazard_type)
            ]) AS dummy
            WHERE FALSE
            UNION ALL
            SELECT * FROM (VALUES {values}) AS t(submission_id, hazard_type)
        ) AS updates
        WHERE e.submission_id = updates.submission_id
          AND e.hazard_type IS NULL
        """

        try:
            job = bq.query(query)
            job.result()
            total_written += len(chunk)
            log(f"  Written chunk {i//chunk_size + 1}: {total_written}/{len(classified)}")
        except Exception as ex:
            log(f"  BQ write error on chunk {i//chunk_size + 1}: {str(ex)[:100]}")
            # Fall back to individual updates for this chunk
            for sid, ht in chunk:
                try:
                    bq.query(f"""
                        UPDATE `{ENRICHMENT}`
                        SET hazard_type = '{ht}'
                        WHERE submission_id = '{sid}'
                          AND hazard_type IS NULL
                    """).result()
                    total_written += 1
                except Exception as e2:
                    log(f"    Individual update failed for {sid[:8]}: {e2}")

    log(f"Total written: {total_written} classifications")
    return total_written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run',    action='store_true')
    ap.add_argument('--limit',      type=int, default=None)
    ap.add_argument('--batch-size', type=int, default=1000,
                    help='Records per BQ write batch (default: 1000)')
    args = ap.parse_args()

    log("=== HAC Hazard Type Classification v2 ===")
    log(f"Dry run: {args.dry_run} | Limit: {args.limit or 'all'}")

    records = fetch_records(args.limit)
    if not records:
        log("No records to classify — already complete!")
        return

    est_cost = len(records) * 0.00015
    log(f"Estimated API cost: ${est_cost:.2f} for {len(records)} records")

    # Classification loop
    classified  = []   # (submission_id, hazard_type) pairs
    stats       = {h: 0 for h in VALID_HAZARD_TYPES}
    stats['errors'] = 0
    consecutive_errors = 0

    for i, row in enumerate(records):
        try:
            result = call_anthropic_with_retry(
                row.narrative_text,
                row.llm_extracted_symbols or ''
            )

            hazard_type = result.get('hazard_type', 'none').lower().strip()
            hazard_type = HAZARD_NORMALIZE.get(hazard_type, hazard_type)
            if hazard_type not in VALID_HAZARD_TYPES:
                hazard_type = 'none'

            confidence = result.get('confidence', '')
            reasoning  = result.get('reasoning', '')

            classified.append((row.submission_id, hazard_type))
            stats[hazard_type] = stats.get(hazard_type, 0) + 1
            consecutive_errors = 0  # Reset on success

            if i % 100 == 0 or i < 5:
                log(f"  [{i+1}/{len(records)}] {hazard_type} ({confidence}) — {reasoning[:70]}")

            # Write intermediate batch every batch_size records
            if len(classified) >= args.batch_size and not args.dry_run:
                batch_update_bq(classified, dry_run=False)
                classified = []

        except Exception as e:
            stats['errors'] += 1
            consecutive_errors += 1
            log(f"  Error [{i+1}] on {row.submission_id[:8]}: {str(e)[:100]}")

            if consecutive_errors >= 50:
                log(f"50 consecutive errors — stopping to prevent runaway")
                break

            # Brief pause on errors
            time.sleep(1)

    # Write remaining classified records
    if classified:
        batch_update_bq(classified, dry_run=args.dry_run)

    # Summary
    log(f"\n=== Classification complete ===")
    log(f"Results: {dict((k, v) for k, v in stats.items() if v > 0)}")

    if not args.dry_run:
        # Final distribution check
        result = bq.query(f"""
        SELECT e.hazard_type, COUNT(*) AS cnt
        FROM `{ENRICHMENT}` e
        JOIN `{NORMALIZED}` n USING (submission_id)
        WHERE n.is_geophysical = TRUE
          AND e.hazard_type IS NOT NULL
        GROUP BY e.hazard_type
        ORDER BY cnt DESC
        """).result()
        log("\nFinal hazard_type distribution:")
        for r in result:
            log(f"  {r.hazard_type}: {r.cnt}")

        # How many still unclassified
        remaining = list(bq.query(f"""
        SELECT COUNT(*) AS cnt
        FROM `{ENRICHMENT}` e
        JOIN `{NORMALIZED}` n USING (submission_id)
        WHERE n.is_geophysical = TRUE
          AND e.hazard_type IS NULL
        """).result())[0].cnt
        log(f"\nStill unclassified: {remaining}")


if __name__ == "__main__":
    main()
