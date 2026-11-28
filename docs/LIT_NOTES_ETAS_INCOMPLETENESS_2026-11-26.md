# Literature notes: ETAS and catalog incompleteness

**Filed:** 2026-11-26 (UTC)
**Block 2 milestone:** M1, literature read before drafting the ETAS amendment (handoff section 9,
action 3)
**Status:** reading notes. Nothing here is a decision. Every design choice below is a candidate
for amendment 4.1 and for the independent expert review that precedes its lock.

---

## 1. What was read, and how

| Source | Access | Reading status |
|---|---|---|
| Mizrahi, Nandan and Wiemer (2021), *Embracing Data Incompleteness for Better Earthquake Forecasting*, JGR Solid Earth, doi:10.1029/2021JB022379. Open access, CC BY-NC. arXiv:2105.00888 | arXiv full text | Read through a web retrieval tool that returns a structured reading of the full text. The first ~91 percent of the document was covered (body, figures and most references). Not read line by line by a human |
| Kamranzad, Naylor, Lindgren, Bayliss, Main and others, *Enhancing the ETAS model: incorporating rate-dependent incompleteness, constructing a representative data set and reducing bias in inversions*, Geophysical Journal International, doi:10.1093/gji/ggaf156. Preprint at ESS Open Archive, 10.22541/essoar.171288630.01457115/v1 | Abstract only. The full-text PDF and the author's Edinburgh thesis (doi:10.7488/era/4997) could not be retrieved | **Abstract-level only.** Treat every statement in section 4 accordingly |
| Naylor, Serafini, Lindgren and Main (2023), *Bayesian modeling of the temporal evolution of seismicity using the ETAS.inlabru package*, Frontiers in Applied Mathematics and Statistics, doi:10.3389/fams.2023.1126759 | Abstract and conclusions | Supporting reference only |

**A human read of the Mizrahi full text is still owed before the amendment locks.** These notes
are adequate for drafting and for framing the expert review questions. They are not adequate as
the sole basis for a locked specification.

---

## 2. Correction to the handoff, section 5

The handoff (ledger row 24) attributes both references to "the Swiss Seismological Service, the
same group behind SeismoStats." **That holds for Mizrahi et al. 2021 only.** The GJI paper comes
from the University of Edinburgh (School of GeoSciences and School of Mathematics), with one
co-author at the Global Earthquake Model Foundation. The two papers take different technical
approaches (section 4). The handoff's statement that both are "candidates" stands.

---

## 3. Mizrahi, Nandan and Wiemer (2021)

**Model.** Spatio-temporal ETAS with an isotropic spatial kernel whose width scales with magnitude,
Omori-Utsu temporal decay with an exponential taper, exponential magnitude productivity, and a
single constant background rate over the region and training window. Fitted by
expectation-maximisation. A spatially or temporally varying background is listed as future work.

**Two incompleteness methods.**

- **Method 1, long-term.** Completeness given as a step function in time (for example, older
  decades complete only at higher magnitudes). Events below the reference magnitude are treated as
  unobserved, and their contribution is restored through two time-dependent correction ratios.
  This lets a long, older catalog with poorer completeness be combined with a modern, more complete
  one.
- **Method 2, short-term (PETAI).** Detection probability depends on magnitude and on the current
  total event rate across the region, through a single network "recovery time" parameter. The
  incompleteness parameters and the ETAS parameters are estimated jointly by iteration until both
  converge. This is the method aimed at short-term aftershock incompleteness, the central problem
  named in handoff section 5.

**Pseudo-prospective experiment.** California, ANSS ComCat, catalog from 1970, with an earlier
trigger-only auxiliary period. 30-day forecast windows from 2000 to early 2020, each fitted on data
up to its start. Forecasts built from 100,000 simulated continuations per window. Scored by
log-likelihood against a homogeneous Poisson reference and pairwise between ETAS variants, with a
CSEP-style T-test for significance.

**Findings that matter here.**

1. **The gain comes from letting small events trigger, with the incompleteness correction
   applied.** Simply lowering the completeness threshold without the correction did not
   significantly beat standard ETAS.
2. **The advantage shrinks as the target magnitude rises.** Above about M3.5, almost no pairwise
   differences between ETAS variants were significant in their experiment. The authors expect
   1-day updating to increase the benefit of small events, which they did not test.
3. **Detection was assumed uniform across the region.** The authors note this broke down during
   the large California sequences and reduced the gain there.
4. **Cost.** About 23 single-core hours for one PETAI fit on California, mostly spent on the ETAS
   optimisation.
5. **Code.** Released as Python repositories `lmizrahi/etas` and `lmizrahi/petai` on GitHub.
   License not stated in the paper. To be checked before adoption.

---

## 4. Kamranzad et al. (GJI, ggaf156), abstract level only

- **Approach.** A censorship function added to the ETAS conditional intensity and likelihood, so
  the inversion can operate on incomplete early-aftershock data. Bayesian inference through
  inlabru (INLA), giving posterior distributions.
- **Scope.** Synthetic tests plus three real sequences: Amatrice 2016, Kermanshah 2017 and
  Ridgecrest 2019. Whether the model is temporal only or spatio-temporal is **not established** from
  the abstract. The ETAS.inlabru package it builds on is temporal.
