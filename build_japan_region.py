#!/usr/bin/env python3
"""
build_japan_region.py

================================================================================
SUPERSEDED 2026-10-14. DO NOT USE. RETAINED AS A RECORD ONLY.
================================================================================

The authoritative CSEP-Japan region definition was obtained from Dr. Hiroshi
Tsuruoka (Earthquake Research Institute, University of Tokyo) on 2026-10-14 and
is committed at data/csep_japan/japan.forecast.nodes. Use csep_japan_region.py.

This script is kept in the repository on purpose. It is evidence that the region
used in the study was requested from the testing centre and adopted unmodified,
rather than constructed by us and then tuned. A reviewer asking whether the
region boundaries could have been chosen to favour a result can see that the
only region we ever built was discarded the moment the real one arrived.

Where the two differ, and why it matters:

    Island group            This reconstruction        Authoritative region
    ---------------------   ------------------------   ---------------------
    Sakishima / Yaeyama     separate comp, 1,034       included, 863 cells
    Okinawa / Amami         in main component          included, 1,137 cells
    Izu-Ogasawara / Bonin   separate comp, 1,206       EXCLUDED entirely
    Daito Islands           separate comp, 318         EXCLUDED
    Minamitorishima         separate comp, 286         EXCLUDED
    Okinotorishima          absent from source         EXCLUDED

    Totals: 5 components, ~16,657 cells   vs   1 component, 20,062 cells

The Izu-Ogasawara row is the substantive one. A 100 km land buffer pulls in a
seismically very active arc that CSEP does not include, and a seismicity-only
argument would have favoured keeping it. That decision is now cited rather than
defended.

Running this script requires the Natural Earth 1:10m Admin 0 Countries shapefile
in ne_10m/, which is NOT committed. The script is preserved for its reasoning and
its record of what was decided, not to be re-executed.

================================================================================

Constructs a CSEP-style gridded testing region for Japan from the published
specification, for use with pyCSEP and floatCSEP.

PROVENANCE AND HONEST LABELLING
-------------------------------
This is a RECONSTRUCTION, not the CSEP-Japan region file.

Tsuruoka et al. (2012), Earth Planets Space 64:661-671, doi:10.5047/eps.2012.06.007,
specifies the "All Japan" testing region as:

    "covers the whole territory of Japan including about 100 km offshore and
     down to a depth of 100 km with a node spacing of 0.1 degrees"

The original node definitions were requested from the CSEP-Japan testing center
at the Earthquake Research Institute, University of Tokyo, and were not
obtainable. pyCSEP 0.8.0 ships region definitions for California, Italy and New
Zealand only. This script therefore derives a region from the published
specification using a public territory boundary, documenting every step so a
reviewer can reproduce it exactly.

Any publication using this region must describe it as constructed following the
published CSEP-Japan All Japan specification, not as the CSEP-Japan region.

DERIVATION
----------
1. Territory boundary: Natural Earth 1:10m Admin 0 Countries, feature where
   ADMIN or SOVEREIGNT is Japan. Natural Earth is public domain.
2. Offshore buffer: 100 km, computed in an azimuthal equidistant projection
   centred on the Japanese archipelago (lat_0=36, lon_0=138, WGS84), then
   reprojected to geographic coordinates. An equidistant projection is used so
   that the buffer distance is true in all directions from the centre.
3. Grid: 0.1 degree spacing, cell origins on a lattice aligned to integer
   multiples of 0.1 degrees from zero. Following the CSEP convention used by
   pyCSEP, the origin of a cell is its lower-left corner (minimum latitude and
   minimum longitude).
4. Cell inclusion rule: a cell is included when its CENTRE falls inside the
   buffered territory polygon. Centre-in is used rather than any-intersection
   because it is unambiguous and does not inflate the region at the coastline.
5. Contiguity: connected components of the included cell set are computed with
   4-connectivity (cells sharing an edge). Components are reported with their
   sizes and bounding boxes. By DEFAULT only the largest component is kept.
   Every other component must be added back explicitly with --keep.

   A size threshold is deliberately NOT the default. A 100 km buffer around any
   isolated island produces a disc of roughly 0.9 degrees radius, which grids to
   about 300 cells regardless of how small the island is. A threshold large
   enough to drop a remote outpost would also be large enough to drop a genuine
   island arc, and the decision would be made by a magic number rather than by a
   person. The components kept and dropped are written to the manifest either
   way, so the choice is on the record.

The depth limit of 100 km in the published specification constrains catalog
filtering, not the 2D region, and is recorded in the manifest for use at that
stage.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
-----------------------------------------
It does not alter the published testing-class parameters. Magnitude range,
magnitude bin width, time window and catalog rules are taken unchanged from
Tsuruoka et al. (2012) and are recorded in the manifest for reference:

    magnitude range   4.0 <= M <= 9.0 in 0.1 magnitude unit bins
                      (bin M=4.0 covers 3.95 <= M < 4.05)
    1-day class       consecutive 1-day windows starting midnight UTC
    3-month class     as 1-day, with a 3-month window
    1-year / 3-year   5.0 <= M <= 9.0
    catalog           JMA, undeclustered, data after 1965 only
    node spacing      0.1 degrees (All Japan and Mainland), 0.05 (Kanto)

Relaxing any of these while also constructing the geometry is how selection on
the outcome enters a study. They are held fixed.

USAGE
-----
  pip3 install --break-system-packages pyshp shapely pyproj numpy

  # fetch the territory shapefile once
  python3 build_japan_region.py --download

  # build the region
  python3 build_japan_region.py --shapefile ne_10m/ne_10m_admin_0_countries.shp

  # inspect components without committing to a selection
  python3 build_japan_region.py --shapefile ... --report-only

  # keep specific components by index, overriding the size rule
  python3 build_japan_region.py --shapefile ... --keep 0,1

OUTPUTS
-------
  japan_region_origins.csv    lon,lat of cell origins (lower-left corners),
                              directly loadable into
                              csep.core.regions.CartesianGrid2D.from_origins
  japan_region_manifest.json  full derivation record, parameters, component
                              report, checksums, and the published class
                              parameters above
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from collections import deque
from datetime import datetime, timezone

try:
    import numpy as np
    import shapefile  # pyshp
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union, transform as shp_transform
    from shapely.prepared import prep
    from pyproj import CRS, Transformer
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\n"
             "Run: pip3 install --break-system-packages pyshp shapely pyproj numpy")


# Natural Earth 1:10m Admin 0 Countries. Public domain.
NE_URLS = [
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip",
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip",
]

SPEC_SOURCE = ("Tsuruoka, H., Hirata, N., Schorlemmer, D., Euchner, F., Nanjo, K.Z., "
               "Jordan, T.H. (2012). CSEP Testing Center and the first results of the "
               "earthquake forecast testing experiment in Japan. Earth, Planets and "
               "Space 64, 661-671. doi:10.5047/eps.2012.06.007")

PUBLISHED_CLASS_PARAMS = {
    "node_spacing_deg_all_japan": 0.1,
    "node_spacing_deg_mainland": 0.1,
    "node_spacing_deg_kanto": 0.05,
    "depth_limit_km_all_japan": 100,
    "depth_limit_km_mainland": 30,
    "depth_limit_km_kanto": 100,
    "magnitude_range_1day_3month": "4.0 <= M <= 9.0, 0.1 magnitude unit bins",
    "magnitude_range_1year_3year": "5.0 <= M <= 9.0, 0.1 magnitude unit bins",
    "magnitude_bin_convention": "bin M=4.0 covers 3.95 <= M < 4.05",
    "time_window_1day": "consecutive 1-day windows beginning midnight UTC",
    "catalog": "Japan Meteorological Agency (JMA)",
    "catalog_declustering": "none; neither testing nor learning catalog is declustered",
    "catalog_start": "1965 (JMA magnitude recomputation incomplete before this)",
    "catalog_latency": "6 months, to allow manual revision of locations",
    "source": SPEC_SOURCE,
}


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_natural_earth(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    last_err = None
    for url in NE_URLS:
        try:
            log(f"Downloading {url}")
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(dest_dir)
            shp = os.path.join(dest_dir, "ne_10m_admin_0_countries.shp")
            if os.path.exists(shp):
                log(f"Extracted to {dest_dir}")
                return shp
        except Exception as e:
            last_err = e
            log(f"  failed: {e}")
    sys.exit(f"Could not download Natural Earth data. Last error: {last_err}\n"
             "Download ne_10m_admin_0_countries.zip manually, extract it, and pass "
             "--shapefile <path to .shp>")


def load_japan(shp_path):
    """Read the Japan feature from a Natural Earth admin_0_countries shapefile."""
    sf = shapefile.Reader(shp_path)
    fields = [f[0] for f in sf.fields[1:]]
    name_fields = [f for f in ("ADMIN", "SOVEREIGNT", "NAME", "NAME_LONG") if f in fields]
    if not name_fields:
        sys.exit(f"No recognisable name field in {shp_path}. Fields: {fields}")

    geoms = []
    matched_attrs = None
    for rec in sf.shapeRecords():
        attrs = dict(zip(fields, rec.record))
        if any(str(attrs.get(f, "")).strip().lower() == "japan" for f in name_fields):
            geoms.append(shape(rec.shape.__geo_interface__))
            if matched_attrs is None:
                matched_attrs = {f: attrs.get(f) for f in name_fields}

    if not geoms:
        sys.exit("No feature named Japan found in the shapefile.")

    geom = unary_union(geoms)
    log(f"Japan territory loaded: {len(geoms)} feature(s), "
        f"{len(getattr(geom, 'geoms', [geom]))} polygon part(s)")
    return geom, matched_attrs


def buffer_km(geom_wgs84, km, lat_0=36.0, lon_0=138.0):
    """Buffer a geographic geometry by km, via an azimuthal equidistant projection."""
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={lat_0} +lon_0={lon_0} "
                          f"+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs")
    wgs84 = CRS.from_epsg(4326)
    fwd = Transformer.from_crs(wgs84, aeqd, always_xy=True).transform
    inv = Transformer.from_crs(aeqd, wgs84, always_xy=True).transform

    projected = shp_transform(fwd, geom_wgs84)
    buffered = projected.buffer(km * 1000.0)
    return shp_transform(inv, buffered)


def grid_region(poly, dh):
    """
    Generate 0.1-degree cell origins whose cell centres fall inside poly.
    Origins lie on a lattice aligned to integer multiples of dh from zero.
    Returns a dict of (i, j) integer lattice index -> (lon_origin, lat_origin).
    """
    minx, miny, maxx, maxy = poly.bounds
    i0, i1 = int(np.floor(minx / dh)), int(np.ceil(maxx / dh))
    j0, j1 = int(np.floor(miny / dh)), int(np.ceil(maxy / dh))
    log(f"Candidate lattice: {i1 - i0} x {j1 - j0} = {(i1 - i0) * (j1 - j0):,} cells")

    prepared = prep(poly)
    cells = {}
    for i in range(i0, i1 + 1):
        lon_o = round(i * dh, 10)
        lon_c = lon_o + dh / 2.0
        for j in range(j0, j1 + 1):
            lat_o = round(j * dh, 10)
            if prepared.contains(Point(lon_c, lat_o + dh / 2.0)):
                cells[(i, j)] = (lon_o, lat_o)
    log(f"Cells with centre inside the buffered territory: {len(cells):,}")
    return cells


def connected_components(cells):
    """4-connected components of the lattice cell set, largest first."""
    unseen = set(cells)
    comps = []
    while unseen:
        seed = next(iter(unseen))
        unseen.discard(seed)
        comp, q = {seed}, deque([seed])
        while q:
            i, j = q.popleft()
            for nb in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if nb in unseen:
                    unseen.discard(nb)
                    comp.add(nb)
                    q.append(nb)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps


def component_report(comps, cells, dh):
    rows = []
    for idx, comp in enumerate(comps):
        lons = [cells[k][0] for k in comp]
        lats = [cells[k][1] for k in comp]
        rows.append({
            "index": idx,
            "n_cells": len(comp),
            "lon_min": round(min(lons), 4),
            "lon_max": round(max(lons) + dh, 4),
            "lat_min": round(min(lats), 4),
            "lat_max": round(max(lats) + dh, 4),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Construct a CSEP-style gridded region for Japan from the "
                    "published All Japan specification.")
    ap.add_argument("--download", action="store_true",
                    help="Download the Natural Earth territory shapefile and exit")
    ap.add_argument("--ne-dir", default="ne_10m",
                    help="Directory for the Natural Earth shapefile (default ne_10m)")
    ap.add_argument("--shapefile", default=None,
                    help="Path to ne_10m_admin_0_countries.shp")
    ap.add_argument("--buffer-km", type=float, default=100.0,
                    help="Offshore buffer in km (default 100, per the published spec)")
    ap.add_argument("--dh", type=float, default=0.1,
                    help="Node spacing in degrees (default 0.1, per the published spec)")
    ap.add_argument("--min-component", type=int, default=None,
                    help="Alternative selection: keep components with at least this "
                         "many cells. Note that a 100 km buffer around any isolated "
                         "island grids to roughly 300 cells, so small thresholds do "
                         "not filter remote outposts")
    ap.add_argument("--keep", default=None,
                    help="Comma-separated component indices to keep. Run "
                         "--report-only first to see the indices. Overrides the "
                         "default of largest-component-only")
    ap.add_argument("--report-only", action="store_true",
                    help="Report connected components and exit without writing output")
    ap.add_argument("--out-prefix", default="japan_region")
    args = ap.parse_args()

    if args.download:
        download_natural_earth(args.ne_dir)
        return

    shp_path = args.shapefile or os.path.join(args.ne_dir, "ne_10m_admin_0_countries.shp")
    if not os.path.exists(shp_path):
        sys.exit(f"Shapefile not found: {shp_path}\nRun with --download first.")

    log(f"Territory source: {shp_path}")
    territory, matched = load_japan(shp_path)

    log(f"Buffering by {args.buffer_km} km in azimuthal equidistant projection "
        f"(lat_0=36, lon_0=138)")
    buffered = buffer_km(territory, args.buffer_km)

    cells = grid_region(buffered, args.dh)
    if not cells:
        sys.exit("No cells generated. Check the territory geometry.")

    comps = connected_components(cells)
    report = component_report(comps, cells, args.dh)

    log("")
    log("Connected components (4-connectivity), largest first:")
    log(f"  {'idx':>4} {'cells':>8}   {'lat range':<20} {'lon range':<20}")
    for r in report:
        log(f"  {r['index']:>4} {r['n_cells']:>8}   "
            f"{r['lat_min']:>7.2f} to {r['lat_max']:<7.2f}  "
            f"{r['lon_min']:>7.2f} to {r['lon_max']:<7.2f}")
    log("")

    if args.report_only:
        log("--report-only set. No output written.")
        return

    if args.keep:
        keep_idx = sorted({int(x) for x in args.keep.split(",") if x.strip() != ""})
        bad = [i for i in keep_idx if i < 0 or i >= len(comps)]
        if bad:
            sys.exit(f"--keep refers to component index/indices that do not exist: {bad}. "
                     f"Valid range is 0 to {len(comps) - 1}.")
        selection_rule = f"explicit --keep {args.keep}"
    elif args.min_component is not None:
        keep_idx = [r["index"] for r in report if r["n_cells"] >= args.min_component]
        selection_rule = f"components with >= {args.min_component} cells"
    else:
        keep_idx = [0]
        selection_rule = ("default: largest component only; every other component "
                          "requires an explicit --keep")

    if not keep_idx:
        sys.exit("Selection kept zero components. Use --keep or lower --min-component.")

    if len(comps) > 1 and not args.keep and args.min_component is None:
        log("")
        log("NOTE: more than one component exists and only the largest is being kept.")
        log("      Review the table above. If a dropped component belongs in the")
        log("      region, rerun with --keep listing every index you want.")

    kept_keys = set()
    for idx in keep_idx:
        kept_keys |= comps[idx]
    dropped = [r for r in report if r["index"] not in keep_idx]

    log(f"Selection rule: {selection_rule}")
    log(f"  kept    components {keep_idx}  ({len(kept_keys):,} cells)")
    if dropped:
        log(f"  dropped {len(dropped)} component(s):")
        for r in dropped:
            log(f"    idx {r['index']}: {r['n_cells']} cell(s) at "
                f"{r['lat_min']:.2f} N, {r['lon_min']:.2f} E")

    origins = sorted((cells[k] for k in kept_keys), key=lambda t: (t[1], t[0]))

    csv_path = f"{args.out_prefix}_origins.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lon", "lat"])
        for lon, lat in origins:
            w.writerow([f"{lon:.4f}", f"{lat:.4f}"])

    lons = [o[0] for o in origins]
    lats = [o[1] for o in origins]

    manifest = {
        "label": "Reconstruction of the CSEP-Japan All Japan testing region",
        "warning": ("This is NOT the CSEP-Japan region file. It is constructed from "
                    "the published specification because the original node "
                    "definitions were not obtainable. Describe it as such in any "
                    "publication."),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "specification_source": SPEC_SOURCE,
        "specification_text": ("covers the whole territory of Japan including about "
                               "100 km offshore and down to a depth of 100 km with a "
                               "node spacing of 0.1 degrees"),
        "derivation": {
            "territory_source": "Natural Earth 1:10m Admin 0 Countries (public domain)",
            "territory_file": os.path.abspath(shp_path),
            "territory_file_sha256": sha256_file(shp_path),
            "territory_feature_match": matched,
            "buffer_km": args.buffer_km,
            "buffer_projection": "+proj=aeqd +lat_0=36 +lon_0=138 +datum=WGS84 +units=m",
            "node_spacing_deg": args.dh,
            "lattice_alignment": "origins at integer multiples of node spacing from zero",
            "cell_origin_convention": "lower-left corner (minimum lat, minimum lon)",
            "cell_inclusion_rule": "cell centre inside the buffered territory polygon",
            "connectivity": "4-connected (cells sharing an edge)",
            "component_selection_rule": selection_rule,
            "components_kept": keep_idx,
            "components_dropped": dropped,
        },
        "region": {
            "n_cells": len(origins),
            "lon_min": round(min(lons), 4),
            "lon_max": round(max(lons) + args.dh, 4),
            "lat_min": round(min(lats), 4),
            "lat_max": round(max(lats) + args.dh, 4),
            "origins_csv": os.path.abspath(csv_path),
        },
        "all_components": report,
        "published_class_parameters_unchanged": PUBLISHED_CLASS_PARAMS,
        "pycsep_usage": (
            "import numpy as np, csv\n"
            "from csep.core.regions import CartesianGrid2D, magnitude_bins, "
            "create_space_magnitude_region\n"
            f"origins = np.loadtxt('{csv_path}', delimiter=',', skiprows=1)\n"
            f"region = CartesianGrid2D.from_origins(origins, dh={args.dh}, "
            "name='japan_allregion_reconstructed')\n"
            "mags = magnitude_bins(3.95, 9.05, 0.1)\n"
            "region = create_space_magnitude_region(region, mags)"
        ),
    }

    manifest_path = f"{args.out_prefix}_manifest.json"
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    log("")
    log(f"Wrote {csv_path}: {len(origins):,} cell origins")
    log(f"Wrote {manifest_path}")
    log(f"  latitude  {min(lats):.2f} to {max(lats) + args.dh:.2f}")
    log(f"  longitude {min(lons):.2f} to {max(lons) + args.dh:.2f}")
    log(f"  origins csv sha256 {sha256_file(csv_path)[:16]}...")


if __name__ == "__main__":
    main()
