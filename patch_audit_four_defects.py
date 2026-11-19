#!/usr/bin/env python3
"""
patch_audit_four_defects.py

Fixes four defects in sentinel_audit.sh, each of which caused the audit to
report something that was not true.

DO NOT RUN THIS WHILE AN AUDIT IS EXECUTING. bash reads a script by byte
offset as it runs, so editing sentinel_audit.sh mid-run corrupts execution.
That is what produced the "----------: command not found" failure and the
syntax error on `done` in the 04:07:53 run on 2026-10-17. Check first:

    pgrep -fa sentinel_audit.sh

----------------------------------------------------------------------------
DEFECT 1. A stopped VM is reported as an idle cost risk.

  VM_COUNT counted every instance regardless of status, so the finding
  "1 compute VM(s) present, confirm each is needed" fired against
  geonet-pull after it was deliberately stopped on 2026-11-13. The audit's
  stated purpose is catching idle cost risk, and a TERMINATED instance is
  not one. Left as is, the finding cries wolf on every future run and gets
  ignored, which is worse than not having it.

  Fix: count RUNNING and non-RUNNING separately. Only running instances
  raise the idle-cost finding. Stopped instances raise a quieter finding
  about their retained disks, which do still cost money.

----------------------------------------------------------------------------
DEFECT 2. The SKU breakdown silently dropped credit rows.

  HAVING net_usd > 0 removed every SKU whose net was zero or negative.
  Free-tier credits appear as negative net, so the listed SKUs summed to
  $12.16 against a project net of $3.90 and could not be reconciled.
  synexis-sfo appeared to reconcile only because it has no VM and
  therefore no large credited SKU.

  Fix: drop the HAVING. Report gross, credits and net per SKU, ordered by
  absolute net so credited rows are visible. Print the all-SKU total
  alongside, so the displayed top rows can be checked against it rather
  than mistaken for the whole.

----------------------------------------------------------------------------
DEFECT 3. Artifact Registry locations were read from the repository name.

  The parsing assumed `gcloud artifacts repositories list
  --format="value(name,...)"` returns the full resource path
  projects/P/locations/LOC/repositories/REPO, and took segment 4 as the
  location. This gcloud version returns the bare repository id, and `cut
  -d/ -f4` on a string with no slash returns the whole string. So the
  location was set to the repository name, every repository compared
  unequal to us-central1, and the audit emitted 15 false OFF-REGION
  findings out of 32 total, every run.

  Fix: ask gcloud for the location field directly, fall back to parsing
  the path when the name does carry one, and when neither is available
  report that the location could not be determined. Never again infer an
  off-region placement from a repository name.

----------------------------------------------------------------------------
DEFECT 4. synexis-foremark was never audited.

  The default project list held synexis-project-sentinel and synexis-sfo.
  The cost section reports synexis-foremark spend because it queries the
  billing export across all projects, so the project was visible in the
  output while none of its infrastructure was ever checked. A blind spot
  that shows up in the cost table is the worst kind, because it looks
  covered.

  Fix: add synexis-foremark to the default list, with no critical tables
  registered for it yet.

----------------------------------------------------------------------------
Idempotent. Keeps a .bak. Verifies with `bash -n` before writing.

Usage:
  python3 patch_audit_four_defects.py --dry-run
  python3 patch_audit_four_defects.py
"""

import argparse
import difflib
import os
import subprocess
import sys

TARGET = "sentinel_audit.sh"
MARKER = "AUDIT_PATCH_FOUR_DEFECTS"

EDITS = []

