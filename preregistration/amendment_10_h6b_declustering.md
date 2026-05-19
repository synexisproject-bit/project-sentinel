# Amendment #10 — H6b: Declustering Requirement and M6.5 Threshold Sensitivity Documentation

**Date:** 2026-05-19
**OSF:** osf.io/8hvf6
**Linked hypothesis:** H6b (seismic-lunar phase relationship)
**Linked commit:** `0b632b0` (H6b execution and H6 ephemeris build)

## Background

H6b tested whether M6.5+ earthquake occurrence within the five pre-registered fault zones is modulated by lunar phase. The pre-registered analysis returned a null result (global_pooled: chi-square p=0.968, bootstrap p=0.976). However, post-hoc diagnostic analysis revealed a systematic methodological confound that prevents this null from being considered definitive: aftershock contamination of the event pool.

## H6b Results Summary

| Fault Zone | N Events | Chi2 | p (chi-square) | p (bootstrap) | Verdict |
|---|---|---|---|---|---|
| global_pooled | 96 | 1.833 | 0.968 | 0.976 | NULL |
| sumatra_andaman | 27 | 9.444 | 0.222 | 0.225 | NULL |
| central_chile | 29 | 7.690 | 0.361 | 0.385 | NULL |
| japan_trench | 34 | 6.000 | 0.540 | 0.585 | NULL |
| cascadia | 3 | — | — | — | INSUFFICIENT_DATA |
| north_anatolian | 3 | — | — | — | INSUFFICIENT_DATA |

Observed lunar phase bin counts (global_pooled, 8 bins x 45 degrees):
[11, 11, 9, 13, 12, 15, 12, 13] vs expected 12.0 per bin.

The distribution appears approximately uniform (p=0.968), consistent with a null result. However, the independence assumption underlying the chi-square test is violated by aftershock sequences documented below. The near-flat bin distribution does not indicate the null is clean — it indicates the contamination is diffuse across bins rather than phase-locked.

## Finding: Aftershock Contamination

The master_earthquakes catalog used for H6b is an undeclustered catalog. Three large earthquake sequences generated M6.5+ aftershocks during the study window that were included in the event pool:

| Mainshock | Date | Magnitude | M6.5+ Aftershocks in Pool |
|---|---|---|---|
| Tohoku | 2011-03-11 | M9.0 | 14 |
| Maule (Chile) | 2010-02-27 | M8.8 | 10 |
| Sumatra-Andaman | 2004-12-26 | M9.1 | 4 |
| **Total** | | | **28 of 96 events (29.2%)** |

Nearly one-third of the global_pooled event pool consists of aftershocks from three sequences. Aftershocks follow Omori-Utsu temporal decay and are not temporally independent events. Their inclusion introduces structured autocorrelation that violates the chi-square test's independence assumption.

The contamination does not visibly distort the bin distribution because aftershock occurrence is not phase-locked to the lunar cycle — the non-independent events diffuse across all eight bins. The problem is not distribution shape but event non-independence: the effective sample size is substantially smaller than n=96, which inflates the apparent power of the null result.

Cross-stream note: This contamination pattern also carries into H6a. The waxing_crescent bin showed 74 events vs ~33 expected in the H6a moderator analysis, consistent with Tohoku aftershock clustering in the early study window. This does not invalidate H6a's confirmed moderator results but is noted for methodological completeness.

## Magnitude Threshold Sensitivity

Three magnitude thresholds were examined diagnostically during H6b execution against the full global catalog (undeclustered, 2010-2025):

| Threshold | N (global catalog) | N (fault pool) | Result | Contamination Note |
|---|---|---|---|---|
| M>=6.0 | 2,288 | ~175 | NULL | Highest — aftershock pool largest |
| M>=6.5 (pre-registered) | 731 | 96 | NULL (p=0.968) | 29.2% aftershocks |
| M>=7.0 | 244 | ~32 | NULL | Reduced but still undeclustered |

All three thresholds returned null under undeclustered conditions. This does not strengthen the null inference, as the contamination mechanism applies at all thresholds.

## Amendment: Declustering Requirement

Any future execution of H6b — or re-analysis at any pre-registered threshold — must use a declustered catalog as primary input. Pre-specified requirements:

- Declustering algorithm: Gardner-Knopoff (1974) or Reasenberg (1985); algorithm must be specified and committed to GitHub prior to catalog processing
- Catalog source: Declustered output applied to master_earthquakes or equivalent global catalog (ISC, ANSS ComCat)
- Magnitude threshold: M>=6.5 (pre-registered primary); M>=6.0 and M>=7.0 retained as sensitivity checks
- Lunar phase binning: Unchanged from original H6b protocol (8 bins x 45 degrees, chi-square test + bootstrap)
- Pre-registration requirement: Declustering parameters committed to GitHub before catalog processing begins

## Status and Classification

H6b is classified as **indeterminate pending declustering**, not null. The p=0.968 result is reported transparently and committed to the pre-registration record, but is not interpreted as evidence against a lunar modulation effect. The contamination of 29.2% of the event pool by non-independent aftershocks is sufficient to preclude a definitive null inference.

A definitive test requires the declustered re-analysis specified above. This is queued for a future phase pending catalog preparation.

## No Pipeline Changes Required

This amendment is documentation only. No BigQuery tables, scripts, or data are modified. The sentinel_eval.h6b_seismic_lunar_results table retains the original results for the record.
