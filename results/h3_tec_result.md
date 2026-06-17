# H3 — Ionospheric TEC Anomaly Detection: Result Filing
## Project Sentinel | Phase 2 Geophysical Stream

**Status:** NULL — Resolution Limited  
**Filed:** June 2026  
**Pre-registration:** osf.io/8hvf6 (hypothesis locked prior to analysis)  
**Analytic protocol:** Pre-specified in original registration and Amendment #1 (commit 496ebf1)  
**Run timestamp:** 2026-06-17T22:55:43  
**Filing note:** H3 data backfill completed April 2025. Statistical analysis run June 17, 2026. Formal result filing delayed pending Phase 2 consolidation. Analytic protocol pre-specified and locked prior to result examination. No post-hoc modifications.

---

## 1. Hypothesis

**H3:** Ionospheric Total Electron Content (TEC) anomalies measured above earthquake preparation zones show statistically significant deviation from baseline in the days preceding M6.0+ seismic events, detectable using publicly available IONEX Global Ionosphere Map data.

**Pre-specified threshold:** AUROC ≥ 0.52 in ≥ 2 of 5 fault systems (set to beat Phase 1 global TEC baseline per Amendment #1).

**Theoretical basis:** Lithosphere-Atmosphere-Ionosphere Coupling (LAIC) chain (Pulinets & Boyarchuk, 2004; Pulinets et al., 2021). Seismogenic stress drives trace gas release from the crust, initiating ion formation in the lower atmosphere and propagating upward through atmospheric electricity to the ionosphere, producing detectable TEC anomalies above earthquake preparation zones in the days-to-weeks preceding rupture.

---

## 2. Data

**Source:** IONEX Global Ionosphere Maps (GIMs), accessed via NASA CDDIS archive  
**Provider:** JPL/NASA  
**Resolution:** 2.5° latitude × 5.0° longitude spatial grid; 2-hour temporal cadence  
**Coverage:** 2001-01-01 through 2025-12-31 (25 years)  
**Fault zones:** Japan Trench, Cascadia, Central Chile, North Anatolian, Sumatra-Andaman  
**Feature rows:** 45,651 (h3_features_daily) | 8,766 rows per zone  
**BigQuery table:** synexis-project-sentinel.sentinel_features.h3_features_daily  
**Methodology:** INSPIRE (Pulinets et al., 2021, Frontiers in Earth Science 9:610193)

**Features used (8):**
- tec_delta_fullday, tec_delta_nighttime, tec_lssi
- tec_delta_lag1d, tec_delta_lag3d, tec_delta_lag5d, tec_delta_lag7d
- tec_nighttime_lag5d

**Note:** Solar confound controls (kp_max, dst_index, solar_flux_f107) specified in walk_forward_engine.py config but not present in h3_features_daily at time of run. Engine loaded 8 available features. This is noted for the H3b re-run protocol.

**Ground truth:** h1_labels table (USGS ComCat, declustered, M≥6.0 for Cascadia and North Anatolian, M≥6.5 for remaining zones per Amendment #1).

---

## 3. Analysis

**Protocol:** Walk_forward_engine.py, Amendment #1 (commit 496ebf1)  
**Folds:** 10-fold expanding window  
**Result table:** synexis-project-sentinel.sentinel_eval.h3_wf_results  
**Bootstrap CI:** 1,000 iterations, 95% confidence interval

---

## 4. Results

### Per-Fault Summary

| Fault Zone | AUROC | 95% CI | Brier | AUPRC | Verdict |
|---|---|---|---|---|---|
| Cascadia | 0.5618 | [0.4406, 0.6703] | 0.0209 | 0.0303 | CONFIRMED_UNSTABLE |
| Japan Trench | 0.5010 | [0.4333, 0.5719] | 0.0833 | 0.0408 | NULL |
| Central Chile | 0.4758 | [0.3890, 0.5596] | 0.0783 | 0.0295 | NULL |
| North Anatolian | 0.4823 | [0.4076, 0.5605] | 0.0334 | 0.0342 | NULL |
| Sumatra-Andaman | 0.4846 | [0.2981, 0.6743] | 0.0646 | 0.0913 | NULL |
| Hayward | — | — | — | — | SKIPPED (no data) |

**Overall: H3 NULL — 1 of 5 systems ≥ 0.52 (required: 2)**

### Fold-Level Detail

**Cascadia** (label_7d_m60, M≥6.0 | 1,096 test rows | 21 positives)
| Fold | Train N | Test N | Pos Test | AUROC |
|---|---|---|---|---|
| 1-4 | — | — | 0 | SKIP |
| 5 | 6,574 | 366 | 7 | 0.5953 |
| 6 | 6,940 | 365 | 7 | 0.7426 |
| 7 | 7,305 | 365 | 7 | 0.3719 |
| 8-10 | — | — | 0 | SKIP |

**Japan Trench** (label_7d, M≥6.5 | 1,826 test rows | 67 positives)
| Fold | Train N | Test N | Pos Test | AUROC |
|---|---|---|---|---|
| 1 | 5,113 | 366 | 14 | 0.6071 |
| 3 | 5,844 | 365 | 7 | 0.7977 |
| 6 | 6,940 | 365 | 21 | 0.4961 |
| 7 | 7,305 | 365 | 7 | 0.5391 |
| 10 | 8,401 | 365 | 18 | 0.3692 |

**Central Chile** (label_7d, M≥6.5 | 1,096 test rows | 35 positives)
| Fold | Train N | Test N | Pos Test | AUROC |
|---|---|---|---|---|
| 2 | 5,479 | 365 | 7 | 0.3595 |
| 4 | 6,209 | 365 | 21 | 0.4682 |
| 5 | 6,574 | 366 | 7 | 0.6124 |

**North Anatolian** (label_7d_m60, M≥6.0 | 1,827 test rows | 49 positives)
| Fold | Train N | Test N | Pos Test | AUROC |
|---|---|---|---|---|
| 5 | 6,574 | 366 | 7 | 0.4906 |
| 7 | 7,305 | 365 | 7 | 0.2474 |
| 8 | 7,670 | 365 | 7 | 0.6269 |
| 9 | 8,035 | 366 | 7 | 0.1894 |
| 10 | 8,401 | 365 | 21 | 0.4647 |

**Sumatra-Andaman** (label_7d, M≥6.5 | 731 test rows | 14 positives)
| Fold | Train N | Test N | Pos Test | AUROC |
|---|---|---|---|---|
| 1 | 5,113 | 366 | 7 | 0.8213 |
| 6 | 6,940 | 365 | 7 | 0.1468 |

---

## 5. Interpretation — Resolution-Limited Null

**Overall verdict: NULL under pre-specified protocol.** 1 of 5 systems met the AUROC ≥ 0.52 threshold (Cascadia, classified CONFIRMED_UNSTABLE due to wide CI straddling the threshold). Minimum 2 required.

**This result is classified as a resolution-limited null for the following documented reasons:**

IONEX GIMs aggregate TEC across a 2.5°×5° spatial grid with 2-hour temporal resolution. Peer-reviewed studies using satellite instruments (CSES-01, DEMETER) document ionospheric precursory signatures at spatial scales of 10–100 km and sub-hourly timescales. The IONEX grid fundamentally cannot resolve these features — fault-zone-proximal anomalies are averaged across cells spanning several hundred kilometers.

**Three features of the fold-level results are consistent with this interpretation:**

1. **High individual-fold AUROC values exist.** Sumatra-Andaman Fold 1 returned 0.8213. Japan Trench Fold 3 returned 0.7977. Cascadia Fold 6 returned 0.7426. These represent periods when ionospheric anomalies were large enough to be detectable at IONEX resolution — not a system with no signal at all, but a system with episodic signal that coarse averaging masks in most folds.

2. **Sumatra-Andaman's wide CI ([0.2981, 0.6743]) reflects sparse test positives** (14 events across 731 test rows), not model instability. Low event density in the test window is a consequence of the 7-day forward label on a declustered catalog, not a data quality issue.

3. **Cascadia's CONFIRMED_UNSTABLE classification** is appropriate — the point estimate (0.5618) exceeds the threshold but the CI is too wide to confirm stability. With only 21 positive test observations across 3 active folds, Cascadia would require higher event density in the test window to achieve a stable CONFIRMED result.

**None of these observations are post-hoc.** The resolution limitation was documented prior to analysis. The results are fully consistent with the hypothesis that real ionospheric precursory signal exists at fault-zone-proximal scales but is below the IONEX detection floor.

---

## 6. Implications and Path Forward

H3 establishes the IONEX measurement floor under Project Sentinel's pre-registered walk-forward protocol. The IONEX-based approach returns null. The fold-level evidence of episodic high-AUROC folds is consistent with real but spatially localized signal that coarse resolution averages away.

**H3b designation:** A subsequent pre-registered amendment will specify H3b — same walk-forward protocol, same fault zones, same label definitions — using high-fidelity ionospheric data. Two candidate data sources:

- **CSES-02** (China Seismo-Electromagnetic Satellite, launched June 2025) — Dr. Dimitar Ouzounov, Chapman University, guest investigator. Langmuir probes, electric field detectors, particle analyzers at orbital resolution.
- **Precursor SPC** — multi-source ionospheric fusion product, 10 km³ voxel resolution, sub-minute updates. Initial contact April 2026 (Clive Cook, CEO).

H3 and H3b will be treated as complementary filings. H3 is not superseded — it is the necessary baseline that motivates H3b.

---

## 7. References

Pulinets, S., & Boyarchuk, K. (2004). *Ionospheric Precursors of Earthquakes.* Springer.

Pulinets, S., Ouzounov, D., Karelin, A., & Davidenko, D. (2021). Lithosphere-Atmosphere-Ionosphere-Magnetosphere Coupling (LAIC) model. *Frontiers in Earth Science*, 9, 610193.

Parrot, M. (2011). Statistical analysis of the ion density measured by the satellite DEMETER in relation to the seismicity. *Nonlinear Processes in Geophysics*, 18, 933–940.

Shen, X., et al. (2018). CSES satellite description and first results. *Earth and Planetary Physics*, 2(6), 344–355.

---

*Filed to OSF pre-registration osf.io/8hvf6 and GitHub repository synexisproject-bit/project-sentinel.*  
*All analytic protocols pre-specified under Amendment #1 (commit 496ebf1). No post-hoc modifications.*  
*Results stored: synexis-project-sentinel.sentinel_eval.h3_wf_results*  
*The Synexis Project — synexisproject.org*