# ---------------------------------------------------------------------------
# DEFECT 4. Project list.
# ---------------------------------------------------------------------------
EDITS.append((
    'PROJECTS=("$@")\n'
    'if [ ${#PROJECTS[@]} -eq 0 ]; then\n'
    '  PROJECTS=(synexis-project-sentinel synexis-sfo)\n'
    'fi\n',

    '# AUDIT_PATCH_FOUR_DEFECTS\n'
    '# synexis-foremark was absent from this list while appearing in the cost\n'
    '# section, which queries the billing export across all projects. Its\n'
    '# spend was visible and its infrastructure was never checked.\n'
    'PROJECTS=("$@")\n'
    'if [ ${#PROJECTS[@]} -eq 0 ]; then\n'
    '  PROJECTS=(synexis-project-sentinel synexis-sfo synexis-foremark)\n'
    'fi\n',
))

EDITS.append((
    'CRITICAL_TABLES[synexis-sfo]=""\n',

    'CRITICAL_TABLES[synexis-sfo]=""\n'
    'CRITICAL_TABLES[synexis-foremark]=""\n',
))

# ---------------------------------------------------------------------------
# DEFECT 1. VM status.
# ---------------------------------------------------------------------------
EDITS.append((
    '  VM_COUNT=$(gcloud compute instances list --project="$P" \\\n'
    '    --format="value(name)" 2>/dev/null | wc -l)\n'
    '  [ "$VM_COUNT" -gt 0 ] && note "$P: $VM_COUNT compute VM(s) present \u2014 '
    'confirm each is needed"\n',

    '  # A TERMINATED instance is not an idle cost risk, and reporting it as\n'
    '  # one trains the reader to ignore the finding. Running and stopped are\n'
    '  # counted separately. Stopped instances still hold their disks, which\n'
    '  # do cost, so they get their own quieter finding.\n'
    '  VM_RUNNING=$(gcloud compute instances list --project="$P" \\\n'
    '    --filter="status=RUNNING" --format="value(name)" 2>/dev/null | wc -l)\n'
    '  VM_TOTAL=$(gcloud compute instances list --project="$P" \\\n'
    '    --format="value(name)" 2>/dev/null | wc -l)\n'
    '  VM_STOPPED=$(( VM_TOTAL - VM_RUNNING ))\n'
    '  [ "$VM_RUNNING" -gt 0 ] && \\\n'
    '    note "$P: $VM_RUNNING compute VM(s) RUNNING, confirm each is needed"\n'
    '  [ "$VM_STOPPED" -gt 0 ] && \\\n'
    '    note "$P: $VM_STOPPED compute VM(s) stopped, not an idle cost risk; '
    'their persistent disks are retained and still billed"\n',
))

