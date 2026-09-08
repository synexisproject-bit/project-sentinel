# Project Sentinel: Infrastructure Status and Incident Record

Living document. Update at each milestone open and close.

**Last updated:** 2026-09-07
**Last audit:** 2026-09-06T21:27:42Z (`audits/audit_script_v2_20260906T212742Z.log`)
**Audit script version:** `sentinel_audit.sh`, revision 2026-09-06 (commit `b6671d8`)

---

## 1. Current state

### Projects

| Project | Purpose |
|---|---|
| `synexis-project-sentinel` | Core research initiative, HAC pipeline, analysis datasets |
| `synexis-sfo` | Synexis Field Observatory, coherence stream ingest |

### Cost

Combined month-to-date spend as of 2026-09-06: **$3.65** (Sentinel $2.99, SFO $0.66).

The multi-region cost anomaly that prompted the July 2026 migration is resolved. Spend is now dominated by storage at negligible volume.

New continuous charges as of 2026-09-06: `geonet-pull` VM (e2-micro, us-central1-a), its 30 GB standard persistent disk, and reserved static IP `34.31.159.25`. See section 4.

### Region posture

Target location for all resources is `us-central1`.

| Resource class | Status |
|---|---|
| BigQuery datasets | All in `us-central1` (12 Sentinel, 4 SFO) |
| GCS buckets, primary | All in `us-central1` |
| GCS buckets, service-created | 3 outside: two Cloud Functions staging buckets in `us-east1`, `synexis-project-sentinel_cloudbuild` in US multi-region. SFO: `synexis-sfo_cloudbuild` in US multi-region (30-day lifecycle rule applied 2026-09-05) |
| Cloud Run services | 27 of 31 outside `us-central1`, in `us-east1` and `us-east4`. All idle, all associated schedulers PAUSED |
| Artifact Registry | ~11.6 GB across 12 repositories, mostly `us-east1` and `us-east4`, plus one `gcr.io` repo in US multi-region |

Cost impact of the off-region remainder is negligible at current volume. It is an accuracy and hygiene matter, not a cost matter.

---

## 2. The July 2026 migration: actual scope

**What moved.** Data storage only: 7 GCS buckets and 12 BigQuery datasets, from US multi-region to `us-central1`. Resources were renamed with a `_central1` or `-central1` suffix as part of the move.

**What did not move.** Cloud Run services, Cloud Run jobs in `us-east1`, Artifact Registry repositories, and service-created staging buckets.

**What was not updated.** Application code referencing the renamed storage resources. This is the gap that produced the incident in section 3.

**What the migration achieved.** The cost anomaly it targeted is resolved. That objective was met.

Any statement that the infrastructure was "fully migrated" is accurate for data storage and inaccurate for compute, container images, and application references.

---

## 3. Incident: HAC archive import pipeline failure

**Detected:** 2026-09-06, by the corrected infrastructure audit script
**Duration:** from the July 2026 migration until detection, approximately two months
**Status:** contained, not remediated

### What happened

`hac-archive-importer/importer.py:22` and `hac-orchestrator/main.py:7` hardcode the bucket name `synexis-project-sentinel-hac-imports`. The July migration renamed that bucket to `synexis-project-sentinel-hac-imports-central1`. Neither file was updated.

Every execution failed with:

```
google.api_core.exceptions.NotFound: 404 GET
https://storage.googleapis.com/storage/v1/b/synexis-project-sentinel-hac-imports/o
The specified bucket does not exist.
```

Two Cloud Scheduler jobs in `us-central1` fired into the failing jobs throughout:

- `hac-import-schedule`, every two hours (`0 */2 * * *`)
- `hac-cluster-nightly`, daily at 03:00 UTC (`0 3 * * *`)

Fifty consecutive executions were sampled with no successful run. The failure predates the sample.

### Consequence

**No HAC archive data was ingested during the affected window.** Any HAC-derived figure computed since July 2026 rests on data static as of the migration date. This should be verified before any HAC-derived number is cited or published.

### Why it went undetected

The audit script's Cloud Scheduler check queried `--location=us-east1` only, a pre-migration value. Both schedulers live in `us-central1` and were therefore invisible to every audit run between the migration and 2026-09-06. The script also had no Cloud Run job execution health check, so failing jobs raised nothing.

### Containment

Both schedulers paused 2026-09-06. No further failing executions.

### Remediation, outstanding

1. Correct the bucket name in both files, redeploy both jobs, verify a successful execution, then unpause the schedulers.
2. Determine the exact start date of the failure window and quantify the ingest gap.
3. Complete the post-migration reference audit in section 5.

