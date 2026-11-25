#!/usr/bin/env python3
"""
migrate_datasets.py — Dependency-aware migration of BigQuery datasets from
US multi-region to us-central1 for synexis-project-sentinel.

WHAT THIS DOES
  1. Scans the specified source datasets, classifying every table as a
     real TABLE or a VIEW.
  2. For VIEWs, parses the view's SQL for fully-qualified references to any
     other table/view in scope, building a dependency graph.
  3. Topologically sorts everything so dependencies are always created
     before dependents (tables first, then views in the right order,
     even across datasets).
  4. Migrates TABLEs via extract-to-Avro -> load, explicitly using
     use_avro_logical_types on BOTH sides (this is what silently broke
     TIMESTAMP columns during the synexis_dreams test migration).
  5. Recreates VIEWs by rewriting their query text to point at the new
     _central1 dataset names, then creating them in dependency order.
  6. Verifies row counts (old vs new) for every table and view, and
     writes a full report.

SAFETY
  - Defaults to DRY RUN. Nothing is created or touched until you pass --execute.
  - Never deletes or modifies anything in the source (US multi-region) datasets.
  - Skips any table/view that already exists in the target dataset with a
    matching row count (idempotent — safe to re-run after a partial failure).
  - Only creates the target datasets/tables/views; deleting the old
    multi-region datasets is a deliberate separate step you run yourself
    after reviewing the migration report.

USAGE
  # Dry run (default) — prints the full migration plan, touches nothing
  python3 migrate_datasets.py

  # Actually run it
  python3 migrate_datasets.py --execute

  # Migrate a subset only
  python3 migrate_datasets.py --datasets sentinel_raw,sentinel_features --execute

REQUIREMENTS
  pip install google-cloud-bigquery --break-system-packages
  (Cloud Shell usually has this preinstalled; if not, run the line above.)
"""

import argparse
import re
import sys
from collections import defaultdict, deque

from google.cloud import bigquery
from google.api_core.exceptions import NotFound, Conflict

PROJECT = "synexis-project-sentinel"
DEFAULT_LOCATION = "us-central1"
DEFAULT_STAGING_BUCKET = "synexis-project-sentinel-raw-central1"

DEFAULT_DATASETS = [
    "hac_intake",
    "sentinel_analysis",
    "sentinel_cur",
    "sentinel_derived",
    "sentinel_eval",
    "sentinel_features",
    "sentinel_geocoding",
    "sentinel_groundtruth",
    "sentinel_mart",
    "sentinel_raw",
    "sentinel_staging",
]

SUFFIX = "_central1"


def target_dataset(ds: str) -> str:
    return f"{ds}{SUFFIX}"


class Node:
    """One table or view, identified by (dataset, table_id)."""

    def __init__(self, dataset, table_id, table_type, view_query=None):
        self.dataset = dataset
        self.table_id = table_id
        self.table_type = table_type  # "TABLE" or "VIEW"
        self.view_query = view_query
        self.deps = set()  # set of (dataset, table_id) this node depends on

    @property
    def key(self):
        return (self.dataset, self.table_id)

    def __repr__(self):
        return f"{self.dataset}.{self.table_id} ({self.table_type})"


def discover(client: bigquery.Client, datasets):
    """Scan all datasets, return dict[(dataset, table_id)] -> Node."""
    nodes = {}
    for ds in datasets:
        print(f"Scanning {ds} ...")
        dataset_ref = bigquery.DatasetReference(PROJECT, ds)
        for tbl in client.list_tables(dataset_ref):
            table_type = tbl.table_type  # "TABLE" or "VIEW"
            if table_type == "VIEW":
                full_table = client.get_table(tbl.reference)
                view_query = full_table.view_query
            else:
                view_query = None
            node = Node(ds, tbl.table_id, table_type, view_query)
            nodes[node.key] = node
    return nodes