- **Representative samples.** The paper asks what makes a representative fitting sample and tests
  time binning, conditioning on a historic run-in period, magnitude combinations (the trade-off
  between the productivity parameters K and alpha) and incompleteness parameter choices. The related
  2023 ETAS.inlabru paper reports that a sample needs quiet periods as well as active sequences; when
  fitting uses active sequences alone, the background rate can come out several times too high.
- **Assessment.** It addresses individual sequences. It is less directly suited to a region-wide,
  1-day, spatio-temporal benchmark than Mizrahi Method 2, unless the full text shows a
  spatio-temporal formulation. Its sampling findings bear directly on the learning-period question
  (section 5, item 4).

---

## 5. Implications for amendment 4.1

Mapped to the item list as revised in `docs/HANDOFF_CORRECTION_2026-11-25.md` (ledger row 25).

| Item | What the reading adds |
|---|---|
| 1. Combination method | Mizrahi's model has a single constant background. One natural combination is ETAS with the smoothed-seismicity model supplying a spatially varying background. This is a candidate only |
| 2. Validation reference | See section 6. The choice of incompleteness treatment constrains which published result the benchmark can be validated against |
| 3. ETAS flavour | Mizrahi: isotropic, with a magnitude-dependent spatial term. Adopting their code would fix this item by inheritance |
| 4. Learning period | Both lines of work support a long learning period containing quiet periods as well as sequences, with an earlier trigger-only auxiliary period. Method 1 would let pre-2016 JMA data with poorer completeness be used without forcing a single cut-off. **This strengthens issue 2.1 of the correction note: pre-2016 data is very likely required** |
| 5. Completeness treatment | Three candidate options, set out in section 6 |
| 6. Smoothing kernel | Not addressed by either paper |
| 7. Background method | Mizrahi uses a constant background, which is weak for a region the size of All Japan. Links to item 1 |
| 8. Pinned versions | Applies to any adopted code. License check required for `lmizrahi/etas` and `lmizrahi/petai` |

**Three items the original list does not contain, which the reading shows the amendment must fix:**

- **9. Refit schedule.** One PETAI fit took about 23 core-hours on California. Refitting before
  each of the 2,922 daily bins is not feasible. The amendment must state how often parameters are
  refitted (for example, yearly), and confirm that between refits each daily forecast uses only data
  before its bin. This fills no new results-table blank; it is required for the registered rule
  that no forecast uses data from its own window or later.
- **10. How expected rates per bin are produced.** The registration scores rate forecasts per bin.
  An ETAS forecast for a 1-day bin is normally obtained by simulation. The number of simulations,
  the seed policy and the conversion of simulated catalogs to expected rates must be fixed. The
  registration already requires simulation counts and seeds to be recorded.
- **11. Spatially varying detection.** Mizrahi's Method 2 ties detection to the total rate across
  the region. All Japan spans about 20 degrees of latitude: a large sequence in Kyushu does not
  degrade detection in Hokkaido. A region-wide detection term is likely a poor approximation here,
  and the authors report this weakness themselves. The amendment must either accept it as a stated
  limitation or adopt a local formulation.

---

## 6. The central tension: incompleteness treatment against validatability

The registration requires the benchmark to be validated against published CSEP-Japan results for
comparable models before the TEC predictor is introduced. A benchmark is most easily validated when
its specification matches the published model it is compared against. The modern incompleteness
treatments post-date most published CSEP-Japan ETAS results, and none of the three papers above
applies them to Japan.

| Option | Completeness treatment | Strength | Weakness |
|---|---|---|---|
| **A** | Standard spatio-temporal ETAS at a constant completeness of 3.7 | Closest match to published CSEP-Japan ETAS, so easiest to validate | Known parameter bias from short-term aftershock incompleteness, the problem handoff section 5 names |
| **B** | Mizrahi Method 2 (PETAI), triggering from events below 3.7 | Addresses the named problem directly, with published code | No published Japan result to validate against. Region-wide detection assumption weak for All Japan. Benefit at M4.0 uncertain |
| **C** | Option A validated against the published reference, then Option B as the benchmark, with the A-to-B difference reported | Validates the implementation and still treats incompleteness | The registration requires validation of the benchmark itself, so this needs an explicit amendment arguing that validating A validates the shared implementation of B. That is a judgement an expert should make, and should not be made by this project alone |

**No option is selected here.** This tension is the first question for the expert reviewer.

---

## 7. Questions for the expert review

1. Which of options A, B and C is defensible for a 1-day All Japan benchmark at M4.0, given the
   registered validation requirement?
2. What learning period and trigger-only auxiliary period would you use for the JMA catalog, and is
   a step-function completeness history (Mizrahi Method 1) appropriate across the pre-2016 network
   changes?
3. Is a region-wide detection term acceptable for All Japan, or is a local formulation required?
4. What refit frequency is defensible for a 2,922-day pseudo-prospective window?
5. How should the ETAS and smoothed-seismicity components be combined into the single registered
   benchmark?

---

## 8. Still to read

- Mizrahi et al. 2021, a human read of the full text, particularly the methods and the treatment of
  the 15-year auxiliary period.
- Kamranzad et al., the full GJI text once a copy is obtained (open access per the journal page;
  retrieval failed in this session).
- The candidate validation references, starting with Zhuang (2011), *Next-day earthquake forecasts
  for the Japan region generated by the ETAS model*, Earth, Planets and Space 63(3), 207 to 216.
- arXiv:2405.10712 on the T-test standardisation (handoff section 7.1, correction note issue 2.4).
