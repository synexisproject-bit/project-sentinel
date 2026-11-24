# Project Sentinel registration ledger

Append-only. One row per locking commit. Rows are added, never edited.

A **locking commit** is one that fixes a rule, specification, protocol, analysis
plan or data snapshot in the repository **before** the data or code it governs
exists. The purpose of this ledger is to let an outside reader verify, in one
pass and without trusting any narrative, that each decision preceded the work it
constrains.

This ledger records evidence only. Gate status, open items and what comes next
belong in the project record, Block 1 Part D, and are deliberately kept out of
here so the two cannot drift apart.

## How to verify any row

```bash
git show <commit>:<file> | sha256sum     # must equal the SHA-256 column
git log -1 --format=%cI <commit>         # must equal the UTC column
```

If a row's hash does not reproduce, the row is wrong or the file was altered.
Either way the discrepancy is the finding, and it is recorded as a new row
rather than corrected in place.

## Evidence layers

Each locked artifact is anchored in up to three independent places, per the
standing Synexis process:

1. **Git commit plus this ledger row.** Local, and alterable only by rewriting
   published history.
2. **A third-party timestamp.** The GitHub push record, an OSF upload, or a
   formal OSF registration with a DOI. Not under the author's control.
3. **Optional encrypted email to an independent custodian.** Used where an
   artifact carries unusual weight.

## Scope

This ledger begins at the Sentinel rebuild, which opened 2026-09-05. Locking
commits from Phase 2 predate the adoption of this process on 2026-11-11 and are
recorded in `AMENDMENTS.md` and in OSF registration `8hvf6`, which is frozen
under CC0 and cannot be amended. They are not backfilled here, because a ledger
that silently absorbs a prior record under a newer convention is less
trustworthy than one that states where it starts.

Rows 1 through 8 were backfilled from the git history on 2026-11-13.
Backfilling is marked in the Notes column. Every backfilled hash was computed
from the committed object, not from a working copy, and every timestamp is the
commit timestamp as recorded by git. Rows 9 onward were written as the commits
were made.

---

## Appending a row

The ledger table is the **last** thing in this file, deliberately, so that
appending to end of file always lands inside the table. Keep it that way. Any
section added later goes above the table, never below it.

```bash
cd ~/project-sentinel

# the three values a row needs
git log -1 --format='%cI  %h' <commit> | sed 's/+00:00/Z/'   # UTC and commit
git show <commit>:<file> | sha256sum                          # SHA-256

# append as a single line of eight pipe-separated fields
printf '| %s | %s | `%s` | `%s` | `%s` | %s | %s | %s |\n' \
  "<n>" "<utc>" "<commit>" "<file>" "<sha256>" \
  "<what it locks>" "<external anchor>" "<notes>" \
  >> docs/registration_ledger.md

# confirm it landed as exactly one line, inside the table
git diff --stat docs/registration_ledger.md     # expect 1 insertion
tail -2 docs/registration_ledger.md
```

Do not renumber, reorder, or revise any existing row. A row that turns out to be
wrong is superseded by a new row that says so and says why.

---

## Ledger

