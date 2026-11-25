# Block 2 handoff: state at Block 1 close

**Filed:** 2026-11-24
**Purpose:** the state of the project at the moment Block 1 closed and before any Block 2
work began, so that what was known in advance is distinguishable from what was learned
after.

This document is written to be self-contained. A reader starting here, with no prior
context, should be able to pick the project up. It records what is settled, what is open,
and what must be locked before any fitting happens.

---

## 1. What this study is

> **Pseudo-prospective evaluation of ionospheric total electron content as an incremental
> predictor over a calibrated seismicity benchmark in the CSEP-Japan testing region**

One region. One predictor, built two ways. One benchmark. Scored as information gain per
earthquake with a 95 percent interval, plus the CSEP consistency tests. The result is
published whichever direction it comes out, including negative, to the same venue on the
same timeline.

**Authority.** The OSF registration at 10.17605/OSF.IO/H5MD2, filed 2026-11-09, governs.
Where any repository document restates it, the registration wins. This note is a
restatement and is subordinate to it.

**Scope rule, quoted because it has already been violated once:**

> Every downstream decision must fill a blank in the results table. Anything that does not
> is out of scope.

See `docs/README_SCOPE_CORRECTION_2026-11-24.md` for the one instance where a repository
document claimed otherwise, and what it cost.

---

## 2. What Block 1 established, with the row that proves each

| Element | Value | Ledger row |
|---|---|---|
| Region | CSEP-Japan All Japan, 20,062 cells, 0.1 degree lattice, supplied by the testing centre and adopted unmodified | 2, 3 |
| Testing class and threshold | CSEP-Japan 1-day class, 4.0 ≤ M ≤ 9.0 in 0.1 bins, adopted unmodified | 5, 8 |
| Publication target and gate register | Part A through E | 7 |
| Raw catalog provenance | SHA-256 of eight yearly JMA archives as received | 6 |
| Catalog builder | Nine registered rules in registered order | 9, 13 |
| Target catalog | 4,442 events at M ≥ 4.0 from 2,161,892 raw records, zero parse failures, zero identity collisions | 10 |
| Completeness protocol | Three subsets, three estimators, SeismoStats 1.0.1, outcome table fixed in advance | 15 |
| Completeness result | Gate 3.7 whole region, 3.6 annual max, 3.9 highest assessed node, 3.7 moving-window max | 16, 17 |
| Benchmark b-value | 0.880043 ± 0.009397 above Mc 3.7 on 8,298 events | 17 |
| Target event count gate | PASS. 4,442 primary, 1,679 at the S1 threshold | 21 |
| Archive | v0.1.0, DOI 10.5281/zenodo.24507348 | 22 |

**The completeness result sits in the middle band** of the protocol's pre-specified outcome
table: the M4.0 threshold is defensible, the margin is thin, and the thinness is reported as
a limitation with added weight given to the S1 secondary.

---

## 3. Known limitations carried into Block 2

1. **71.1 percent of spatial grid nodes could not be assessed for completeness**, 6,825 of
   9,595, concentrated offshore where published completeness is worst. The highest
   *assessed* node of 3.9 is not the highest node. Whether this changes how the spatial
   component of the evaluation is reported is unresolved.
2. **The lowest magnitude bin is depleted by 22.5 percent** relative to the Gutenberg-Richter
   trend from the bins below. 12.2 points are intrinsic to the raw bulletin, 10.3 points come
   from this study's registered region and depth filters. About 63 percent of the intrinsic
   part is accounted for by the measured velocity-to-displacement magnitude offset. The
   remainder is unexplained, as is why the region filter concentrates its effect at M4.0.
   See `docs/D9_FINDINGS_CORRECTION_2026-11-23.md`.
3. **Target counts are not counts of independent events.** The design does not decluster,
   by registered decision. April 2016 runs 3.75 times the monthly median on the M7.0
   Kumamoto sequence. This bears on realised power and is not quantified.
4. **Environment capture is incomplete for Block 1.** `estimate_mc_d9.py` recorded its
   SeismoStats version at run time, so that is attested. The numpy, pandas and scipy versions
   were never recorded and the Cloud Shell VM has since reprovisioned, so the versions in
   `docs/block1_environment.txt` are later observations and not proof. **Block 2 scripts must
   capture the whole resolved environment inside the results file at run time.**

---

## 4. The four amendments owed

Each must be filed **before** the work it governs begins. None has been filed. No work they
govern has begun.

### 4.1 ETAS parameterization and smoothing kernel

The first and the most consequential. It must fix, at minimum:

1. **Which model "Benchmark" denotes.** The registered results table has rows for smoothed
   seismicity, for ETAS, and for "Benchmark + TEC". It never states whether the benchmark is
   ETAS, smoothed seismicity, or a combination. Information gain per earthquake is computed
   relative to it, so this one word determines the headline number.
2. **The validation reference.** The registered abstract carries a blank:
   `[BENCHMARK VALIDATION REFERENCE]`. Until it names a specific published Japan result and
   a numeric agreement criterion, the benchmark is a model rather than a benchmark. This is
   the most important unfilled blank in the project.
3. ETAS flavour: isotropic or anisotropic spatial kernel, and whether a magnitude-dependent
   spatial term is included.
4. The auxiliary catalog used for fitting: magnitude floor, time span, and whether it extends
   before 2016.
