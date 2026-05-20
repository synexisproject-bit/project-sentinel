# Amendment #10b — H6a Reclassification: PRELIMINARY

**Date:** 2026-05-20
**OSF:** osf.io/8hvf6
**Commit:** d360519
**Linked amendment:** Amendment #10a (d2561ec)
**Original H6a commit:** 9f67636
**H6a status:** Reclassified PRELIMINARY (was CONFIRMED)

## Summary

The original H6a confirmed result (lunar phase × high_emotion p=0.013;
Mars elongation × high_urgency p=0.005) is reclassified as PRELIMINARY
following pre-registered declustered re-analysis. Two compounding artifacts
identified and corrected. All three corrected re-analyses returned null
per Amendment #10a pre-registered success criteria.

## Artifacts Identified

**Artifact 1 — Aftershock contamination:** Undeclustered catalog inflated
waxing_crescent bin (~74 events vs ~33 expected) via Tohoku aftershock
clustering. Documented in Amendment #10.

**Artifact 2 — Duplicate event matching:** Join between
master_earthquakes_declustered and fault_events produced 173 rows from
76 distinct events (2.3x inflation). Events near multiple fault zone
boundaries matched multiple fault_events records, inflating effective
sample size and between-bin variance.

## Three Re-Analysis Runs

| Run | N | Lunar p | Mars p | FDR | Assessment |
|---|---|---|---|---|---|
| Original H6a | ~385 | 0.013 | 0.005 | Both YES | Artifacts present |
| Run 1: Global declustered | 965 | 0.822 | 0.157 | None | Wrong scope |
| Run 2: Fault zone duped | 173 | 0.093 | 0.000 | Mars YES | Duplicate artifact |
| Run 3: Fault zone clean | 76 | 0.442 | 0.126 | None | CORRECT TEST |

## Run 3 FDR Results (correct controlled comparison)

All primary and secondary moderators NULL. Jupiter tertiary exploratory
p=0.0045/0.0095 survives but pre-specified as non-confirmatory.

Results table: sentinel_eval.h6a_hac_moderator_results_declustered_deduped

## Power Limitation

n=76 (~9.5/bin) is underpowered. Between-bin variance for zscore (0.0238)
is large relative to global mean (0.0067). Null does not definitively
exclude a real effect — excludes detection at this power level.

## Classification

H6a: PRELIMINARY pending prospective replication with adequate power.
Original data and results retained. This amendment supersedes the
CONFIRMED classification only.
