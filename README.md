# Project Sentinel

[![DOI](https://zenodo.org/badge/1164284697.svg)](https://doi.org/10.5281/zenodo.24507347)

A pre-registered evaluation of whether geophysical and environmental predictors add
forecasting information beyond an established earthquake forecasting benchmark, conducted
on the CSEP-Japan All Japan testing region.

Maintained by [The Synexis Project](https://synexisproject.org). Research Director:
Joseph Charles Tulloss.

**Pre-registration:** [10.17605/OSF.IO/H5MD2](https://doi.org/10.17605/OSF.IO/H5MD2),
filed before any evaluation against the target catalog.

---

## Status: read this first

**No forecast has been produced and no result exists.** This release contains the
foundation of the evaluation and none of the evaluation itself.

| Block | Content | Status |
|---|---|---|
| **1** | Region, threshold, catalog, magnitude completeness | **Complete. This release.** |
| 2 | Benchmark forecast (ETAS and smoothed seismicity), validated against published results | Not started |
| 3 | The predictor under test: ionospheric total electron content, built two ways from published specifications, plus the S2 negative control | Not started |
| 4 | Evaluation: consistency tests, information gain per earthquake with interval | Not started |

Until Block 2 exists there is nothing to measure against, so no claim about added
forecasting information is possible in either direction. Nothing in this repository should
be read as evidence that any predictor improves earthquake forecasts.

This repository also contains earlier exploratory work predating the pre-registered
rebuild. See [Earlier work in this repository](#earlier-work-in-this-repository) below.
That work is retained rather than removed so the record is complete, and it is
methodologically separate from Block 1.

**On the anomalous-cognition work, stated plainly rather than buried.** The wider Project
Sentinel program examines anomalous-cognition data within the same analytical framework.
**That work is not part of this study.** This study tests one geophysical predictor against
a calibrated seismicity benchmark, and the registration states that anything which does not
fill a blank in its results table is out of scope. No anomalous-cognition stream appears in
that table.

The earlier program is described under [Earlier work in this repository](#earlier-work-in-this-repository).
Most of its streams returned null against their pre-registered criteria and are published
as null. It is noted here because it is public and anyone who looks will find it, and an
accurate statement from the maintainer is better than a discovery later. Block 1 can be
assessed entirely on its own terms: it is a region definition, a catalog built under
pre-registered rules, and a completeness estimate, and it contains nothing from that work.

---

## The registered design

The registered working title states the scope precisely:

> Pseudo-prospective evaluation of ionospheric total electron content as an incremental
> predictor over a calibrated seismicity benchmark in the CSEP-Japan testing region

| Element | Value |
|---|---|
| Region | CSEP-Japan All Japan testing region, adopted unmodified, 20,062 cells on a 0.1 by 0.1 degree lattice |
| Testing class | CSEP-Japan 1-day class, adopted unmodified. 4.0 ≤ M ≤ 9.0 in 0.1 magnitude bins |
| Evaluation window | 2016-01-01 to 2023-12-31 inclusive, UTC |
| Benchmark | An ETAS model and a smoothed-seismicity model, implemented in floatCSEP and validated against a published result before any predictor is introduced |
| Predictor under test | **One.** Ionospheric total electron content, constructed two ways from published specifications |
| Primary analysis | M ≥ 4.0 |
| S1, secondary | M ≥ 4.5, robustness check against the JMA magnitude-scale transition, subordinate to the primary with that ordering fixed in advance |
| S2, negative control | The identical comparison with the predictor built from a time-shifted field, so a positive information gain can be distinguished from a pipeline artifact |
| Scoring | Information gain per earthquake over the benchmark, with a 95 percent interval, plus the CSEP N, S, M and L consistency tests |
| Evaluation mode | Pseudo-prospective. Forecasts for each bin use only information available before that bin |
| Declustering | None. Fixed in advance |

Four specifications are deliberately deferred to registration amendments, each to be filed
before the work it governs begins:

1. ETAS parameterization and smoothing kernel, before any fitting
2. TEC predictor construction, shell height and elevation cutoff, before building
3. GEONET station subset size, spatial criterion and selection method, before bulk retrieval
4. The S2 time-shift interval, with the predictor amendment

None of the four has been filed. No work they govern has begun.

---

## What Block 1 established

**Target catalog.** 2,161,892 raw JMA Seismological Bulletin records for 2016 to 2023,
every one accounted for by one of nine pre-registered selection rules, with zero parse
failures and zero event-identity collisions, yielding **4,442 target events** at M ≥ 4.0
and 1,679 at M ≥ 4.5. Per-rule attrition is recorded in
`data/jma_catalog/jma_attrition.md`.

**Magnitude completeness.** Estimated on three catalog subsets with three estimators from
SeismoStats 1.0.1, pinned, under a protocol locked six days before any estimate existed.
Gate values: 3.7 for the whole region, 3.6 as the annual maximum, 3.9 at the highest
assessed spatial node, 3.7 as the moving-window maximum. **Nothing reaches 4.0**, which
places the result in the middle band of the protocol's pre-specified outcome table: the
M4.0 threshold is defensible, the margin is thin, and the thinness is reported as a
limitation with added weight given to the S1 secondary analysis.

**Benchmark b-value.** 0.880043 ± 0.009397 above Mc 3.7 on 8,298 events, consistent to
within 1.7 percent with the independently built target catalog.

**Known limitations, recorded rather than resolved.**

- 71.1 percent of spatial grid nodes could not be assessed for completeness, concentrated
  offshore where published completeness is worst. The highest *assessed* node of 3.9 is
  therefore not the highest node.
- The lowest magnitude bin of the target catalog is depleted by 22.5 percent relative to
  the Gutenberg-Richter trend from the bins below it. Of that, 12.2 points are intrinsic
  to the raw bulletin and the remaining 10.3 points arise from this study's own registered
  region and depth filters. See `docs/D9_FINDINGS_CORRECTION_2026-11-23.md`.
- Target event counts are not counts of independent events, since the design does not
  decluster. April 2016 holds 3.75 times the monthly median on the M7.0 Kumamoto sequence.

---

## The registration ledger

Every rule, specification and analysis plan in this project is locked by commit before the
data or code it governs. `docs/registration_ledger.md` is an append-only record with one
row per locking commit: UTC timestamp, commit hash, file path, SHA-256 of the file
contents, what it locks, its external anchor, and notes. Rows are added and never edited.

**Anyone can verify every row** from a clone, with no trust in the maintainer required:

```bash
git clone https://github.com/synexisproject-bit/project-sentinel
cd project-sentinel
while IFS='|' read -r _ row ts commit path claimed rest; do
  c=$(echo "$commit" | tr -d ' `'); p=$(echo "$path" | tr -d ' `')
  cl=$(echo "$claimed" | tr -d ' `'); [ -z "$c" ] && continue
  a=$(git show "$c:$p" 2>/dev/null | sha256sum | cut -d' ' -f1)
  [ "$a" = "$cl" ] && echo "row ${row// /} OK" || echo "row ${row// /} MISMATCH $p"
done < <(grep '^| [0-9]' docs/registration_ledger.md)
```

The ledger includes its own corrections. Row 18 records a finding about the catalog;
row 19, filed three days later, records that the mechanism claimed in row 18 was wrong,
identifies the real cause, and leaves row 18 intact so a reader can see what was believed
when. Row 21 records that a gate carrying a hard consequence was registered without a
numeric threshold, which is a defect in the gate definition rather than in the work.

---

## Block 1 files

Code:

| File | Purpose |
|---|---|
| `build_japan_region.py`, `csep_japan_region.py` | Region ingest and lattice handling |
| `build_jma_catalog.py` | The catalog builder. Implements the nine registered rules in registered order with per-rule attrition |
| `estimate_mc_d9.py` | Magnitude completeness under the locked protocol. All estimators from SeismoStats, nothing hand-implemented |
| `count_target_events.py` | The D10 target event count record |
| `diagnose_m40_step.py` | Diagnostic isolating which registered rule produces the M4.0 deficit |
| `sentinel_audit.sh` | Infrastructure and cost audit, run at the start and end of every milestone |

Registered documents, in `docs/`:

| File | Purpose |
|---|---|
| `BLOCK1_publication_target_and_region_selection_2026-11-09.docx` | Publication target, region selection record, gate register |
| `BLOCK1_ADDENDUM_testing_class_and_threshold_2026-10-19.docx` | Testing class and magnitude threshold |
| `ADDENDUM_CORRECTION_2026-11-09.md` | Dated correction to the above |
| `BLOCK1_ADDENDUM1_mc_protocol_2026-11-14.docx` | The completeness protocol, including the outcome table fixed before any estimate existed |
| `D9_FINDINGS_NOTE_2026-11-20.md` | Two post-hoc findings |
| `D9_FINDINGS_CORRECTION_2026-11-23.md` | Correction to the above |
| `D10_GATE_CLOSURE_2026-11-24.md` | Target event count gate closure |
| `registration_ledger.md` | The append-only locking record |

Data, with provenance and terms in [`NOTICE`](NOTICE):

| Path | Content |
|---|---|
| `data/csep_japan/japan.forecast.nodes` | Region definition, supplied by the testing centre |
| `data/jma_catalog/` | Derived catalog products and manifests. **Edited derivatives of the JMA bulletin, not the bulletin itself** |
| `data/d9/` | Completeness results |

---

## Reproducing Block 1

Python 3.11 or later.

`build_jma_catalog.py`, `count_target_events.py` and `diagnose_m40_step.py` use only the
standard library. `estimate_mc_d9.py` additionally requires the packages in
`requirements_block1.txt`, where SeismoStats is pinned to the registered version.

```bash
pip install -r requirements_block1.txt
```

The raw JMA archives are not redistributed here. Obtain them from JMA and confirm they
match the inputs used:

```bash
sha256sum -c data/jma_catalog/sha256_raw.txt
```

Then:

```bash
# target catalog
python3 build_jma_catalog.py --zips data/jma_catalog \
    --region data/csep_japan/japan.forecast.nodes

# target event count, the D10 gate record
python3 count_target_events.py \
    --catalog data/jma_catalog/jma_target_catalog.csv \
    --out /tmp/d10_check.json
```

`estimate_mc_d9.py` runs against a larger working catalog built at a lower magnitude
threshold, which exceeds GitHub's file size limit and is therefore stored outside the
repository. Its location and SHA-256 are in
`data/jma_catalog/jma_mc_working_location.txt`, and the script verifies that hash and
refuses to run on any other catalog.

---

## Earlier work in this repository

Project Sentinel ran four earlier phases before this rebuild, across six hazard types and
several data streams including a collective dream and anomalous-experience corpus. That
code is still here, under `fusion_agents/`, `h1_*` through `h6_*`, `hac_*` and related
paths. It is retained for completeness of the record.

Readers should know three things about it.

**Most of it returned null.** H1 walk-forward, H2 displacement, H2 strain, H3 TEC and H4
convergence all returned null against their pre-registered criteria, and are published as
such rather than withdrawn.

**Two streams met their pre-registered significance criteria**, in analyses of an
anomalous-experience corpus. Those findings are population-level aggregate statistics, not
individual prediction, they have not been externally replicated, and they are not
published in a peer-reviewed venue. They are not evidence for anything in the current
rebuild and they play no part in it.

**The rebuild exists because the earlier evaluations were not scored against a published
forecasting benchmark.** They used AUROC against an internal seismic-only baseline, with
no calibrated probabilities and no information-gain scoring. That is why this work starts
again from a region definition and a catalog rather than building on those results.

The region was selected on event rate, instrumentation density and the existence of
external benchmark precedent. The selection record in
`docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx` states explicitly
that it is independent of prior Sentinel outcome results, and records a correction to an
earlier version of that claim that had overstated it.

---

## Citation

Archived on Zenodo. Two DOIs exist and they are not interchangeable:

| DOI | What it points at | Use it for |
|---|---|---|
| [10.5281/zenodo.24507347](https://doi.org/10.5281/zenodo.24507347) | All versions, always resolving to the newest | Citing this work in general, in a manuscript or a reference list |
| [10.5281/zenodo.24507348](https://doi.org/10.5281/zenodo.24507348) | `v0.1.0` specifically, frozen | Reproducing or checking a claim against the exact archive it was made from |

Structured metadata is in [`CITATION.cff`](CITATION.cff). If you use the derived catalog,
please also cite the JMA Seismological Bulletin as its source and note that the files here
are edited derivatives, as set out in [`NOTICE`](NOTICE).

## Licence

Source code and Synexis-authored documents: Apache License 2.0, see [`LICENSE`](LICENSE).

Third-party data redistributed here is **not** covered by that licence and remains under
its providers' terms. See [`NOTICE`](NOTICE) before reusing any file under `data/` or
`de421.bsp`.

## Contact

The Synexis Project, https://synexisproject.org
