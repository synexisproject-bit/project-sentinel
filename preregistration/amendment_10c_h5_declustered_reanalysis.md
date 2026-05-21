# Amendment #10c — H5-Cascade-1 Re-analysis Against Declustered Catalog

**Date:** 2026-05-21
**OSF:** osf.io/8hvf6
**Linked analysis:** H5-Cascade-1 (HAC centroid in ionospheric LAIC window)
**Linked amendments:** Amendment #10 (H6b declustering), #10b (H6a reclassification)

## Rationale

The H5-Cascade-1 analysis used master_earthquakes (undeclustered). The M6+
event pool contains 2,307 events of which 1,332 (57.7%) are aftershocks by
Gardner-Knopoff classification. Post-event HAC reporting inflation is
documented (water z=-3.52, urgency z=-2.97, H5-SEA Round 3). Aftershocks
occurring days to weeks after a mainshock therefore carry elevated HAC signal
in their pre-event window that reflects mainshock reporting, not pre-seismic
signal. This could bias the SEA centroid toward the ionospheric window.

This amendment pre-registers a declustered re-analysis to determine whether
the H5-Cascade-1 centroid result is robust to aftershock removal.

## Original H5-Cascade-1 Result (for reference)

| Metric | Centroid | CI Lower | CI Upper | Classification |
|---|---|---|---|---|
| water | -3.597 | -4.938 | -2.215 | IONOSPHERIC |
| high_urgency | -3.879 | -5.228 | -2.590 | IONOSPHERIC |
| high_emotion | -3.753 | -5.622 | -2.197 | IONOSPHERIC |

## Pre-Registered Parameters

- Input catalog: sentinel_groundtruth.master_earthquakes_declustered
- Filter: is_mainshock = TRUE
- Magnitude threshold: M>=6.0 (unchanged)
- Date range: 2010-01-01 to 2026-12-31 (unchanged)
- Signal table: sentinel_features.hac_features_daily (unchanged)
- Window: ±20 days (unchanged)
- Permutation iterations: 2000 (unchanged)
- Results table: sentinel_eval.h5_cascade_results_declustered

## Pre-Registered Success Criteria

ROBUST: All three metric centroids remain in IONOSPHERIC window
  (centroid_day between -5 and -1, CI does not overlap 0)
PARTIALLY ROBUST: 2 of 3 metrics remain IONOSPHERIC
PRELIMINARY: 1 or 0 metrics remain IONOSPHERIC
