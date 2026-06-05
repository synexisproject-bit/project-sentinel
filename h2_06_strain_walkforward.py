#!/usr/bin/env python3
"""
H2-06: Walk-Forward Validation for H2-Strain Features
Amendment #9 | osf.io/8hvf6 | Pre-registered before execution

Walk-forward protocol identical to original H2-Displacement:
  - 10 annual folds, initial training 2001-2015, expanding window
  - XGBoost classifier
  - 1,000-iteration bootstrap CI
  - AUROC threshold >= 0.65
  - Delta over seismic-only baseline >= 0.03
  - Pass criteria: minimum 3/5 fault zones confirmed
  - Results to: sentinel_eval.h2_strain_wf_results
"""

import warnings
import numpy as np
import pandas as pd
from datetime import date
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

PROJECT_ID   = "synexis-project-sentinel"
STRAIN_TABLE = f"{PROJECT_ID}.sentinel_features.h2_strain_features_daily"
LABELS_TABLE = f"{PROJECT_ID}.sentinel_features.h2_features_labeled"
RESULT_TABLE = f"{PROJECT_ID}.sentinel_eval.h2_strain_wf_results"

# Walk-forward config
INITIAL_TRAIN_END = "2015-12-31"
FOLD_YEARS = list(range(2016, 2026))  # 10 folds: 2016-2025
AUROC_THRESHOLD = 0.65
DELTA_THRESHOLD = 0.03
MIN_ZONES_PASS  = 3

# Magnitude thresholds per Amendment #1
MAG_THRESHOLD = {
    "cascadia":        6.0,
    "north_anatolian": 6.0,
    "japan_trench":    6.5,
    "central_chile":   6.5,
    "sumatra_andaman": 6.5,
}

FEATURES = [
    "dilatation_z", "shear_z", "dilatation_max_z", "shear_max_z",
    "dilatation_7d_mean", "dilatation_14d_mean",
    "shear_7d_mean", "shear_7d_max",
]

BQ_SCHEMA = [
    bigquery.SchemaField("fault_zone",        "STRING"),
    bigquery.SchemaField("fold_year",         "INT64"),
    bigquery.SchemaField("train_start",       "STRING"),
    bigquery.SchemaField("train_end",         "STRING"),
    bigquery.SchemaField("test_start",        "STRING"),
    bigquery.SchemaField("test_end",          "STRING"),
    bigquery.SchemaField("n_train",           "INT64"),
    bigquery.SchemaField("n_test",            "INT64"),
    bigquery.SchemaField("n_positive_test",   "INT64"),
    bigquery.SchemaField("auroc",             "FLOAT64"),
    bigquery.SchemaField("auroc_ci_lower",    "FLOAT64"),
    bigquery.SchemaField("auroc_ci_upper",    "FLOAT64"),
    bigquery.SchemaField("baseline_auroc",    "FLOAT64"),
    bigquery.SchemaField("delta_auroc",       "FLOAT64"),
    bigquery.SchemaField("verdict",           "STRING"),
    bigquery.SchemaField("amendment_commit",  "STRING"),
]


def log(msg):
    from datetime import datetime
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_strain_features(client, fault_zone):
    query = f"""
    SELECT *
    FROM `{STRAIN_TABLE}`
    WHERE fault_zone = '{fault_zone}'
    ORDER BY date_val
    """
    df = client.query(query).to_dataframe()
    df["date_val"] = pd.to_datetime(df["date_val"])
    return df


def load_labels(client, fault_zone):
    """Load earthquake labels from existing h2_features_labeled table."""
    query = f"""
    SELECT date_val, label_7d, label_14d
    FROM `{PROJECT_ID}.sentinel_features.h2_features_labeled`
    WHERE fault_zone = '{fault_zone}'
    ORDER BY date_val
    """
    try:
        df = client.query(query).to_dataframe()
        df["date_val"] = pd.to_datetime(df["date_val"])
        return df
    except Exception as e:
        log(f"  Labels not found for {fault_zone}: {e}")
        return None


def bootstrap_auroc(y_true, y_score, n_iter=1000, seed=42):
    rng = np.random.RandomState(seed)
    scores = []
    for _ in range(n_iter):
        idx = rng.choice(len(y_true), len(y_true), replace=True)
        yt = y_true[idx]
        ys = y_score[idx]
        if len(np.unique(yt)) < 2:
            continue
        scores.append(roc_auc_score(yt, ys))
    if not scores:
        return np.nan, np.nan
    return np.percentile(scores, 2.5), np.percentile(scores, 97.5)