5. **The completeness treatment.** See section 5.
6. Smoothing kernel and bandwidth selection rule for the time-independent model.
7. Background rate estimation method.
8. Pinned versions of every package, as with SeismoStats.

### 4.2 GEONET station subset rule

Before bulk retrieval. Governs which GNSS stations contribute TEC pierce points, which
determines achievable spatial resolution. **This is part of the TEC predictor, not a
separate strain predictor.** Access is approved through 31 March 2027 and the application
must be resubmitted each April. Publications must cite the DOI on the GSI GEONET English
page, which is a separate open item.

### 4.3 TEC predictor construction

Shell height, elevation cutoff, and the two published specifications named. Depends on 4.2.

### 4.4 S2 time-shift interval

Filed with the predictor amendment, so the negative control is locked at the same moment as
the thing it controls.

---

## 5. The central technical problem of Block 2

For a 1-day testing class, forecast skill is dominated by the hours after a mainshock, which
is exactly when the catalog is least complete. Small aftershocks are missed because
overlapping waveforms cannot be resolved. ETAS fitted on a catalog treated as complete
returns biased values for every parameter simultaneously.

A direct treatment exists from the Swiss Seismological Service, the same group behind
SeismoStats:

- Mizrahi, Nandan and Wiemer (2021), *Embracing Data Incompleteness for Better Earthquake
  Forecasting*, JGR Solid Earth, doi:10.1029/2021JB022379
- *Enhancing the ETAS model: incorporating rate-dependent incompleteness, constructing a
  representative data set and reducing bias in inversions*, GJI 242(1), ggaf156

**This reframes an open question carried from D9.** The findings note recorded the question
"which cut-off should the benchmark b-value be fitted above" as a single number to decide. If
the amendment adopts a time-varying completeness treatment, there is no single cut-off and
the question becomes which completeness model to adopt. The D9 result is still load-bearing:
Mc 3.7 against a 4.0 target threshold is what tells you how far below the threshold an
auxiliary catalog can be trusted.

**Provenance note:** these references have been identified, not read. They are candidates for
the amendment, not decisions.

---

## 6. Tooling

| Layer | Choice | Status |
|---|---|---|
| Experiment harness | floatCSEP | **Named in the registration.** JOSS 11(118), 9408, published 2026-02-20, repository `cseptesting/floatcsep` |
| Consistency and comparative tests | pyCSEP | Inherited from floatCSEP |
| Completeness and b-value | SeismoStats 1.0.1 | Pinned by the registered protocol, already used |
| ETAS incompleteness treatment | Undecided | Candidates in section 5 |

These share authors and institutions, which is a coherent stack rather than four unrelated
tools.

---

## 7. Open questions, carried not resolved

1. **The CSEP T-test standardization.** arXiv:2405.10712 argues it is incorrectly
   standardized, that its variance estimate uses only bins with positive counts when it
   should use all forecast bins, and that in simulation the rejection rate is 46.5 percent
   against a nominal 10 percent across 400 replicates. It recommends working with score
   differences and a Diebold-Mariano test instead. **Not read, only a fetched summary, and a
   preprint.** The registered design scores information gain per earthquake with a 95 percent
   interval, so if it holds up it matters. Settle it before the evaluation method is locked.
2. **Whether the 71.1 percent unassessable node fraction changes spatial reporting.**
3. **Whether the evaluation should move to its own repository before submission.** Not
   concealment, which was considered and rejected and is recorded in the D11 closure note,
   but modularity: a reviewer following a data-availability statement should land on the
   twenty files that constitute the evaluation rather than four hundred that include the
   earlier program. The ledger lives in this repository and rows 1 through 22 reference
   commits here, so a split needs the ledger carried forward with a documented handoff rather
   than a silent copy.
4. **A courtesy notification to the CSEP-Japan testing centre** that the region file supplied
   in October is archived under a DOI and credited. A notification, not a permission request,
   to go in the next exchange rather than as a separate email.

---

## 8. Process, carried forward unchanged

1. **Every rule, specification and analysis plan is locked by commit before the data or code
   it governs.** Locked files are never edited. A superseded or incorrect file is corrected by
   a new dated note with its own ledger row, leaving the original visible. This has been used
   three times: rows 18 to 19, row 21's record of a missing gate threshold, and the README
   scope correction.
2. **The registration ledger is append-only.** One row per locking commit: UTC time, commit
   hash, file path, SHA-256 of contents, what it locks, external anchor, notes.
3. **`sentinel_audit.sh` runs at the start and end of every milestone.** Set
   `CLOUDSDK_CORE_DISABLE_PROMPTS=1`, or the run hangs on an invisible gcloud prompt at
   `synexis-foremark`. A v1.2 fixing this inside the script is owed.
4. **Any gate with a stated consequence should carry a number, fixed before the quantity is
   computed.** D10 did not, which is recorded as a defect in the gate definition at row 21.

---

## 9. First actions in Block 2

1. Run `sentinel_audit.sh` as the milestone-opening audit.
2. Read the registration at 10.17605/OSF.IO/H5MD2 directly, not a restatement of it.
3. Read Mizrahi et al. 2021 and the GJI extension before drafting the ETAS amendment.
4. Identify and name the benchmark validation reference. Nothing else in Block 2 should start
   before this exists, because it defines what success looks like for the whole block.
5. Draft the ETAS amendment, lock it by commit with its ledger row, and only then fit
   anything.
