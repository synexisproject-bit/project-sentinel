# D11 gate closure: Zenodo archive and DOI

**Gate:** D11, Block 1 gate register
**Source document:** `docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx`, ledger row 7
**Closed:** 2026-11-24
**Decision:** PASS. All three conditions met.

**This gate closes Block 1.**

---

## The registered gate

> **D11** Zenodo-GitHub integration wired, v0.1.0 tagged, DOI confirmed to mint.
> Status at registration: OPEN.

Three conditions, all three met, each verifiable independently of this note.

---

## The two DOIs

Zenodo mints two identifiers for an archived repository and they are not
interchangeable. Conflating them is the most common way a citation in a manuscript
silently stops meaning what its author intended.

| DOI | Resolves to | Use |
|---|---|---|
| **10.5281/zenodo.24507347** | All versions. Always the most recent | The manuscript, reference lists, correspondence, the project website |
| **10.5281/zenodo.24507348** | `v0.1.0` specifically. Frozen | Reproducing or checking a claim against the exact archive it was made from |

**Ledger row 22 records the version DOI**, `10.5281/zenodo.24507348`, because the ledger
locks specific artifacts. A row pointing at the concept DOI would claim to lock something
while actually pointing at whatever is newest, which is the opposite of what a ledger row
is for.

Record published 2026-11-24, version label `v0.1.0`.

---

## What was done, and the one ordering constraint that mattered

| Step | Evidence |
|---|---|
| 1. Archive content prepared | Commit `256d9cf`: LICENSE, NOTICE, CITATION.cff, .zenodo.json, requirements_block1.txt, docs/block1_environment.txt, README replaced, 33 junk files removed |
| 2. Zenodo-GitHub integration enabled | Toggle switched on for `synexisproject-bit/project-sentinel` **before** any release existed |
| 3. Annotated tag created and pushed | `v0.1.0` at `256d9cf`, tagged 2026-11-24T16:31:24Z, 48-line message |
| 4. GitHub release published | Release id `457038892`, published 2026-11-24T16:32:29Z, `draft=false` |
| 5. DOIs minted | Concept `10.5281/zenodo.24507347`, version `10.5281/zenodo.24507348` |

**Steps 2 and 4 had to happen in that order.** Zenodo archives releases published after the
repository is switched on and is blind to any release that predates it. A release created
first is not archived, produces no DOI, and the only recovery is to delete both the release
and the tag and redo them. The toggle went on at approximately 16:27Z and the release
published at 16:32:29Z, five minutes later, so the ordering held.

The tag is annotated rather than lightweight, so it carries a signed-off message object in
git recording what the release contains, rather than being a bare pointer.

---

## What is in the archive

244 files at `v0.1.0`, down from 277 before the preparation commit removed 33 editor
backups, `__pycache__` artifacts and a stray 868 KB IGS IONEX test file. The diff was 780
insertions against 19,686 deletions, so close to twenty thousand lines of build detritus
are absent from a permanent citable record.

`docs/registration_ledger.md` carries **21 rows at this tag**, each with a SHA-256 of the
file it locks. Every row reproduces from the committed git object.

**Archive scope, decided deliberately.** The archive contains the whole repository,
including earlier exploratory work predating this rebuild, among it anomalous-cognition
and RNG streams. Curating that out was considered and rejected. The work is already public
in this repository, on OSF, in the project's canonical public description and in a
conference talk, so removing it from the archive alone would create an inconsistency
between the archive and everything else, and that inconsistency is what would read as
concealment. `README.md` declares it instead, names the streams in the status table rather
than euphemising them, and states that those predictors enter only at Block 3 behind a
benchmark that must first validate, scored by the same metric as every other candidate.

Whether the evaluation should later live in a repository of its own, for modularity rather
than concealment, is carried to the Block 2 handoff as an open decision.

---

## Third-party data in a permanent public archive

A Zenodo record is a formal, citable redistribution, which is a different act from having
a file in a repository. Three providers were considered before tagging.

