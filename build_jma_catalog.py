#!/usr/bin/env python3
"""
build_jma_catalog.py

Builds the Project Sentinel target earthquake catalog from the JMA Seismological
Bulletin hypocenter files, applying the nine pre-registered filtering rules in
the order they were registered, and reporting how many events each rule removes.

PRE-REGISTRATION
----------------
The rules implemented here are fixed in:

  docs/BLOCK1_ADDENDUM_testing_class_and_threshold_2026-10-19.docx
  committed 3b4f784, sha256 5251152d5d4cec398e7e6113c9e6ec06c87fedf7ed20fe5e10780c83e0f46d12

and in the OSF pre-registration:

  DOI 10.17605/OSF.IO/H5MD2, registered and archived 2026-11-09

This script implements those rules. It does not interpret them, extend them, or
improve on them. Where a rule does not cover a case the data actually contains,
this script does NOT invent a rule: it excludes the event under the rule that
could not be satisfied and reports the count separately under "open questions"
so the decision is visible and can be settled by amendment. See REGISTERED RULE
WATCH below for the three such cases known at the time of writing.

Closes gate item D8. Feeds D9 (magnitude of completeness) and D10 (target event
count, the hard gate).

RULES AS REGISTERED
-------------------
Applied in this order. Rules 1 and 2 are conversions and remove nothing; they
are listed because the registered rule set lists them and because applying them
out of order would silently corrupt every later test.

  1  Time zone        JMA hypocenter times are Japan Standard Time, UTC+9. All
                      origin times converted to UTC before any other step.
  2  Coordinates      Latitude and longitude are recorded as integer degrees
                      plus decimal minutes, not decimal degrees. Converted
                      before any spatial test.
  3  Window           Origin time within 2016-01-01T00:00:00Z to
                      2023-12-31T23:59:59Z.
  4  Region           Epicentre falls inside a cell of the adopted CSEP-Japan
                      All Japan region, 20,062 cells at 0.1 degree, using cell
                      origins obtained as midpoint minus 0.05 degrees.
  5  Depth            Depth less than or equal to 100 km, per the published All
                      Japan region definition.
  6  Event type       Subsidiary information code (column 61) equal to 1,
                      natural earthquake. Excludes artificial events (3),
                      eruption earthquakes and others (4), and low-frequency
                      earthquakes (5).
  7  Solution quality Hypocenter determination flag (column 96) not N
                      (undetermined, not accepted, or fixed) and not F (far
                      field). Location precision (column 60) not 8 (undetermined
                      or not accepted).
  8  Magnitude scale  JMA magnitude per section 3. Take the first magnitude if
                      its type code is one of V, v, D or d. Otherwise take the
                      second magnitude if its type code is one of those four.
                      Otherwise exclude the event.
  9  Threshold        M greater than or equal to 4.0, with the 0.1 bin
                      convention of section 3 (the M = 4.0 bin covers
                      3.95 <= M < 4.05).

Declustering: none, per the addendum, following published CSEP-Japan practice.

REGISTERED RULE WATCH
---------------------
Three cases are not covered by the nine rules as written. This script applies
the rules literally and counts each case so the effect is measured rather than
assumed. None is silently resolved.

  W1  Magnitude type code J (MJ). JMA documentation lists J alongside V, v, D
      and d as a JMA magnitude. The registered rule enumerates only V, v, D, d,
      so an event whose only magnitude carries type J is excluded by rule 8 as
      written. No J-coded event appeared in the 2023 catalog year during format
      verification. If the count below is non-zero and material, that is an
      amendment question, not a thing to fix in code.

  W2  Record type (column 1). Values are J (JMA), U (USGS), I (other
      international). The registered rules do not filter on record type. This
      script does not add such a filter. It reports how many non-J records
      survive all nine rules.

  W3  Missing depth. Rule 5 requires depth <= 100 km. An event with no depth
      value cannot be shown to satisfy it, so it is excluded under rule 5 and
      counted separately as depth-missing rather than folded into the
      depth-exceeded count.

MODES
-----
Default mode builds the registered target catalog at M >= 4.0.

--working-catalog builds the D9 sub-threshold working catalog: rules 1 through 8
applied exactly as registered, rule 9 relaxed to --min-magnitude. It exists
because magnitude of completeness cannot be estimated from a catalog truncated
at the completeness threshold; the estimate needs the roll-off below it. The
working catalog is written under the jma_mc_working_ prefix, is never evaluated,
and does not supersede or widen the registered catalog. The mode refuses a floor
at or above the registered threshold, refuses --min-magnitude without
--working-catalog, and verifies after writing that every registered output file
is byte-identical to what it was before the run.

OUTPUTS
-------
  <out>/jma_target_catalog.csv        the target catalog, UTC, decimal degrees
  <out>/jma_attrition.json            per-rule attrition, machine readable
  <out>/jma_attrition.md              per-rule attrition, for the manuscript
  <out>/jma_catalog_manifest.json     provenance: input hashes, output hashes,
                                      rule text, counts, tool versions
  <out>/jma_excluded_sample.csv       up to N excluded records per rule, for
                                      spot-checking the filters by hand

USAGE
-----
  # Prove the parser against the registered fixtures before trusting it
  python3 build_jma_catalog.py --selftest

  # Confirm the column map empirically against a real file, no filtering
  python3 build_jma_catalog.py --verify-format --zips data/jma_catalog

  # Build the catalog
  python3 build_jma_catalog.py \
      --zips data/jma_catalog \
      --region data/csep_japan/japan.forecast.nodes \
      --out data/jma_catalog

  # Build the D9 sub-threshold working catalog (never the evaluation set)
  python3 build_jma_catalog.py \
      --zips data/jma_catalog \
      --region data/csep_japan/japan.forecast.nodes \
      --out data/jma_catalog \
      --working-catalog --min-magnitude 1.0

Run --selftest and --verify-format before the first production run. The column
map below is taken from JMA's published hypocenter format description. Asserting
a fixed-width layout without checking it against the actual bytes is the single
most likely way for this script to be quietly wrong.

Author: Joseph Charles Tulloss, The Synexis Project
License: Apache-2.0
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import sys
import zipfile
from collections import Counter, OrderedDict

SCRIPT_VERSION = "1.1.0"

# ---------------------------------------------------------------------------
# Pre-registration anchors. Verified, not asserted: --selftest checks the
# region file hash when a region file is supplied.
# ---------------------------------------------------------------------------

ADDENDUM_SHA256 = "5251152d5d4cec398e7e6113c9e6ec06c87fedf7ed20fe5e10780c83e0f46d12"
ADDENDUM_COMMIT = "3b4f784"
REGISTRATION_DOI = "10.17605/OSF.IO/H5MD2"
REGION_SHA256 = "94f94b19a0b1eaf1db125b0570005c4724b526b0aaf38e91d7482704fe50dcf2"
REGION_N_CELLS = 20062

# Registered window, rule 3. UTC.
WINDOW_START = dt.datetime(2016, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
WINDOW_END = dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)

# Registered threshold and bin convention, rules 9 and section 3.
# The M = 4.0 bin covers 3.95 <= M < 4.05, so the inclusion test is M >= 3.95.
MAG_THRESHOLD_NOMINAL = 4.0
MAG_BIN_WIDTH = 0.1
MAG_INCLUSION_FLOOR = MAG_THRESHOLD_NOMINAL - MAG_BIN_WIDTH / 2.0  # 3.95

# Registered depth limit, rule 5.
DEPTH_MAX_KM = 100.0

# Registered magnitude type codes, rule 8 / section 3.
JMA_MAG_CODES = ("V", "v", "D", "d")

# Registered region geometry.
DH_DEG = 0.1
MIDPOINT_OFFSET_DEG = 0.05

# Lattice arithmetic is done in exact integers to avoid float boundary errors.
# Coordinates arrive as integer degrees plus hundredths of a minute, so one
# degree is exactly 6000 units and one 0.1-degree cell is exactly 600 units.
UNITS_PER_DEGREE = 6000
UNITS_PER_CELL = 600

JST = dt.timezone(dt.timedelta(hours=9))

# ---------------------------------------------------------------------------
# JMA hypocenter record layout.
#
# Source: JMA, "Format of hypocenter data",
#   https://www.data.jma.go.jp/eqev/data/bulletin/data/format/fmthyp_e.html
#
# Columns below are the published 1-based inclusive ranges. SLICES holds the
# equivalent 0-based Python byte slices. Records are sliced as BYTES, never as
# decoded text: the region-name field can carry multi-byte characters, and
# decoding the whole line first would shift every column after it.
# ---------------------------------------------------------------------------

COLUMNS = OrderedDict([
    # name                 (col_start, col_end)   1-based inclusive
    ("record_type",        (1, 1)),
    ("year",               (2, 5)),
    ("month",              (6, 7)),
    ("day",                (8, 9)),
    ("hour",               (10, 11)),
    ("minute",             (12, 13)),
    ("second",             (14, 17)),    # F4.2, hundredths implied
    ("origin_time_error",  (18, 21)),
    ("lat_deg",            (22, 24)),
    ("lat_min",            (25, 28)),    # F4.2, hundredths of a minute
    ("lat_error",          (29, 32)),
    ("lon_deg",            (33, 36)),
    ("lon_min",            (37, 40)),    # F4.2, hundredths of a minute
    ("lon_error",          (41, 44)),
    ("depth",              (45, 49)),    # F5.2, or I3 + 2 blanks for slice
    ("depth_error",        (50, 52)),
    ("mag1",               (53, 54)),    # F2.1, letter-coded if negative
    ("mag1_type",          (55, 55)),
    ("mag2",               (56, 57)),
    ("mag2_type",          (58, 58)),
    ("travel_time_table",  (59, 59)),
    ("location_precision", (60, 60)),
    ("subsidiary_info",    (61, 61)),
    ("max_intensity",      (62, 62)),
    ("damage_class",       (63, 63)),
    ("tsunami_class",      (64, 64)),
    ("district_number",    (65, 65)),
    ("region_number",      (66, 68)),
    ("region_name",        (69, 92)),
    ("n_stations",         (93, 95)),
    ("determination_flag", (96, 96)),
])

SLICES = {k: slice(a - 1, b) for k, (a, b) in COLUMNS.items()}
RECORD_MIN_BYTES = 61  # everything the nine rules need except column 96


class ParseError(Exception):
    """A record that cannot be read as a hypocenter record at all."""


# ---------------------------------------------------------------------------
# Field decoding
# ---------------------------------------------------------------------------

def _field(raw: bytes, name: str) -> bytes:
    return raw[SLICES[name]]


def _text(raw: bytes, name: str) -> str:
    return _field(raw, name).decode("ascii", errors="replace")


def _int_or_none(raw: bytes, name: str):
    s = _text(raw, name).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise ParseError(f"field {name!r} is not an integer: {s!r}")


def decode_magnitude(field: str):
    """
    Decode a two-character JMA magnitude field.

    Positive magnitudes are F2.1 with the decimal point implied: '45' is 4.5.

    Negative magnitudes are letter-coded, per the addendum and the JMA format
    description:
        '-1' .. '-9'  ->  -0.1 .. -0.9
        'A0' .. 'A9'  ->  -1.0 .. -1.9
        'B0' .. 'B9'  ->  -2.0 .. -2.9
        'C0' .. 'C9'  ->  -3.0 .. -3.9

    A parser that coerces these to zero is wrong somewhere else too, so this
    decodes them even though every such event falls far below threshold.

    Returns None for a blank field.
    """
    s = field.strip()
    if not s:
        return None
    if len(s) == 1:
        s = "0" + s
    head, tail = s[0], s[1]
    if not tail.isdigit():
        raise ParseError(f"magnitude field has non-digit second character: {field!r}")
    d = int(tail)
    if head.isdigit():
        return int(head) + d / 10.0
    if head == "-":
        return -(d / 10.0)
    if head in ("A", "B", "C"):
        whole = ord(head) - ord("A") + 1
        return -(whole + d / 10.0)
    raise ParseError(f"unrecognized magnitude encoding: {field!r}")


def decode_depth(field: str):
    """
    Decode the five-character depth field.

    Depth-free solutions give km with two implied decimals across all five
    characters ('01234' is 12.34 km). Depth-slice solutions give integer km in
    the first three characters with the last two blank ('012  ' is 12 km).

    Returns (depth_km, method) where method is 'free', 'slice' or 'missing'.
    """
    if len(field) < 5:
        field = field.ljust(5)
    whole, frac = field[:3], field[3:5]
    if not whole.strip():
        return None, "missing"
    try:
        w = int(whole)
    except ValueError:
        raise ParseError(f"depth field is not numeric: {field!r}")
    if not frac.strip():
        return float(w), "slice"
    try:
        f = int(frac)
    except ValueError:
        raise ParseError(f"depth decimal part is not numeric: {field!r}")
    return w + f / 100.0, "free"


def decode_coordinate(deg_field: str, min_field: str, which: str):
    """
    Decode degrees plus hundredths-of-a-minute into both an exact integer
    lattice value and a decimal degree value.

    Returns (units, degrees) where units is exact integer sixthousandths of a
    degree, used for the region test, and degrees is the float used for output.
    """
    # JMA right-justifies the degrees field, so a negative single-digit value
    # arrives with the sign separated from the digit, as '- 6'. Internal
    # whitespace is removed before conversion. The sign is taken from the text
    # rather than from the integer, because a latitude between 0 and -1 degree
    # has a degrees field of '-0', whose integer value carries no sign.
    d = deg_field.replace(" ", "")
    m = min_field.replace(" ", "")
    if not d or d == "-":
        raise ParseError(f"{which} degrees field is blank")
    negative = d.startswith("-")
    try:
        deg = abs(int(d))
    except ValueError:
        raise ParseError(f"{which} degrees field is not an integer: {deg_field!r}")
    if not m:
        minutes_hundredths = 0
    else:
        try:
            minutes_hundredths = int(m)
        except ValueError:
            raise ParseError(f"{which} minutes field is not an integer: {min_field!r}")
        if minutes_hundredths < 0:
            raise ParseError(f"{which} minutes field is negative: {min_field!r}")
    units = deg * UNITS_PER_DEGREE + minutes_hundredths
    if negative:
        units = -units
    return units, units / float(UNITS_PER_DEGREE)


def parse_record(raw: bytes) -> dict:
    """
    Parse one hypocenter record from raw bytes into a dict.

    Applies registered rules 1 (JST to UTC) and 2 (degrees plus minutes to
    decimal degrees). Those two rules are conversions: they remove nothing, and
    performing them here guarantees they precede every spatial and temporal
    test, which is what the registered ordering requires.
    """
    raw = raw.rstrip(b"\r\n")
    if len(raw) < RECORD_MIN_BYTES:
        raise ParseError(f"record is {len(raw)} bytes, shorter than the {RECORD_MIN_BYTES} "
                         f"the registered rules require")
    raw = raw.ljust(96)

    rec = {}
    rec["record_type"] = _text(raw, "record_type")

    year = _int_or_none(raw, "year")
    month = _int_or_none(raw, "month")
    day = _int_or_none(raw, "day")
    if year is None or month is None or day is None:
        raise ParseError("origin date is incomplete")
    hour = _int_or_none(raw, "hour") or 0
    minute = _int_or_none(raw, "minute") or 0

    sec_field = _text(raw, "second")
    sec_whole = sec_field[:2].strip()
    sec_frac = sec_field[2:4].strip()
    second = int(sec_whole) if sec_whole else 0
    microsecond = int(sec_frac) * 10000 if sec_frac else 0

    # RULE 1. JMA origin times are Japan Standard Time. Convert to UTC before
    # anything else touches the time. Seconds can reach 60 in this format when
    # a solution rounds up, which datetime refuses, so carry the overflow.
    carry = dt.timedelta(0)
    if second >= 60:
        carry += dt.timedelta(seconds=second - 59)
        second = 59
    try:
        t_jst = dt.datetime(year, month, day, hour, minute, second,
                            microsecond, tzinfo=JST) + carry
    except ValueError as e:
        raise ParseError(f"origin time is not a valid datetime: {e}")
    rec["origin_time_utc"] = t_jst.astimezone(dt.timezone.utc)
    rec["origin_time_jst"] = t_jst

    # RULE 2. Degrees plus decimal minutes, not decimal degrees.
    lat_units, lat_deg = decode_coordinate(_text(raw, "lat_deg"),
                                           _text(raw, "lat_min"), "latitude")
    lon_units, lon_deg = decode_coordinate(_text(raw, "lon_deg"),
                                           _text(raw, "lon_min"), "longitude")
    rec["lat_units"] = lat_units
    rec["lon_units"] = lon_units
    rec["latitude"] = lat_deg
    rec["longitude"] = lon_deg

    depth_km, depth_method = decode_depth(_text(raw, "depth"))
    rec["depth_km"] = depth_km
    rec["depth_method"] = depth_method

    rec["mag1"] = decode_magnitude(_text(raw, "mag1"))
    rec["mag1_type"] = _text(raw, "mag1_type").strip()
    rec["mag2"] = decode_magnitude(_text(raw, "mag2"))
    rec["mag2_type"] = _text(raw, "mag2_type").strip()

    rec["location_precision"] = _text(raw, "location_precision").strip()
    rec["subsidiary_info"] = _text(raw, "subsidiary_info").strip()
    rec["determination_flag"] = _text(raw, "determination_flag").strip()
    rec["n_stations"] = _int_or_none(raw, "n_stations")

    # Region name is the only field that can carry multi-byte characters.
    # Decoded last, from its own byte slice, so it cannot shift any column.
    name_bytes = _field(raw, "region_name")
    for enc in ("ascii", "cp932", "latin-1"):
        try:
            rec["region_name"] = name_bytes.decode(enc).strip()
            break
        except UnicodeDecodeError:
            continue
    else:
        rec["region_name"] = ""

    return rec


def select_jma_magnitude(rec: dict):
    """
    RULE 8, exactly as registered.

      Take the first magnitude if its type code is one of V, v, D or d.
      Otherwise take the second magnitude if its type code is one of those four.
      Otherwise exclude the event.

    Returns (magnitude, type_code) or (None, None).
    """
    if rec["mag1_type"] in JMA_MAG_CODES and rec["mag1"] is not None:
        return rec["mag1"], rec["mag1_type"]
    if rec["mag2_type"] in JMA_MAG_CODES and rec["mag2"] is not None:
        return rec["mag2"], rec["mag2_type"]
    return None, None


# ---------------------------------------------------------------------------
# Region, rule 4
# ---------------------------------------------------------------------------

def load_region_cells(path: str):
    """
    Load the authoritative CSEP-Japan All Japan region and return the set of
    integer cell keys, plus the file's SHA-256.

    The file holds cell MIDPOINTS. Origins are midpoint minus 0.05 degrees, as
    confirmed by Dr. Tsuruoka (email 2026-10-16) and corroborated by pyCSEP's
    handling of the equivalent Italy and New Zealand node files.

    Keys are computed in exact integer arithmetic. Midpoints are exact
    hundredths of a degree, so rounding to hundredths is lossless here, and the
    cell index is an exact integer division. Doing this in floating point
    misplaces any epicentre that lands exactly on a cell boundary.
    """
    h = hashlib.sha256()
    cells = set()
    lons, lats = [], []
    with open(path, "rb") as f:
        for raw in f:
            h.update(raw)
            s = raw.decode("ascii", errors="replace").strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            lon_mid, lat_mid = float(parts[0]), float(parts[1])
            lons.append(lon_mid)
            lats.append(lat_mid)
            lon_origin_h = int(round(lon_mid * 100)) - int(round(MIDPOINT_OFFSET_DEG * 100))
            lat_origin_h = int(round(lat_mid * 100)) - int(round(MIDPOINT_OFFSET_DEG * 100))
            if lon_origin_h % 10 or lat_origin_h % 10:
                raise ValueError(
                    f"cell origin is not on the 0.1 degree lattice: "
                    f"midpoint ({lon_mid}, {lat_mid}) gives origin "
                    f"({lon_origin_h / 100}, {lat_origin_h / 100}). "
                    f"The midpoint convention may not hold for this file."
                )
            cells.add((lon_origin_h // 10, lat_origin_h // 10))
    return cells, h.hexdigest(), (min(lons), max(lons), min(lats), max(lats))


def cell_key(lon_units: int, lat_units: int):
    """Exact integer cell index for an epicentre. Floor division, so a point on
    a boundary belongs to the cell the boundary opens."""
    return (lon_units // UNITS_PER_CELL, lat_units // UNITS_PER_CELL)


# ---------------------------------------------------------------------------
# The filter chain
# ---------------------------------------------------------------------------

RULE_TEXT = OrderedDict([
    (1, ("Time zone",
         "JMA hypocenter times are Japan Standard Time, UTC+9. All origin times "
         "converted to UTC before any other step.")),
    (2, ("Coordinates",
         "Latitude and longitude are recorded as integer degrees plus decimal "
         "minutes, not decimal degrees. Converted before any spatial test.")),
    (3, ("Window",
         "Origin time within 2016-01-01T00:00:00Z to 2023-12-31T23:59:59Z.")),
    (4, ("Region",
         "Epicentre falls inside a cell of the adopted CSEP-Japan All Japan "
         "region, 20,062 cells at 0.1 degree, using cell origins obtained as "
         "midpoint minus 0.05 degrees.")),
    (5, ("Depth",
         "Depth less than or equal to 100 km, per the published All Japan "
         "region definition.")),
    (6, ("Event type",
         "Subsidiary information code (column 61) equal to 1, natural "
         "earthquake. Excludes artificial events (3), eruption earthquakes and "
         "others (4), and low-frequency earthquakes (5).")),
    (7, ("Solution quality",
         "Hypocenter determination flag (column 96) not N and not F. Location "
         "precision (column 60) not 8.")),
    (8, ("Magnitude scale",
         "JMA magnitude per section 3. First magnitude if its type is V, v, D "
         "or d; otherwise the second if its type is one of those four; "
         "otherwise exclude.")),
    (9, ("Threshold",
         "M >= 4.0, with the 0.1 bin convention of section 3 "
         "(the M = 4.0 bin covers 3.95 <= M < 4.05).")),
])


class Attrition:
    """Counts events in, out and removed at each registered rule, plus the
    diagnostics the rules do not cover."""

    def __init__(self, sample_limit=25):
        self.removed = Counter()
        self.surviving_after = OrderedDict()
        self.parse_errors = Counter()
        self.n_records = 0
        self.n_parse_failed = 0
        self.watch = {
            "W1_excluded_with_J_magnitude_only": 0,
            "W1_examples": [],
            "W2_non_J_record_types_surviving": Counter(),
            "W3_depth_missing": 0,
        }
        self.detail = {
            "rule5_depth_exceeded": 0,
            "rule6_subsidiary_code_counts": Counter(),
            "rule7_determination_flag_counts": Counter(),
            "rule7_location_precision_counts": Counter(),
            "rule8_mag_type_pairs_excluded": Counter(),
            "selected_mag_type_counts": Counter(),
            "depth_method_counts": Counter(),
            # Composition of the surviving target set. Rule 7 as registered
            # excludes location precision 8 only. JMA code 7 means "poor", and
            # was in use up to March 2016, inside the registered window. These
            # counters quantify what the rule as written lets through, so that
            # question is settled by a number and, if it matters, by amendment.
            "target_location_precision": Counter(),
            "target_determination_flag": Counter(),
            "target_record_type": Counter(),
        }
        self.samples = {r: [] for r in RULE_TEXT}
        self.sample_limit = sample_limit

    def drop(self, rule: int, rec: dict, reason: str = ""):
        self.removed[rule] += 1
        if len(self.samples[rule]) < self.sample_limit:
            self.samples[rule].append({
                "rule": rule,
                "reason": reason,
                "origin_time_utc": rec["origin_time_utc"].isoformat()
                                   if rec.get("origin_time_utc") else "",
                "latitude": rec.get("latitude"),
                "longitude": rec.get("longitude"),
                "depth_km": rec.get("depth_km"),
                "mag1": rec.get("mag1"), "mag1_type": rec.get("mag1_type"),
                "mag2": rec.get("mag2"), "mag2_type": rec.get("mag2_type"),
                "subsidiary_info": rec.get("subsidiary_info"),
                "location_precision": rec.get("location_precision"),
                "determination_flag": rec.get("determination_flag"),
                "record_type": rec.get("record_type"),
                "region_name": rec.get("region_name"),
            })


def apply_rules(rec: dict, cells: set, att: Attrition,
                mag_floor: float = MAG_INCLUSION_FLOOR):
    """
    Apply registered rules 3 through 9 in order. Rules 1 and 2 were applied in
    parse_record. Returns (keep, magnitude, mag_type).

    Each rule is applied exactly as registered. Where a rule cannot be
    satisfied because the data does not carry what the rule needs, the event is
    excluded under that rule and the case is counted under the rule watch.

    mag_floor exists solely for the D9 working catalog, where rule 9 is
    deliberately relaxed because magnitude of completeness cannot be estimated
    from a catalog truncated at the completeness threshold. It defaults to the
    registered floor, so the target catalog path is unaffected. Rules 1 through
    8 are identical in both modes.
    """
    att.detail["depth_method_counts"][rec["depth_method"]] += 1

    # RULE 3. Window.
    t = rec["origin_time_utc"]
    if not (WINDOW_START <= t <= WINDOW_END):
        att.drop(3, rec, "origin time outside the registered window")
        return False, None, None

    # RULE 4. Region.
    if cell_key(rec["lon_units"], rec["lat_units"]) not in cells:
        att.drop(4, rec, "epicentre outside the CSEP-Japan All Japan region")
        return False, None, None

    # RULE 5. Depth.
    if rec["depth_km"] is None:
        att.watch["W3_depth_missing"] += 1
        att.drop(5, rec, "depth not determined, so depth <= 100 km cannot be satisfied")
        return False, None, None
    if rec["depth_km"] > DEPTH_MAX_KM:
        att.detail["rule5_depth_exceeded"] += 1
        att.drop(5, rec, f"depth {rec['depth_km']} km exceeds {DEPTH_MAX_KM} km")
        return False, None, None

    # RULE 6. Event type.
    code = rec["subsidiary_info"]
    att.detail["rule6_subsidiary_code_counts"][code or "(blank)"] += 1
    if code != "1":
        att.drop(6, rec, f"subsidiary information code {code or '(blank)'} is not 1")
        return False, None, None

    # RULE 7. Solution quality.
    flag = rec["determination_flag"]
    prec = rec["location_precision"]
    att.detail["rule7_determination_flag_counts"][flag or "(blank)"] += 1
    att.detail["rule7_location_precision_counts"][prec or "(blank)"] += 1
    if flag in ("N", "F"):
        att.drop(7, rec, f"determination flag {flag}")
        return False, None, None
    if prec == "8":
        att.drop(7, rec, "location precision 8, undetermined or not accepted")
        return False, None, None

    # RULE 8. Magnitude scale.
    mag, mtype = select_jma_magnitude(rec)
    if mag is None:
        pair = f"{rec['mag1_type'] or '_'}/{rec['mag2_type'] or '_'}"
        att.detail["rule8_mag_type_pairs_excluded"][pair] += 1
        if "J" in (rec["mag1_type"], rec["mag2_type"]):
            att.watch["W1_excluded_with_J_magnitude_only"] += 1
            if len(att.watch["W1_examples"]) < 25:
                att.watch["W1_examples"].append({
                    "origin_time_utc": t.isoformat(),
                    "mag1": rec["mag1"], "mag1_type": rec["mag1_type"],
                    "mag2": rec["mag2"], "mag2_type": rec["mag2_type"],
                })
        att.drop(8, rec, f"no JMA magnitude; type codes {pair}")
        return False, None, None

    # RULE 9. Threshold, with the registered bin convention.
    if mag < mag_floor:
        att.drop(9, rec, f"M {mag:.1f} below the bin floor {mag_floor}")
        return False, None, None

    att.detail["selected_mag_type_counts"][mtype] += 1
    att.detail["target_location_precision"][prec or "(blank)"] += 1
    att.detail["target_determination_flag"][flag or "(blank)"] += 1
    att.detail["target_record_type"][rec["record_type"] or "(blank)"] += 1
    if rec["record_type"] != "J":
        att.watch["W2_non_J_record_types_surviving"][rec["record_type"] or "(blank)"] += 1

    return True, mag, mtype


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def iter_source_records(paths, sha_index: dict):
    """
    Yield (source_label, line_number, raw_bytes) from the given .zip archives or
    plain hypocenter files, in sorted order so the run is reproducible.

    Reading straight out of the zip keeps the SHA-256 that was recorded at
    acquisition attached to the thing actually parsed.
    """
    for p in paths:
        if p.lower().endswith(".zip"):
            digest = sha256_file(p)
            sha_index[os.path.basename(p)] = digest
            with zipfile.ZipFile(p) as z:
                for name in sorted(z.namelist()):
                    if name.endswith("/"):
                        continue
                    with z.open(name) as fh:
                        for i, raw in enumerate(io.BufferedReader(fh), start=1):
                            yield f"{os.path.basename(p)}:{name}", i, raw
        else:
            sha_index[os.path.basename(p)] = sha256_file(p)
            with open(p, "rb") as fh:
                for i, raw in enumerate(fh, start=1):
                    yield os.path.basename(p), i, raw


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_inputs(spec: str):
    """
    Resolve the input specification to a list of source files, one per catalog
    year, plus a list of files deliberately skipped.

    A year can be present both as h<year>.zip and as the plain h<year> file
    extracted from it. Ingesting both double-counts that entire year, which
    inflates the target count and corrupts every downstream test. One source
    per year is selected, and the archive is preferred because the archive is
    what the acquisition record in data/jma_catalog/sha256_raw.txt hashed.

    Returns (inputs, skipped) where skipped holds (path, reason) pairs so the
    manifest records what was left out and why.
    """
    if not os.path.isdir(spec):
        return [spec], []

    by_year = {}
    for n in sorted(os.listdir(spec)):
        full = os.path.join(spec, n)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(n)
        is_zip = ext.lower() == ".zip"
        if not (is_zip or (n.startswith("h") and n[1:].isdigit())):
            continue
        key = stem if is_zip else n
        by_year.setdefault(key, []).append((full, is_zip))

    inputs, skipped = [], []
    for key in sorted(by_year):
        candidates = by_year[key]
        zips = [p for p, z in candidates if z]
        plains = [p for p, z in candidates if not z]
        if zips:
            inputs.append(zips[0])
            for p in zips[1:] + plains:
                skipped.append((p, f"another source for {key} was already selected; "
                                   f"the archive is authoritative because the "
                                   f"acquisition record hashes the archive"))
        else:
            inputs.append(plains[0])
            for p in plains[1:]:
                skipped.append((p, f"another source for {key} was already selected"))
    return inputs, skipped


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_attrition_markdown(path, att, n_kept, inputs, region_info,
                             working=None):
    lines = []
    if working:
        lines.append("# JMA sub-threshold WORKING catalog attrition\n")
        lines.append("> **This is not the registered target catalog.**\n>\n"
                     f"> Rule 9 is deliberately relaxed to M >= {working['nominal']} "
                     f"(inclusion floor {working['floor']}), against the registered "
                     f"threshold of M >= {MAG_THRESHOLD_NOMINAL}. Rules 1 through 8 "
                     "are applied exactly as registered and are identical to the "
                     "target catalog.\n>\n"
                     "> It exists because magnitude of completeness cannot be "
                     "estimated from a catalog truncated at the completeness "
                     "threshold: the estimate needs the roll-off below it. This "
                     "product is an input to D9 only. It is never evaluated, never "
                     "used as the target set, and does not supersede or widen the "
                     "registered catalog, which remains "
                     "`jma_target_catalog.csv` at M >= 4.0.\n")
    else:
        lines.append("# JMA catalog attrition\n")
    lines.append(f"Generated by `build_jma_catalog.py` v{SCRIPT_VERSION}.\n")
    lines.append(f"Rules pre-registered in the Block 1 Addendum (commit "
                 f"`{ADDENDUM_COMMIT}`) and at DOI {REGISTRATION_DOI}.\n")
    lines.append("Each rule is applied in the registered order. The count removed "
                 "by each rule is the number of events that reached that rule and "
                 "failed it, so the column sums to the difference between the raw "
                 "record count and the target count.\n")

    lines.append("\n## Per-rule attrition\n")
    lines.append("| Rule | Name | Removed | Surviving |")
    lines.append("|---|---|---:|---:|")
    for r, (name, _) in RULE_TEXT.items():
        lines.append(f"| {r} | {name} | {att.removed[r]:,} | "
                     f"{att.surviving_after.get(r, 0):,} |")
    lines.append(f"\n**Raw records read:** {att.n_records:,}")
    lines.append(f"**Records that would not parse:** {att.n_parse_failed:,}")
    lines.append(f"**{'Working' if working else 'Target'} events:** "
                 f"{n_kept:,}\n")

    lines.append("\n## Registered rule watch\n")
    lines.append("Cases the nine rules do not cover. Applied literally and counted, "
                 "not resolved in code.\n")
    lines.append(f"- **W1**, events excluded by rule 8 that carry a type `J` "
                 f"magnitude: **{att.watch['W1_excluded_with_J_magnitude_only']:,}**")
    w2 = att.watch["W2_non_J_record_types_surviving"]
    lines.append(f"- **W2**, non-`J` record types surviving all nine rules: "
                 f"**{sum(w2.values()):,}**"
                 + (f" ({dict(w2)})" if w2 else ""))
    lines.append(f"- **W3**, events excluded at rule 5 for having no depth: "
                 f"**{att.watch['W3_depth_missing']:,}**")

    lines.append("\n## Diagnostics\n")
    lines.append(f"- Depth solution method: {dict(att.detail['depth_method_counts'])}")
    lines.append(f"- Depth exceeded {DEPTH_MAX_KM:g} km: "
                 f"{att.detail['rule5_depth_exceeded']:,}")
    lines.append(f"- Subsidiary information codes seen at rule 6: "
                 f"{dict(att.detail['rule6_subsidiary_code_counts'])}")
    lines.append(f"- Determination flags seen at rule 7: "
                 f"{dict(att.detail['rule7_determination_flag_counts'])}")
    lines.append(f"- Location precision codes seen at rule 7: "
                 f"{dict(att.detail['rule7_location_precision_counts'])}")
    lines.append(f"- Magnitude type pairs excluded at rule 8: "
                 f"{dict(att.detail['rule8_mag_type_pairs_excluded'])}")
    lines.append(f"- Magnitude scale of target events: "
                 f"{dict(att.detail['selected_mag_type_counts'])}")

    lines.append("\n## Composition of the target set\n")
    lines.append("Rule 7 as registered excludes location precision 8 only. JMA "
                 "code 7 means poor location precision and was in use up to "
                 "March 2016, inside the registered window. The counts below "
                 "quantify what the rule as written admits. Any change is an "
                 "amendment, not a code change.\n")
    lines.append(f"- Location precision: "
                 f"{dict(att.detail['target_location_precision'])}")
    lines.append(f"- Determination flag: "
                 f"{dict(att.detail['target_determination_flag'])}")
    lines.append(f"- Record type: {dict(att.detail['target_record_type'])}")
    n_poor = att.detail["target_location_precision"].get("7", 0)
    n_auto = (att.detail["target_determination_flag"].get("A", 0)
              + att.detail["target_determination_flag"].get("a", 0))
    lines.append(f"- Target events at poor location precision (code 7): "
                 f"**{n_poor:,}**")
    lines.append(f"- Target events from automatic solutions (flag A or a): "
                 f"**{n_auto:,}**")

    lines.append("\n## Inputs\n")
    lines.append("| File | SHA-256 |")
    lines.append("|---|---|")
    for k, v in sorted(inputs.items()):
        lines.append(f"| `{k}` | `{v}` |")

    lines.append("\n## Region\n")
    lines.append(f"- File SHA-256: `{region_info['sha256']}`")
    lines.append(f"- Matches the registered region hash: "
                 f"{region_info['sha256'] == REGION_SHA256}")
    lines.append(f"- Cells: {region_info['n_cells']:,} "
                 f"(registered: {REGION_N_CELLS:,})")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def make_record(**kw) -> bytes:
    """Build a synthetic 96-byte hypocenter record for testing."""
    buf = bytearray(b" " * 96)

    def put(name, value):
        sl = SLICES[name]
        width = sl.stop - sl.start
        v = str(value)
        if len(v) > width:
            raise ValueError(f"{name}: {v!r} wider than {width}")
        buf[sl] = v.rjust(width).encode("ascii")

    defaults = {
        "record_type": "J", "year": "2020", "month": "06", "day": "15",
        "hour": "12", "minute": "30", "second": "4500",
        "lat_deg": " 35", "lat_min": "3000", "lon_deg": " 139",
        "lon_min": "3000", "depth": "01000", "mag1": "45", "mag1_type": "V",
        "location_precision": "1", "subsidiary_info": "1",
        "determination_flag": "K",
    }
    defaults.update(kw)
    for k, v in defaults.items():
        put(k, v)
    return bytes(buf)


def selftest(region_path=None) -> int:
    failures = []

    def check(label, got, want):
        ok = got == want
        if not ok:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")

    print("Magnitude decoding, including the registered negative encoding")
    check("'45' decodes", decode_magnitude("45"), 4.5)
    check("'40' decodes", decode_magnitude("40"), 4.0)
    check("'-1' is -0.1", decode_magnitude("-1"), -0.1)
    check("'-9' is -0.9", decode_magnitude("-9"), -0.9)
    check("'A0' is -1.0", decode_magnitude("A0"), -1.0)
    check("'A9' is -1.9", decode_magnitude("A9"), -1.9)
    check("'B0' is -2.0", decode_magnitude("B0"), -2.0)
    check("'C0' is -3.0", decode_magnitude("C0"), -3.0)
    check("blank is None", decode_magnitude("  "), None)

    print("\nDepth decoding, depth-free and depth-slice")
    check("'01234' is 12.34 km free", decode_depth("01234"), (12.34, "free"))
    check("'012  ' is 12 km slice", decode_depth("012  "), (12.0, "slice"))
    check("blank is missing", decode_depth("     "), (None, "missing"))

    print("\nRule 1, Japan Standard Time to UTC")
    r = parse_record(make_record(year="2016", month="01", day="01",
                                 hour="08", minute="59", second="5900"))
    check("2016-01-01 08:59:59 JST is 2015-12-31 23:59:59 UTC",
          r["origin_time_utc"].isoformat(), "2015-12-31T23:59:59+00:00")
    r = parse_record(make_record(year="2016", month="01", day="01",
                                 hour="09", minute="00", second="0000"))
    check("2016-01-01 09:00:00 JST is 2016-01-01 00:00:00 UTC",
          r["origin_time_utc"].isoformat(), "2016-01-01T00:00:00+00:00")

    print("\nRule 2, degrees plus decimal minutes")
    r = parse_record(make_record(lat_deg=" 35", lat_min="3000",
                                 lon_deg=" 139", lon_min="4500"))
    check("35 deg 30.00 min is 35.5", round(r["latitude"], 6), 35.5)
    check("139 deg 45.00 min is 139.75", round(r["longitude"], 6), 139.75)
    check("latitude not read as 35.30", r["latitude"] != 35.30, True)

    print("\nNegative coordinates, where padding separates the sign from the digit")
    check("'- 6' with 30.00 min is -6.5",
          round(decode_coordinate("- 6", "3000", "latitude")[1], 6), -6.5)
    check("' -0' keeps its sign, giving -0.5",
          round(decode_coordinate(" -0", "3000", "latitude")[1], 6), -0.5)
    check("'-12' with 00.00 min is -12.0",
          round(decode_coordinate("-12", "0000", "latitude")[1], 6), -12.0)

    print("\nInput selection, one source per catalog year")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for n in ("h2016.zip", "h2023.zip", "h2023", "readme.txt"):
            open(os.path.join(td, n), "wb").close()
        got, skip = collect_inputs(td)
        check("a year present as both archive and plain file is read once",
              sorted(os.path.basename(p) for p in got), ["h2016.zip", "h2023.zip"])
        check("the plain duplicate is skipped, not ingested",
              [os.path.basename(p) for p, _ in skip], ["h2023"])
        check("unrelated files are ignored",
              any("readme" in p for p in got), False)

    print("\nRule 8, magnitude selection as registered")
    r = parse_record(make_record(mag1="45", mag1_type="V", mag2="47", mag2_type="W"))
    check("first magnitude taken when type is V", select_jma_magnitude(r), (4.5, "V"))
    r = parse_record(make_record(mag1="47", mag1_type="W", mag2="45", mag2_type="d"))
    check("falls through to second when first is W", select_jma_magnitude(r), (4.5, "d"))
    r = parse_record(make_record(mag1="47", mag1_type="W", mag2="45", mag2_type="B"))
    check("excluded when neither is a JMA scale", select_jma_magnitude(r), (None, None))
    r = parse_record(make_record(mag1="45", mag1_type="J", mag2="  ", mag2_type=" "))
    check("type J excluded by the rule as written", select_jma_magnitude(r), (None, None))

    print("\nRule 9, the 0.1 bin convention")
    check("inclusion floor is 3.95", MAG_INCLUSION_FLOOR, 3.95)
    check("M 4.0 is inside the M4.0 bin", 4.0 >= MAG_INCLUSION_FLOOR, True)
    check("M 3.9 is outside", 3.9 >= MAG_INCLUSION_FLOOR, False)

    print("\nRule 4, exact integer lattice")
    # A point exactly on a cell boundary must land in the cell the boundary opens.
    r = parse_record(make_record(lat_deg=" 35", lat_min="0600",
                                 lon_deg=" 139", lon_min="0600"))
    check("35 deg 06.00 min is exactly 35.1", round(r["latitude"], 9), 35.1)
    check("boundary point keys to the cell it opens",
          cell_key(r["lon_units"], r["lat_units"]), (1391, 351))
    r = parse_record(make_record(lat_deg=" 35", lat_min="0599",
                                 lon_deg=" 139", lon_min="0599"))
    check("a point just below the boundary keys one cell lower",
          cell_key(r["lon_units"], r["lat_units"]), (1390, 350))

    if region_path and os.path.exists(region_path):
        print("\nRegion file, against the registered hash")
        cells, digest, bounds = load_region_cells(region_path)
        check("SHA-256 matches the registration", digest, REGION_SHA256)
        check("cell count matches the registration", len(cells), REGION_N_CELLS)
        print(f"  midpoint bounds lon [{bounds[0]}, {bounds[1]}] "
              f"lat [{bounds[2]}, {bounds[3]}]")
    else:
        print("\nRegion file not supplied, skipping the region checks. "
              "Pass --region to include them.")

    print()
    if failures:
        print(f"SELFTEST FAILED, {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELFTEST PASSED. Every registered rule behaves as written.")
    return 0


# ---------------------------------------------------------------------------
# Format verification against real data
# ---------------------------------------------------------------------------

def verify_format(inputs, limit=200000) -> int:
    """
    Report the observed value distribution in every fixed column, so the column
    map can be confirmed against the actual bytes rather than assumed.

    This changes nothing and writes nothing. Run it once per data source before
    trusting a production run.
    """
    sha_index = {}
    seen = {k: Counter() for k in
            ("record_type", "mag1_type", "mag2_type", "location_precision",
             "subsidiary_info", "determination_flag", "travel_time_table")}
    lengths = Counter()
    years = Counter()
    lat_deg = Counter()
    lon_deg = Counter()
    n = 0
    bad = 0
    first_lines = []

    for label, lineno, raw in iter_source_records(inputs, sha_index):
        stripped = raw.rstrip(b"\r\n")
        lengths[len(stripped)] += 1
        if len(first_lines) < 3:
            first_lines.append((label, stripped))
        n += 1
        try:
            rec = parse_record(raw)
        except ParseError:
            bad += 1
            continue
        for k in seen:
            if k == "travel_time_table":
                v = stripped.ljust(96)[SLICES[k]].decode("ascii", "replace").strip()
            else:
                v = rec.get(k, "")
            seen[k][v or "(blank)"] += 1
        years[rec["origin_time_jst"].year] += 1
        lat_deg[int(rec["latitude"])] += 1
        lon_deg[int(rec["longitude"])] += 1
        if n >= limit:
            break

    print(f"Records examined: {n:,}   unparseable: {bad:,}\n")
    print("Record lengths in bytes (a fixed-width format should be nearly uniform):")
    for L, c in sorted(lengths.items())[:12]:
        print(f"  {L:>4} bytes  {c:>10,}")
    print("\nFirst records, with a column ruler:")
    ruler = "".join(str((i + 1) % 10) for i in range(96))
    tens = "".join(str(((i + 1) // 10) % 10) for i in range(96))
    print(f"  {tens}")
    print(f"  {ruler}")
    for label, b in first_lines:
        print(f"  {b.decode('ascii', 'replace')[:96]}   <- {label}")
    for k, c in seen.items():
        print(f"\n{k} (column {COLUMNS[k][0]}"
              f"{'' if COLUMNS[k][0] == COLUMNS[k][1] else '-' + str(COLUMNS[k][1])}):")
        for v, cnt in c.most_common(15):
            print(f"  {v!r:>12}  {cnt:>10,}")
    print(f"\nOrigin years seen (JST): "
          f"{sorted(years)[:3]} ... {sorted(years)[-3:]}" if years else "")
    print(f"Latitude degrees range: {min(lat_deg) if lat_deg else '-'} "
          f"to {max(lat_deg) if lat_deg else '-'}")
    print(f"Longitude degrees range: {min(lon_deg) if lon_deg else '-'} "
          f"to {max(lon_deg) if lon_deg else '-'}")
    print("\nConfirm before any production run:")
    print("  - record lengths are consistent with a 96-byte fixed-width format")
    print("  - magnitude type codes are drawn from J/D/d/V/v/W/B/S and blank")
    print("  - subsidiary information codes are drawn from 1-5 and blank")
    print("  - determination flags are drawn from K/S/k/s/A/a/N/F and blank")
    print("  - latitude degrees fall roughly in 20-50, longitude in 120-150")
    return 0


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(args) -> int:
    inputs, skipped = collect_inputs(args.zips)
    if not inputs:
        print(f"No hypocenter archives or files found at {args.zips}", file=sys.stderr)
        return 2
    print(f"Inputs ({len(inputs)}):")
    for p in inputs:
        print(f"  {p}")
    if skipped:
        print(f"\nSkipped ({len(skipped)}), to avoid ingesting a year twice:")
        for p, why in skipped:
            print(f"  {p}\n    {why}")

    print(f"\nRegion: {args.region}")
    cells, region_sha, bounds = load_region_cells(args.region)
    region_info = {"path": args.region, "sha256": region_sha, "n_cells": len(cells),
                   "midpoint_bounds": {"lon_min": bounds[0], "lon_max": bounds[1],
                                       "lat_min": bounds[2], "lat_max": bounds[3]}}
    if region_sha != REGION_SHA256:
        print(f"  REGION HASH MISMATCH\n"
              f"    expected {REGION_SHA256}\n"
              f"    got      {region_sha}\n"
              f"  The region file is not the one the study registered. Stopping.",
              file=sys.stderr)
        return 3
    if len(cells) != REGION_N_CELLS:
        print(f"  Region has {len(cells)} cells, registered count is "
              f"{REGION_N_CELLS}. Stopping.", file=sys.stderr)
        return 3
    print(f"  SHA-256 matches the registration, {len(cells):,} cells")

    # Mode. The default path builds the registered target catalog. The working
    # path relaxes rule 9 for D9 and writes under distinct names so the two can
    # never be confused, and so a working build cannot overwrite the registered
    # catalog even by accident.
    working = None
    prefix = "jma_"
    mag_floor = MAG_INCLUSION_FLOOR
    if args.working_catalog:
        nominal = args.min_magnitude
        if nominal >= MAG_THRESHOLD_NOMINAL:
            print(f"--min-magnitude {nominal} is not below the registered "
                  f"threshold {MAG_THRESHOLD_NOMINAL}, so a working catalog would "
                  f"serve no purpose. Use the default mode for the target "
                  f"catalog.", file=sys.stderr)
            return 4
        if nominal < -3.0:
            print(f"--min-magnitude {nominal} is below the JMA magnitude "
                  f"encoding floor of -3.9.", file=sys.stderr)
            return 4
        mag_floor = nominal - MAG_BIN_WIDTH / 2.0
        prefix = "jma_mc_working_"
        working = {"nominal": nominal, "floor": round(mag_floor, 4)}
        print(f"\nWORKING CATALOG MODE")
        print(f"  Rule 9 relaxed to M >= {nominal}, inclusion floor "
              f"{mag_floor:.2f}.")
        print(f"  Rules 1 through 8 are applied exactly as registered.")
        print(f"  Output prefix: {prefix}")
        print(f"  This is a D9 input. It is not the target catalog and is never")
        print(f"  evaluated. The registered catalog stays at "
              f"jma_target_catalog.csv.")

    os.makedirs(args.out, exist_ok=True)

    # A working build must never touch the registered product.
    if working:
        protected = [os.path.join(args.out, n) for n in
                     ("jma_target_catalog.csv", "jma_attrition.md",
                      "jma_attrition.json", "jma_catalog_manifest.json",
                      "jma_excluded_sample.csv")]
        before = {p: sha256_file(p) for p in protected if os.path.exists(p)}
    else:
        before = {}

    att = Attrition(sample_limit=args.sample_limit)
    sha_index = {}
    kept = []

    print("\nApplying the nine registered rules in order...")
    for label, lineno, raw in iter_source_records(inputs, sha_index):
        if not raw.strip():
            continue
        att.n_records += 1
        try:
            rec = parse_record(raw)
        except ParseError as e:
            att.n_parse_failed += 1
            att.parse_errors[str(e)[:80]] += 1
            continue
        keep, mag, mtype = apply_rules(rec, cells, att, mag_floor)
        if keep:
            kept.append({
                "event_id": f"{rec['origin_time_utc'].strftime('%Y%m%d%H%M%S')}"
                            f"_{int(round(rec['latitude'] * 10000))}"
                            f"_{int(round(rec['longitude'] * 10000))}",
                "origin_time_utc": rec["origin_time_utc"]
                                   .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "longitude": round(rec["longitude"], 6),
                "latitude": round(rec["latitude"], 6),
                "depth_km": rec["depth_km"],
                "magnitude": round(mag, 2),
                "magnitude_type": mtype,
                "depth_method": rec["depth_method"],
                "n_stations": rec["n_stations"],
                "record_type": rec["record_type"],
                "location_precision": rec["location_precision"],
                "determination_flag": rec["determination_flag"],
                "region_name": rec["region_name"],
                "source_file": label,
                "source_line": lineno,
            })

    # Surviving counts, rule by rule.
    surviving = att.n_records - att.n_parse_failed
    for r in RULE_TEXT:
        surviving -= att.removed[r]
        att.surviving_after[r] = surviving

    kept.sort(key=lambda e: (e["origin_time_utc"], e["event_id"],
                             e["source_file"], e["source_line"]))

    # Event ids are built from time and location, so two records sharing a
    # second and a rounded epicentre would collide. Disambiguate in sorted
    # order, which makes the suffix deterministic across runs, and report any
    # collisions rather than letting a duplicate key pass silently into the
    # evaluation.
    seen_ids = Counter()
    n_collisions = 0
    for e in kept:
        base = e["event_id"]
        seen_ids[base] += 1
        if seen_ids[base] > 1:
            e["event_id"] = f"{base}-{seen_ids[base]}"
            n_collisions += 1
    if n_collisions:
        print(f"\nNote: {n_collisions:,} event id collision(s) disambiguated with a "
              f"sequence suffix. Identical time and rounded epicentre, which can "
              f"indicate duplicated records in the source. Check "
              f"jma_target_catalog.csv before D10.")

    cat_path = os.path.join(
        args.out, f"{prefix}catalog.csv" if working else "jma_target_catalog.csv")
    fields = ["event_id", "origin_time_utc", "longitude", "latitude", "depth_km",
              "magnitude", "magnitude_type", "depth_method", "n_stations",
              "record_type", "location_precision", "determination_flag",
              "region_name", "source_file", "source_line"]
    with open(cat_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(kept)

    exc_path = os.path.join(args.out, f"{prefix}excluded_sample.csv")
    sample_rows = [s for r in RULE_TEXT for s in att.samples[r]]
    if sample_rows:
        with open(exc_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(sample_rows[0].keys()))
            w.writeheader()
            w.writerows(sample_rows)

    att_json = {
        "script": "build_jma_catalog.py",
        "script_version": SCRIPT_VERSION,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "preregistration": {
            "addendum_commit": ADDENDUM_COMMIT,
            "addendum_sha256": ADDENDUM_SHA256,
            "registration_doi": REGISTRATION_DOI,
        },
        "raw_records": att.n_records,
        "parse_failures": att.n_parse_failed,
        "parse_failure_reasons": dict(att.parse_errors),
        "rules": [
            {"rule": r, "name": RULE_TEXT[r][0], "text": RULE_TEXT[r][1],
             "removed": att.removed[r], "surviving_after": att.surviving_after[r]}
            for r in RULE_TEXT
        ],
        "target_events": len(kept),
        "registered_rule_watch": {
            "W1_excluded_with_J_magnitude_only":
                att.watch["W1_excluded_with_J_magnitude_only"],
            "W1_examples": att.watch["W1_examples"],
            "W2_non_J_record_types_surviving":
                dict(att.watch["W2_non_J_record_types_surviving"]),
            "W3_depth_missing": att.watch["W3_depth_missing"],
        },
        "diagnostics": {k: (dict(v) if isinstance(v, Counter) else v)
                        for k, v in att.detail.items()},
    }
    att_json_path = os.path.join(args.out, f"{prefix}attrition.json")
    with open(att_json_path, "w", encoding="utf-8") as f:
        json.dump(att_json, f, indent=2)

    att_md_path = os.path.join(args.out, f"{prefix}attrition.md")
    write_attrition_markdown(att_md_path, att, len(kept), sha_index,
                             region_info, working)

    manifest = {
        "artifact": ("D9 sub-threshold WORKING catalog, NOT the registered "
                     "target catalog" if working
                     else "JMA target earthquake catalog"),
        "gate_item": "D9 input" if working else "D8",
        "is_registered_target_catalog": not bool(working),
        "script": "build_jma_catalog.py",
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(os.path.abspath(__file__)),
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "preregistration": {
            "addendum": "docs/BLOCK1_ADDENDUM_testing_class_and_threshold_2026-10-19.docx",
            "addendum_commit": ADDENDUM_COMMIT,
            "addendum_sha256": ADDENDUM_SHA256,
            "registration_doi": REGISTRATION_DOI,
            "registration_date": "2026-11-09",
            "rules_applied_in_registered_order": True,
            "declustering": "none, per the addendum, following CSEP-Japan practice",
        },
        "window_utc": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "magnitude": {
            "registered_threshold_nominal": MAG_THRESHOLD_NOMINAL,
            "registered_inclusion_floor": MAG_INCLUSION_FLOOR,
            "bin_width": MAG_BIN_WIDTH,
            "applied_threshold_nominal": (working["nominal"] if working
                                          else MAG_THRESHOLD_NOMINAL),
            "applied_inclusion_floor": mag_floor,
            "rule9_relaxed": bool(working),
            "rule9_relaxation_reason": (
                "Magnitude of completeness cannot be estimated from a catalog "
                "truncated at the completeness threshold; the estimate requires "
                "the roll-off below it. Rules 1 through 8 are applied exactly as "
                "registered. This product is a D9 input only and is never "
                "evaluated." if working else None),
            "accepted_type_codes": list(JMA_MAG_CODES),
        },
        "depth_max_km": DEPTH_MAX_KM,
        "region": region_info,
        "inputs": sha_index,
        "inputs_skipped": [{"path": p, "reason": why} for p, why in skipped],
        "outputs": {},
        "counts": {
            "raw_records": att.n_records,
            "parse_failures": att.n_parse_failed,
            "target_events": len(kept),
            "event_id_collisions_disambiguated": n_collisions,
        },
    }
    for p in (cat_path, att_json_path, att_md_path):
        manifest["outputs"][os.path.basename(p)] = sha256_file(p)
    if sample_rows:
        manifest["outputs"][os.path.basename(exc_path)] = sha256_file(exc_path)

    man_path = os.path.join(args.out, f"{prefix}manifest.json"
                            if working else "jma_catalog_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # A working build must leave the registered product byte-identical. This is
    # checked rather than assumed, because the one thing this mode must never do
    # is alter the catalog the evaluation runs on.
    if working and before:
        for p, h in before.items():
            now = sha256_file(p) if os.path.exists(p) else None
            if now != h:
                print(f"\nABORT: the working build changed a registered file.\n"
                      f"  {p}\n  before {h}\n  after  {now}\n"
                      f"This should be impossible. Do not use either output.",
                      file=sys.stderr)
                return 5
        print(f"\nVerified unchanged by this build: "
              f"{', '.join(os.path.basename(p) for p in sorted(before))}")

    # Console summary.
    print(f"\nRaw records read: {att.n_records:,}")
    if att.n_parse_failed:
        print(f"Unparseable records: {att.n_parse_failed:,}")
        for reason, c in att.parse_errors.most_common(5):
            print(f"    {c:>8,}  {reason}")
    print(f"\n{'Rule':<5} {'Name':<18} {'Removed':>12} {'Surviving':>12}")
    print("-" * 50)
    for r, (name, _) in RULE_TEXT.items():
        print(f"{r:<5} {name:<18} {att.removed[r]:>12,} "
              f"{att.surviving_after[r]:>12,}")
    print("-" * 50)
    label = "WORKING EVENTS" if working else "TARGET EVENTS"
    print(f"{'':<5} {label:<18} {'':>12} {len(kept):>12,}")

    print("\nRegistered rule watch")
    print(f"  W1  excluded at rule 8 while carrying a type J magnitude: "
          f"{att.watch['W1_excluded_with_J_magnitude_only']:,}")
    w2 = att.watch["W2_non_J_record_types_surviving"]
    print(f"  W2  non-J record types surviving all nine rules: {sum(w2.values()):,}"
          + (f"  {dict(w2)}" if w2 else ""))
    print(f"  W3  excluded at rule 5 for having no depth: "
          f"{att.watch['W3_depth_missing']:,}")
    for key, label in (("W1_excluded_with_J_magnitude_only", "W1"),
                       ("W3_depth_missing", "W3")):
        if att.watch[key]:
            print(f"      {label} is non-zero. Decide by amendment before D10, "
                  f"not in code.")
    if sum(w2.values()):
        print("      W2 is non-zero. Decide by amendment before D10, not in code.")

    print(f"\nComposition of the target set")
    print(f"  magnitude scale:     {dict(att.detail['selected_mag_type_counts'])}")
    print(f"  location precision:  {dict(att.detail['target_location_precision'])}")
    print(f"  determination flag:  {dict(att.detail['target_determination_flag'])}")
    print(f"  record type:         {dict(att.detail['target_record_type'])}")
    n_poor = att.detail["target_location_precision"].get("7", 0)
    if n_poor:
        print(f"  NOTE: {n_poor:,} target event(s) carry location precision 7, "
              f"poor. Rule 7 as registered excludes code 8 only, so these are "
              f"admitted. Decide by amendment before D10 if it matters.")
    print(f"\nWritten to {args.out}/")
    for p in (cat_path, att_md_path, att_json_path, man_path):
        print(f"  {os.path.basename(p)}")
    print(f"\nCatalog SHA-256: "
          f"{manifest['outputs'][os.path.basename(cat_path)]}")
    if working:
        print("\nThis is the D9 sub-threshold WORKING catalog. It is not the "
              "registered target catalog, is never evaluated, and does not "
              "supersede jma_target_catalog.csv. Commit it under its own name "
              "with a ledger row stating that rule 9 was relaxed and why.")
    else:
        print("\nD8 is not closed until the catalog, the attrition report and "
              "the manifest are committed and the manifest hash is recorded in "
              "the registration ledger.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build the Sentinel target catalog from JMA hypocenter files, "
                    "applying the nine pre-registered filtering rules.")
    ap.add_argument("--zips", default="data/jma_catalog",
                    help="directory of h<year>.zip archives, a single .zip, or a "
                         "plain hypocenter file")
    ap.add_argument("--region", default="data/csep_japan/japan.forecast.nodes",
                    help="the authoritative CSEP-Japan node file")
    ap.add_argument("--out", default="data/jma_catalog",
                    help="output directory")
    ap.add_argument("--sample-limit", type=int, default=25,
                    help="excluded records to retain per rule for spot-checking")
    ap.add_argument("--working-catalog", action="store_true",
                    help="build the D9 sub-threshold WORKING catalog instead of "
                         "the registered target catalog: rules 1 through 8 as "
                         "registered, rule 9 relaxed to --min-magnitude, written "
                         "under the jma_mc_working_ prefix. Required for the "
                         "magnitude of completeness estimate, which cannot be "
                         "made from a catalog truncated at the threshold.")
    ap.add_argument("--min-magnitude", type=float, default=1.0,
                    help="nominal magnitude floor for --working-catalog "
                         "(default 1.0). The 0.1 bin convention applies, so the "
                         "inclusion floor is this minus 0.05. Ignored without "
                         "--working-catalog.")
    ap.add_argument("--selftest", action="store_true",
                    help="run the registered-rule fixtures and exit")
    ap.add_argument("--verify-format", action="store_true",
                    help="report observed column values against the column map "
                         "and exit, writing nothing")
    args = ap.parse_args()

    if args.min_magnitude != 1.0 and not args.working_catalog:
        print("--min-magnitude only applies with --working-catalog. The "
              "registered threshold of M >= 4.0 is fixed by the "
              "pre-registration and is not a command line option.",
              file=sys.stderr)
        return 4

    if args.selftest:
        return selftest(args.region)
    if args.verify_format:
        return verify_format(collect_inputs(args.zips)[0])
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