# ---------------------------------------------------------------------------
# DEFECT 3. Artifact Registry location.
# ---------------------------------------------------------------------------
EDITS.append((
    '  head2 "Artifact Registry"\n'
    '  AR_FOUND=0\n'
    '  while IFS=$\'\\t\' read -r ARNAME ARFMT ARSIZE; do\n'
    '    [ -z "${ARNAME:-}" ] && continue\n'
    '    AR_FOUND=1\n'
    '    ARLOC=$(echo "$ARNAME" | cut -d/ -f4 | lower)\n'
    '    ARREPO=$(echo "$ARNAME" | awk -F/ \'{print $NF}\')\n'
    '    case "${ARSIZE:-}" in\n'
    '      \'\'|*[!0-9]*) ARMB="?" ;;\n'
    '      *)           ARMB=$(( ARSIZE / 1048576 )) ;;\n'
    '    esac\n'
    '    if [ "$ARLOC" != "$EXPECTED_LOCATION" ]; then\n'
    '      printf \'  %-34s %-8s %8s MB  [%s]  <-- OFF-REGION\\n\' "$ARREPO" '
    '"$ARFMT" "$ARMB" "$ARLOC"\n'
    '      note "$P: Artifact Registry repo $ARREPO is in $ARLOC (${ARMB} MB), '
    'expected $EXPECTED_LOCATION"\n'
    '    else\n'
    '      printf \'  %-34s %-8s %8s MB  [%s]\\n\' "$ARREPO" "$ARFMT" "$ARMB" '
    '"$ARLOC"\n'
    '    fi\n'
    '  done < <(gcloud artifacts repositories list --project="$P" \\\n'
    '      --format="value(name,format,sizeBytes)" 2>/dev/null)\n'
    '  [ "$AR_FOUND" -eq 0 ] && echo "  (none)"\n',

    '  head2 "Artifact Registry"\n'
    '  AR_FOUND=0\n'
    '  # The previous version took the location from path segment 4 of the\n'
    '  # resource name. This gcloud version returns the bare repository id in\n'
    '  # `name`, and `cut -d/ -f4` on a string with no slash returns the whole\n'
    '  # string, so the location became the repository name, nothing ever\n'
    '  # equalled us-central1, and 15 of 32 findings per run were false.\n'
    '  #\n'
    '  # The location is now requested explicitly. If gcloud does not supply\n'
    '  # it and the name carries no path, the location is reported as\n'
    '  # undetermined rather than guessed. An audit that cannot tell must say\n'
    '  # so, not assert.\n'
    '  #\n'
    '  # An explicit non-whitespace separator is required. Tab is IFS\n'
    '  # whitespace, so bash collapses a run of tabs and an empty field\n'
    '  # disappears, shifting every later field left. sizeBytes is empty for\n'
    '  # several repositories here, which would silently move the location\n'
    '  # into the size column and lose it.\n'
    '  AR_RAW=$(gcloud artifacts repositories list --project="$P" \\\n'
    '      --format="value[separator=\'|\'](name,format,sizeBytes,location)" \\\n'
    '      2>/dev/null)\n'
    '  if [ -z "$AR_RAW" ]; then\n'
    '    AR_RAW=$(gcloud artifacts repositories list --project="$P" \\\n'
    '        --format="value[separator=\'|\'](name,format,sizeBytes)" 2>/dev/null)\n'
    '  fi\n'
    '  while IFS=\'|\' read -r ARNAME ARFMT ARSIZE ARLOCRAW; do\n'
    '    [ -z "${ARNAME:-}" ] && continue\n'
    '    AR_FOUND=1\n'
    '    ARREPO=$(echo "$ARNAME" | awk -F/ \'{print $NF}\')\n'
    '    if [ -n "${ARLOCRAW:-}" ]; then\n'
    '      ARLOC=$(printf \'%s\' "$ARLOCRAW" | lower)\n'
    '    elif printf \'%s\' "$ARNAME" | grep -q \'/locations/\'; then\n'
    '      ARLOC=$(printf \'%s\' "$ARNAME" \\\n'
    '        | sed -n \'s#.*/locations/\\([^/]*\\)/.*#\\1#p\' | lower)\n'
    '    else\n'
    '      ARLOC=""\n'
    '    fi\n'
    '    case "${ARSIZE:-}" in\n'
    '      \'\'|*[!0-9]*) ARMB="?" ;;\n'
    '      *)           ARMB=$(( ARSIZE / 1048576 )) ;;\n'
    '    esac\n'
    '    if [ -z "$ARLOC" ]; then\n'
    '      printf \'  %-34s %-8s %8s MB  [location undetermined]\\n\' '
    '"$ARREPO" "$ARFMT" "$ARMB"\n'
    '      note "$P: Artifact Registry repo $ARREPO location could not be read '
    'from this gcloud version; NOT treated as off-region"\n'
    '    elif [ "$ARLOC" != "$EXPECTED_LOCATION" ]; then\n'
    '      printf \'  %-34s %-8s %8s MB  [%s]  <-- OFF-REGION\\n\' "$ARREPO" '
    '"$ARFMT" "$ARMB" "$ARLOC"\n'
    '      note "$P: Artifact Registry repo $ARREPO is in $ARLOC (${ARMB} MB), '
    'expected $EXPECTED_LOCATION"\n'
    '    else\n'
    '      printf \'  %-34s %-8s %8s MB  [%s]\\n\' "$ARREPO" "$ARFMT" "$ARMB" '
    '"$ARLOC"\n'
    '    fi\n'
    '  done <<< "$AR_RAW"\n'
    '  [ "$AR_FOUND" -eq 0 ] && echo "  (none)"\n',
))