def build_dependencies(nodes):
    """For every VIEW node, find references to other known nodes in its query."""
    all_keys = list(nodes.keys())
    for node in nodes.values():
        if node.table_type != "VIEW" or not node.view_query:
            continue
        query = node.view_query
        for (dep_ds, dep_table) in all_keys:
            if (dep_ds, dep_table) == node.key:
                continue
            # Match fully-qualified refs like:
            #   `synexis-project-sentinel.dep_ds.dep_table`
            #   synexis-project-sentinel.dep_ds.dep_table
            #   dep_ds.dep_table   (unqualified, same-project shorthand)
            patterns = [
                rf"{re.escape(PROJECT)}\.{re.escape(dep_ds)}\.{re.escape(dep_table)}\b",
                rf"(?<![\w.]){re.escape(dep_ds)}\.{re.escape(dep_table)}\b",
            ]
            if any(re.search(p, query) for p in patterns):
                node.deps.add((dep_ds, dep_table))


def topo_sort(nodes):
    """Kahn's algorithm. Returns ordered list of Node, deps before dependents."""
    in_degree = {k: 0 for k in nodes}
    children = defaultdict(list)
    for node in nodes.values():
        for dep in node.deps:
            if dep not in nodes:
                continue  # dependency outside our scan scope; ignore
            children[dep].append(node.key)
            in_degree[node.key] += 1

    queue = deque(k for k, d in in_degree.items() if d == 0)
    ordered = []
    while queue:
        # tables before views when both are unblocked, for readability
        batch = sorted(queue, key=lambda k: (nodes[k].table_type == "VIEW", k))
        k = batch[0]
        queue.remove(k)
        ordered.append(nodes[k])
        for child in children[k]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(ordered) != len(nodes):
        remaining = set(nodes) - {n.key for n in ordered}
        raise RuntimeError(f"Cycle detected or unresolved deps among: {remaining}")
    return ordered


def rewrite_view_query(query, datasets):
    """Point a view's query at the _central1 target datasets."""
    new_query = query
    for ds in datasets:
        new_query = re.sub(
            rf"{re.escape(PROJECT)}\.{re.escape(ds)}\.",
            f"{PROJECT}.{target_dataset(ds)}.",
            new_query,
        )
        new_query = re.sub(
            rf"(?<![\w.]){re.escape(ds)}\.",
            f"{target_dataset(ds)}.",
            new_query,
        )
    return new_query


def row_count(client, dataset, table_id):
    query = f"SELECT COUNT(*) AS n FROM `{PROJECT}.{dataset}.{table_id}`"
    try:
        result = list(client.query(query).result())
        return result[0].n
    except NotFound:
        return None


def ensure_dataset(client, dataset_id, location, execute):
    ref = bigquery.DatasetReference(PROJECT, dataset_id)
    try:
        client.get_dataset(ref)
        print(f"  dataset {dataset_id} already exists")
        return
    except NotFound:
        pass
    print(f"  {'[EXECUTE] ' if execute else '[DRY RUN] '}create dataset {dataset_id} in {location}")
    if execute:
        ds = bigquery.Dataset(ref)
        ds.location = location
        client.create_dataset(ds)


def migrate_table(client, node, staging_bucket, execute, report):
    src_ds, tbl = node.dataset, node.table_id
    tgt_ds = target_dataset(src_ds)

    old_count = row_count(client, src_ds, tbl)
    existing_count = row_count(client, tgt_ds, tbl)
    if existing_count is not None and existing_count == old_count:
        print(f"  SKIP {src_ds}.{tbl} — already migrated, row counts match ({old_count})")
        report.append((src_ds, tbl, "TABLE", "skipped", old_count, existing_count))
        return

    uri = f"gs://{staging_bucket}/migrate/{src_ds}/{tbl}/*.avro"
    print(f"  {'[EXECUTE] ' if execute else '[DRY RUN] '}migrate TABLE {src_ds}.{tbl} -> {tgt_ds}.{tbl}  (rows: {old_count})")

    if not execute:
        report.append((src_ds, tbl, "TABLE", "dry-run", old_count, None))
        return

    src_table_ref = f"{PROJECT}.{src_ds}.{tbl}"
    extract_job = client.extract_table(
        src_table_ref,
        uri,
        job_config=bigquery.ExtractJobConfig(
            destination_format="AVRO",
            use_avro_logical_types=True,
        ),
    )
    extract_job.result()

    load_job = client.load_table_from_uri(
        uri,
        f"{PROJECT}.{tgt_ds}.{tbl}",
        job_config=bigquery.LoadJobConfig(
            source_format="AVRO",
            use_avro_logical_types=True,
            write_disposition="WRITE_TRUNCATE",
        ),
    )
    load_job.result()

    new_count = row_count(client, tgt_ds, tbl)
    status = "OK" if new_count == old_count else "MISMATCH"
    report.append((src_ds, tbl, "TABLE", status, old_count, new_count))
    print(f"    -> {status}: old={old_count} new={new_count}")


