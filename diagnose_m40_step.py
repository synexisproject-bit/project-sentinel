#!/usr/bin/env python3
"""
diagnose_m40_step.py

Isolates what produces the M4.0 deficit reported in
docs/D9_FINDINGS_NOTE_2026-11-20.md, and by how much each registered rule
contributes to it.

WHY THIS EXISTS
---------------
The findings note at commit c2c5245 reported an isolated 20 percent deficit in
the M4.0 bin of subset P, relative to the Gutenberg-Richter trend projected
from the bins below, and attributed it to the JMA velocity-to-displacement
magnitude changeover.

A later check on the raw bulletin found the deficit present but about half as
large: roughly 12 percent relative to neighbouring bins, against roughly 25
percent after the nine registered filtering rules. So the anomaly is real in
JMA's catalog, and something in the filtering amplifies it. That raw check
compared different populations, however, so the amplification was suggestive
rather than established.

This script settles it by applying the registered rules one at a time, in the
registered order, and recomputing the M3.9 to M4.0 step after each. Whichever
stage moves the ratio is the cause.

It imports parse_record, select_jma_magnitude, load_region_cells and cell_key
from the committed build_jma_catalog.py rather than reimplementing them, so the
decomposition cannot diverge from the pipeline it is explaining.

This is a diagnostic. It computes nothing the registered protocol depends on,
changes no output, and writes only its own report.

USAGE
-----
    python3 diagnose_m40_step.py \
        --zips data/jma_catalog \
        --region data/csep_japan/japan.forecast.nodes \
        --out docs/m40_step_diagnostic.json

Author: Joseph Charles Tulloss, The Synexis Project
License: Apache-2.0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter, OrderedDict

import build_jma_catalog as B

# Bins examined. Wide enough to establish the local trend on both sides.
BIN_LO, BIN_HI = 3.3, 4.5

# b used to project each bin from the one below. 0.88 is the value fitted above
# the subset P primary Mc in the D9 run, so the projection is consistent with
# the figure the findings note reported.
B_PROJ = 0.88

# Registered rules applied cumulatively, in the registered order. Rules 1 and 2
# are conversions performed inside parse_record and remove nothing.
STAGES = [
    ("A_parsed",        "parsed, record type J, some magnitude present"),
    ("B_window",        "+ rule 3, origin time inside the registered window"),
    ("C_region",        "+ rule 4, epicentre inside the CSEP-Japan region"),
    ("D_depth",         "+ rule 5, depth <= 100 km"),
    ("E_type",          "+ rule 6, subsidiary information code 1"),
    ("F_quality",       "+ rule 7, determination flag not N or F, precision not 8"),
    ("G_scale",         "+ rule 8, JMA magnitude selected (V, v, D, d)"),
    ("H_manual",        "+ subset P restriction, flag in K, S, k, s"),
]


def binof(m):
    return round(round(m, 1), 1)


def ratio_table(counts):
    """For each bin, observed count against the count projected from the bin
    below it at b = B_PROJ. A ratio near 1 means the bin is on trend."""
    out = OrderedDict()
    prev = None
    b = BIN_LO
    while b <= BIN_HI + 1e-9:
        key = f"{b:.1f}"
        n = counts.get(binof(b), 0)
        if prev is None or prev == 0:
            out[key] = {"n": n, "expected": None, "ratio": None}
        else:
            exp = prev * 10 ** (-B_PROJ * 0.1)
            out[key] = {"n": n, "expected": round(exp, 1),
                        "ratio": round(n / exp, 3) if exp else None}
        prev = n
        b = round(b + 0.1, 1)
    return out


def step_at_40(counts):
    n39 = counts.get(3.9, 0)
    n40 = counts.get(4.0, 0)
    if not n39:
        return None
    exp = n39 * 10 ** (-B_PROJ * 0.1)
    return round(n40 / exp, 3)


def neighbour_median(counts):
    """Median of the on-trend ratios excluding the 4.0 step, so the step can be
    read against what the rest of the distribution is doing."""
    rs = []
    b = BIN_LO + 0.1
    while b <= BIN_HI + 1e-9:
        if abs(b - 4.0) > 1e-9:
            prev = counts.get(binof(round(b - 0.1, 1)), 0)
            n = counts.get(binof(b), 0)
            if prev:
                rs.append(n / (prev * 10 ** (-B_PROJ * 0.1)))
        b = round(b + 0.1, 1)
    rs.sort()
    if not rs:
        return None
    k = len(rs) // 2
    return round(rs[k] if len(rs) % 2 else (rs[k - 1] + rs[k]) / 2, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", default="data/jma_catalog")
    ap.add_argument("--region", default="data/csep_japan/japan.forecast.nodes")
    ap.add_argument("--out", default="docs/m40_step_diagnostic.json")
    args = ap.parse_args()

    inputs, skipped = B.collect_inputs(args.zips)
    print(f"Inputs ({len(inputs)}):")
    for p in inputs:
        print(f"  {p}")
    for p, why in skipped:
        print(f"  skipped {p}")

    cells, region_sha, _ = B.load_region_cells(args.region)
    print(f"Region sha256 {region_sha}")
    if region_sha != B.REGION_SHA256:
        sys.exit("Region file is not the registered one. Stopping.")

    # Per-stage histograms, each keyed by magnitude bin.
    hist = {name: Counter() for name, _ in STAGES}

    # Cross-tabulations for the two bins that matter, taken at stage F, which is
    # the last point before rule 8 touches the magnitude value.
    xtab = {3.9: {}, 4.0: {}}
    for b in xtab:
        xtab[b] = {"mag1_type": Counter(), "mag2_type": Counter(),
                   "rule8_outcome": Counter(), "flag": Counter(),
                   "depth_band": Counter(), "subsidiary": Counter()}

    # Where rule 8 moves an event between bins, or drops it.
    rule8_moves = Counter()
    n_records = n_parse_fail = 0

    for label, lineno, raw in B.iter_source_records(inputs, {}):
        if not raw.strip():
            continue
        n_records += 1
        try:
            rec = B.parse_record(raw)
        except B.ParseError:
            n_parse_fail += 1
            continue
        if rec["record_type"] != "J":
            continue

        # The magnitude as JMA reports it first, independent of rule 8.
        m_raw = rec["mag1"] if rec["mag1"] is not None else rec["mag2"]
        if m_raw is None:
            continue
        b_raw = binof(m_raw)
        in_range = BIN_LO - 0.05 <= m_raw <= BIN_HI + 0.05

        t = rec["origin_time_utc"]
        ok_window = B.WINDOW_START <= t <= B.WINDOW_END
        ok_region = B.cell_key(rec["lon_units"], rec["lat_units"]) in cells
        ok_depth = rec["depth_km"] is not None and rec["depth_km"] <= B.DEPTH_MAX_KM
        ok_type = rec["subsidiary_info"] == "1"
        ok_qual = (rec["determination_flag"] not in ("N", "F")
                   and rec["location_precision"] != "8")
        manual = rec["determination_flag"] in ("K", "S", "k", "s")

        if in_range:
            hist["A_parsed"][b_raw] += 1
            if ok_window:
                hist["B_window"][b_raw] += 1
                if ok_region:
                    hist["C_region"][b_raw] += 1
                    if ok_depth:
                        hist["D_depth"][b_raw] += 1
                        if ok_type:
                            hist["E_type"][b_raw] += 1
                            if ok_qual:
                                hist["F_quality"][b_raw] += 1

        # Stage F reached: record the cross-tab and what rule 8 then does.
        reached_F = ok_window and ok_region and ok_depth and ok_type and ok_qual
        if reached_F and b_raw in xtab:
            x = xtab[b_raw]
            x["mag1_type"][rec["mag1_type"] or "(blank)"] += 1
            x["mag2_type"][rec["mag2_type"] or "(blank)"] += 1
            x["flag"][rec["determination_flag"] or "(blank)"] += 1
            x["subsidiary"][rec["subsidiary_info"] or "(blank)"] += 1
            d = rec["depth_km"]
            x["depth_band"][("0-30" if d <= 30 else "30-60" if d <= 60
                             else "60-100")] += 1

        # Rule 8 and the subset restriction, using the SELECTED magnitude.
        m_sel, t_sel = B.select_jma_magnitude(rec)
        if reached_F and b_raw in xtab:
            if m_sel is None:
                xtab[b_raw]["rule8_outcome"]["excluded, no JMA scale"] += 1
            elif binof(m_sel) == b_raw:
                xtab[b_raw]["rule8_outcome"][f"kept in bin, type {t_sel}"] += 1
            else:
                xtab[b_raw]["rule8_outcome"][
                    f"moved to {binof(m_sel):.1f}, type {t_sel}"] += 1
                rule8_moves[(b_raw, binof(m_sel))] += 1

        if reached_F and m_sel is not None:
            b_sel = binof(m_sel)
            if BIN_LO - 0.05 <= m_sel <= BIN_HI + 0.05:
                hist["G_scale"][b_sel] += 1
                if manual:
                    hist["H_manual"][b_sel] += 1

    # ---------------------------------------------------------------
    print(f"\nRecords read {n_records:,}, parse failures {n_parse_fail:,}")
    print(f"\n{'stage':<12} {'n(3.9)':>8} {'n(4.0)':>8} {'step@4.0':>9} "
          f"{'nbr median':>11} {'relative':>9}")
    print("-" * 64)
    report_stages = OrderedDict()
    for name, desc in STAGES:
        c = hist[name]
        s = step_at_40(c)
        nb = neighbour_median(c)
        rel = round(s / nb, 3) if (s and nb) else None
        report_stages[name] = {
            "description": desc,
            "n_3.9": c.get(3.9, 0), "n_4.0": c.get(4.0, 0),
            "step_at_4.0": s, "neighbour_median_ratio": nb,
            "step_relative_to_neighbours": rel,
            "bins": ratio_table(c),
        }
        print(f"{name:<12} {c.get(3.9,0):>8,} {c.get(4.0,0):>8,} "
              f"{str(s):>9} {str(nb):>11} {str(rel):>9}")

    print("\nInterpretation guide")
    print("  step@4.0 below the neighbour median means the 4.0 bin is depleted.")
    print("  The stage where 'relative' first drops is the one that introduces")
    print("  or amplifies the deficit. A drop at G_scale points at rule 8 and")
    print("  the magnitude-scale changeover; a drop at C_region or D_depth")
    print("  points at the spatial or depth filter instead.")

    print("\nRule 8 bin movements, counts by (from, to)")
    for (a, b), n in sorted(rule8_moves.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {a:.1f} -> {b:.1f}: {n:,}")
    if not rule8_moves:
        print("  none: rule 8 never changed an event's magnitude bin")

    for b in (3.9, 4.0):
        print(f"\nCross-tab at stage F for the M{b:.1f} bin")
        for k, c in xtab[b].items():
            top = ", ".join(f"{kk}={vv:,}" for kk, vv in c.most_common(6))
            print(f"  {k:<14} {top}")

    payload = {
        "script": "diagnose_m40_step.py",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": ("Isolate which registered rule produces or amplifies the "
                    "M4.0 deficit reported in docs/D9_FINDINGS_NOTE_2026-11-20.md "
                    "at commit c2c5245."),
        "b_used_for_projection": B_PROJ,
        "region_sha256": region_sha,
        "records_read": n_records,
        "parse_failures": n_parse_fail,
        "stages": report_stages,
        "rule8_bin_movements": {f"{a:.1f}->{b:.1f}": n
                                for (a, b), n in rule8_moves.items()},
        "cross_tab_stage_F": {f"{b:.1f}": {k: dict(v) for k, v in x.items()}
                              for b, x in xtab.items()},
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
