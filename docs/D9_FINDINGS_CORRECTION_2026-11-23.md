# Correction to the D9 findings note: the M4.0 deficit was misattributed

**Target document:** `docs/D9_FINDINGS_NOTE_2026-11-20.md`
**Target commit:** `c2c5245`, ledger row 18
**Note filed:** 2026-11-23
**Status of the target:** committed and hashed in the ledger. Not edited.
**Diagnostic:** `diagnose_m40_step.py`, output at `docs/m40_step_diagnostic.json`

---

## What this corrects

Section 3 of the findings note reported an isolated 20 percent deficit in the M4.0
magnitude bin of subset P and attributed it to the JMA velocity-to-displacement
magnitude changeover, operating through registered rule 8.

**The attribution was wrong.** Rule 8 contributes nothing to the deficit. It never moved
a single event between magnitude bins and never excluded one from either the M3.9 or the
M4.0 bin. The amplification comes from rule 4, the region filter, with a smaller
contribution from rule 5, the depth filter.

The note also presented the mechanism as understood. It is not. Even the portion present
in the raw bulletin is only partly accounted for.

---

## How this was established

`diagnose_m40_step.py` applies the nine registered rules cumulatively, in the registered
order, and recomputes the M3.9 to M4.0 step after each. It imports `parse_record`,
`select_jma_magnitude`, `load_region_cells` and `cell_key` from the committed
`build_jma_catalog.py` rather than reimplementing them, so the decomposition cannot
diverge from the pipeline it explains.

The diagnostic was validated against two controls before being run on real data. In the
first, half the M4.0 bin was given a non-JMA first magnitude type with no usable second
magnitude; the ratios held at 0.999 through rule 7 and dropped to 0.498 at rule 8, and
the cross-tabulation named the cause. In the second, half the M4.0 bin was given a depth
of 150 km instead; the drop moved to rule 5 and rule 8 stayed clean. So the diagnostic
identifies the responsible rule rather than confirming a prior suspicion.

**Definitions.** `step@4.0` is the observed M4.0 count divided by the count projected
from the M3.9 bin at b = 0.88. `neighbour median` is the median of the same ratio across
every other bin from M3.3 to M4.5, so it captures what the rest of the distribution is
doing. `relative shortfall` is one minus the ratio of those two, and is the figure
quoted below.

---

## Stage-by-stage attribution

| Stage | Rule added | n(3.9) | n(4.0) | step@4.0 | neighbour median | relative shortfall | change |
|---|---|---|---|---|---|---|---|
| A | none, parsed only | 2,037 | 1,526 | 0.917 | 1.045 | **12.2%** | baseline |
| B | rule 3, time window | 2,036 | 1,525 | 0.917 | 1.045 | 12.2% | +0.0 pp |
| C | rule 4, region | 1,220 | 818 | 0.821 | 1.032 | **20.4%** | **+8.2 pp** |
| D | rule 5, depth ≤ 100 km | 1,121 | 731 | 0.799 | 1.031 | **22.5%** | **+2.1 pp** |
| E | rule 6, event type | 1,121 | 731 | 0.799 | 1.031 | 22.5% | +0.0 pp |
| F | rule 7, solution quality | 1,121 | 731 | 0.799 | 1.031 | 22.5% | +0.0 pp |
| G | rule 8, magnitude scale | 1,121 | 731 | 0.799 | 1.031 | 22.5% | **+0.0 pp** |
| H | subset P restriction | 1,121 | 731 | 0.799 | 1.031 | 22.5% | +0.0 pp |

**Attribution.** Of the 22.5 percent relative shortfall in subset P: **12.2 points are
present in the raw bulletin before any rule is applied**, 8.2 points are added by the
region filter, and 2.1 points by the depth filter. Rules 3, 6, 7, 8 and the subset
restriction add nothing.

---

## Rule 8 does nothing here, and the note said it did

The diagnostic reports, verbatim: *"none: rule 8 never changed an event's magnitude
bin."* The cross-tabulation at the stage immediately before rule 8 confirms it for both
bins.

| Bin | first magnitude types present | rule 8 outcome |
|---|---|---|
| M3.9 | V 811, D 309, v 1 | kept in bin: V 811, D 309, v 1. None moved, none excluded. |
| M4.0 | D 435, V 296 | kept in bin: D 435, V 296. None moved, none excluded. |

The reason is straightforward in hindsight. Rule 8 accepts V, v, D and d equally. Both
the velocity and the displacement scale are JMA scales, so a changeover between them
passes rule 8 untouched. The note's proposed mechanism required rule 8 to treat them
differently, and it does not.

**The magnitude-scale changeover itself is confirmed.** The displacement share runs 27.6
percent at M3.9 (309 of 1,121) and 59.5 percent at M4.0 (435 of 731), matching the
figures in the findings note exactly. The changeover is real, it is at M4.0, and it is
not the route by which the registered rules amplify the deficit.

---

## How much of the raw deficit the scale changeover explains

