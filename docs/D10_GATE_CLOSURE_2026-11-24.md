# D10 gate closure: target event count

**Gate:** D10, Block 1 gate register
**Source document:** `docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx`, ledger row 7
**Closed:** 2026-11-24
**Decision:** PASS. The hard consequence is not triggered.
**Evidence:** `count_target_events.py`, output at `docs/d10_target_counts.json`

---

## The registered gate

> **D10** Target event count computed. **HARD GATE: if too low, the region decision reopens.**
> Status at registration: OPEN. Blocked on D9.

The criterion it serves is the first of the five region-selection criteria in Part B of the
same document:

> Target event count sufficient to distinguish a result, positive or null

and the justification recorded there:

> On criterion 1, Japan produces the highest rate of target-magnitude events of any
> candidate considered, which directly determines whether the evaluation has the power to
> distinguish benchmark-plus-TEC from benchmark alone.

---

## First finding: no numeric threshold was registered

**"Too low" is never quantified.** Not in the gate register, not in Part B, not in the
Block 1 Addendum, not in the Addendum Correction. The gate carries a hard consequence,
reopening the region decision, with no number attached to it.

This is stated first because the same document is explicit about the failure mode it
creates:

> The evaluation window, the testing class and the magnitude threshold jointly determine
> which earthquakes count as target events. Deciding any of them after inspecting event
> counts would be selection on the outcome, however reasonable the resulting choice.

A gate whose pass condition is decided after seeing the count is the same error in a
different place. The closure below is therefore constructed so that the judgment rests on
an external, published comparison rather than on an impression formed after looking at the
number, and the post-hoc character of the judgment is recorded rather than hidden.

---

## The counts

| Analysis | Threshold | N | Per year |
|---|---|---|---|
| **Primary** | M ≥ 4.0 | **4,442** | 555.2 |
| **S1 secondary** | M ≥ 4.5 | **1,679** | 209.9 |

S1 is included because it is a registered secondary analysis with its own power question,
and the gate wording mentions only one count. A gate assessed on the primary alone would
leave S1 unassessed.

Context, not registered analyses:

| Threshold | N |
|---|---|
| M ≥ 5.0 | 579 |
| M ≥ 5.5 | 202 |
| M ≥ 6.0 | 64 |
| M ≥ 6.5 | 16 |

By year:

| Year | N | | Year | N |
|---|---|---|---|---|
| 2016 | 769 | | 2020 | 518 |
| 2017 | 459 | | 2021 | 579 |
| 2018 | 560 | | 2022 | 616 |
| 2019 | 459 | | 2023 | 482 |

Every year in the registered window is populated. The thinnest year holds 459 target
events, which is itself four times the published anchor below.

---

## Chain of custody

The count was computed from `data/jma_catalog/jma_target_catalog.csv`, which hashes to
`148a16a8f88454a8575d0e09b1d36f1076d5ab8bc0f184ae4fec315f48d3fcc1`.

That value appears in the committed `data/jma_catalog/jma_catalog_manifest.json` at
`outputs/jma_target_catalog.csv`, and that manifest is hashed at **ledger row 10**. So the
count runs on the catalog the manifest attests to, and the manifest predates this gate by
eleven days.

---

## Second finding: the published comparative anchor

Tsuruoka, Hirata and Tsuruoka (2012), *CSEP Testing Center and the first results of the
earthquake forecast testing experiment in Japan*, Earth Planets Space 64,
doi:10.5047/eps.2012.06.007.

That paper reports the first results of the CSEP-Japan experiment. For the All Japan
region, 3-month class, over 1 November 2009 to 31 January 2010, it evaluated submitted
models against **115 target earthquakes of M ≥ 4**, and applied the CSEP consistency tests
plus the comparative T and W tests to that set.

The comparison is direct rather than analogous:

| | This study | Tsuruoka et al. 2012 |
|---|---|---|
| Region | CSEP-Japan All Japan | CSEP-Japan All Japan |
| Threshold band | 4.0 ≤ M ≤ 9.0 | 4.0 ≤ M ≤ 9.0 |
| Target events | 4,442 | 115 |
| Comparative tests applied | planned | applied and reported |

| Ratio | Value |
|---|---|
| primary / anchor | **38.6×** |
| S1 / anchor | **14.6×** |

**An independent cross-check falls out of this.** The anchor's 115 events in one quarter
implies about 460 target events per year. This study measures 555 per year, with a
year-to-year range of 459 to 769. The anchor's implied rate sits inside this study's
observed range. Two catalogs built eighteen years apart by different people from the same
bulletin, on the same region at the same threshold, agree on the rate. That is weak
evidence, and it is evidence pointing the right way, and it was not constructed for this
purpose.

---

## Precision scaling

The CSEP comparative T-test statistic is

```
Theta = sqrt(N_T) * IGPE / s
```

so the width of any interval on the information gain per earthquake scales as
`1 / sqrt(N_T)`. The count enters only through its square root.

| | Precision relative to the anchor |
|---|---|
| primary, N = 4,442 | **6.21×** tighter |
| S1, N = 1,679 | **3.82×** tighter |