# ---------------------------------------------------------------------------
# DEFECT 2. SKU breakdown dropped credit rows.
# ---------------------------------------------------------------------------
EDITS.append((
    '  SKU_SQL="\n'
    '    SELECT\n'
    '      project.id AS project,\n'
    '      service.description AS service,\n'
    '      sku.description AS sku,\n'
    '      ROUND(SUM(cost)\n'
    '            + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2)\n'
    '        AS net_usd\n'
    '    FROM \\`${BILLING_EXPORT_TABLE}\\`\n'
    '    WHERE DATE(usage_start_time) >= DATE_TRUNC(CURRENT_DATE(), MONTH)\n'
    '    GROUP BY project, service, sku\n'
    '    HAVING net_usd > 0\n'
    '    ORDER BY net_usd DESC\n'
    '    LIMIT 10\n'
    '  "\n',

    '  # HAVING net_usd > 0 was dropping every credited SKU, because free-tier\n'
    '  # credits land as negative net. The listed SKUs summed to $12.16 against\n'
    '  # a project net of $3.90 and could not be reconciled. Gross, credits and\n'
    '  # net are now all reported, ordered by absolute net so credited rows are\n'
    '  # visible, with no HAVING filter.\n'
    '  SKU_SQL="\n'
    '    SELECT\n'
    '      project.id AS project,\n'
    '      service.description AS service,\n'
    '      sku.description AS sku,\n'
    '      ROUND(SUM(cost), 2) AS gross_usd,\n'
    '      ROUND(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2)\n'
    '        AS credits_usd,\n'
    '      ROUND(SUM(cost)\n'
    '            + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2)\n'
    '        AS net_usd\n'
    '    FROM \\`${BILLING_EXPORT_TABLE}\\`\n'
    '    WHERE DATE(usage_start_time) >= DATE_TRUNC(CURRENT_DATE(), MONTH)\n'
    '    GROUP BY project, service, sku\n'
    '    ORDER BY ABS(net_usd) DESC\n'
    '    LIMIT 15\n'
    '  "\n',
))

