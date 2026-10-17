#!/usr/bin/env python3
"""
csep_japan_region.py

Loads and verifies the official CSEP-Japan forecast node file.

PROVENANCE
----------
The node file `japan.forecast.nodes` was provided by Dr. Hiroshi Tsuruoka
(Earthquake Research Institute, University of Tokyo) by email on 2026-10-14,
in response to a direct request for the CSEP-Japan testing region definition.

This is the authoritative region definition, not a reconstruction. The earlier
script `build_japan_region.py` reconstructed a candidate region from the
published specification because the region file was not obtainable at the time.
That reconstruction is SUPERSEDED and is retained only as a record that it was
prepared and then discarded in favour of the authoritative file.

FILE FORMAT
-----------
Two whitespace-separated columns, longitude then latitude, in decimal degrees.
One row per spatial cell. No header.

Values are cell MIDPOINTS, not cell origins. This follows the convention pyCSEP
applies to the equivalent Italy and New Zealand node files
(`csep/core/regions.py`, `italy_csep_region` and `nz_csep_region`, both with
`use_midpoint=True` by default, which compute `origins = points - dh/2`).
The Japan file carries the same .X5 fractional offset as both of those files,
which is the signature of midpoints on a 0.1 degree lattice whose cell edges
fall on integer multiples of 0.1.

The midpoint-versus-origin reading shifts every cell assignment by half a cell
in both axes. Confirmed directly by Dr. Tsuruoka, email 2026-10-16: the
coordinates are cell centres and origins are the values minus 0.05 degrees.
The pyCSEP precedent above is retained as independent corroboration.

USAGE
-----
  python3 csep_japan_region.py --verify
  python3 csep_japan_region.py --verify --stations data/geonet_station_roster.csv
  python3 csep_japan_region.py --verify --write-manifest --write-origins

As a library:
  from csep_japan_region import load_midpoints, load_origins, japan_csep_region
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

# Default location of the node file relative to the repository root.
DEFAULT_NODES = "data/csep_japan/japan.forecast.nodes"

# Cell size of the CSEP-Japan 0.1 degree testing classes.
DH = 0.1

# SHA-256 of the file as received, computed on 2026-10-15 before any handling.
# A mismatch means the file was altered in transit, by the mail client, or by a
# text-mode transfer that rewrote line endings. Do not proceed on a mismatch.
EXPECTED_SHA256 = "94f94b19a0b1eaf1db125b0570005c4724b526b0aaf38e91d7482704fe50dcf2"

PROVENANCE = {
    "source": "Dr. Hiroshi Tsuruoka, Earthquake Research Institute, University of Tokyo",
    "source_email": "tsuru@eri.u-tokyo.ac.jp",
    "received": "2026-10-14",
    "received_via": "email attachment, in response to a direct request",
    "filename_as_received": "japan.forecast.nodes",
    "authoritative": True,
    "region_variant": "All Japan testing region",
    "region_variant_confirmed": (
        "Dr. Hiroshi Tsuruoka, email 2026-10-16, in reply to a direct question"
    ),
    "midpoint_convention_confirmed": (
        "Dr. Hiroshi Tsuruoka, email 2026-10-16: coordinates are cell centres, "
        "origins are the values minus 0.05 degrees"
    ),
    "reconstruction_superseded": "build_japan_region.py",
    "midpoint_convention_basis": (
        "pyCSEP 0.8.0 csep/core/regions.py treats the equivalent Italy and New "
        "Zealand node files as midpoints by default (use_midpoint=True, "
        "origins = points - dh/2). The Japan file shares their format and their "
        ".X5 fractional offset."
    ),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_midpoints(path=DEFAULT_NODES):
    """Return an (N, 2) array of cell midpoints as (lon, lat) in degrees."""
    pts = np.loadtxt(path)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(f"{path}: expected two columns, got shape {pts.shape}")
    return pts


def load_origins(path=DEFAULT_NODES, dh=DH):
    """Return an (N, 2) array of cell origins, the lower-left corner of each cell."""
    return load_midpoints(path) - dh / 2.0


def japan_csep_region(path=DEFAULT_NODES, dh_scale=1, magnitudes=None,
                      name="csep-japan", use_midpoint=True):
    """
    Return a pyCSEP CartesianGrid2D for the CSEP-Japan testing region.

    Mirrors csep.core.regions.nz_csep_region, so the Japan region is built by
    the same code path as the regions pyCSEP ships. Requires pycsep installed.
    """
    try:
        from csep.core.regions import CartesianGrid2D, compute_vertices, \
            increase_grid_resolution
        from csep.models import Polygon
    except ImportError as e:
        raise ImportError(
            "pycsep is required for japan_csep_region(). "
            "Install with: pip3 install --break-system-packages pycsep==0.8.0"
        ) from e

    if dh_scale % 2 != 0 and dh_scale != 1:
        raise ValueError("dh_scale must be a factor of two or equal unity.")

    dh = DH
    points = np.loadtxt(path)
    origins = np.array(points) - dh / 2 if use_midpoint else np.array(points)

    if dh_scale > 1:
        origins = increase_grid_resolution(origins, dh, dh_scale)
        dh = dh / dh_scale

    bboxes = compute_vertices(origins, dh)
    return CartesianGrid2D([Polygon(b) for b in bboxes], dh,
                           magnitudes=magnitudes, name=name)


def lattice_keys(pts, dh=DH):
    """Integer lattice index of each cell, derived from its midpoint."""
    return (np.round((pts[:, 0] - dh / 2) / dh).astype(int),
            np.round((pts[:, 1] - dh / 2) / dh).astype(int))


def connected_components(keys_i, keys_j):
    """4-connected components of the cell set, largest first."""
    cells = set(zip(keys_i.tolist(), keys_j.tolist()))
    seen, comps = set(), []
    for c in cells:
        if c in seen:
            continue
        stack, comp = [c], []
        seen.add(c)
        while stack:
            i, j = stack.pop()
            comp.append((i, j))
            for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if n in cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps


def station_coverage(stations_csv, keys_i, keys_j, dh=DH):
    """
    Count roster stations whose position falls inside a region cell.

    Returns (n_inside, n_outside, n_unparsed, examples_inside, examples_outside).
    A station outside the region contributes no usable TEC pierce points for
    this evaluation, so this is the coverage figure the study actually depends on.
    """
    cells = set(zip(keys_i.tolist(), keys_j.tolist()))
    inside, outside, unparsed = 0, 0, 0
    ex_in, ex_out = [], []

    with open(stations_csv, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        cols = rdr.fieldnames or []
        lon_col = next((c for c in ("lon_deg", "lon", "longitude") if c in cols), None)
        lat_col = next((c for c in ("lat_deg", "lat", "latitude") if c in cols), None)
        name_col = next((c for c in ("name_en", "name", "site_id") if c in cols), None)
        if not lon_col or not lat_col:
            raise ValueError(f"{stations_csv}: no longitude/latitude column found in {cols}")

        for row in rdr:
            try:
                lon = float(row[lon_col])
                lat = float(row[lat_col])
            except (TypeError, ValueError):
                unparsed += 1
                continue
            k = (int(np.floor(lon / dh)), int(np.floor(lat / dh)))
            label = (row.get(name_col) or "").strip() or row.get("site_id", "?")
            if k in cells:
                inside += 1
                if len(ex_in) < 6:
                    ex_in.append(label)
            else:
                outside += 1
                if len(ex_out) < 12:
                    ex_out.append(f"{label} ({lon:.2f}, {lat:.2f})")

    return inside, outside, unparsed, ex_in, ex_out


def main():
    ap = argparse.ArgumentParser(description="Verify the CSEP-Japan node file.")
    ap.add_argument("--nodes", default=DEFAULT_NODES, help=f"Node file (default {DEFAULT_NODES})")
    ap.add_argument("--verify", action="store_true", help="Run all checks and print a report")
    ap.add_argument("--stations", help="GEONET roster CSV, to report station coverage")
    ap.add_argument("--write-manifest", action="store_true",
                    help="Write data/csep_japan_region_manifest.json")
    ap.add_argument("--write-origins", action="store_true",
                    help="Write data/csep_japan_region_origins.csv")
    args = ap.parse_args()

    if not os.path.exists(args.nodes):
        sys.exit(f"Node file not found: {args.nodes}\n"
                 f"Upload japan.forecast.nodes and place it there first.")

    digest = sha256_file(args.nodes)
    pts = load_midpoints(args.nodes)
    lon, lat = pts[:, 0], pts[:, 1]
    ki, kj = lattice_keys(pts)
    n_unique = len({(a, b) for a, b in zip(ki.tolist(), kj.tolist())})

    ulon, ulat = np.unique(lon), np.unique(lat)
    dlon = np.diff(ulon)
    dlat = np.diff(ulat)
    frac_lon = sorted({int(round((v * 100) % 10)) for v in lon})
    frac_lat = sorted({int(round((v * 100) % 10)) for v in lat})
    comps = connected_components(ki, kj)

    checks = []

    def check(label, ok, detail=""):
        checks.append((label, ok, detail))

    check("SHA-256 matches the file as received", digest == EXPECTED_SHA256,
          digest if digest == EXPECTED_SHA256 else f"got {digest}, expected {EXPECTED_SHA256}")
    check("No duplicate cells", n_unique == len(pts), f"{len(pts)} rows, {n_unique} unique cells")
    check("Longitude spacing is a uniform 0.1 deg",
          len(dlon) > 0 and np.allclose(dlon, DH, atol=1e-9),
          f"min {dlon.min():.4f}, max {dlon.max():.4f}" if len(dlon) else "")
    check("Latitude spacing is a uniform 0.1 deg",
          len(dlat) > 0 and np.allclose(dlat, DH, atol=1e-9),
          f"min {dlat.min():.4f}, max {dlat.max():.4f}" if len(dlat) else "")
    check("All values carry the .X5 midpoint offset",
          frac_lon == [5] and frac_lat == [5],
          f"lon offsets {frac_lon}, lat offsets {frac_lat}")
    check("Region is a single 4-connected component", len(comps) == 1,
          f"{len(comps)} component(s): {[len(c) for c in comps][:8]}")

    print("CSEP-Japan region file verification")
    print("=" * 64)
    print(f"File       {args.nodes}")
    print(f"SHA-256    {digest}")
    print(f"Cells      {len(pts):,}")
    print(f"Longitude  {lon.min():.2f} to {lon.max():.2f}   ({len(ulon)} distinct columns)")
    print(f"Latitude   {lat.min():.2f} to {lat.max():.2f}   ({len(ulat)} distinct rows)")
    print(f"Cell size  {DH} deg, midpoint convention, origins = midpoint - {DH/2}")
    print(f"Area       approx {len(pts) * DH * DH * 111.32 * 111.32 * np.cos(np.radians(lat.mean())):,.0f} km2 "
          f"(nominal, cos(mean lat) only)")
    print()
    print("Checks")
    print("-" * 64)
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if detail and not ok:
            print(f"        {detail}")
        elif detail and label.startswith("No duplicate"):
            print(f"        {detail}")
    print()

    print("Coverage of named island groups")
    print("-" * 64)
    groups = [
        ("Sakishima / Yaeyama", 122.0, 126.0, 23.0, 26.0),
        ("Okinawa / Amami", 126.0, 130.0, 25.5, 29.0),
        ("Amami / Tokara", 129.9, 130.6, 26.8, 27.6),
        ("Daito Islands", 130.8, 131.6, 25.4, 26.3),
        ("Izu-Ogasawara / Bonin", 139.0, 143.5, 23.0, 29.0),
        ("Minamitorishima", 152.0, 156.0, 23.0, 26.0),
        ("Okinotorishima", 135.0, 137.5, 19.5, 21.5),
        ("Kanto", 138.0, 141.0, 34.0, 37.0),
        ("Hokkaido and offshore", 139.0, 147.6, 41.0, 46.6),
    ]
    for nm, lo1, lo2, la1, la2 in groups:
        m = (lon >= lo1) & (lon <= lo2) & (lat >= la1) & (lat <= la2)
        print(f"  {nm:<24} {int(m.sum()):>6,} cells")
    print()

    if args.stations:
        if not os.path.exists(args.stations):
            print(f"Station roster not found: {args.stations}")
        else:
            n_in, n_out, n_bad, ex_in, ex_out = station_coverage(args.stations, ki, kj)
            total = n_in + n_out
            print("GEONET station coverage of the region")
            print("-" * 64)
            print(f"  Inside the region   {n_in:>6,}  ({100.0*n_in/total:.1f}% of {total:,} located)")
            print(f"  Outside the region  {n_out:>6,}")
            if n_bad:
                print(f"  Unparsed rows       {n_bad:>6,}")
            if ex_out:
                print("  Outside, examples:")
                for e in ex_out:
                    print(f"      {e}")
            print()
            print("  Stations outside the region contribute no pierce points inside it.")
            print("  This count is the input to the D16 station subset decision.")
            print()

    if args.write_origins:
        os.makedirs("data", exist_ok=True)
        out = "data/csep_japan_region_origins.csv"
        origins = pts - DH / 2.0
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["cell_index", "origin_lon_deg", "origin_lat_deg",
                        "midpoint_lon_deg", "midpoint_lat_deg", "dh_deg"])
            for n, ((ox, oy), (mx, my)) in enumerate(zip(origins, pts)):
                w.writerow([n, f"{ox:.4f}", f"{oy:.4f}", f"{mx:.4f}", f"{my:.4f}", DH])
        print(f"Wrote {out}  ({len(pts):,} rows)")

    if args.write_manifest:
        os.makedirs("data", exist_ok=True)
        manifest = {
            "region": "CSEP-Japan testing region",
            "region_variant": "All Japan testing region",
            "region_variant_basis": (
                "Confirmed by Dr. Hiroshi Tsuruoka (Earthquake Research Institute, "
                "University of Tokyo) by email 2026-10-16, in reply to a direct "
                "question. Independently consistent with the file itself: 0.1 deg "
                "cells, offshore coverage and the full Ryukyu arc together "
                "distinguish All Japan from the Mainland and Kanto regions."
            ),
            "coordinate_convention_basis": (
                "Confirmed by Dr. Tsuruoka, email 2026-10-16. Corroborated by "
                "pyCSEP 0.8.0, which applies the same midpoint convention to the "
                "equivalent Italy and New Zealand node files."
            ),
            "provenance": PROVENANCE,
            "file": os.path.basename(args.nodes),
            "sha256": digest,
            "sha256_matches_as_received": digest == EXPECTED_SHA256,
            "n_cells": int(len(pts)),
            "n_unique_cells": int(n_unique),
            "dh_deg": DH,
            "coordinate_convention": "cell midpoints; origins = midpoint - dh/2",
            "bounds_midpoints": {
                "lon_min": float(lon.min()), "lon_max": float(lon.max()),
                "lat_min": float(lat.min()), "lat_max": float(lat.max()),
            },
            "n_distinct_lon_columns": int(len(ulon)),
            "n_distinct_lat_rows": int(len(ulat)),
            "n_connected_components_4": len(comps),
            "component_sizes": [len(c) for c in comps],
            "checks": [{"check": c, "pass": bool(k)} for c, k, _ in checks],
            "verified_utc": datetime.now(timezone.utc).isoformat(),
        }
        out = "data/csep_japan_region_manifest.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Wrote {out}")

    failed = [c for c, ok, _ in checks if not ok]
    if failed:
        print()
        print(f"{len(failed)} check(s) failed. Do not build on this file until resolved.")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
