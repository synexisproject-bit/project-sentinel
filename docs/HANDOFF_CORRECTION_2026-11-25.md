# Correction and findings note: Block 2 handoff read against the registration

**Filed:** 2026-11-25 (UTC)
**Corrects:** `docs/BLOCK2_HANDOFF_2026-11-24.md`, ledger row 24, sha256
`ea01034236db5d9ba665383d010cc17b6db6278ce7fb2cf43fecc60587f53ac1`. That file is locked and
is not edited. This note records the correction and leaves the original visible.
**Sources read directly:** the registration text at osf.io/h5md2 (DOI 10.17605/OSF.IO/H5MD2),
and Part A of `docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx`, sha256
`69ca09ace5768599ee8111f2f1d9775a8afb868aa0ada7a9d8350e419660cbf9` as received (to be
checked against ledger row 7).
**Status:** written before any Block 2 analysis, fitting or amendment drafting.

---

## 1. Correction: what "Benchmark" means

**Handoff, section 4.1 item 1, states:** the registered results table "never states whether
the benchmark is ETAS, smoothed seismicity, or a combination."

**The registration states it is a combination.** Statistical models field: "Two components,
combined into a single benchmark: an epidemic-type aftershock sequence (ETAS) model, and a
smoothed-seismicity model." The Study design field repeats it: "The benchmark forecast
combines an epidemic-type aftershock sequence model with a smoothed-seismicity model." The
primary index and the inference criteria both compute information gain of benchmark-plus-TEC
relative to "benchmark alone."

**What is actually open** is narrower and still decisive for the headline number:

1. **The combination method is unspecified.** The registration fixes that the benchmark is a
   combination of the two components. It does not fix how they combine (for example ETAS
   using the smoothed-seismicity model as its background rate, or a weighted ensemble of two
   independent forecasts, with the weights fixed how).
2. **Part A's results table conflicts with the registration.** It has no row for the combined
   benchmark, and it marks smoothed seismicity as the "reference" in the information gain
   column. Under the registration the primary information gain is relative to the combined
   benchmark. The registration governs.

The ETAS amendment (handoff 4.1) must therefore fix the combination method, add the combined
benchmark as a row in the results table, and state that information gain in the smoothed
seismicity and ETAS rows is descriptive, with the primary comparison taken against the combined
benchmark.

**How the error arose:** the handoff was written from Part A's table and a recollection of the
registration. The registration was not reread. This is the failure mode recorded at ledger row
23, repeated once more.

---

## 2. Open issues found in the same reading, to be resolved by amendment

These are not errors in the handoff. They are discrepancies between registered documents,
recorded here with today's date so they are on the record before Block 2 work begins.

### 2.1 Learning period versus "no further catalog acquisition"

The registration states that both benchmark components use "only data preceding each forecast
bin," and separately that "No further catalog acquisition is planned; data collection for the
earthquake side is complete." The acquired catalog starts 2016-01-01, which is also the first
forecast day. As registered, forecasts early in the window would have little or no learning
data. Published CSEP-Japan models use learning periods of years to decades.

**Resolution owed in amendment 4.1 (handoff item 4):** fix the learning period. If it extends
before 2016, the amendment must explicitly supersede the "no further acquisition" statement,
give the reason, and be locked before any pre-2016 archive is retrieved. The pre-2016 catalog
also needs its own provenance hashes, the same filters with the evaluation-window filter
replaced by the learning-window filter, and a completeness assessment.

### 2.2 Two TEC specifications versus a single primary test

Part A's results table has two test rows, "Benchmark + TEC (spec 1)" and "(spec 2)". The
registration's inference criteria state that "Primary inference rests on a single test" and
apply no multiplicity correction on that basis.

**Resolution owed in amendment 4.3:** state which specification carries the primary inference
and which is secondary, or how the two combine into one predictor, or what multiplicity
correction applies. Fixed before either predictor is built.

### 2.3 The validation gate carries no numbers

The registered decision rule says the TEC comparison is not run "if the benchmark fails its
consistency tests or departs materially from published results for equivalent models."
Neither "fails" nor "materially" has a number. Process rule 4 (ledger row 21) requires one.

**Resolution owed in amendment 4.1:** the quantile thresholds that count as failing each of N,
S, M and L, which tests the gate applies to, and the numeric agreement criterion against the
named validation reference.

### 2.4 The comparative test is bound to the pyCSEP implementation

The registration makes "the comparative test as implemented in pyCSEP" the operative
definition of the primary index. The standardization question carried at handoff section 7.1
(arXiv:2405.10712) therefore cannot be settled by quietly changing method. Any alternative must
be filed by amendment before evaluation, and the registered pyCSEP result must still be
reported.

### 2.5 Minor: L-test column

Part A's results table has N, S and M test columns. The registration applies N, S, M and L. The
registration governs, and the L-test is reported.

---

## 3. Effect on Block 2

No locked decision changes. The ETAS amendment's list of items to fix (handoff 4.1) becomes:

1. The benchmark **combination method**, and the combined benchmark row in the results table
   (replaces handoff item 1)
2. The validation reference and **numeric** agreement criterion, plus numeric consistency-test
   gate thresholds (extends handoff item 2)
3. ETAS flavour (unchanged)
4. The auxiliary catalog and **learning period**, with explicit treatment of the registered "no
   further acquisition" statement (extends handoff item 4)
5. The completeness treatment (unchanged)
6. The smoothing kernel and bandwidth rule (unchanged)
7. The background rate method (unchanged)
8. Pinned versions, with the full resolved environment captured inside each results file at
   run time (unchanged)
