# Amendment #10a — H6a Re-analysis Against Declustered Catalog

**Date:** 2026-05-19
**OSF:** osf.io/8hvf6
**Linked analysis:** H6a (HAC moderator — lunar phase and planetary elongation)
**Linked amendment:** Amendment #10 (H6b declustering requirement)

## Rationale

Amendment #10 documented that 29.2% of the H6b event pool consisted of non-independent aftershocks from Tohoku/Maule/Sumatra. The same undeclustered catalog underlies H6a — specifically the waxing_crescent lunar phase bin showed 74 events vs ~33 expected, consistent with Tohoku aftershock clustering. This amendment pre-registers a declustered re-analysis of H6a to determine whether the confirmed moderator results (lunar phase p=0.013, Mars elongation p=0.005) are robust to aftershock removal.

## Pre-Registered Declustering Parameters

**Algorithm:** Gardner-Knopoff (1974) as cited in Grünthal et al. (2009)

**Distance window:**
L(M) = 10^(0.1238 * M + 0.983) km

**Time window (forward-looking, aftershocks only):**
- M < 6.5: T(M) = 10^(0.5409 * M - 0.547) days
- M >= 6.5: T(M) = 10^(0.032 * M + 2.7389) days

**Application:** Applied to sentinel_groundtruth.master_earthquakes
**Output table:** sentinel_groundtruth.master_earthquakes_declustered
**Flag column:** is_mainshock BOOLEAN

**Magnitude scope:** All events used as potential mainshocks regardless of magnitude
**Direction:** Forward-looking only (aftershocks removed; foreshocks retained)

## Pre-Registered Analysis

H6a (h6a_hac_moderator_v2.py or equivalent) re-run with earthquake event pool
filtered to is_mainshock = TRUE. All other parameters unchanged:
- fault_id = global
- magnitude threshold: M >= 6.0 (as in original H6a)
- HAC signal table: sentinel_features.hac_features_daily
- Moderators: lunar phase (8 bins), Mars elongation, Jupiter distance
- Bootstrap permutations: 2000
- FDR correction: Benjamini-Hochberg

## Success Criteria

If lunar phase (high_emotion) and Mars elongation (high_urgency) remain
FDR-significant in the declustered re-analysis, H6a confirmed results are
classified as robust. If either drops below FDR significance, results are
reclassified as preliminary pending further replication.
