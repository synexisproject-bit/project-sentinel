# D9 findings note: magnitude of completeness results and two post-hoc discoveries

**Filed:** 2026-11-20
**Protocol locked at:** `b7ffa07`, `docs/BLOCK1_ADDENDUM1_mc_protocol_2026-11-14.docx`,
sha256 `1c2a6cd408b45bfd9071c0e8dfeae0201be73ffc535c7b752e263d3af0bed1eb`, ledger row 15
**Registration:** 10.17605/OSF.IO/H5MD2
**Analysis run:** `estimate_mc_d9.py` v1.0.0, seismostats 1.0.1, started 2026-11-19T04:07:06Z,
six stages, about 3.3 hours on 4 cores
**Working catalog:** 798,205 events, sha256 `f48dbc7f83af685f392b45830c419982c14189f67947e7114eb95543ac05a9cd`

---

## Why this is a note and not a revision

The D9 protocol was fixed at `b7ffa07` before any Mc value existed. Everything in
sections 2 and 3 below was discovered **after** that lock, in diagnostics run on the
results. Neither discovery is a reason to change the protocol, and neither is recorded
by editing it.

The amendment stays as committed. This note carries what was found, when, and what it
does and does not change. Section 7 of the amendment required a further amendment only
if Mc reached 4.0 in some scope. It did not. This note exists because a newly found
systematic feature of the evaluation set belongs on the record with a timestamp before
the evaluation runs, rather than appearing for the first time in a manuscript.

---

## 1. The registered gate outcome

Section 7 reads the **highest** of E1, E2 and E3 on subset P, not the registered
primary, so that no estimator choice can decide the gate.

| Scope | E1 (MBS-WW) | E2 (KS) | E3 (MAXC) | gate | Band |
|---|---|---|---|---|---|
| Whole region, subset P | 3.7 | 3.7 | 2.0 | **3.7** | 3.5 to 4.0 |
| Annual maximum (2016) | 3.6 | 2.9 | 2.0 | **3.6** | 3.5 to 4.0 |
| Highest assessed spatial node | — | — | — | **3.9** | 3.5 to 4.0 |
| Moving-window maximum | — | — | — | **3.7** | 3.5 to 4.0 |

**No scope reaches 4.0.** Zero of 2,770 assessed spatial nodes, zero of 1,383 moving
windows, zero of eight annual windows. Forty-two nodes (1.5 percent of those assessed)
and seven windows (0.5 percent) sit at or above 3.5.

**D9 therefore closes in the middle band of section 7:** the registered M ≥ 4.0
threshold is defensible, the margin is thin, the margin is reported as a limitation,
and the already-registered S1 sensitivity analysis at M ≥ 4.5 carries added weight in
interpretation. The ordering stays exactly as registered: M4.0 primary, S1 subordinate.

### Supporting results

**Subsets at full size.** All three returned E1 3.7 and E2 3.7. E3 returned 2.0 for P
and R and 1.2 for Q.

**The b-value is identical across all three subsets**, to every reported digit:
b = 0.880043, Shi and Bolt sigma = 0.009397, 8,298 events above M3.65. This is correct,
not a defect. Every event at M ≥ 4.0 in the target catalog is a closely examined K or S
solution, so above M3.65 the three subsets contain the same events and must give the
same b. It follows that **the manual-versus-automatic distinction the amendment was
built around has no effect on the b-value that enters the smoothed-seismicity
benchmark.** The automatic and unexamined solutions lie entirely below M3.65.

**An independent consistency check passes.** With b = 0.88, scaling the 4,442 events at
M ≥ 3.95 in the registered target catalog down to M ≥ 3.65 predicts
4,442 × 10^(0.88 × 0.3) = 8,158 events. The observed count is 8,298, agreeing to within
1.7 percent. The b-value and the counts are mutually consistent with a catalog built by
a separate code path.

**The equal-size comparison changed the conclusion, as intended.** At full size P and Q
both gave 3.7, no difference. At n = 234,612 over 20 draws, P gave a median of 3.7
(range 3.5 to 3.7) and Q gave 3.1 (range 2.8 to 3.7). The two comparisons disagree, and
the amendment specifies that the equal-size comparison governs interpretation:
**automatic solutions lower the apparent Mc by about 0.6**, an effect the full-size
comparison hid entirely behind the sample-size effect. R matched P at 3.7 in every draw,
so the unexamined manual solutions (flags k and s) make no difference.

**Annual, subset P:** 3.6, 3.3, 2.7, 2.7, 2.7, 3.5, 3.3, 2.7 for 2016 through 2023. The
elevated years are 2016, 2021 and 2022.