| # | UTC | Commit | File | SHA-256 | What it locks | External anchor | Notes |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-05T06:10:04Z | `1467bba` | `audits/audit_rebuild_block1_open_20260905T060720Z.log` | `d81eaf5c8111d1aeff9ba94c617de76ec74bd80bde7c2165853849dc825afd95` | Milestone-open infrastructure and cost baseline for the rebuild. Establishes the state of the GCP estate before any rebuild work, so later cost and configuration claims have a reference point. | GitHub push record | Backfilled 2026-11-13. Contains no document; the Block 1 record itself was first committed at `d268fce`. |
| 2 | 2026-10-16T04:04:30Z | `dc6bf58` | `data/csep_japan/japan.forecast.nodes` | `94f94b19a0b1eaf1db125b0570005c4724b526b0aaf38e91d7482704fe50dcf2` | The evaluation region. The authoritative CSEP-Japan All Japan testing region, 20,062 cells at 0.1 degree, received from Dr. Hiroshi Tsuruoka (ERI, University of Tokyo) and adopted unmodified. Locked before any catalog filtering. | GitHub push record; email from the source institution dated 2026-10-14 | Backfilled 2026-11-13. Hash is identical to the file as received, so the adoption is verifiable against the sender's copy. |
| 3 | 2026-10-17T04:44:52Z | `08ab561` | `data/csep_japan_region_manifest.json` | `04cd691f4851d904baa153f51749b3fff89f7cf11e5bcb918ed1f21d8b1d8b51` | The region's provenance and coordinate convention. Records Dr. Tsuruoka's written confirmation (email 2026-10-16) that the file is the All Japan region and that coordinates are cell midpoints, with origins at midpoint minus 0.05 degrees. | GitHub push record; confirming email 2026-10-16 | Backfilled 2026-11-13. The convention shifts every cell assignment by half a cell, so it is locked rather than inferred. |
| 4 | 2026-10-17T04:45:17Z | `38f1770` | `audits/audit_milestone_20261017T042804Z.log` | `4680f11bcfd741cd793b2be3fbd012309ba5fec176544f03139668dd6fcaa445` | Milestone audit and cost record at the Block 1 midpoint. Same commit fixed two defects in `sentinel_audit.sh` (critical-table target, cost reporting). | GitHub push record | Backfilled 2026-11-13. Audit script at this commit: `a236ecf8850ac7cc9cab3d3a9563c8bd9eb588d4e1780f77aa08b7e0e2a8e5f2`. |
| 5 | 2026-10-19T21:57:41Z | `3b4f784` | `docs/BLOCK1_ADDENDUM_testing_class_and_threshold_2026-10-19.docx` | `5251152d5d4cec398e7e6113c9e6ec06c87fedf7ed20fe5e10780c83e0f46d12` | **The analysis-defining lock.** D6 magnitude threshold (4.0 to 9.0 in 0.1 bins), D7 testing class (CSEP-Japan 1-day), D12 evaluation window (2016-01-01 to 2023-12-31 UTC), the nine catalog filtering rules, the no-declustering decision, and sensitivity analysis S1 at M4.5. Locked before the catalog was downloaded. | GitHub push record; OSF registration DOI 10.17605/OSF.IO/H5MD2 | Backfilled 2026-11-13. **Frozen. Never edited.** One error corrected by separate note, row 8. |
| 6 | 2026-10-19T21:57:56Z | `0d5a9ea` | `data/jma_catalog/sha256_raw.txt` | `50535f950205e58d88368b76297af747658c86f036705d0ffd8d7cc3affde045` | The raw data snapshot. SHA-256 of all eight JMA Seismological Bulletin hypocenter archives, `h2016.zip` through `h2023.zip`, as downloaded. Fixes which bytes the study was built from. | GitHub push record | Backfilled 2026-11-13. Committed 15 seconds after the filtering rules, so the rules demonstrably precede the data. The archives themselves are gitignored; the hashes are the record. |
| 7 | 2026-11-10T04:55:02Z | `d268fce` | `docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx` | `69ca09ace5768599ee8111f2f1d9775a8afb868aa0ada7a9d8350e419660cbf9` | The Block 1 record: publication target, region selection rationale, license allocation, gate statuses, and the milestone checklist. Records the pre-registration DOI. | GitHub push record; OSF registration DOI 10.17605/OSF.IO/H5MD2, archived 2026-11-09 | Backfilled 2026-11-13. First commit of this document; a draft claim that it had been committed at `1467bba` was found false on verification and removed before committing. |
| 8 | 2026-11-10T04:55:35Z | `19fe41c` | `docs/ADDENDUM_CORRECTION_2026-11-09.md` | `c91a4913fc2f3b34135aac797f2c3ba467ff053fc7fd8ea8efd0db03466bf632` | Correction against the frozen addendum (row 5). The addendum's "82 percent of events carry the displacement scale" at M4.5 is the M5-bin share (117 of 142); the M4 bin is 41 percent (396 of 960); the M4.5 share was never computed. Also corrects the −0.020 offset attribution to the 293 MV 4.x paired events, against +0.038 across all 463. | GitHub push record; registration DOI 10.17605/OSF.IO/H5MD2 carries the precise wording | Backfilled 2026-11-13. The addendum was not edited. The correction is a separate dated artifact so both the error and its correction carry timestamps. |
| 9 | 2026-11-13T22:56:32Z | `afe5d84` | `build_jma_catalog.py` | `a1390e762d619d32c6000b06fd05f9788210d56061397421a4c9745ba7fcf680` | The catalog construction implementation. Applies the nine filtering rules of row 5 in the registered order, with per-rule attrition reporting and a 40-check self-test that verifies the region file hash against row 2. | GitHub push record | **Not a pre-registration lock, and must not be read as one.** The governing lock is row 5, committed 2026-10-19, 25 days before this script ran. This script was committed in the same session as its outputs (row 10) and therefore does not predate them. What it records is which implementation produced the catalog, so a reader can reproduce it. Same commit also records `infra/geonet-pull_instance_2026-11-13.yaml`, the GEONET puller VM configuration captured before the instance was stopped, checked for credentials before committing. |
| 10 | 2026-11-13T22:56:58Z | `f39c231` | `data/jma_catalog/jma_catalog_manifest.json` | `5be4ea6c78994b55e987542df48f15de5f6a5ae8ae7e0c21a27ba7080660d802` | The D8 target catalog and its attrition record. 4,442 events at M ≥ 4.0, 2016-2023, from 2,161,892 raw records, every one accounted for by a rule, with zero parse failures and zero event-id collisions. The manifest is the row's subject because it carries the SHA-256 of every input archive and every output file, so this one hash fixes the whole product. Catalog itself: `148a16a8f88454a8575d0e09b1d36f1076d5ab8bc0f184ae4fec315f48d3fcc1`. | GitHub push record | Rule 7 removed nothing, which is a property of the 2016-2023 bulletin rather than a defect: it contains no N or F determination flags and no location precision 8 among events reaching that rule. All three registered rule-watch items (W1 type J magnitude, W2 record type, W3 missing depth) measured zero, so no amendment is required on any of them. Zero target events carry location precision 7 or M, answering both quality questions raised during format verification. |
| 11 | 2026-11-13T23:13:30Z | `5ffd2e9` | `audits/audit_milestone_d8_close_20261113T230646Z.log` | `80c326a20de1561edeaf9fbce5b4c30937f44e84962169c846fd8cec018e08df` | Milestone close audit for D8. Infrastructure and cost state after the catalog build, paired with the milestone-open audit committed at `afe5d84` as `audits/audit_milestone_d8_open_20261113T220508Z.log`. Records geonet-pull as TERMINATED with its 30 GB disk and static IP 34.31.159.25 retained. | GitHub push record | Required by the standing workflow rule, which runs this audit at the start and end of every major milestone. Month-to-date cost figures are cumulative and therefore identical across the two runs; the effect of stopping the VM appears as the E2 Instance Core and RAM lines ceasing to grow, visible once billing export latency clears. |
| 12 | 2026-11-19T03:01:54Z | `e2e0cb8` | `sentinel_audit.sh` | `a03a664b889035fedb624f76f963cea978ad629f2aa03558de35b52b3ef5c130` | The audit tool that produces the milestone evidence in rows 1, 4 and 11. Four defects fixed: stopped VMs reported as idle cost risk, a HAVING clause dropping credited SKUs, Artifact Registry locations read from the repository name, and synexis-foremark absent from the project list. | GitHub push record | Findings before and after this commit are not directly comparable. The repaired SKU reporting showed the stopped geonet-pull VM cost about 0.69 USD per month net, not the 7.46 the broken table implied. Verification run committed in the same commit. |
| 13 | 2026-11-19T03:28:17Z | `e95dc7e` | `build_jma_catalog.py` | `bcf3b46fe61fa42b54cc5542ec88ee715fcb62ed20f6887e375ac3b2aa954b69` | Catalog construction implementation v1.1.0, adding the D9 sub-threshold working mode. Rules 1 through 8 unchanged and applied as registered; rule 9 relaxed only under an explicit flag. | GitHub push record | Not a pre-registration lock. The governing lock is row 5. Target-mode output verified byte-identical to the committed a1390e76 version on the same inputs. Four guards prevent a working build altering the registered catalog, including a byte-identity check that aborts on any change. |
| 14 | 2026-11-19T03:28:17Z | `e95dc7e` | `data/jma_catalog/jma_mc_working_manifest.json` | `93cd4e42af30bc49c55bd2bf0586869f7fd0a3cc4911870b1f01239997d1abb9` | The D9 sub-threshold working catalog, 798,205 events at M >= 1.0, built with rule 9 relaxed. A D9 input only, never evaluated, and does not supersede the registered target catalog. The manifest is the ledger subject because it carries the hash of every input and output. | GitHub push record | Catalog sha256 f48dbc7f83af685f392b45830c419982c14189f67947e7114eb95543ac05a9cd. The 114,732,381-byte CSV is not in git, being over GitHub's 100 MB limit; it is at gs://synexis-project-sentinel-exports-central1/d9/jma_mc_working_catalog.csv generation 1795058203453781, verified on upload by matching md5 e044d547b1e02e4abc550d24f29fe95c, and is reproducible from the committed builder per jma_mc_working_location.txt. Rules 1 through 8 removed identical counts in both builds, so only rule 9 differs. Zero events at location precision M and 31 at precision 7. |
| 15 | 2026-11-19T03:32:41Z | `b7ffa07` | `docs/BLOCK1_ADDENDUM1_mc_protocol_2026-11-14.docx` | `1c2a6cd408b45bfd9071c0e8dfeae0201be73ffc535c7b752e263d3af0bed1eb` | THE D9 METHOD LOCK. Subsets, estimators, confidence levels, sampling, windows, bootstrap counts, trial grid, and what each possible Mc result means for the D10 gate. Fixed before any Mc value was computed. | GitHub push record | Estimators from SeismoStats 1.0.1, pinned, nothing hand-implemented. The gate reads the highest of the three estimators rather than the primary, so no estimator choice can decide it. Computational budget measured at this study's sample sizes rather than extrapolated. |
| 16 | 2026-11-20T06:11:05Z | `f398329` | `estimate_mc_d9.py` | `a0a54d1e2a4b25cd215b3d53601b3581c8a7226eac3cd70115fd3811dae08c47` | The D9 analysis implementation. Applies the protocol locked at row 15 with all estimators from SeismoStats 1.0.1, pinned; nothing hand-implemented. | GitHub push record | Not a pre-registration lock. The governing lock is row 15, committed six days earlier. The script verifies the working catalog hash against the registered value and refuses to run on any other catalog. |
| 17 | 2026-11-20T06:11:05Z | `f398329` | `data/d9/d9_summary.json` | `93b0144efe390edfbccda44d757d4e5d809e9278fd5ba4bbfadb72a5767e8102` | The D9 results. Gate outcome on subset P: whole region 3.7, annual maximum 3.6, highest assessed spatial node 3.9, moving-window maximum 3.7. No scope reaches 4.0. D9 closes in the middle band of section 7: threshold defensible, margin thin, reported as a limitation, S1 given added weight. | GitHub push record | Benchmark b-value 0.880043 plus or minus 0.009397 above the subset P E1 Mc of 3.7. 71.1 percent of grid nodes could not be assessed, concentrated offshore. Subset R in 2016 returned gate 4.1, above the threshold; R is diagnostic and section 7 evaluates on P. Independent check: b and counts agree with the separately built target catalog to within 1.7 percent. |
| 18 | 2026-11-20T06:12:57Z | `c2c5245` | `docs/D9_FINDINGS_NOTE_2026-11-20.md` | `9d35abe997b371235016e0b048edf2c98b02b1454821d0f8bf3d6c8e7896c479` | Two post-hoc findings recorded as a dated note rather than a protocol revision: the aggregate frequency-magnitude distribution is curved so the whole-region Mc measures heterogeneity rather than completeness, and there is an isolated 20 percent deficit at exactly M4.0 coinciding with the velocity-to-displacement scale changeover. | GitHub push record | Both found after the method lock at b7ffa07. The protocol is not edited. The registered design is unchanged, including the M4.0 primary and S1 subordinate ordering, which is deliberately not reordered on the strength of these findings. Withdraws two interim apparent-b figures that were artifacts of a truncated extract. |
| 19 | 2026-11-23T06:25:04Z | `335e4de` | `docs/D9_FINDINGS_CORRECTION_2026-11-23.md` | `be6050ef638e49e8c71d81e6e945b8bcebb7e55cc11fe761d2ae74d0b1cc0f85` | Correction against the D9 findings note at row 18. The M4.0 deficit was attributed to the magnitude-scale changeover operating through rule 8; rule 8 contributes nothing and moves no events. The amplification is rule 4, the region filter, with rule 5 adding less. | GitHub push record | Of the 22.5 percent relative shortfall in subset P, 12.2 points are intrinsic to the raw bulletin and 10.3 points come from this study's registered filters. The scale changeover is confirmed at M4.0 and accounts for about 63 percent of the intrinsic part. Row 18 is not edited. Established by diagnose_m40_step.py, validated against two planted causes before use. |
| 20 | 2026-11-24T06:06:16Z | `eff0361` | `audits/audit_milestone_d9_close_20261124T054310Z.log` | `ba4af7a5b242f31a995b88d11d3dde03bf8ee4925b8470c0f5b9ffb999da5588` | Milestone infrastructure audit at D9 close, all three GCP projects, required by the standing start-and-end-of-milestone workflow rule. 33 findings, none bearing on the rebuild; 17 are a gcloud reporting limitation and the substantive 11 are all legacy pipeline. Month-to-date spend 19.73 USD net. | GitHub push record | The previous milestone audit was the D8 close on 2026-11-13, so D9 ran without one. Two incomplete attempts are committed beside this log with _INCOMPLETE suffixes rather than deleted; both hung at synexis-foremark on an invisible gcloud API-enablement prompt, since the script discards stderr. Completed with CLOUDSDK_CORE_DISABLE_PROMPTS=1. Script repair to follow as v1.2. |
| 21 | 2026-11-24T06:18:25Z | `e28930c` | `docs/D10_GATE_CLOSURE_2026-11-24.md` | `f61d585893146f61f5c8700b1a348598805cce16e71d3c2fa0e122a176462857` | Closes gate D10, the target event count hard gate. PASS; the region decision does not reopen. Primary M4.0 count 4,442 target events, registered S1 secondary M4.5 count 1,679, every year of the window populated. | GitHub push record | No numeric threshold was ever registered for this gate despite its hard consequence, which is recorded as a defect in the gate definition. The pass rests on an external anchor: Tsuruoka et al. 2012 applied the CSEP comparative T and W tests to 115 target events on the same region at the same threshold band, so this study exceeds it 38.6x on the primary and 14.6x on S1, giving 6.21x and 3.82x the precision under 1/sqrt(N) scaling. Counts are undeclustered by registered design and are not counts of independent events; April 2016 runs 3.75x the monthly median on the Kumamoto sequence. |
