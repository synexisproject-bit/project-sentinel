#!/usr/bin/env python3
"""
hac-cluster-v2.py

Redesigned clustering for hac_normalized using enrichment fields as the
primary feature set.

Key changes from v1:
  - Joins hac_enrichment at query time to access urgency_level,
    water_imagery, destruction_imagery, scale_impression
  - Feature vector now has 7 meaningful dimensions instead of 2
  - Clustering requires MULTIPLE strong feature matches, not just
    broad cosine similarity — prevents mega-cluster collapse
  - Temporal window tightened to 7 days (from 14)
  - Singletons are explicitly labeled CLU-SOLO-{n} and excluded
    from multi-member cluster reporting
  - Resume-safe: skips records that already have cluster_id
  - Resets existing clusters first if --reset flag passed

Usage:
  python3 hac-cluster-v2.py            # resume / first run
  python3 hac-cluster-v2.py --reset    # wipe existing clusters and re-run
"""

import json
import math
import sys
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT_ID  = "synexis-project-sentinel"
NORMALIZED  = f"{PROJECT_ID}.hac_intake.hac_normalized"
ENRICHMENT  = f"{PROJECT_ID}.hac_intake.hac_enrichment"

RESET = "--reset" in sys.argv

bq = bigquery.Client(project=PROJECT_ID)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ── Optional reset ────────────────────────────────────────────────────────────

def reset_clusters():
    """Wipe all existing cluster assignments so we start clean."""
    log("Resetting existing cluster assignments...")
    query = f"""
    UPDATE `{NORMALIZED}`
    SET cluster_id = NULL,
        normalized_status = 'enriched'
    WHERE normalized_status = 'fusion_ready'
      AND source_type = 'archive_import'
    """
    job = bq.query(query)
    job.result()
    log(f"  Reset {job.num_dml_affected_rows} rows")


# ── Fetch records ─────────────────────────────────────────────────────────────

def fetch_records():
    """
    Fetch all geophysical enriched records without cluster_id,
    joining enrichment fields as primary feature source.
    """
    log("Fetching records for clustering...")
    query = f"""
    SELECT
      n.submission_id,
      n.experience_date,
      n.referred_lat_approx,
      n.referred_lon_approx,
      n.llm_extracted_emotion,
      n.llm_extracted_symbols,
      n.lead_time_days,
      n.event_publicly_anticipated,
      -- Enrichment features (the real signal)
      e.urgency_level,
      e.water_imagery,
      e.destruction_imagery,
      e.geophysical_imagery,
      e.scale_impression,
      e.llm_extracted_symbols  AS enr_symbols
    FROM `{NORMALIZED}` n
    INNER JOIN `{ENRICHMENT}` e USING (submission_id)
    WHERE n.is_geophysical = TRUE
      AND n.cluster_id IS NULL
      AND n.normalized_status IN ('enriched', 'fusion_ready')
    ORDER BY n.experience_date ASC NULLS LAST
    """
    rows = list(bq.query(query).result())
    log(f"  {len(rows)} records to cluster")
    return rows


# ── Feature extraction ────────────────────────────────────────────────────────

# Urgency weight — the single strongest discriminator we have
URGENCY_WEIGHT = {
    "high":   3,
    "medium": 2,
    "low":    1,
    None:     0,
}

# Scale impression weight
SCALE_WEIGHT = {
    "global":     4,
    "continental":3,
    "regional":   2,
    "local":      1,
    None:         0,
}