The Block 1 Addendum measured the velocity and displacement scales as offset by about
0.020 magnitude units in the MV 4.x bin. Magnitudes are reported on a 0.1 grid, so a
systematic shift of that size moves roughly 0.020 / 0.1 = 20 percent of a bin's events
across its lower boundary, applied to whatever share of the bin uses the shifted scale.

Modelling that, with each bin losing `MD_share × 0.20` of its events to the bin below
and gaining the corresponding share from the bin above:

| Bin | displacement share | fraction displaced down |
|---|---|---|
| M3.8 | 18.8% | 3.8% |
| M3.9 | 27.6% | 5.5% |
| M4.0 | 59.5% | 11.9% |
| M4.1 | 65.4% | 13.1% |

| | value |
|---|---|
| step@4.0 predicted from the offset alone | 0.948 |
| step@4.0 observed in the raw bulletin | 0.917 |
| unexplained residual | −0.031 |
| **share of the raw shortfall explained** | **about 63 percent** |

So the scale changeover with the measured offset accounts for roughly two thirds of the
12.2 percent raw deficit under a simple uniform-shift model. It is a plausible principal
cause and not a complete one. The model is crude: it assumes events are uniformly
distributed within each 0.1 bin and that the offset is a constant 0.020, where the
addendum measured 0.020 in the MV 4.x bin against +0.038 across all 463 paired events.

---

## What remains unexplained

Two things, stated as open rather than resolved.

**Why the region filter concentrates its effect at M4.0.** Rule 4 removes 40.1 percent
of the M3.9 bin and 46.4 percent of the M4.0 bin, 6.3 percentage points more at M4.0.
Events outside the CSEP-Japan region are predominantly distant, and distant events are
on average larger, so some magnitude-dependent removal is expected. That would steepen
the whole distribution, and it does: the neighbour median falls from 1.045 to 1.032. But
the M4.0 step falls much further, from 0.917 to 0.821, so the region filter depletes that
bin specifically, beyond its general effect. No mechanism for that is established here.

**The remaining 37 percent of the raw deficit.** The offset model leaves a residual of
−0.031 in the step ratio unaccounted for.

Neither affects any registered decision. Both are recorded so that the writeup describes
a partially understood effect as partially understood.

---

## What this changes

| Claim in the findings note | Status |
|---|---|
| An isolated deficit exists at exactly M4.0 | **Stands.** Confirmed in the raw bulletin and at every filtering stage. |
| The displacement share jumps from 27.6 to 59.5 percent in the same bin | **Stands.** Reproduced exactly. |
| The deficit in subset P is about 20 percent | **Revised to 22.5 percent** by the stricter definition used here. |
| The deficit is a property of the JMA catalog that any CSEP-Japan participant inherits | **Revised.** 12.2 points are intrinsic to the bulletin. The remaining 10.3 points arise from this study's registered region and depth filters, which another participant need not share. |
| The scale changeover is the cause | **Revised.** It is the plausible principal cause of the intrinsic 12.2 points, explaining about two thirds of them. It is not the cause of the amplification. |
| Rule 8 is the route by which it operates | **Withdrawn.** Rule 8 contributes nothing and moves no events. |
| The E1 and E2 Mc values of 3.7 are most likely detecting this step | **Unchanged in substance, weaker in support.** The step is real and in the right place, but the step the estimators see in subset P is now known to be substantially of this study's own making, which makes the inference less clean rather than more. |
| The lowest bin of the target catalog is depleted and carries the most weight in the N-test and M-test | **Stands, and is the figure that matters.** The evaluation runs on the filtered catalog, where the shortfall is 22.5 percent. |

---

## What is unchanged

Nothing in the registered protocol. The threshold stays at M ≥ 4.0, the testing class,
window, nine filtering rules and no-declustering decision stand as registered, the target
catalog is unchanged at 4,442 events, and the M4.0 primary with S1 subordinate ordering
is not reordered.

The D9 gate outcome is unchanged: the middle band of section 7 of the amendment,
threshold defensible, margin thin, reported as a limitation.

---

## Consequence for the enquiry to the CSEP-Japan testing centre

The draft enquiry stated that the M4.0 bin holds about 20 percent fewer events than the
trend predicts. **That figure is wrong for the purpose, because the question concerns
JMA's catalog and most of the 20 percent is this study's own filtering.** The correct
figure to put to the testing centre is the raw one, about 12 percent, and the enquiry is
revised accordingly before being sent.

---

## Why this is a note and not an edit

The findings note is committed at `c2c5245` and hashed at ledger row 18. Editing it would
break that hash and remove the record of what was claimed on 2026-11-20. The error and
its correction both carry timestamps instead, three days apart, and a reader can see
exactly what was believed when.

The error was found because the note made a specific, checkable numerical claim with a
named mechanism. A note saying only that a deficit was observed near M4.0 would have
passed unexamined into the manuscript.

## Verification

```bash
cd ~/project-sentinel
python3 diagnose_m40_step.py \
    --zips data/jma_catalog \
    --region data/csep_japan/japan.forecast.nodes \
    --out /tmp/check.json
python3 -c "import json; d=json.load(open('docs/m40_step_diagnostic.json'))['stages']; \
[print(k, v['step_relative_to_neighbours']) for k,v in d.items()]"
```
