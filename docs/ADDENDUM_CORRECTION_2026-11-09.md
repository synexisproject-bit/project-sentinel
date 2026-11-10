# Correction note against the Block 1 Addendum

**Target document:** `docs/BLOCK1_ADDENDUM_testing_class_and_threshold_2026-10-19.docx`
**Target commit:** `3b4f784`
**Note filed:** 2026-11-09
**Status of the target:** frozen. Not edited, now or later.

---

## Why this note exists rather than an edit

The addendum pre-registers three decisions (D6 magnitude threshold, D7 testing
class, D12 evaluation window) and the nine catalog filtering rules. It was
committed before the catalog was built, which is the whole point of it: it fixes
those choices at a timestamp that precedes the data work they govern.

A pre-registration that is silently edited after the fact is worth nothing. So
the addendum stays exactly as committed at `3b4f784`, errors included, and
corrections are filed as separate dated notes like this one. A reviewer can
reconstruct what was claimed when, and what was later found to be wrong, from
the commit history alone.

---

## The correction

### What the addendum says

Section 6 of the addendum, in the discussion of the M4.5 alternative threshold,
describes M4.5 as a threshold at which

> 82 percent of events carry the displacement scale.

### What the measurement actually shows

The 82 percent figure is the displacement-magnitude (MD) share **within the M5
magnitude bin**, not the share at M4.5 and above.

| Bin | Events with displacement scale | Total events in bin | Share |
|---|---|---|---|
| M4 bin (4.0 ≤ M < 5.0) | 396 | 960 | 41 % |
| M5 bin (5.0 ≤ M < 6.0) | 117 | 142 | 82 % |

The share of events at **M ≥ 4.5** carrying the displacement scale was never
computed. It is bounded by the two figures above and is therefore somewhere
between 41 and 82 percent, but no measured value exists for it. The addendum's
sentence attaches the M5-bin figure to an M4.5 threshold, which is not what was
measured.

### What this does and does not affect

**Does not affect the registered design.** The threshold that was
pre-registered, and that the analysis will use, is **M ≥ 4.0**. The M4.5
discussion in section 6 is the rationale for *not* choosing M4.5 as the primary
threshold. The erroneous figure made the M4.5 option look cleaner than the
measurement supports, which if anything argued weakly *for* a threshold that was
not adopted. No downstream decision rests on it.

**Does not affect the scale-transition conclusion.** The substantive finding in
section 6 is that the MV-to-MD magnitude-scale transition is benign at the
threshold actually chosen, which rests on the paired-event offset, not on the
bin shares. That measurement is unaffected.

**Does affect how the M4.5 sensitivity analysis is described.** The registered
analysis plan carries S1, a full repeat of the evaluation at M ≥ 4.5 as a
robustness check. Any writeup of S1 must describe the scale composition at
M ≥ 4.5 from a measurement actually made, not from the addendum's sentence.

---

## Related correction, same review

A second figure was corrected in the same 2026-11-09 review and is recorded here
for completeness, since it also originates in the magnitude-scale work:

The **−0.020 magnitude offset** between the velocity and displacement scales
belongs to the **293 paired events in the MV 4.x bin**, not to all 463 paired
events. The mean offset across all 463 paired events is **+0.038**. Both figures
are small relative to the 0.1-magnitude bin width used by the CSEP 1-day testing
class, so the conclusion that the transition is benign at M ≥ 4.0 holds under
either figure. The registration carries the per-bin attribution.

---

## Authoritative wording

Where this note, the addendum and the registration disagree, the registration
governs:

**DOI 10.17605/OSF.IO/H5MD2** — filed and archived 2026-11-09, before any
catalog filtering, any magnitude-of-completeness estimate and any evaluation.
Component `osf.io/yfg8w` under project `osf.io/b3zah`.

The registration carries the precise wording for both figures above.

---

## Record of the chain

| Item | Reference |
|---|---|
| Addendum as committed, with the erroneous sentence | `3b4f784` |
| This correction note | commit of 2026-11-09 |
| Registration carrying the precise wording | 10.17605/OSF.IO/H5MD2 |
| Revised Block 1 recording the correction in its revision history | commit of 2026-11-09 |