**JMA.** Checked rather than assumed. JMA provides its content under the Public Data
License version 1.0, which JMA states is compatible with CC BY 4.0, requiring the source to
be cited and, where content has been edited, a statement to that effect. `NOTICE` carries
an explicit statement of editing: that these files are not the JMA Seismological Bulletin,
must not be cited as it, and were produced by applying the nine registered rules. The raw
archives are not redistributed; only their SHA-256 values are recorded, so a reader who
obtains the bulletin from JMA can confirm the inputs match.

**The CSEP-Japan region file.** Supplied directly by the testing centre at the Earthquake
Research Institute, University of Tokyo, and public in this repository since ledger row 2.
Retained in the archive, because removing it would break the chain at row 2 and make the
region unverifiable from the archive, which is the reason it is committed at all. `NOTICE`
attributes it fully and states that no review, endorsement or association by the testing
centre or anyone affiliated with it is implied, and that correspondence has been limited to
factual questions. A courtesy notification that the file is archived and credited is owed
in the next exchange with the testing centre; it is a notification rather than a permission
request, and it is deliberately not a separate email.

**GEONET and JPL DE421.** Both documented in `NOTICE`. No GEONET observation data is
redistributed, only a station roster derived from published station information. Recording
the GEONET DOI that publications are required to cite remains an open gate item.

---

## What this gate does not establish

D11 is an archiving and identifier gate. It makes Block 1 citable and frozen. It says
nothing about whether the science in it is correct, and nothing in the archive should be
read as a result. The archived release states this in its own first paragraph.

---

## Block 1 closure

With D11 closed, Block 1 is complete.

| Gate | Outcome |
|---|---|
| Region geometry locked | CSEP-Japan All Japan, 20,062 cells, adopted unmodified |
| Testing class and threshold locked | M4.0 primary, M4.5 S1 secondary, S2 time-shifted control |
| Catalog acquired with hash record | Eight yearly archives, SHA-256 manifest |
| D8 catalog built | 4,442 target events from 2,161,892 records, zero parse failures |
| D9 completeness | Gate 3.7, nothing reaches 4.0, middle band of the pre-specified outcome table |
| D10 target event count | PASS, 4,442 primary and 1,679 S1, hard consequence not triggered |
| D11 archive and DOI | PASS, this note |

**Carried forward to Block 2, unresolved and recorded as such:**

1. Four registration amendments owed before the work each governs: ETAS parameterization
   and smoothing kernel; TEC predictor construction with shell height and elevation cutoff;
   the GEONET station subset rule; the S2 time-shift interval.
2. Which cut-off the benchmark b-value should be fitted above, flagged in the D9 findings
   note.
3. arXiv:2405.10712, which argues the CSEP T-test standardization over-rejects and
   recommends Diebold-Mariano on score differences. Not read, only a fetched summary, and a
   preprint. To be settled before the evaluation method is locked, since the registered
   design scores information gain per earthquake with a 95 percent interval.
4. Whether 71.1 percent of spatial nodes being unassessable changes anything about how the
   spatial component of the evaluation is reported.
5. Whether the evaluation should move to its own repository before submission.
6. Environment capture. `estimate_mc_d9.py` recorded its SeismoStats version into its
   results file at run time, which is why that version is attested while numpy, pandas and
   scipy are not. Block 2 scripts should capture the whole resolved environment the same
   way.
7. `sentinel_audit.sh` v1.2, to set gcloud prompts off inside the script rather than
   relying on an environment variable the operator has to remember.

---

## Verification

```bash
git clone https://github.com/synexisproject-bit/project-sentinel
cd project-sentinel

# the tag is annotated and points at the preparation commit
git cat-file -t v0.1.0          # tag
git rev-parse --short v0.1.0^{commit}   # 256d9cf

# the archive contents
git ls-tree -r --name-only v0.1.0 | wc -l    # 244
git show v0.1.0:docs/registration_ledger.md | grep -c '^| [0-9]'   # 21
```

Both DOIs resolve:

- https://doi.org/10.5281/zenodo.24507347 (all versions)
- https://doi.org/10.5281/zenodo.24507348 (v0.1.0)