---

## 4. Expected resources

Resources the audit will flag that are intentional. Findings on these are known, not new.

| Resource | Project | Purpose | Added |
|---|---|---|---|
| `geonet-pull` (e2-micro, us-central1-a) | Sentinel | Fixed-IP host for GEONET RINEX retrieval; GSI binds access to a single registered IPv4 address | 2026-09-06 |
| `geonet-pull-ip` (34.31.159.25, us-central1) | Sentinel | Reserved static address registered with GSI. Do not release while the GEONET authorization is active | 2026-09-06 |
| 30 GB standard persistent disk on `geonet-pull` | Sentinel | Boot and staging disk | 2026-09-06 |

Note: stopping `geonet-pull` does not reduce cost reliably, since a reserved static IP attached to a stopped instance bills at a higher rate than one attached to a running instance.

---

## 5. Post-migration reference audit: open workstream

Not started. Scope defined 2026-09-06.

Pre-migration resource names remain hardcoded across several files. Each reference requires individual verification, because some resources changed dataset as well as region. A mechanical suffix append would produce new wrong paths.

### Bucket references, confirmed defects

| File | Line | Reference |
|---|---|---|
| `hac-archive-importer/importer.py` | 22 | `synexis-project-sentinel-hac-imports` |
| `hac-orchestrator/main.py` | 7 | `synexis-project-sentinel-hac-imports` |

### Dataset references, requiring triage

| File | Note |
|---|---|
| `sentinel-geocoding-pipeline/deploy/diagnostic_queries.sql` | `sentinel_geocoding`, `sentinel_analysis` |
| `sentinel-geocoding-pipeline/deploy/deploy.sh` | `sentinel_groundtruth`, `sentinel_geocoding`, `sentinel_analysis` |
| `sentinel-geocoding-pipeline/geocoding_job/main.py` | `sentinel_geocoding` |
| `sentinel-geocoding-pipeline/spatial_analysis_job/spatial_analysis.py` | `sentinel_geocoding`, `sentinel_analysis` |
| `hac_superposed_epoch.py` | References `sentinel_features.hac_features_daily`; the table is actually in `sentinel_analysis_central1`. Dataset changed, not just region |
| `epoch_test.sql` | `sentinel_groundtruth` |
| `fusion_status.sh` | `sentinel_raw`, `sentinel_mart`. Fusion stack is fully paused; triage for dead code before editing |

### Related

`h3-tec-backfill` (us-central1) also reports a failed latest execution, same era. Cause not yet diagnosed. Relevant to the Sentinel rebuild, since H3 is the closest prior TEC work.

---

## 6. Repository status

| Repository | Remote | Note |
|---|---|---|
| `project-sentinel` | `github.com/synexisproject-bit/project-sentinel` | Canonical working clone |
| `sentinel_repo` | same remote | Stale local clone, last commit 2026-03-03. Candidate for removal |
| `project-sentinel-backup-20260705` | same remote | Pre-migration snapshot. Retain until the rebuild is underway |
| `hac-archive-importer` | none | Versioned locally 2026-09-06 (`18e6c1e`). Production source. Needs a remote; check for credentials before pushing |
| `hac-orchestrator` | none | Versioned locally 2026-09-06 (`5bce743`). Production source. Needs a remote; check for credentials before pushing |

Both HAC repositories existed only as unversioned files in an ephemeral Cloud Shell home directory until 2026-09-06.

---

## 7. Known audit script limitations

Current revision `2026-09-06` (commit `b6671d8`):

- Artifact Registry location parsing is defective. `--format="value(name)"` returns the short repository name rather than the full resource path, so every repository is reported as off-region with an unparsed size. False positives, not false negatives. Fix pending: iterate over locations explicitly rather than parsing the name.
- Scheduler scan covers `us-central1`, `us-east1`, `us-east4` only. A scheduler created elsewhere would not be seen.
- Month-to-date cost requires `BILLING_EXPORT_TABLE`. BigQuery billing export is not yet configured, so cost is read from the console.

---

## 8. Recommended next actions

1. Enable BigQuery billing export. Free, and it lets the audit script report cost directly.
2. Create a budget with alert thresholds on both projects.
3. Fix the two hardcoded bucket names, redeploy, verify, unpause.
4. Fix the Artifact Registry check in the audit script.
5. Work the section 5 reference audit.
6. Decide the fate of the 27 off-region Cloud Run services and ~11.6 GB of Artifact Registry. Low cost, so this is deliberate cleanup rather than urgent.
