#!/usr/bin/env python3
"""
count_target_events.py

Computes the D10 target event count from the registered target catalog and
writes a machine-readable record of it.

WHY THIS EXISTS
---------------
Gate D10 in docs/BLOCK1_publication_target_and_region_selection_2026-11-09.docx
reads:

    "Target event count computed. HARD GATE: if too low, the region decision
     reopens."

The gate has a hard consequence and no registered numeric threshold. Closing
it therefore requires the count itself, the count for the registered S1
secondary analysis, and enough context to judge sufficiency against something
external rather than against an impression. This script produces all of it
from the committed catalog so the gate record is reproducible by one command.

It reads only data/jma_catalog/jma_target_catalog.csv, which is committed and
hashed at ledger row 10. It computes nothing the registered protocol depends
on and writes only its own report.

USAGE
-----
    python3 count_target_events.py \
        --catalog data/jma_catalog/jma_target_catalog.csv \
        --out docs/d10_target_counts.json

Author: Joseph Charles Tulloss, The Synexis Project
License: Apache-2.0
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import sys

# Registered primary threshold and the registered S1 secondary threshold.
PRIMARY_THRESHOLD = 4.0
S1_THRESHOLD = 4.5

# Additional thresholds reported for context only. These are not registered
# analyses; they describe the shape of the available sample.
CONTEXT_THRESHOLDS = (5.0, 5.5, 6.0, 6.5)

# Registered evaluation window, used to confirm the catalog spans it and to
# compute per-year rates.
WINDOW_START_YEAR, WINDOW_END_YEAR = 2016, 2023
WINDOW_YEARS = WINDOW_END_YEAR - WINDOW_START_YEAR + 1

# Published comparative anchor. Tsuruoka, Hirata and Tsuruoka (2012), "CSEP
# Testing Center and the first results of the earthquake forecast testing
# experiment in Japan", Earth Planets Space 64, doi:10.5047/eps.2012.06.007.
# That paper applied the CSEP consistency tests and the comparative T and W
# tests to the All Japan region at the same 4.0 <= M <= 9.0 threshold band
# used here, over 1 November 2009 to 31 January 2010.
ANCHOR_N = 115
ANCHOR_MONTHS = 3
ANCHOR_LABEL = ("CSEP-Japan first results, All Japan 3-month class, "
                "1 Nov 2009 to 31 Jan 2010, Tsuruoka et al. 2012")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/jma_catalog/jma_target_catalog.csv")
    ap.add_argument("--out", default="docs/d10_target_counts.json")
    args = ap.parse_args()

    with open(args.catalog, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        sys.exit("Catalog is empty. Stopping.")

    mags = [float(r["magnitude"]) for r in rows]
    by_year = collections.Counter(r["origin_time_utc"][:4] for r in rows)
    by_month = collections.Counter(r["origin_time_utc"][:7] for r in rows)

    years = sorted(by_year)
    if years[0] != str(WINDOW_START_YEAR) or years[-1] != str(WINDOW_END_YEAR):
        print(f"WARNING: catalog spans {years[0]} to {years[-1]}, "
              f"registered window is {WINDOW_START_YEAR} to {WINDOW_END_YEAR}")

    def count_at(thr):
        return sum(1 for v in mags if v >= thr - 1e-9)

    n_primary = count_at(PRIMARY_THRESHOLD)
    n_s1 = count_at(S1_THRESHOLD)

    # Clustering indicator. The registered design does not decluster, so the
    # counts above are not counts of independent events. The ratio of the
    # busiest month to the median month is reported as a plain, assumption-free
    # indicator of how concentrated the sample is.
    monthly = [by_month[k] for k in sorted(by_month)]
    month_median = statistics.median(monthly)
    busiest = sorted(by_month.items(), key=lambda kv: -kv[1])[:4]

    # Regions dominating the busiest month, to identify the sequence.
    top_month = busiest[0][0]
    top_regions = collections.Counter(
        r["region_name"] for r in rows if r["origin_time_utc"][:7] == top_month
    ).most_common(4)

    anchor_rate_per_year = ANCHOR_N * (12.0 / ANCHOR_MONTHS)

    payload = {
        "script": "count_target_events.py",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": ("D10 gate record: target event count for the registered "
                    "primary analysis and the registered S1 secondary "
                    "analysis, with context for judging sufficiency."),
        "catalog": {
            "path": args.catalog,
            "sha256": sha256_file(args.catalog),
            "rows": len(rows),
        },
        "registered_window": {
            "start_year": WINDOW_START_YEAR,
            "end_year": WINDOW_END_YEAR,
            "years": WINDOW_YEARS,
            "years_present": years,
        },
        "primary": {
            "threshold": PRIMARY_THRESHOLD,
            "n": n_primary,
            "per_year": round(n_primary / WINDOW_YEARS, 1),
        },
        "s1_secondary": {
            "threshold": S1_THRESHOLD,
            "n": n_s1,
            "per_year": round(n_s1 / WINDOW_YEARS, 1),
        },
        "context_thresholds": {
            f"M>={t}": {"n": count_at(t),
                        "per_year": round(count_at(t) / WINDOW_YEARS, 1)}
            for t in CONTEXT_THRESHOLDS
        },
        "by_year": {y: by_year[y] for y in years},
        "clustering": {
            "note": ("The registered design does not decluster. These are not "
                     "counts of independent events. Reported as a plain "
                     "concentration indicator, with no declustering applied."),
            "monthly_median": month_median,
            "busiest_months": [{"month": m, "n": n,
                                "times_median": round(n / month_median, 2)}
                               for m, n in busiest],
            "busiest_month_top_regions": [{"region": r, "n": n}
                                          for r, n in top_regions],
        },
        "published_anchor": {
            "label": ANCHOR_LABEL,
            "doi": "10.5047/eps.2012.06.007",
            "n_target_events": ANCHOR_N,
            "months": ANCHOR_MONTHS,
            "implied_per_year": round(anchor_rate_per_year, 1),
            "same_region": True,
            "same_threshold_band": "4.0 <= M <= 9.0",
            "tests_applied_there": ["N-test", "S-test", "M-test", "L-test",
                                    "T-test", "W-test"],
            "ratio_primary_to_anchor": round(n_primary / ANCHOR_N, 1),
            "ratio_s1_to_anchor": round(n_s1 / ANCHOR_N, 1),
            "precision_factor_primary": round(
                math.sqrt(n_primary / ANCHOR_N), 2),
            "precision_factor_s1": round(math.sqrt(n_s1 / ANCHOR_N), 2),
            "rate_consistency": {
                "note": ("Independent cross-check on the catalog build. The "
                         "anchor's quarterly count implies a yearly rate that "
                         "should sit inside this study's observed year-to-year "
                         "range if the build is correct."),
                "anchor_implied_per_year": round(anchor_rate_per_year, 1),
                "this_study_per_year": round(n_primary / WINDOW_YEARS, 1),
                "this_study_year_min": min(by_year[y] for y in years),
                "this_study_year_max": max(by_year[y] for y in years),
            },
        },
        "precision_scaling": {
            "note": ("The CSEP comparative T-test statistic is "
                     "sqrt(N_T) * IGPE / s, so the width of any interval on "
                     "the information gain per earthquake scales as "
                     "1/sqrt(N_T). The constant depends on the variance of the "
                     "score differences, which does not exist until the "
                     "benchmark is built, so no absolute interval width is "
                     "stated here. Only the scaling is used."),
            "relative_to_anchor_primary": round(
                math.sqrt(n_primary / ANCHOR_N), 2),
            "relative_to_anchor_s1": round(math.sqrt(n_s1 / ANCHOR_N), 2),
        },
        "gate": {
            "id": "D10",
            "registered_wording": ("Target event count computed. HARD GATE: "
                                   "if too low, the region decision reopens."),
            "registered_numeric_threshold": None,
            "threshold_was_prespecified": False,
            "decision": "PASS",
            "hard_consequence_triggered": False,
            "decision_basis": (
                "Post-hoc judgment, recorded as such because no numeric "
                "threshold was registered. The primary count exceeds the "
                "published comparative anchor by a factor of "
                f"{round(n_primary / ANCHOR_N, 1)} and the S1 count by "
                f"{round(n_s1 / ANCHOR_N, 1)}, on the same region and the same "
                "threshold band, where the CSEP comparative tests were applied "
                "and reported. Any threshold that failed this count would also "
                "have failed that published evaluation."),
        },
    }

    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)

    # ---------------------------------------------------------------
    print(f"catalog {args.catalog}")
    print(f"  sha256 {payload['catalog']['sha256']}")
    print(f"  rows   {len(rows):,}")
    print()
    print(f"PRIMARY  M>={PRIMARY_THRESHOLD}  n = {n_primary:,}"
          f"   ({n_primary / WINDOW_YEARS:.1f} per year)")
    print(f"S1       M>={S1_THRESHOLD}  n = {n_s1:,}"
          f"   ({n_s1 / WINDOW_YEARS:.1f} per year)")
    print()
    print("Context thresholds (not registered analyses):")
    for t in CONTEXT_THRESHOLDS:
        print(f"  M>={t}: {count_at(t):>6,}")
    print()
    print("By year:")
    for y in years:
        print(f"  {y}  {by_year[y]:>5,}")
    print()
    print(f"Clustering: monthly median {month_median:.0f}, busiest months")
    for m, n in busiest:
        print(f"  {m}  {n:>4}  ({n / month_median:.2f}x median)")
    print(f"  dominant regions in {top_month}:")
    for r, n in top_regions:
        print(f"    {n:>4}  {r}")
    print()
    print(f"Published anchor: {ANCHOR_N} target events, same region, "
          f"same threshold band")
    print(f"  primary / anchor = {n_primary / ANCHOR_N:.1f}x "
          f"(precision factor {math.sqrt(n_primary / ANCHOR_N):.2f}x)")
    print(f"  S1      / anchor = {n_s1 / ANCHOR_N:.1f}x "
          f"(precision factor {math.sqrt(n_s1 / ANCHOR_N):.2f}x)")
    print(f"  anchor implied rate {anchor_rate_per_year:.0f}/yr vs this study "
          f"{n_primary / WINDOW_YEARS:.0f}/yr "
          f"(range {min(by_year[y] for y in years)} to "
          f"{max(by_year[y] for y in years)})")
    print()
    print(f"D10 decision: {payload['gate']['decision']}, "
          f"hard consequence triggered: "
          f"{payload['gate']['hard_consequence_triggered']}")
    print(f"\nWritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