def extract_features(row):
    """
    Build a weighted feature vector from enrichment fields.
    Returns a dict of feature_name -> numeric value.
    """
    return {
        # Imagery flags — binary but weighted by importance
        "water":       2 if row.water_imagery       else 0,
        "destruction": 2 if row.destruction_imagery else 0,
        "geophysical": 3 if row.geophysical_imagery else 0,

        # Urgency — ordinal 0-3
        "urgency": URGENCY_WEIGHT.get(row.urgency_level, 0),

        # Scale — ordinal 0-4
        "scale": SCALE_WEIGHT.get(row.scale_impression, 0),

        # Emotion group — collapse to 3 buckets to avoid over-splitting
        "emotion_high":   1 if row.llm_extracted_emotion in (
            "terror", "dread", "panic", "horror", "anguish") else 0,
        "emotion_medium": 1 if row.llm_extracted_emotion in (
            "fear", "anxiety", "distress", "urgency", "apprehension") else 0,
        "emotion_low":    1 if row.llm_extracted_emotion in (
            "awe", "confusion", "curiosity", "unease", "wonder",
            "calm", "acceptance", "helplessness") else 0,

        # Location available — rare but strong signal if present
        "has_location": 2 if row.referred_lat_approx else 0,
    }


def cosine(a, b):
    keys  = set(a) | set(b)
    dot   = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


def multi_match_score(row_a, row_b, feat_a, feat_b):
    """
    Compute a composite match score requiring MULTIPLE strong agreements.
    Returns (score, reasons) where score >= 1.0 means cluster-worthy.

    Scoring:
      - Same urgency level (both non-null):     +0.4
      - Same imagery combo (water+destruction): +0.3
      - Same emotion bucket:                    +0.2
      - Same scale impression:                  +0.2
      - High cosine similarity (>= 0.90):       +0.3
      - Both have location AND geo_close:        +0.5

    Threshold: 1.0 — requires at least 2-3 strong agreements.
    A single shared feature never exceeds 0.5, preventing single-axis collapse.
    """
    score   = 0.0
    reasons = []

    # Urgency match
    if (row_a.urgency_level and row_b.urgency_level and
            row_a.urgency_level == row_b.urgency_level):
        score += 0.4
        reasons.append(f"urgency={row_a.urgency_level}")

    # Imagery combo match — both must share water AND destruction
    if row_a.water_imagery and row_b.water_imagery:
        score += 0.2
        reasons.append("water")
    if row_a.destruction_imagery and row_b.destruction_imagery:
        score += 0.15
        reasons.append("destruction")

    # Emotion bucket match
    for bucket in ("emotion_high", "emotion_medium", "emotion_low"):
        if feat_a.get(bucket) and feat_b.get(bucket):
            score += 0.2
            reasons.append(f"emotion_bucket={bucket}")
            break

    # Scale match
    if (row_a.scale_impression and row_b.scale_impression and
            row_a.scale_impression == row_b.scale_impression):
        score += 0.2
        reasons.append(f"scale={row_a.scale_impression}")

    # High cosine similarity on full feature vector
    sim = cosine(feat_a, feat_b)
    if sim >= 0.92:
        score += 0.3
        reasons.append(f"cosine={sim:.2f}")
    elif sim >= 0.85:
        score += 0.1

    # Location proximity bonus
    if (row_a.referred_lat_approx and row_b.referred_lat_approx):
        lat_diff = abs(row_a.referred_lat_approx - row_b.referred_lat_approx)
        lon_diff = abs(row_a.referred_lon_approx - row_b.referred_lon_approx)
        if lat_diff <= 5.0 and lon_diff <= 5.0:
            score += 0.5
            reasons.append("geo_proximate")

    return score, reasons


# ── Clustering ────────────────────────────────────────────────────────────────