**Annual, subset R, 2016: E2 returned 4.1, gate 4.1.** This is above the registered
threshold. R is the diagnostic subset and section 7 evaluates the gate on subset P, so
this does not trigger the amendment clause. It is recorded here rather than omitted.

**Spatial coverage.** 2,770 of 9,595 nodes met the 500-event sufficiency criterion.
Node gate values ran from 1.2 to 3.9 with a median of 2.0. The highest was at
141.65 E, 38.50 N, off Tohoku near the trench; a cluster at 3.6 sits at 140.1 to 140.7 E,
32.0 to 32.5 N, south of Honshu. Both are offshore, consistent with Wiemer and Wyss
(2000) reporting offshore completeness near 3.2 against 1.3 inland.

---

## 2. Post-hoc finding: the aggregate distribution has no single completeness magnitude

The apparent b-value over subset P drifts monotonically and never settles:

| Range | apparent b | events above lower bound |
|---|---|---|
| M1.8 to 2.3 | 0.663 | 219,597 |
| M2.0 to 2.5 | 0.704 | 164,640 |
| M2.5 to 3.0 | 0.768 | 73,235 |
| M3.0 to 3.5 | 0.809 | 30,262 |
| M3.5 to 4.0 | 0.891 | 11,923 |
| M4.0 to 4.5 | 0.903 | 4,274 |

A catalog complete above some Mc shows a constant slope above it. This one curves
continuously. The spatial stage found individual node completeness spanning 1.2 to 3.9,
and pooling populations with different completeness and different b cannot produce a
single Gutenberg-Richter law.

**The whole-region value of 3.7 therefore measures spatial and temporal heterogeneity
rather than a completeness level.** The spatially resolved result is the informative
one, and its median of 2.0 agrees closely with the published mainland figure of 1.9
(Tsuruoka et al. 2012) and with the mode-based estimate below.

The mode of the non-cumulative distribution is at M1.8 with 28,643 events, giving
MAXC = 2.0, which is what E3 returned at every annual window for subset P.

**A correction to an interim figure.** The first pass at this table reported apparent b
of 1.131 at M4.5 to 5.0 and 2.165 at M5.0 to 5.5. Those were artifacts of a data extract
truncated at M5.5 and are withdrawn. The curvature below M4.5 is unaffected and is what
this finding rests on.

---

## 3. Post-hoc finding: a step in the distribution at exactly M4.0

Projecting each 0.1 bin from the one below it at b = 0.88:

| step | expected | observed | ratio |
|---|---|---|---|
| M3.3 to 3.4 | 2,517 | 2,486 | 0.99 |
| M3.4 to 3.5 | 2,030 | 2,082 | 1.03 |
| M3.5 to 3.6 | 1,700 | 1,711 | 1.01 |
| M3.6 to 3.7 | 1,397 | 1,440 | 1.03 |
| M3.7 to 3.8 | 1,176 | 1,295 | 1.10 |
| M3.8 to 3.9 | 1,057 | 1,121 | 1.06 |
| **M3.9 to 4.0** | **915** | **731** | **0.80** |
| M4.0 to 4.1 | 597 | 654 | 1.10 |
| M4.1 to 4.2 | 534 | 566 | 1.06 |
| M4.2 to 4.3 | 462 | 434 | 0.94 |
| M4.3 to 4.4 | 354 | 378 | 1.07 |

Every adjacent step across M3.3 to M4.4 falls between 0.94 and 1.10 except one. The
M3.9 to M4.0 step is 0.80, a 20 percent deficit, and it is isolated.

The displacement-magnitude share over the same bins:

| M | displacement share |
|---|---|
| 3.6 | 2.6% |
| 3.7 | 7.4% |
| 3.8 | 18.8% |
| 3.9 | 27.6% |
| **4.0** | **59.5%** |
| 4.1 | 65.4% |
| 4.2 | 77.7% |

**The step and the magnitude-scale changeover fall in the same bin.** JMA appears to
move from velocity magnitude to displacement magnitude around M4.0. The Block 1 Addendum
measured those two scales as offset by about −0.02 magnitude units in the MV 4.x bin
(see `docs/ADDENDUM_CORRECTION_2026-11-09.md` for the precise attribution of that
figure). Reported in 0.1 bins, a systematic offset of that size moves a substantial
fraction of boundary-adjacent events down one bin, inflating M3.9 and depleting M4.0.
That is quantitatively what is observed.

### Consequences

**The E1 and E2 values of 3.7 are most likely detecting this step, not incompleteness.**
Both estimators returned 3.7, which is 0.3 units below the step and the bin where the
displacement share first becomes non-trivial at 7.4 percent.

**The registered M ≥ 4.0 threshold sits on the changeover, and the lowest bin of the
target catalog is about 20 percent depleted relative to the trend from below.** The
CSEP-Japan 1-day class forecasts in 0.1 magnitude bins starting at 4.0. That lowest bin
carries the most events and therefore the most weight in the N-test and the M-test, so a
forecast calibrated to the Gutenberg-Richter trend will over-predict it.

