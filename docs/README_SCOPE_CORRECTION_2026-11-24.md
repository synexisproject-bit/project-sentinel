# Correction: the README overstated the scope of the registered study

**Target document:** `README.md`
**Target commits:** `256d9cf`, archived at tag `v0.1.0` and DOI 10.5281/zenodo.24507348, and `49e8457`
**Note filed:** 2026-11-24
**Status of the target:** archived under a DOI. The v0.1.0 archive is not and cannot be edited.
**Fix:** corrected `README.md` on `main`, released as `v0.1.1`

---

## What this corrects

The README described the study as testing multiple candidate predictors. It does not.
**The registered study tests one predictor.**

Two statements were wrong.

**In the status table:**

> | 3 | Candidate predictors: total electron content, GNSS strain, and anomalous-cognition streams | Not started |

**In the paragraph on the anomalous-cognition work:**

> Those streams enter only at Block 3, behind a benchmark that must first be built and
> validated against published results. They are scored by the same metric as every other
> candidate predictor [...] If the benchmark in Block 2 does not validate, Block 3 does not
> run at all and no predictor of any kind is evaluated.

Both describe the **Project Sentinel program**. Neither describes the **registered study
that this repository documents**. The error is the conflation of the two in a document whose
stated purpose is to describe the latter.

---

## What is actually registered

Part A of `docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx`, ledger
row 7, is explicit.

**Working title:**

> Pseudo-prospective evaluation of ionospheric total electron content as an incremental
> predictor over a calibrated seismicity benchmark in the CSEP-Japan testing region

**Scope rule, stated at the head of Part A:**

> This section is written before any data is touched. Every downstream decision must fill a
> blank in the results table below. **Anything that does not is out of scope.**

**The results table has four rows:**

| Model |
|---|
| Smoothed seismicity (reference) |
| ETAS |
| Benchmark + TEC (spec 1) |
| Benchmark + TEC (spec 2) |

There is no GNSS strain row. There is no anomalous-cognition row. The registered predictor
set is total electron content, built two ways, with the S2 negative control and the S1
secondary analysis at M ≥ 4.5.

---

## How the error arose

The amendment list names a "GEONET station subset rule." GEONET is the Geospatial
Information Authority of Japan's GNSS network, and GNSS data supports both strain
measurement and ionospheric TEC derivation. The README was written on the assumption that
a GEONET amendment implied a strain predictor.

It does not. GEONET appears in this study as the **source of the TEC pierce points**. The
registered abstract makes this unambiguous:

> Data characterization established a pierce-point sampling density of [DENSITY] within the
> target region, corresponding to an effective spatial resolution of [RESOLUTION].

The station subset rule governs which GNSS stations contribute pierce points, which
determines achievable TEC resolution. It is part of the TEC predictor, not a second
predictor.

---

## Severity

**Recorded without minimising it.** A README that claims a pre-registered study tests
predictors its registration does not name is the specific failure mode that pre-registration
exists to prevent. A reviewer comparing the README against the OSF registration would find
the discrepancy immediately, and the natural reading of such a discrepancy is scope creep
against a registration.

Three things limit the damage, none of which excuse it:

1. **The registration is unaffected and governs.** The OSF registration at
   10.17605/OSF.IO/H5MD2 predates the README by fifteen days and is authoritative over any
   restatement. Nothing in the registered design changed, was added to, or was reinterpreted.
2. **No work was performed under the wrong scope.** Blocks 2 through 4 have not started. No
   strain data was retrieved, no anomalous-cognition stream was prepared for this study, and
   no amendment was filed under the mistaken reading.
3. **Block 1 is unaffected in every particular.** The region, window, testing class,
   threshold, nine filtering rules, 4,442-event target catalog and completeness results are
   all independent of which predictor is tested downstream.

What is not limited: the erroneous statements are archived under DOI 10.5281/zenodo.24507348
and cannot be removed from it. They are corrected forward, not erased.

---

## What changes

| | |
|---|---|
| `README.md` on `main` | Corrected. The status table names one predictor. The registered design table now carries the working title, the testing class, the benchmark description and an explicit "Predictor under test: **One**" row. The anomalous-cognition paragraph distinguishes the program from this study and states that no anomalous-cognition stream appears in the registered results table |
| `v0.1.0` and its DOI | Unchanged and uneditable. Retains the error |
| `v0.1.1` | Tagged with the corrected README, so the concept DOI 10.5281/zenodo.24507347 resolves to the corrected version |
| This note | The dated record of what was claimed, when, and why it was wrong |

Anyone citing the concept DOI reaches the corrected text. Anyone citing the version DOI for
v0.1.0 reaches the uncorrected text and, from `main`, this note.

---

## What is unchanged

The registered protocol in every respect. The region, the testing class, the M4.0 primary
threshold, the M4.5 S1 secondary, the S2 time-shifted negative control, the 2016 to 2023
window, the nine filtering rules, the no-declustering decision, the 4,442-event target
catalog, the completeness results, and the benchmark b-value.

Ledger rows 1 through 22 are unaffected. None of them records a claim about predictor scope.

---

## Why this is a note and a new version rather than an edit

`README.md` at `v0.1.0` is archived under a DOI. Editing the archive is not possible and
would not be done if it were. The version DOI exists precisely so that a frozen artifact can
be superseded rather than altered, and this is the first use of that mechanism in this
project.

The error was found while answering a question about the Block 2 benchmark, which required
reading Part A of the registered document closely rather than from recollection. That is the
general lesson: a restatement drifts from its source unless it is checked against the source,
and this project's own documents warn about exactly that.
