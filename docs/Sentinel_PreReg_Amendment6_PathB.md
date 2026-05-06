# Project Sentinel — Pre-Registration Amendment #6
## Path B: Event Salience Stratification Analysis

**OSF Registration:** https://osf.io/8hvf6
**Date:** 2026-05-06
**Status:** Pre-registered before analysis execution
**Supersedes:** Amendment #5 (within-source normalization, geophysical_imagery deprecation)

---

## 1. Motivation

Phase 2 SEA returned a clean null across all corpus permutations tested in
Amendments #1-5. The null stands. However Phase 2 treated all M6+ events as
equivalent — a scientifically unjustified assumption. The Dunne (1927) hypothesis
predicts that high-salience events (major casualties, global media coverage) should
generate stronger pre-event dream signal than low-salience events, because the
dreamer's future emotional experience of a M8.0 disaster is qualitatively different
from their future experience of reading a brief wire story about a minor tremor.
Amendment #6 tests this prediction directly.

---

## 2. Hypotheses

**H_B1 (Primary):** Mean normalized feature score in the -7 to -1 day pre-event
window is significantly higher than the post-event baseline (+1 to +7 days) for
M7.0+ earthquake and tsunami events. Features: water_imagery, destruction_imagery,
high_urgency, high_emotion. Within-source normalization from Amendment #5.
Statistical test: two-tailed t-test or Wilcoxon, 2,000-permutation validation,
alpha = 0.05.

**H_B2 (Secondary A):** Same as H_B1, extended window -14 to -1 days pre-event.
Direct comparison with Phase 2 protocol.

**H_B3 (Secondary B):** Same as H_B1, restricted to M7.5+ events only.

**H_B4 (Secondary C):** Same as H_B1, restricted to M8.0+ events with >=10 dreams
in ±14 day window (n=14 events). Non-parametric test required.
Bonferroni correction across secondaries: alpha = 0.0167.

**Exploratory only (no p-values):** M8.0+ events, -90 to -1 day window.
Descriptive visualization only. Motivated by Tohoku NEXA case (cbf61709).

---

## 3. Event Catalog

Source: sentinel_groundtruth.events
Criteria: hazard IN ('earthquake','tsunami') AND mag >= 7.0

Coverage (pre-analysis characterization):
- M8.0+: 57 events, mean 7.1 dreams/window, 14 with adequate coverage
- M7.5-7.9: 180 events, mean 10.5 dreams/window, 76 with adequate coverage
- M7.0-7.4: 354 events, mean 10.6 dreams/window, 152 with adequate coverage

---

## 4. Dream Corpus

Source: hac_intake.hac_normalized
Criteria: is_sentinel_eligible=TRUE, experience_date IS NOT NULL, is_duplicate=FALSE
Normalization: within-source z-score (Amendment #5)
Date confidence weighting: high/medium = 1.0, low/unknown/NULL = 0.5

---

## 5. Outcome Reporting

Results reported regardless of direction. Effect sizes and CIs reported alongside
p-values. Null result is meaningful and will be reported fully.

---

## 6. What This Cannot Establish

A positive result is consistent with Dunne salience hypothesis but does not confirm
it. Alternative explanations include corpus composition artifacts, retrospective
reporting inflation, and multiple comparison issues. Independent prospective
replication required before causal interpretation.

---

*Filed prior to any analysis of feature scores or pre/post distributions.
The Section 3 coverage statistics were produced by a count query only.*

*Amendment #5 null results stand and are unaffected.*
