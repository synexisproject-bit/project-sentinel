#!/usr/bin/env python3
"""
estimate_mc_d9.py

Magnitude of completeness analysis for Project Sentinel, gate item D9.

Implements the protocol locked at:

  docs/BLOCK1_ADDENDUM1_mc_protocol_2026-11-14.docx
  commit b7ffa07, sha256 1c2a6cd408b45bfd9071c0e8dfeae0201be73ffc535c7b752e263d3af0bed1eb
  ledger row 15

under OSF registration 10.17605/OSF.IO/H5MD2, amending the Block 1 Addendum
at commit 3b4f784.

This script implements that protocol. It does not choose parameters. Every
number below comes from the amendment, which was committed before any Mc value
existed. Nothing here may be tuned after inspecting results; a change is a new
amendment with its own date, reason and ledger row.

WHAT IS LOCKED, AND WHERE IT COMES FROM
---------------------------------------
Subsets, by JMA hypocenter determination flag in column 96:
    P  manual            K, S, k, s     PRIMARY; source of the benchmark b-value
    Q  full              all events     declared secondary
    R  closely examined  K, S           diagnostic

Estimators, all from SeismoStats 1.0.1 (Swiss Seismological Service, ETH
Zurich). Nothing is hand-implemented.
    E1  b-value stability (MBS-WW)   REGISTERED PRIMARY, stability_range 0.5
    E2  Kolmogorov-Smirnov           p_value_pass 0.1
    E3  maximum curvature            correction_factor 0.2

Trial grid: M1.0 to M4.5 in 0.1 steps. If nothing at or below 4.5 passes, the
result is "not attained below M4.5", which is a gate failure under section 7 of
the amendment and is NOT retried with a wider grid.

THE GATE READS THE HIGHEST OF E1, E2 AND E3, NOT THE PRIMARY. D10 passes only
where all three agree Mc is below the registered M4.0 threshold. The primary
designation governs only which b-value is reported.

Bootstrap: E1 and E3 only. E2 carries no outer bootstrap because its p-value is
already obtained by simulation.
    headline scopes      1,000 resamples; E2 at 10,000 synthetic draws
    moving windows         200 resamples; E2 at  1,000 synthetic draws
    spatial nodes          200 resamples; E2 at  1,000 synthetic draws

Temporal: eight annual windows 2016-2023 UTC, plus a moving window of 5,000
consecutive events stepped by 1,000.

Spatial: 0.25 degree grid, nearest 500 events within 100 km. A node with fewer
than 500 events inside that radius is reported insufficient, not estimated from
a smaller sample.

Equal-size comparison: every cross-subset comparison is also made on 20 random
subsamples per subset drawn without replacement to 234,612, the size of the
smallest subset. Estimated Mc rises with sample size even when true completeness
is fixed, so the full-size comparison alone cannot separate detection regime
from sample size. Where full-size and equal-size disagree in direction, the
equal-size comparison governs interpretation. Both are reported.

Scale mixing: displacement-magnitude share per 0.1 bin, and Mc and b estimated
separately on velocity-only and displacement-only events wherever either carries
at least 1,000 events.

STAGES AND CHECKPOINTING
------------------------
Each stage writes its own output file and is skipped on a later run if that file
already exists, unless --force is given. A failure in one stage therefore costs
that stage, not the run.

    headline     whole-region estimates for P, Q, R
    equalsize    20 subsamples per subset at 234,612
    annual       eight annual windows per subset
    moving       moving-window series per subset
    spatial      0.25 degree grid, subset P
    scalemix     magnitude-scale composition and split estimates

USAGE
-----
    python3 estimate_mc_d9.py --catalog jma_mc_working_catalog.csv --out results/
    python3 estimate_mc_d9.py --catalog ... --out ... --stages headline,annual
    python3 estimate_mc_d9.py --catalog ... --out ... --workers 4

Requires: seismostats==1.0.1, pandas, numpy, scipy.

Author: Joseph Charles Tulloss, The Synexis Project
License: Apache-2.0
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SCRIPT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Locked constants. Every one of these is fixed by the amendment at b7ffa07.
# Changing any of them requires a new amendment, not an edit here.
# ---------------------------------------------------------------------------

AMENDMENT_COMMIT = "b7ffa07"
AMENDMENT_SHA256 = "1c2a6cd408b45bfd9071c0e8dfeae0201be73ffc535c7b752e263d3af0bed1eb"
REGISTRATION_DOI = "10.17605/OSF.IO/H5MD2"
WORKING_CATALOG_SHA256 = (
    "f48dbc7f83af685f392b45830c419982c14189f67947e7114eb95543ac05a9cd")

DELTA_M = 0.1
MC_TRIAL_MIN = 1.0
MC_TRIAL_MAX = 4.5
REGISTERED_THRESHOLD = 4.0          # the D10 gate boundary
GATE_COMFORT = 3.5                  # section 7 margin boundary

SUBSETS = {
    "P": {"flags": ("K", "S", "k", "s"), "role": "PRIMARY, manual"},
    "Q": {"flags": None,                 "role": "secondary, full"},
    "R": {"flags": ("K", "S"),           "role": "diagnostic, closely examined"},
}
PRIMARY_SUBSET = "P"

E2_PASS_P = 0.1
E3_CORRECTION = 0.2
E1_STABILITY_RANGE = 0.5

BOOT_HEADLINE = 1000
BOOT_WINDOW = 200
E2_DRAWS_HEADLINE = 10000
E2_DRAWS_WINDOW = 1000

ANNUAL_YEARS = list(range(2016, 2024))
MOVING_WINDOW = 5000
MOVING_STEP = 1000

GRID_DEG = 0.25
NODE_NEAREST = 500
NODE_MAX_RADIUS_KM = 100.0

EQUALSIZE_N = 234612               # size of subset R, the smallest
EQUALSIZE_DRAWS = 20

SCALEMIX_MIN_EVENTS = 1000

STAGES = ["headline", "equalsize", "annual", "moving", "spatial", "scalemix"]

_QUIET = contextlib.redirect_stdout(io.StringIO())


# ---------------------------------------------------------------------------
# Estimators. Thin wrappers so the locked parameters appear exactly once.
# ---------------------------------------------------------------------------

def _mcs_grid():
    from seismostats.utils import bin_to_precision
    return bin_to_precision(
        np.arange(MC_TRIAL_MIN, MC_TRIAL_MAX + DELTA_M / 2, DELTA_M), DELTA_M)


def e1_mbs(mags):
    """b-value stability, MBS-WW. REGISTERED PRIMARY. Returns (mc, b) or (None, None)."""
    from seismostats.analysis import estimate_mc_b_stability
    with contextlib.redirect_stdout(io.StringIO()):
        mc, info = estimate_mc_b_stability(
            mags, delta_m=DELTA_M, mcs_test=_mcs_grid(),
            stability_range=E1_STABILITY_RANGE)
    return mc, (info.get("best_b_value") if mc is not None else None)


def e2_ks(mags, draws):
    """Kolmogorov-Smirnov. Returns mc or None."""
    from seismostats.analysis import estimate_mc_ks
    with contextlib.redirect_stdout(io.StringIO()):
        mc, _ = estimate_mc_ks(mags, delta_m=DELTA_M, mcs_test=_mcs_grid(),
                               p_value_pass=E2_PASS_P, n=draws)
    return mc


def e3_maxc(mags):
    """Maximum curvature plus the conventional correction. Returns mc."""
    from seismostats.analysis import estimate_mc_maxc
    with contextlib.redirect_stdout(io.StringIO()):
        mc, _ = estimate_mc_maxc(mags, fmd_bin=DELTA_M,
                                 correction_factor=E3_CORRECTION)
    return mc


def b_above(mags, mc):
    """Aki maximum likelihood with the Tinti and Mulargia binning correction,
    plus the Shi and Bolt uncertainty. Returns (b, sigma_b, n)."""
    if mc is None:
        return None, None, 0
    from seismostats.analysis import ClassicBValueEstimator
    sel = mags[mags >= mc - DELTA_M / 2]
    if len(sel) < 2:
        return None, None, int(len(sel))
    est = ClassicBValueEstimator()
    with contextlib.redirect_stdout(io.StringIO()):
        est.calculate(sel, mc=mc, delta_m=DELTA_M)
        return float(est.b_value), float(est.std), int(len(sel))


def bootstrap_mc(mags, n_resamples, seed):
    """Bootstrap E1 and E3 only, per the amendment. E2 is excluded because its
    p-value already comes from simulation and an outer bootstrap over several
    thousand nodes would take days."""
    rng = np.random.default_rng(seed)
    e1, e3 = [], []
    n = len(mags)
    for _ in range(n_resamples):
        s = mags[rng.integers(0, n, n)]
        mc1, _ = e1_mbs(s)
        if mc1 is not None:
            e1.append(mc1)
        e3.append(e3_maxc(s))
    def ci(v):
        if not v:
            return None
        a = np.asarray(v, dtype=float)
        return {"median": round(float(np.median(a)), 2),
                "ci95_low": round(float(np.percentile(a, 2.5)), 2),
                "ci95_high": round(float(np.percentile(a, 97.5)), 2),
                "n_successful": int(len(a))}
    return ci(e1), ci(e3)


def assess(mags, label, e2_draws, n_boot, seed, with_b=True):
    """Run all three estimators plus the gate reading on one sample."""
    t0 = time.time()
    mags = np.asarray(mags, dtype=float)
    out = {"label": label, "n_events": int(len(mags))}

    def r2(v):
        # Float arithmetic in the estimators yields values like
        # 2.4000000000000004. Magnitudes are on a 0.1 grid, so round.
        return None if v is None else round(float(v), 2)

    mc1, b_at_mc1 = e1_mbs(mags)
    mc1 = r2(mc1)
    mc2 = r2(e2_ks(mags, e2_draws))
    mc3 = r2(e3_maxc(mags))
    out["E1_mbs"] = mc1
    out["E2_ks"] = mc2
    out["E3_maxc"] = mc3
    out["E1_b_at_mc"] = b_at_mc1

    # THE GATE. Highest of the three, not the primary. A None from E1 or E2
    # means that estimator found no passing cut-off at or below M4.5, which is
    # itself a gate failure and must not be silently dropped from the maximum.
    vals = [mc1, mc2, mc3]
    if any(v is None for v in vals):
        out["gate_mc"] = None
        out["gate_note"] = ("at least one estimator found no passing cut-off at "
                            "or below M4.5; reported as not attained, which is a "
                            "gate failure under section 7")
    else:
        out["gate_mc"] = round(float(max(vals)), 2)
    out["gate_verdict"] = gate_verdict(out["gate_mc"])

    if with_b:
        b, sb, nb = b_above(mags, mc1)
        out["b_value"] = b
        out["b_sigma_shi_bolt"] = sb
        out["b_n_events_above_mc"] = nb

    if n_boot:
        c1, c3 = bootstrap_mc(mags, n_boot, seed)
        out["E1_bootstrap"] = c1
        out["E3_bootstrap"] = c3
        out["bootstrap_resamples"] = n_boot
    out["E2_synthetic_draws"] = e2_draws
    out["seconds"] = round(time.time() - t0, 2)
    return out


def gate_verdict(gate_mc):
    """Section 7 of the amendment, applied to a single scope. Fixed before any
    value existed."""
    if gate_mc is None:
        return "NOT_ATTAINED_BELOW_4.5 — gate failure, amendment required"
    if gate_mc < GATE_COMFORT:
        return "below 3.5 — threshold supported with margin"
    if gate_mc < REGISTERED_THRESHOLD:
        return "3.5 to 4.0 — defensible, margin thin, report as limitation"
    return "at or above 4.0 — threshold NOT supported here, amendment required"


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_catalog(path, verify_hash=True):
    print(f"Loading {path}")
    digest = sha256_file(path)
    print(f"  sha256 {digest}")
    if digest == WORKING_CATALOG_SHA256:
        print("  matches the registered working catalog hash")
    else:
        msg = (f"  CATALOG HASH MISMATCH\n"
               f"    expected {WORKING_CATALOG_SHA256}\n"
               f"    got      {digest}")
        if verify_hash:
            print(msg, file=sys.stderr)
            sys.exit("Refusing to run on a catalog that is not the registered one. "
                     "Pass --no-verify-hash only if you intend that.")
        print(msg + "\n  continuing because --no-verify-hash was given")

    df = pd.read_csv(path)
    from seismostats.utils import bin_to_precision
    df["magnitude"] = bin_to_precision(df["magnitude"].to_numpy(float), DELTA_M)
    df["origin_time_utc"] = pd.to_datetime(df["origin_time_utc"], format="mixed",
                                           utc=True)
    df["year"] = df["origin_time_utc"].dt.year
    df = df.sort_values("origin_time_utc").reset_index(drop=True)
    print(f"  {len(df):,} events, "
          f"{df['origin_time_utc'].min()} to {df['origin_time_utc'].max()}")
    return df, digest


def subset(df, key):
    flags = SUBSETS[key]["flags"]
    return df if flags is None else df[df["determination_flag"].isin(flags)]


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_headline(df, args):
    res = {}
    for k in SUBSETS:
        s = subset(df, k)
        print(f"  subset {k} ({SUBSETS[k]['role']}): {len(s):,} events")
        res[k] = assess(s["magnitude"].to_numpy(), f"headline_{k}",
                        E2_DRAWS_HEADLINE, BOOT_HEADLINE, seed=1000 + ord(k))
        print(f"    E1 {res[k]['E1_mbs']}  E2 {res[k]['E2_ks']}  "
              f"E3 {res[k]['E3_maxc']}  gate {res[k]['gate_mc']}  "
              f"[{res[k]['seconds']}s]")
    res["_benchmark_b_value"] = {
        "from_subset": PRIMARY_SUBSET,
        "b_value": res[PRIMARY_SUBSET].get("b_value"),
        "sigma_shi_bolt": res[PRIMARY_SUBSET].get("b_sigma_shi_bolt"),
        "above_mc": res[PRIMARY_SUBSET].get("E1_mbs"),
        "note": ("This is the b-value that enters the smoothed-seismicity "
                 "benchmark, per the amendment: fitted above the subset P "
                 "E1 primary Mc."),
    }
    return res


def _equalsize_one(a):
    mags, label, seed = a
    return assess(mags, label, E2_DRAWS_WINDOW, 0, seed, with_b=True)


def stage_equalsize(df, args):
    """Removes the sample-size confound. Estimated Mc rises with sample size
    even at fixed true completeness, so a P-versus-Q difference at full size
    cannot be attributed to detection regime on its own."""
    jobs = []
    for k in SUBSETS:
        s = subset(df, k)["magnitude"].to_numpy()
        if len(s) < EQUALSIZE_N:
            print(f"  subset {k}: {len(s):,} events, fewer than {EQUALSIZE_N:,}; "
                  f"skipped")
            continue
        for i in range(EQUALSIZE_DRAWS):
            rng = np.random.default_rng(7000 + ord(k) * 100 + i)
            idx = rng.choice(len(s), EQUALSIZE_N, replace=False)
            jobs.append((s[idx], f"equalsize_{k}_{i:02d}", 9000 + ord(k) * 100 + i))
    print(f"  {len(jobs)} subsample estimates at n={EQUALSIZE_N:,}")
    with Pool(args.workers) as p:
        out = p.map(_equalsize_one, jobs)
    summary = {}
    for k in SUBSETS:
        rows = [r for r in out if r["label"].startswith(f"equalsize_{k}_")]
        if not rows:
            continue
        summary[k] = {}
        for est in ("E1_mbs", "E2_ks", "E3_maxc", "gate_mc", "b_value"):
            v = [r[est] for r in rows if r.get(est) is not None]
            summary[k][est] = ({"median": float(np.median(v)),
                                "min": float(np.min(v)), "max": float(np.max(v)),
                                "n": len(v)} if v else None)
        print(f"  subset {k}: gate_mc median "
              f"{summary[k]['gate_mc']['median'] if summary[k]['gate_mc'] else None}")
    return {"draws": out, "summary": summary,
            "equal_size_n": EQUALSIZE_N, "n_draws_per_subset": EQUALSIZE_DRAWS,
            "note": ("Where the full-size and equal-size comparisons disagree in "
                     "direction, the equal-size comparison governs interpretation, "
                     "per the amendment.")}


def _annual_one(a):
    mags, label, seed = a
    return assess(mags, label, E2_DRAWS_HEADLINE, BOOT_HEADLINE, seed)


def stage_annual(df, args):
    jobs = []
    for k in SUBSETS:
        s = subset(df, k)
        for y in ANNUAL_YEARS:
            m = s[s["year"] == y]["magnitude"].to_numpy()
            if len(m) < 100:
                continue
            jobs.append((m, f"annual_{k}_{y}", 2000 + ord(k) * 10 + (y - 2016)))
    print(f"  {len(jobs)} annual estimates")
    with Pool(args.workers) as p:
        out = p.map(_annual_one, jobs)
    for r in out:
        print(f"  {r['label']}: n={r['n_events']:,} E1 {r['E1_mbs']} "
              f"E2 {r['E2_ks']} E3 {r['E3_maxc']} gate {r['gate_mc']}")
    return out


def _moving_one(a):
    mags, label, seed = a
    return assess(mags, label, E2_DRAWS_WINDOW, BOOT_WINDOW, seed, with_b=False)


def stage_moving(df, args):
    jobs = []
    for k in SUBSETS:
        s = subset(df, k).reset_index(drop=True)
        m = s["magnitude"].to_numpy()
        t = s["origin_time_utc"].to_numpy()
        for i0 in range(0, len(m) - MOVING_WINDOW + 1, MOVING_STEP):
            jobs.append((m[i0:i0 + MOVING_WINDOW],
                         f"moving_{k}_{i0}_{str(t[i0])[:10]}_{str(t[i0 + MOVING_WINDOW - 1])[:10]}",
                         3000 + i0))
    print(f"  {len(jobs)} moving-window estimates "
          f"({MOVING_WINDOW:,} events, step {MOVING_STEP:,})")
    with Pool(args.workers) as p:
        out = p.map(_moving_one, jobs)
    return out


def _node_one(a):
    mags, label, seed = a
    return assess(mags, label, E2_DRAWS_WINDOW, BOOT_WINDOW, seed, with_b=True)


def stage_spatial(df, args):
    """0.25 degree grid, nearest 500 events within 100 km. Nodes below that
    sample are reported insufficient rather than estimated from less data."""
    from scipy.spatial import cKDTree
    s = subset(df, PRIMARY_SUBSET)
    lat0 = float(s["latitude"].mean())
    kx = 111.320 * np.cos(np.radians(lat0))
    ky = 110.574
    pts = np.column_stack([s["longitude"].to_numpy() * kx,
                           s["latitude"].to_numpy() * ky])
    tree = cKDTree(pts)
    mags = s["magnitude"].to_numpy()

    lons = np.arange(122.40, 147.60 + 1e-9, GRID_DEG)
    lats = np.arange(23.00, 46.60 + 1e-9, GRID_DEG)
    print(f"  subset {PRIMARY_SUBSET}, {len(s):,} events; "
          f"grid {len(lons)} x {len(lats)} = {len(lons) * len(lats):,} nodes")

    jobs, insufficient = [], []
    for lo in lons:
        for la in lats:
            d, i = tree.query([lo * kx, la * ky], k=NODE_NEAREST,
                              distance_upper_bound=NODE_MAX_RADIUS_KM)
            ok = np.isfinite(d)
            if ok.sum() < NODE_NEAREST:
                insufficient.append({"lon": round(float(lo), 3),
                                     "lat": round(float(la), 3),
                                     "n_within_radius": int(ok.sum())})
                continue
            jobs.append((mags[i[ok]], f"node_{lo:.2f}_{la:.2f}",
                         int(abs(lo * 1000 + la))))
    print(f"  {len(jobs):,} sufficient nodes, {len(insufficient):,} insufficient "
          f"({100 * len(insufficient) / max(1, len(lons) * len(lats)):.1f}% of grid)")
    with Pool(args.workers) as p:
        out = p.map(_node_one, jobs)
    gated = [r["gate_mc"] for r in out if r["gate_mc"] is not None]
    worst = round(max(gated), 2) if gated else None
    print(f"  highest node gate_mc: {worst}")
    return {"nodes": out, "insufficient": insufficient,
            "grid_deg": GRID_DEG, "nearest": NODE_NEAREST,
            "max_radius_km": NODE_MAX_RADIUS_KM,
            "n_sufficient": len(jobs), "n_insufficient": len(insufficient),
            "highest_node_gate_mc": worst,
            "highest_node_verdict": gate_verdict(worst),
            "note": ("A region too sparse to assess is a finding about the "
                     "evaluation, not an absence of one. Insufficient nodes are "
                     "listed with their counts.")}


def stage_scalemix(df, args):
    """Required by the addendum: the velocity-to-displacement transition reaches
    below the threshold, and b-value feeds the benchmark."""
    out = {}
    for k in SUBSETS:
        s = subset(df, k)
        bins = {}
        for mb, grp in s.groupby(s["magnitude"].round(1)):
            d = int((grp["magnitude_type"].isin(["D", "d"])).sum())
            bins[f"{mb:.1f}"] = {"n": int(len(grp)), "n_displacement": d,
                                 "displacement_share": round(d / len(grp), 4)}
        split = {}
        for name, types in (("velocity", ["V", "v"]), ("displacement", ["D", "d"])):
            m = s[s["magnitude_type"].isin(types)]["magnitude"].to_numpy()
            if len(m) < SCALEMIX_MIN_EVENTS:
                split[name] = {"n_events": int(len(m)),
                               "skipped": f"fewer than {SCALEMIX_MIN_EVENTS} events"}
                continue
            r = assess(m, f"scalemix_{k}_{name}", E2_DRAWS_WINDOW, 0, 5000)
            split[name] = r
        cmp_note = None
        v, d = split.get("velocity"), split.get("displacement")
        if (v and d and v.get("b_value") is not None
                and d.get("b_value") is not None):
            sep = abs(v["b_value"] - d["b_value"])
            tot = (v.get("b_sigma_shi_bolt") or 0) + (d.get("b_sigma_shi_bolt") or 0)
            cmp_note = {
                "b_velocity": v["b_value"], "b_displacement": d["b_value"],
                "separation": round(sep, 4), "combined_sigma": round(tot, 4),
                "differ_beyond_combined_uncertainty": bool(sep > tot),
                "action_if_true": ("reported as a limitation on the benchmark and "
                                   "NOT averaged away, per the amendment"),
            }
        out[k] = {"per_bin": bins, "split_estimates": split,
                  "b_comparison": cmp_note}
        print(f"  subset {k}: {len(bins)} magnitude bins tabulated")
    return out


STAGE_FN = {"headline": stage_headline, "equalsize": stage_equalsize,
            "annual": stage_annual, "moving": stage_moving,
            "spatial": stage_spatial, "scalemix": stage_scalemix}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="D9 magnitude of completeness analysis, implementing the "
                    "protocol locked at commit b7ffa07.")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stages", default=",".join(STAGES))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--force", action="store_true",
                    help="rerun stages whose output already exists")
    ap.add_argument("--no-verify-hash", dest="verify_hash", action="store_false")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    t_start = time.time()
    print("=" * 72)
    print(" PROJECT SENTINEL D9: MAGNITUDE OF COMPLETENESS")
    print(f" protocol locked at {AMENDMENT_COMMIT}, registration {REGISTRATION_DOI}")
    print(f" estimate_mc_d9.py v{SCRIPT_VERSION}, {args.workers} workers")
    print(f" started {dt.datetime.now(dt.timezone.utc).isoformat()}")
    print("=" * 72)

    import seismostats
    sv = getattr(seismostats, "__version__", "unknown")
    print(f"seismostats {sv}")
    if sv != "1.0.1":
        print(f"  WARNING: the amendment pins 1.0.1; this is {sv}. Results may "
              f"differ from the registered protocol.", file=sys.stderr)

    df, digest = load_catalog(args.catalog, args.verify_hash)
    for k in SUBSETS:
        print(f"  subset {k}: {len(subset(df, k)):,} events "
              f"({SUBSETS[k]['role']})")

    wanted = [s.strip() for s in args.stages.split(",") if s.strip()]
    done = {}
    for name in wanted:
        if name not in STAGE_FN:
            sys.exit(f"Unknown stage {name!r}. Choose from {STAGES}.")
        path = os.path.join(args.out, f"d9_{name}.json")
        if os.path.exists(path) and not args.force:
            print(f"\n[{name}] already present, skipping ({path})")
            done[name] = "skipped, output already present"
            continue
        print(f"\n[{name}] starting")
        t0 = time.time()
        try:
            result = STAGE_FN[name](df, args)
        except Exception as e:                      # keep other stages alive
            print(f"[{name}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            done[name] = f"FAILED: {type(e).__name__}: {e}"
            continue
        payload = {
            "stage": name,
            "script": "estimate_mc_d9.py",
            "script_version": SCRIPT_VERSION,
            "seismostats_version": sv,
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "protocol": {"amendment_commit": AMENDMENT_COMMIT,
                         "amendment_sha256": AMENDMENT_SHA256,
                         "registration_doi": REGISTRATION_DOI},
            "catalog_sha256": digest,
            "elapsed_seconds": round(time.time() - t0, 1),
            "result": result,
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"[{name}] done in {payload['elapsed_seconds']}s -> {path}")
        done[name] = f"ok, {payload['elapsed_seconds']}s"

    summary = {
        "script": "estimate_mc_d9.py", "script_version": SCRIPT_VERSION,
        "seismostats_version": sv,
        "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_seconds": round(time.time() - t_start, 1),
        "catalog_sha256": digest,
        "protocol": {"amendment_commit": AMENDMENT_COMMIT,
                     "amendment_sha256": AMENDMENT_SHA256,
                     "registration_doi": REGISTRATION_DOI},
        "locked_parameters": {
            "subsets": {k: {"flags": v["flags"], "role": v["role"]}
                        for k, v in SUBSETS.items()},
            "primary_subset": PRIMARY_SUBSET,
            "trial_grid": [MC_TRIAL_MIN, MC_TRIAL_MAX, DELTA_M],
            "E1_stability_range": E1_STABILITY_RANGE,
            "E2_p_value_pass": E2_PASS_P,
            "E3_correction_factor": E3_CORRECTION,
            "bootstrap_headline": BOOT_HEADLINE,
            "bootstrap_window": BOOT_WINDOW,
            "E2_draws_headline": E2_DRAWS_HEADLINE,
            "E2_draws_window": E2_DRAWS_WINDOW,
            "moving_window": MOVING_WINDOW, "moving_step": MOVING_STEP,
            "grid_deg": GRID_DEG, "node_nearest": NODE_NEAREST,
            "node_max_radius_km": NODE_MAX_RADIUS_KM,
            "equalsize_n": EQUALSIZE_N, "equalsize_draws": EQUALSIZE_DRAWS,
        },
        "gate_rule": ("The D10 gate reads the HIGHEST of E1, E2 and E3, not the "
                      "registered primary. It passes only where all three agree "
                      "Mc is below M4.0."),
        "stages": done,
        "outputs": {},
    }
    for name in STAGES:
        p = os.path.join(args.out, f"d9_{name}.json")
        if os.path.exists(p):
            summary["outputs"][f"d9_{name}.json"] = sha256_file(p)
    sp = os.path.join(args.out, "d9_summary.json")
    with open(sp, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n" + "=" * 72)
    for k, v in done.items():
        print(f"  {k:<12} {v}")
    print(f"  total {summary['total_seconds']}s")
    print(f"\nWritten to {args.out}/")
    print("D9 is not closed until these outputs are committed and the summary "
          "hash is recorded in the registration ledger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