**The threshold is not a choice originating with this study.** M ≥ 4.0 is the CSEP-Japan
standard for the registered 1-day testing class, set by the testing centre at ERI,
University of Tokyo. Any participant in that experiment inherits the same step. This is
a property of the JMA catalog rather than of this study's design.

**S1 was registered for this and is unaffected.** The M ≥ 4.5 sensitivity analysis sits
well above the transition, where the displacement share is 85.6 percent and stable. It
was registered before any of this was known, as a robustness check against the
magnitude-scale transition specifically. Its position in the design is unchanged:
subordinate to the M4.0 primary, with that ordering fixed in advance. It is **not**
promoted on the strength of this finding, because reordering a registered design once the
primary looks awkward is the move pre-registration exists to prevent.

---

## 4. Post-hoc finding: the coverage gap is larger than anticipated

**71.1 percent of grid nodes could not be assessed.** 6,825 of 9,595 nodes held fewer
than 500 events within 100 km.

Section 7 anticipated insufficient coverage and specified that it be reported with the
fraction stated. The fraction is larger than expected when that clause was written, and
it is not randomly distributed. Event density is lowest offshore, which is where nodes
fail the sufficiency test, and offshore is where published completeness is worst.

**The region most likely to exceed Mc 4.0 is largely the region that could not be
assessed.** The highest assessed node is 3.9. That is not the same statement as the
highest node being 3.9, and the distinction is reported as a limitation rather than
elided.

---

## 5. The scale-mixing check could not be completed

The amendment required Mc and b estimated separately on velocity-only and
displacement-only events wherever either carried at least 1,000 events. The result:

| subset | events | E1 | b |
|---|---|---|---|
| velocity only | 359,605 | 4.0 | 1.868 |
| displacement only | 4,295 | not attained below M4.5 | — |

A b-value of 1.868 is far outside the physical range of roughly 0.8 to 1.2, and the
displacement subset found no passing cut-off at all, so the comparison the amendment
called for could not be made.

The reason is the finding in section 3, seen from another angle. The two scales are
**magnitude-segregated rather than overlapping**: velocity is used below the changeover
and displacement above it. Velocity-only above M4.0 is a truncated tail, which produces
an artificially steep slope. Displacement-only is concentrated at high magnitude with no
low-magnitude roll-off to fit.

This is reported as a finding about the catalog, not as a failed analysis. The check as
specified cannot be performed on a catalog whose two magnitude scales do not overlap,
and recording that is more useful than a spurious b-value comparison would have been.

---

## 6. What is unchanged

| Item | Status |
|---|---|
| Registered threshold | M ≥ 4.0, unchanged |
| Testing class | CSEP-Japan 1-day, unchanged |
| Evaluation window | 2016-01-01 to 2023-12-31 UTC, unchanged |
| Nine filtering rules | unchanged |
| Declustering | none, unchanged |
| Target catalog | 4,442 events, unchanged, sha256 `148a16a8f88454a8575d0e09b1d36f1076d5ab8bc0f184ae4fec315f48d3fcc1` |
| Primary and S1 ordering | M4.0 primary, S1 subordinate, unchanged |
| Benchmark b-value | 0.880 ± 0.009, fitted above the subset P E1 Mc of 3.7, per the amendment |
| D9 gate outcome | middle band of section 7: defensible, margin thin |

---

## 7. Open items this note creates

| Item | Why |
|---|---|
| Ask the CSEP-Japan testing centre whether the M4.0 scale changeover is a known catalog feature and whether established practice exists for the lowest magnitude bin | If there is existing practice, adopting it is better than inventing something. Enquiry drafted 2026-11-20. |
| Decide, before the evaluation runs, whether anything about the lowest bin changes | Any change is a further amendment with its own date and ledger row. The default is no change, with the bias reported. |
| Benchmark b-value choice | b = 0.880 is fitted above M3.65 per the amendment. If the M3.7 figure is an artifact of the step rather than a completeness level, a b fitted above a lower cut-off may describe the seismicity better. This is a question for the ETAS and smoothing amendment, which is still open, and is noted rather than decided here. |

---

## Verification

Every figure in this note comes from the committed stage outputs. To reproduce:

```bash
gsutil -m cp gs://synexis-project-sentinel-exports-central1/d9/results/*.json .
# per-bin counts used in sections 2 and 3:
python3 -c "import json; print(json.load(open('d9_scalemix.json'))['result']['P']['per_bin'])"
```

The estimator, all six stage outputs and this note are committed together. The
`d9_summary.json` hash is recorded in the registration ledger.
