# Amendment #8a — Hayward Fault: Execution Suspension (Phase 3)

**Date:** 2026-05-19
**OSF:** osf.io/8hvf6
**Linked amendment:** Amendment #8 (Hayward exploratory pre-registration, commit `66dd37f`)

## Finding

USGS ComCat (NCSN) catalog ingested for Hayward bounding box (37.2–38.1N, -122.4 to -121.6W), M≥2.5, 2001–2025. Result: 902 total events, 0 M5.5+, 2 M5.0+.

The Hayward fault is in a seismically locked inter-seismic period. No qualifying ground truth events exist within the pre-registered M≥5.5 threshold for the 2001–2025 study window.

## Decision

Hayward fault analysis is suspended for Phase 3. The H1, H2, hgeo, and H4 feature builds will not be executed for this fault system.

## Rationale

With zero M≥5.5 events, walk-forward analysis cannot be performed. Lowering the threshold would require substantive revision to Amendment #8 and would reduce scientific comparability with the other five fault systems. This is a structural limitation of the study period, not a catalog deficiency.

## Future phases

Hayward remains pre-registered as an exploratory target. If a M≥5.5 event occurs, the pipeline can be executed against the pre-registered protocol without further amendment.

## Catalog artifact

`sentinel_groundtruth.hayward_ncsn_earthquakes` — 902 rows retained for reference.