# Reconciliation footer, appended after the SKU query output.
EDITS.append((
    '  if ! SKU_OUT=$(bq query --nouse_legacy_sql --format=pretty "$SKU_SQL" 2>&1); then\n'
    '    echo "  SKU query failed:"\n'
    '    echo "$SKU_OUT" | sed \'s/^/    /\'\n'
    '  else\n'
    '    echo "$SKU_OUT" | sed \'s/^/  /\'\n'
    '  fi\n',

    '  if ! SKU_OUT=$(bq query --nouse_legacy_sql --format=pretty "$SKU_SQL" 2>&1); then\n'
    '    echo "  SKU query failed:"\n'
    '    echo "$SKU_OUT" | sed \'s/^/    /\'\n'
    '  else\n'
    '    echo "$SKU_OUT" | sed \'s/^/  /\'\n'
    '  fi\n'
    '\n'
    '  # The table above is a top-N subset and will not sum to the project\n'
    '  # totals. This prints the all-SKU figures so the subset can be checked\n'
    '  # against them instead of being mistaken for the whole.\n'
    '  RECON_SQL="\n'
    '    SELECT\n'
    '      COUNT(*) AS sku_rows,\n'
    '      ROUND(SUM(gross), 2) AS all_sku_gross_usd,\n'
    '      ROUND(SUM(cred), 2)  AS all_sku_credits_usd,\n'
    '      ROUND(SUM(gross) + SUM(cred), 2) AS all_sku_net_usd\n'
    '    FROM (\n'
    '      SELECT\n'
    '        SUM(cost) AS gross,\n'
    '        SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS cred\n'
    '      FROM \\`${BILLING_EXPORT_TABLE}\\`\n'
    '      WHERE DATE(usage_start_time) >= DATE_TRUNC(CURRENT_DATE(), MONTH)\n'
    '      GROUP BY project.id, service.description, sku.description\n'
    '    )\n'
    '  "\n'
    '  if RECON_OUT=$(bq query --nouse_legacy_sql --format=pretty "$RECON_SQL" 2>&1); then\n'
    '    echo ""\n'
    '    echo "  All SKUs, month to date, for reconciliation against the "\\\n'
    '         "project table above:"\n'
    '    echo "$RECON_OUT" | sed \'s/^/  /\'\n'
    '  fi\n',
))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=TARGET)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"Not found: {args.file}. Run this from the repository root.")

    # Guard against patching a script that bash is part way through reading.
    #
    # A plain `pgrep -f sentinel_audit.sh` is not usable here: it matches any
    # process whose command line merely MENTIONS the name, including the shell
    # that invoked this patch if that command line happens to refer to the
    # script. Candidates are therefore filtered down to processes that are
    # actually executing it, excluding this process, its parent, and anything
    # running this patch script.
    running = []
    try:
        pids = subprocess.run(["pgrep", "-f", "sentinel_audit.sh"],
                              capture_output=True, text=True).stdout.split()
        me, parent = os.getpid(), os.getppid()
        myname = os.path.basename(__file__)
        for pid in pids:
            if pid in (str(me), str(parent)):
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    argv = f.read().split(b"\0")
            except OSError:
                continue
            argv = [a.decode("utf-8", "replace") for a in argv if a]
            if any(myname in a for a in argv):
                continue
            # Executing the script means it appears as an argument in its own
            # right, not buried inside a longer compound command string.
            if any(os.path.basename(a) == TARGET for a in argv):
                running.append((pid, " ".join(argv)[:90]))
    except FileNotFoundError:
        pass
    if running:
        print("sentinel_audit.sh appears to be running:", file=sys.stderr)
        for pid, cmd in running:
            print(f"  pid {pid}: {cmd}", file=sys.stderr)
        sys.exit("bash reads a script by byte offset as it runs, so patching it "
                 "now would corrupt that run.\nWait for it to finish, then try "
                 "again. Nothing changed.")

    original = open(args.file, encoding="utf-8").read()

    if MARKER in original:
        sys.exit("Already patched. Nothing changed.")

    patched = original
    for n, (old, new) in enumerate(EDITS, 1):
        count = patched.count(old)
        if count != 1:
            sys.exit(f"Edit {n} matched {count} times, expected exactly 1.\n"
                     f"Nothing changed. First 70 characters sought:\n  {old[:70]!r}")
        patched = patched.replace(old, new, 1)

    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=args.file, tofile=args.file + " (patched)"))
    print(diff)

    if args.dry_run:
        print("\nDry run. Nothing written.")
        return

    tmp = args.file + ".patched.tmp"
    open(tmp, "w", encoding="utf-8").write(patched)
    chk = subprocess.run(["bash", "-n", tmp], capture_output=True, text=True)
    if chk.returncode != 0:
        os.unlink(tmp)
        sys.exit(f"Patched script fails `bash -n`:\n{chk.stderr}\nNothing written.")
    os.unlink(tmp)

    open(args.file + ".bak", "w", encoding="utf-8").write(original)
    open(args.file, "w", encoding="utf-8").write(patched)
    os.chmod(args.file, 0o755)
    print(f"\nWrote {args.file}. Original kept at {args.file}.bak")
    print("Syntax checked with `bash -n`. Run the audit to confirm behaviour:")
    print("  ./sentinel_audit.sh 2>&1 | tail -40")
    print("\nExpect: geonet-pull reported as stopped rather than as an idle cost")
    print("risk, Artifact Registry repositories showing real locations or")
    print("'location undetermined', the 15 false OFF-REGION findings gone,")
    print("credited SKUs visible with an all-SKU reconciliation line, and")
    print("synexis-foremark audited as its own section.")


if __name__ == "__main__":
    main()