def migrate_view(client, node, all_datasets, execute, report):
    src_ds, tbl = node.dataset, node.table_id
    tgt_ds = target_dataset(src_ds)

    old_count = row_count(client, src_ds, tbl)
    existing_count = row_count(client, tgt_ds, tbl)
    if existing_count is not None and existing_count == old_count:
        print(f"  SKIP {src_ds}.{tbl} (view) — already migrated, row counts match")
        report.append((src_ds, tbl, "VIEW", "skipped", old_count, existing_count))
        return

    new_query = rewrite_view_query(node.view_query, all_datasets)
    print(f"  {'[EXECUTE] ' if execute else '[DRY RUN] '}recreate VIEW {src_ds}.{tbl} -> {tgt_ds}.{tbl}")

    if not execute:
        report.append((src_ds, tbl, "VIEW", "dry-run", old_count, None))
        return

    table_ref = f"{PROJECT}.{tgt_ds}.{tbl}"
    view = bigquery.Table(table_ref)
    view.view_query = new_query
    try:
        client.delete_table(table_ref, not_found_ok=True)
        client.create_table(view)
    except Conflict:
        pass

    new_count = row_count(client, tgt_ds, tbl)
    status = "OK" if new_count == old_count else "MISMATCH"
    report.append((src_ds, tbl, "VIEW", status, old_count, new_count))
    print(f"    -> {status}: old={old_count} new={new_count}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default=",".join(DEFAULT_DATASETS))
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--staging-bucket", default=DEFAULT_STAGING_BUCKET)
    ap.add_argument("--execute", action="store_true", help="Actually run. Default is dry run.")
    args = ap.parse_args()

    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    client = bigquery.Client(project=PROJECT)

    print(f"=== {'EXECUTING' if args.execute else 'DRY RUN'} migration for: {', '.join(datasets)} ===\n")

    nodes = discover(client, datasets)
    build_dependencies(nodes)
    ordered = topo_sort(nodes)

    print(f"\nDiscovered {len(nodes)} objects "
          f"({sum(1 for n in nodes.values() if n.table_type == 'TABLE')} tables, "
          f"{sum(1 for n in nodes.values() if n.table_type == 'VIEW')} views)\n")

    print("Migration order:")
    for n in ordered:
        dep_str = f"  <- depends on {sorted(n.deps)}" if n.deps else ""
        print(f"  {n.dataset}.{n.table_id} ({n.table_type}){dep_str}")
    print()

    print("Ensuring target datasets exist:")
    for ds in datasets:
        ensure_dataset(client, target_dataset(ds), args.location, args.execute)
    print()

    report = []
    for node in ordered:
        if node.table_type == "TABLE":
            migrate_table(client, node, args.staging_bucket, args.execute, report)
        else:
            migrate_view(client, node, datasets, args.execute, report)

    print("\n=== REPORT ===")
    print(f"{'dataset':<22}{'table':<40}{'type':<8}{'status':<10}{'old':>8}{'new':>8}")
    mismatches = 0
    for ds, tbl, ttype, status, old, new in report:
        print(f"{ds:<22}{tbl:<40}{ttype:<8}{status:<10}{str(old):>8}{str(new):>8}")
        if status == "MISMATCH":
            mismatches += 1

    print(f"\n{len(report)} objects processed, {mismatches} mismatches.")
    if mismatches:
        print("!! Review MISMATCH rows above before deleting any source data.")
        sys.exit(1)


if __name__ == "__main__":
    main()