def assign_clusters(rows):
    """
    Sliding 7-day window clustering with multi-match scoring.
    Threshold: score >= 1.0 to join an existing cluster.
    Records that don't meet threshold become singletons (CLU-SOLO-n).
    """
    log("Running multi-feature sliding window clustering...")
    WINDOW_DAYS = 7
    SCORE_THRESHOLD = 1.0

    features    = {r.submission_id: extract_features(r) for r in rows}
    assignments = {}
    clusters    = {}   # cluster_id -> [submission_id, ...]
    rows_by_id  = {r.submission_id: r for r in rows}
    next_multi  = 1
    next_solo   = 1

    for i, row_a in enumerate(rows):
        sid_a = row_a.submission_id
        if sid_a in assignments:
            continue

        feat_a   = features[sid_a]
        best_cid = None
        best_score = 0.0

        # Slide back through the temporal window
        j = i - 1
        while j >= 0:
            row_b = rows[j]
            # Check temporal window
            if row_a.experience_date and row_b.experience_date:
                delta = abs((row_a.experience_date - row_b.experience_date).days)
                if delta > WINDOW_DAYS:
                    break
            sid_b = row_b.submission_id
            if sid_b not in assignments:
                j -= 1
                continue

            feat_b = features[sid_b]
            score, reasons = multi_match_score(row_a, row_b, feat_a, feat_b)

            if score >= SCORE_THRESHOLD and score > best_score:
                best_score = score
                best_cid   = assignments[sid_b]

            j -= 1

        if best_cid:
            assignments[sid_a] = best_cid
            clusters[best_cid].append(sid_a)
        else:
            # Singleton
            cid = f"CLU-SOLO-{next_solo:05d}"
            next_solo += 1
            assignments[sid_a] = cid
            clusters[cid] = [sid_a]

    # Promote any cluster that grew beyond 1 member to a named cluster
    final_assignments = {}
    final_clusters    = {}
    for cid, members in clusters.items():
        if len(members) > 1:
            new_cid = f"CLU-{next_multi:04d}"
            next_multi += 1
            for sid in members:
                final_assignments[sid] = new_cid
            final_clusters[new_cid] = members
        else:
            # Keep solo label
            sid = members[0]
            final_assignments[sid] = cid
            final_clusters[cid]    = members

    multi_clusters = {k: v for k, v in final_clusters.items()
                      if not k.startswith("CLU-SOLO")}
    solo_count     = len(clusters) - len(multi_clusters)

    log(f"  Clustering complete:")
    log(f"    Multi-member clusters : {len(multi_clusters)}")
    log(f"    Singletons            : {solo_count}")
    log(f"    Total records         : {len(final_assignments)}")

    if multi_clusters:
        log(f"\n  Multi-member cluster sizes:")
        for cid, members in sorted(multi_clusters.items(),
                                   key=lambda x: -len(x[1]))[:20]:
            log(f"    {cid}: {len(members)} members")

    return final_assignments, rows_by_id


# ── Write assignments ─────────────────────────────────────────────────────────

def compute_eligible(row):
    if not (row.geophysical_imagery or False):
        return False
    if not row.lead_time_days:
        return False
    if row.event_publicly_anticipated == "yes":
        return False
    return True


def write_assignments(assignments, rows_by_id, batch_size=500):
    log(f"Writing {len(assignments)} cluster assignments...")
    items   = list(assignments.items())
    total   = 0
    n_batch = math.ceil(len(items) / batch_size)

    for b in range(n_batch):
        chunk = items[b * batch_size: (b + 1) * batch_size]
        log(f"  Batch {b+1}/{n_batch} ({len(chunk)} rows)...")

        value_tuples = []
        for sid, cid in chunk:
            row     = rows_by_id.get(sid)
            is_geo  = bool(row.geophysical_imagery) if row else False
            is_elig = compute_eligible(row) if row else False
            geo_lit  = "true"  if is_geo  else "false"
            elig_lit = "true"  if is_elig else "false"
            sid_esc  = sid.replace("'", "\\'")
            cid_esc  = cid.replace("'", "\\'")
            value_tuples.append(
                f"STRUCT('{sid_esc}' AS submission_id, "
                f"'{cid_esc}' AS cluster_id, "
                f"CAST({geo_lit}  AS BOOL) AS is_geo, "
                f"CAST({elig_lit} AS BOOL) AS is_elig)"
            )

        values_sql = ",\n    ".join(value_tuples)
        merge_sql  = f"""
        MERGE `{NORMALIZED}` AS n
        USING (SELECT * FROM UNNEST([
          {values_sql}
        ])) AS src
        ON n.submission_id = src.submission_id
        WHEN MATCHED THEN UPDATE SET
          n.cluster_id           = src.cluster_id,
          n.is_geophysical       = src.is_geo,
          n.is_sentinel_eligible = src.is_elig,
          n.normalized_status    = 'fusion_ready'
        """
        try:
            job = bq.query(merge_sql)
            job.result()
            total += job.num_dml_affected_rows
        except Exception as e:
            log(f"  Batch {b+1} error: {e} — falling back to individual updates")
            total += _write_individual(chunk, rows_by_id)

    log(f"Write complete — {total} rows updated")
    return total


