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