**No absolute interval width is stated here, deliberately.** The constant depends on the
variance of the score differences between the benchmark and the benchmark-plus-predictor
forecast. Neither forecast exists yet, so that variance does not exist yet. Any number
quoted for the achievable interval width today would be an invention. Only the scaling is
used, and the scaling is enough for this gate.

---

## Third finding: the counts are not counts of independent events

The registered design does not decluster. That decision stands. It does mean the figures
above overstate the independent information in the sample, and the gate record should say
so rather than let a reader assume 4,442 independent observations.

Concentration, with no declustering applied and no model assumed:

| Month | N | Times the monthly median of 40 |
|---|---|---|
| 2016-04 | 148 | 3.75× |
| 2016-11 | 148 | 3.75× |
| 2022-03 | 126 | 3.19× |
| 2020-06 | 119 | 3.01× |

April 2016 is identified: 112 of its 148 events are in Kumamoto prefecture, 72 of them in
NW Kumamoto. That is the M7.0 Kumamoto sequence.

The effective number of independent events is therefore materially below 4,442, by an
amount this note does not estimate, because estimating it requires a declustering choice
that is not registered and that the design deliberately avoids. The gate is assessed on
the registered count. The clustering is recorded as a limitation bearing on realized
power, to be carried into the evaluation writeup.

Note that the same caveat applies with equal force to the published anchor, whose 115
events fall in a single quarter and are not declustered either. The 38.6× ratio is
therefore a comparison of like with like.

---

## Gate decision

**D10: PASS. The hard consequence is not triggered. The region decision does not reopen.**

The basis, stated so a reader can disagree with it:

1. The primary analysis has 4,442 target events and the registered S1 secondary has 1,679.
2. The published CSEP-Japan evaluation on the same region at the same threshold band
   reached and reported comparative T-test and W-test conclusions on 115.
3. Interval width scales as `1/sqrt(N_T)`, so this study's counts deliver 6.21× and 3.82×
   the precision of that published evaluation.
4. No plausible pre-specified threshold would have failed this count. A threshold that
   failed 4,442 target events would also have failed the first published CSEP-Japan
   comparative evaluation, and every CSEP-Japan evaluation reported since at that
   threshold.

**The post-hoc character of this judgment is recorded, not waived.** No numeric threshold
existed to be met. Point 4 is the argument that the absence cannot have changed the
outcome, and it is checkable: anyone who thinks the gate should have failed has to name a
threshold between 115 and 4,442 and defend it against the published record.

What would have changed the decision: a count near or below the anchor, a year with no
target events, or an S1 count small enough that the secondary analysis could not be run at
all. None of these obtains.

---

## Registration defect recorded

**D10 as written has a hard consequence and no quantitative criterion.** That is a defect
in the gate definition rather than in the work, and it is recorded here so it is visible
in the record rather than discovered by a reviewer.

The practice this implies for the remaining gates: any gate whose failure has a stated
consequence should carry a number, fixed before the quantity is computed. The four
amendments still owed, on ETAS parameterization, TEC predictor construction, the GEONET
station subset and the S2 time-shift interval, are the next opportunity to apply that, and
each should state its own pass condition numerically where one is meaningful.

---

## A separate finding, for the evaluation amendment rather than for this gate

While sourcing the precision scaling above, a methodological critique of the CSEP T-test
surfaced that bears on Block 4 and should be read before the evaluation method is locked.

The preprint *Enhancing the statistical evaluation of earthquake forecasts: an application
to Italy*, arXiv:2405.10712, argues that the CSEP T-test's standardization is incorrect:
that its variance estimate uses only bins with positive counts when it should use all
forecast bins, that it ignores spatio-temporal dependence, and that in simulation the
resulting p-value is not uniform under the null. The figure reported is a rejection rate of
46.5 percent against a nominal 10 percent across 400 replicates. The paper recommends
working with score differences and a Diebold-Mariano test in place of the CSEP T-test.

**Provenance, stated plainly: this has not been read.** The above comes from a summary of a
fetched copy, not from reading the paper, and the paper is a preprint. It is recorded here
as a thing to verify, not as an established result, and it changes nothing in this gate,
which rests on count scaling that holds under any of these standardizations.

If it holds up, it matters a great deal, because the registered design scores information
gain per earthquake with a 95 percent interval. The right time to settle it is before the
evaluation amendment, not after a result exists. Added to the Block 2 handoff.

---

## What is unchanged

Nothing in the registered protocol. The region, the testing class, the M4.0 primary
threshold, the M4.5 S1 secondary, the S2 negative control, the 2016 to 2023 window, the
nine filtering rules, the no-declustering decision and the target catalog of 4,442 events
all stand as registered.

---

## Verification

```bash
cd ~/project-sentinel
python3 count_target_events.py \
    --catalog data/jma_catalog/jma_target_catalog.csv \
    --out /tmp/d10_check.json

# the catalog this ran on is the one ledger row 10's manifest attests to
sha256sum data/jma_catalog/jma_target_catalog.csv
python3 -c "import json; print(json.load(open('data/jma_catalog/jma_catalog_manifest.json'))['outputs']['jma_target_catalog.csv'])"
```

Both commands print `148a16a8f88454a8575d0e09b1d36f1076d5ab8bc0f184ae4fec315f48d3fcc1`.