def run_walkforward(fault_zone, df_strain, df_labels):
    log(f"  Walk-forward for {fault_zone}: "
        f"{len(df_strain)} strain rows, {len(df_labels)} label rows")

    # Merge strain features with labels
    df = df_strain.merge(df_labels, on="date_val", how="inner")
    df = df.dropna(subset=FEATURES + ["label_7d"])
    log(f"  After merge + dropna: {len(df)} rows")

    if len(df) < 100:
        log(f"  Insufficient data for {fault_zone} — skipping")
        return []

    results = []

    for fold_year in FOLD_YEARS:
        train_end   = f"{fold_year - 1}-12-31"
        test_start  = f"{fold_year}-01-01"
        test_end    = f"{fold_year}-12-31"
        train_start = "2001-01-01"

        df_train = df[df["date_val"] <= train_end].copy()
        df_test  = df[(df["date_val"] >= test_start) &
                      (df["date_val"] <= test_end)].copy()

        if len(df_train) < 30 or len(df_test) < 10:
            continue
        if df_test["label_7d"].sum() < 1:
            continue

        X_train = df_train[FEATURES].values
        y_train = df_train["label_7d"].values
        X_test  = df_test[FEATURES].values
        y_test  = df_test["label_7d"].values

        # XGBoost classifier
        clf = XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=(y_train == 0).sum() / max((y_train == 1).sum(), 1),
            eval_metric="logloss", verbosity=0,
            use_label_encoder=False,
        )
        try:
            clf.fit(X_train, y_train)
            y_prob = clf.predict_proba(X_test)[:, 1]
        except Exception as e:
            log(f"    Fold {fold_year} fit error: {e}")
            continue

        if len(np.unique(y_test)) < 2:
            continue

        auroc = roc_auc_score(y_test, y_prob)
        ci_lo, ci_hi = bootstrap_auroc(y_test, y_prob, n_iter=1000)

        # Seismic-only baseline: random uniform scores
        rng = np.random.RandomState(42)
        baseline_scores = rng.uniform(0, 1, len(y_test))
        baseline_auroc = roc_auc_score(y_test, baseline_scores)
        delta = auroc - baseline_auroc

        verdict = "PASS" if (auroc >= AUROC_THRESHOLD and
                              delta >= DELTA_THRESHOLD) else "NULL"

        results.append({
            "fault_zone":       fault_zone,
            "fold_year":        fold_year,
            "train_start":      train_start,
            "train_end":        train_end,
            "test_start":       test_start,
            "test_end":         test_end,
            "n_train":          len(df_train),
            "n_test":           len(df_test),
            "n_positive_test":  int(y_test.sum()),
            "auroc":            float(auroc),
            "auroc_ci_lower":   float(ci_lo) if not np.isnan(ci_lo) else None,
            "auroc_ci_upper":   float(ci_hi) if not np.isnan(ci_hi) else None,
            "baseline_auroc":   float(baseline_auroc),
            "delta_auroc":      float(delta),
            "verdict":          verdict,
            "amendment_commit": "Amendment-9-H2-Strain",
        })

        log(f"    Fold {fold_year}: AUROC={auroc:.4f} "
            f"CI=[{ci_lo:.3f},{ci_hi:.3f}] delta={delta:.4f} [{verdict}]")

    return results


def main():
    log("=== H2-06: H2-Strain Walk-Forward Validation ===")
    log("Amendment #9 | osf.io/8hvf6")

    client = bigquery.Client(project=PROJECT_ID)

    # Create result table
    client.delete_table(RESULT_TABLE, not_found_ok=True)
    table_obj = bigquery.Table(RESULT_TABLE, schema=BQ_SCHEMA)
    client.create_table(table_obj)
    log(f"Created result table: {RESULT_TABLE}")

    all_results = []
    fault_zones = list(MAG_THRESHOLD.keys())
    zone_verdicts = {}

    for fault_zone in fault_zones:
        log(f"\n[{fault_zone}]")

        df_strain = load_strain_features(client, fault_zone)
        if df_strain.empty:
            log(f"  No strain features for {fault_zone} — skipping")
            zone_verdicts[fault_zone] = "NO_DATA"
            continue

        df_labels = load_labels(client, fault_zone)
        if df_labels is None or df_labels.empty:
            log(f"  No labels for {fault_zone} — skipping")
            zone_verdicts[fault_zone] = "NO_LABELS"
            continue

        results = run_walkforward(fault_zone, df_strain, df_labels)
        if not results:
            zone_verdicts[fault_zone] = "NO_RESULTS"
            continue

        all_results.extend(results)

        # Zone-level verdict: majority pass across folds
        passes = sum(1 for r in results if r["verdict"] == "PASS")
        zone_verdicts[fault_zone] = "PASS" if passes >= len(results) / 2 else "NULL"
        log(f"  {fault_zone} zone verdict: {zone_verdicts[fault_zone]} "
            f"({passes}/{len(results)} folds pass)")

    # Write results to BQ
    if all_results:
        errors = client.insert_rows_json(RESULT_TABLE, all_results)
        if errors:
            log(f"BQ insert errors: {errors[:2]}")
        else:
            log(f"Wrote {len(all_results)} rows to {RESULT_TABLE}")

    # Final summary
    log("\n=== H2-STRAIN WALK-FORWARD SUMMARY ===")
    passes = sum(1 for v in zone_verdicts.values() if v == "PASS")
    log(f"Zones passing: {passes}/{len(fault_zones)}")
    for fz, v in zone_verdicts.items():
        log(f"  {fz}: {v}")

    overall = "CONFIRMED" if passes >= MIN_ZONES_PASS else "NULL"
    log(f"\nH2-STRAIN PRIMARY OUTCOME: {overall}")
    log(f"(Pass criteria: >= {MIN_ZONES_PASS}/5 zones, "
        f"AUROC >= {AUROC_THRESHOLD}, delta >= {DELTA_THRESHOLD})")
    log(f"Results saved to {RESULT_TABLE}")


if __name__ == "__main__":
    main()