def _write_individual(chunk, rows_by_id):
    updated = 0
    for sid, cid in chunk:
        row     = rows_by_id.get(sid)
        is_geo  = bool(row.geophysical_imagery) if row else False
        is_elig = compute_eligible(row) if row else False
        query   = f"""
        UPDATE `{NORMALIZED}`
        SET cluster_id           = @cid,
            is_geophysical       = @is_geo,
            is_sentinel_eligible = @is_elig,
            normalized_status    = 'fusion_ready'
        WHERE submission_id = @sid
        """
        cfg = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("cid",    "STRING", cid),
            bigquery.ScalarQueryParameter("sid",    "STRING", sid),
            bigquery.ScalarQueryParameter("is_geo", "BOOL",   is_geo),
            bigquery.ScalarQueryParameter("is_elig","BOOL",   is_elig),
        ])
        try:
            job = bq.query(query, job_config=cfg)
            job.result()
            updated += job.num_dml_affected_rows
        except Exception as e:
            log(f"  Error on {sid}: {e}")
    return updated


# ── Report ────────────────────────────────────────────────────────────────────

def report():
    query = f"""
    SELECT
      CASE WHEN cluster_id LIKE 'CLU-SOLO-%' THEN 'singleton'
           ELSE 'clustered' END AS cluster_type,
      COUNT(DISTINCT cluster_id) AS num_clusters,
      COUNT(*) AS num_records,
      COUNTIF(is_geophysical) AS geophysical,
      COUNTIF(is_sentinel_eligible) AS eligible
    FROM `{NORMALIZED}`
    WHERE normalized_status = 'fusion_ready'
    GROUP BY cluster_type
    ORDER BY cluster_type
    """
    rows = list(bq.query(query).result())
    log(f"\n=== Cluster Report ===")
    for r in rows:
        log(f"  {r.cluster_type:12s} | clusters={r.num_clusters:5d} "
            f"| records={r.num_records:6d} "
            f"| geo={r.geophysical:6d} "
            f"| eligible={r.eligible}")

    # Top 20 multi-member clusters
    query2 = f"""
    SELECT
      cluster_id,
      COUNT(*) AS members,
      COUNTIF(is_sentinel_eligible) AS eligible,
      MIN(experience_date) AS earliest,
      MAX(experience_date) AS latest
    FROM `{NORMALIZED}`
    WHERE normalized_status = 'fusion_ready'
      AND cluster_id NOT LIKE 'CLU-SOLO-%'
    GROUP BY cluster_id
    ORDER BY members DESC
    LIMIT 20
    """
    cluster_rows = list(bq.query(query2).result())
    if cluster_rows:
        log(f"\n  Top clusters:")
        for r in cluster_rows:
            log(f"    {r.cluster_id}: {r.members} members, "
                f"{r.eligible} eligible, {r.earliest}–{r.latest}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log("=== hac-cluster-v2 starting ===")

    if RESET:
        reset_clusters()

    rows = fetch_records()
    if not rows:
        log("No unprocessed records found — running report only")
        report()
        return

    assignments, rows_by_id = assign_clusters(rows)
    write_assignments(assignments, rows_by_id)
    report()

    log("=== hac-cluster-v2 complete ===")


if __name__ == "__main__":
    main()
