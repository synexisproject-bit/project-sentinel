"""
Project Sentinel — Walk-Forward Validation Engine
Phase 2 Amendment #1 (commit 496ebf1)

Implements 10-fold expanding-window walk-forward validation as specified
in sentinel_phase2_amendment_1.docx.

Usage:
    # H1-WF (seismic features re-run under amended protocol):
    python walk_forward_engine.py --hypothesis h1

    # H3 (regional TEC — after TEC pipeline is built):
    python walk_forward_engine.py --hypothesis h3

    # H4 (convergence — after H1-WF, H2, H3 complete):
    python walk_forward_engine.py --hypothesis h4

Output:
    - Per-fold AUROC table printed to console
    - Pooled AUROC + 95% CI printed to console
    - Results saved to BigQuery: sentinel_eval.{hypothesis}_wf_results

Pre-registration commits:
    f172953 — Phase 2 pre-registration
    496ebf1 — Amendment #1 (this protocol)
"""

import argparse
import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score
from sklearn.preprocessing import StandardScaler
from sklearn.utils import resample
import xgboost as xgb

warnings.filterwarnings('ignore')

PROJECT = "synexis-project-sentinel"

# ── Amendment #1: Walk-forward fold structure ─────────────────────────────────
# Initial training window: 2001-2015 (15 years minimum)
# 10 annual test folds: 2016 through 2025
FOLDS = [
    {"train_end": "2015-12-31", "test_start": "2016-01-01", "test_end": "2016-12-31", "fold": 1},
    {"train_end": "2016-12-31", "test_start": "2017-01-01", "test_end": "2017-12-31", "fold": 2},
    {"train_end": "2017-12-31", "test_start": "2018-01-01", "test_end": "2018-12-31", "fold": 3},
    {"train_end": "2018-12-31", "test_start": "2019-01-01", "test_end": "2019-12-31", "fold": 4},
    {"train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2020-12-31", "fold": 5},
    {"train_end": "2020-12-31", "test_start": "2021-01-01", "test_end": "2021-12-31", "fold": 6},
    {"train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2022-12-31", "fold": 7},
    {"train_end": "2022-12-31", "test_start": "2023-01-01", "test_end": "2023-12-31", "fold": 8},
    {"train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2024-12-31", "fold": 9},
    {"train_end": "2024-12-31", "test_start": "2025-01-01", "test_end": "2025-12-31", "fold": 10},
]

# ── Amendment #1: Magnitude threshold stratification ─────────────────────────
# Cascadia and North Anatolian use M≥6.0 label column
# All others use M≥6.5 label column
FAULT_LABEL_COL = {
    "japan_trench":    "label_7d",     # M≥6.5
    "cascadia":        "label_7d_m60", # M≥6.0 — requires new label column
    "central_chile":   "label_7d",     # M≥6.5
    "north_anatolian": "label_7d_m60", # M≥6.0 — requires new label column
    "sumatra_andaman": "label_7d",     # M≥6.5
}

# ── Pre-registered thresholds (unchanged from original pre-registration) ──────
HYPOTHESIS_CONFIG = {
    "h1": {
        "name": "H1-WF",
        "description": "Seismic catalog features under walk-forward protocol",
        "auroc_threshold": 0.60,
        "min_faults": 3,
        "features": [
            "b_value_90d",
            "mean_mag_90d",
            "event_count_90d",
            "quiescence_z_stat",
            "baseline_365d_mean",
            "foreshock_rate_z",
            "event_count_7d",
            "baseline_30d_mean",
        ],
        "feature_table": "sentinel_features.h1_features_daily",
        "label_table":   "sentinel_features.h1_labels",
        "result_table":  "sentinel_eval.h1_wf_results",
    },
    "h3": {
        "name": "H3",
        "description": "Regional TEC features (INSPIRE methodology)",
        "auroc_threshold": 0.52,  # Must beat Phase 1 global TEC baseline
        "min_faults": 2,          # ≥2 of 5 systems
        "features": [
            "tec_delta_fullday",
            "tec_delta_nighttime",
            "tec_lssi",
            "tec_delta_lag1d",
            "tec_delta_lag3d",
            "tec_delta_lag5d",
            "tec_delta_lag7d",
            "tec_nighttime_lag5d",
            # Solar confound controls
            "kp_max",
            "dst_index",
            "solar_flux_f107",
        ],
        "feature_table": "sentinel_features.h3_features_daily",
        "label_table":   "sentinel_features.h1_labels",  # Same labels
        "result_table":  "sentinel_eval.h3_wf_results",
    },
    "h4": {
        "name": "H4",
        "description": "Multi-stream convergence model",
        "auroc_threshold": 0.65,
        "min_faults": 3,
        "features": [],  # Populated dynamically from all available streams
        "feature_table": "sentinel_features.h4_features_daily",
        "label_table":   "sentinel_features.h1_labels",
        "result_table":  "sentinel_eval.h4_wf_results",
    },
    "h2": {
        "name": "H2",
        "description": "GPS deformation features (fault-perpendicular stack)",
        "auroc_threshold": 0.58,
        "min_faults": 2,
        "features": [
            "z_fp", "z_east", "z_north", "z_up", "z_fp_std",
            "z_fp_3d_mean", "z_fp_7d_mean", "z_fp_14d_mean", "z_fp_30d_mean",
            "z_fp_7d_std", "z_fp_14d_std", "z_fp_30d_std",
            "z_fp_7d_max_abs", "z_fp_14d_max_abs", "z_fp_30d_max_abs",
            "z_fp_delta_3d", "z_fp_delta_7d", "z_fp_delta_14d",
            "z_up_7d_mean", "z_up_14d_mean", "z_up_30d_mean",
            "z_fp_std_7d_mean", "z_fp_std_14d_mean",
            "n_stations_7d_mean", "n_stations_30d_mean",
        ],
        "feature_table": "sentinel_features.h2_features_final",
        "label_table":   "sentinel_features.h1_labels",
        "result_table":  "sentinel_eval.h2_wf_results",
    },
}

# ── XGBoost base params ───────────────────────────────────────────────────────
XGB_BASE_PARAMS = {
    "n_estimators":     300,
    "max_depth":        4,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "eval_metric":      "auc",
    "random_state":     42,
    "tree_method":      "hist",
    "verbosity":        0,
}

BOOTSTRAP_ITERS = 1000
MIN_POSITIVE_OBSERVATIONS = 5


# ── Data loading ──────────────────────────────────────────────────────────────

def load_all_data(client, config, fault_id):
    """Load full feature + label dataset for one fault system."""

    label_col = FAULT_LABEL_COL.get(fault_id, "label_7d")

    # Check if M≥6.0 label column exists — if not, use M≥6.5 with warning
    if label_col == "label_7d_m60":
        try:
            test_query = f"""
            SELECT {label_col} FROM `{PROJECT}.{config['label_table']}`
            WHERE fault_id = '{fault_id}' LIMIT 1
            """
            client.query(test_query).result()
        except Exception:
            print(f"  WARNING: label_7d_m60 not found for {fault_id}.")
            print(f"  Run h3_00_build_m60_labels.sql first to create M>=6.0 labels.")
            print(f"  Falling back to label_7d (M>=6.5) for now.")
            label_col = "label_7d"

    query = f"""
    SELECT
        f.date_val,
        f.fault_id,
        {", ".join(f"f.{feat}" for feat in config["features"] if feat in get_available_columns(client, config["feature_table"]))},
        l.{label_col} AS label,
        l.label_7d,
        l.max_upcoming_magnitude
    FROM `{PROJECT}.{config["feature_table"]}` f
    JOIN `{PROJECT}.{config["label_table"]}` l
        ON f.date_val = l.date_val AND f.fault_id = l.fault_id
    WHERE f.fault_id = '{fault_id}'
    ORDER BY f.date_val
    """

    df = client.query(query).to_dataframe()
    df["date_val"] = pd.to_datetime(df["date_val"])
    return df, label_col


def get_available_columns(client, table_path):
    """Get available column names from a BigQuery table."""
    dataset, table = table_path.split(".")
    query = f"""
    SELECT column_name FROM `{PROJECT}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{table}'
    """
    try:
        return [row.column_name for row in client.query(query).result()]
    except Exception:
        return []


def load_fault_data_simple(client, config, fault_id):
    """Simplified loader using available features only."""

    label_col = FAULT_LABEL_COL.get(fault_id, "label_7d")
    available = get_available_columns(client, config["feature_table"])
    features_to_use = [f for f in config["features"] if f in available]

    if not features_to_use:
        print(f"  ERROR: No features from config found in {config['feature_table']}")
        print(f"  Available columns: {available}")
        return None, label_col, []

    # Check if M≥6.0 label exists
    label_available = get_available_columns(client, config["label_table"])
    if label_col not in label_available:
        print(f"  WARNING: {label_col} not in label table. Using label_7d instead.")
        label_col = "label_7d"

    feat_select = ", ".join(f"f.{feat}" for feat in features_to_use)

    # h3_features_daily uses 'day' column, h1_features_daily uses 'date_val'
    date_col = "day" if config["feature_table"].endswith("h3_features_daily") else "date_val"

    query = f"""
    SELECT
        f.{date_col} AS date_val,
        f.fault_id,
        {feat_select},
        l.{label_col} AS label,
        l.max_upcoming_magnitude
    FROM `{PROJECT}.{config["feature_table"]}` f
    JOIN `{PROJECT}.{config["label_table"]}` l
        ON f.{date_col} = l.date_val AND f.fault_id = l.fault_id
    WHERE f.fault_id = '{fault_id}'
      AND f.{date_col} >= '2001-01-01'
    ORDER BY f.{date_col}
    """

    df = client.query(query).to_dataframe()
    df["date_val"] = pd.to_datetime(df["date_val"])
    print(f"  Loaded {len(df):,} rows | Features: {len(features_to_use)} | Label: {label_col}")
    return df, label_col, features_to_use


# ── Walk-forward core ─────────────────────────────────────────────────────────

def run_single_fold(df, features, label_col, fold_spec):
    """Train on data up to train_end, test on test_start to test_end."""

    train_end   = pd.Timestamp(fold_spec["train_end"])
    test_start  = pd.Timestamp(fold_spec["test_start"])
    test_end    = pd.Timestamp(fold_spec["test_end"])

    train = df[df["date_val"] <= train_end].copy()
    test  = df[(df["date_val"] >= test_start) & (df["date_val"] <= test_end)].copy()

    # Fill NaN
    train[features] = train[features].fillna(0)
    test[features]  = test[features].fillna(0)

    y_train = train['label'].values
    y_test  = test['label'].values

    n_pos_train = int(y_train.sum())
    n_pos_test  = int(y_test.sum())

    if n_pos_train < 3:
        return {
            "fold": fold_spec["fold"],
            "status": "SKIP_INSUFFICIENT_TRAIN",
            "n_train": len(train),
            "n_test": len(test),
            "n_pos_train": n_pos_train,
            "n_pos_test": n_pos_test,
            "auroc": None,
            "brier": None,
            "probas": None,
            "y_test": None,
        }

    if len(np.unique(y_test)) < 2:
        return {
            "fold": fold_spec["fold"],
            "status": "SKIP_NO_TEST_POSITIVES",
            "n_train": len(train),
            "n_test": len(test),
            "n_pos_train": n_pos_train,
            "n_pos_test": n_pos_test,
            "auroc": None,
            "brier": None,
            "probas": test[features].values.tolist() if len(test) > 0 else None,
            "y_test": y_test.tolist(),
        }

    X_train = train[features].values
    X_test  = test[features].values

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    pos_rate  = y_train.mean()
    scale_pos = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0

    params = XGB_BASE_PARAMS.copy()
    params["scale_pos_weight"] = scale_pos

    model = xgb.XGBClassifier(**params)
    model.fit(X_train_s, y_train, verbose=False)

    probas = model.predict_proba(X_test_s)[:, 1]
    auroc  = float(roc_auc_score(y_test, probas))
    brier  = float(brier_score_loss(y_test, probas))

    return {
        "fold":         fold_spec["fold"],
        "status":       "OK",
        "n_train":      len(train),
        "n_test":       len(test),
        "n_pos_train":  n_pos_train,
        "n_pos_test":   n_pos_test,
        "auroc":        auroc,
        "brier":        brier,
        "probas":       probas.tolist(),
        "y_test":       y_test.tolist(),
        "feature_importances": dict(zip(features, model.feature_importances_.tolist())),
    }


def bootstrap_auroc_ci(y_true, y_score, n_iterations=BOOTSTRAP_ITERS, ci=0.95):
    """Bootstrap 95% CI for AUROC on pooled test observations."""
    if len(np.unique(y_true)) < 2:
        return None, None
    aurocs = []
    n = len(y_true)
    for _ in range(n_iterations):
        idx = resample(np.arange(n), random_state=None)
        y_b = y_true[idx]
        s_b = y_score[idx]
        if len(np.unique(y_b)) < 2:
            continue
        aurocs.append(roc_auc_score(y_b, s_b))
    if len(aurocs) < 100:
        return None, None
    lower = np.percentile(aurocs, (1 - ci) / 2 * 100)
    upper = np.percentile(aurocs, (1 - (1 - ci) / 2) * 100)
    return float(lower), float(upper)


def run_walk_forward(df, features, label_col, fault_id, hypothesis):
    """Run all 10 folds and compute pooled AUROC with CI."""

    print(f"\n  Running {len(FOLDS)} folds...")
    print(f"  {'Fold':5s} {'Train N':>8s} {'Test N':>7s} {'Pos Train':>9s} {'Pos Test':>8s} {'AUROC':>7s} {'Status'}")
    print(f"  {'─'*65}")

    fold_results = []
    all_probas = []
    all_y_test = []

    for fold_spec in FOLDS:
        result = run_single_fold(df, features, label_col, fold_spec)
        fold_results.append(result)

        auroc_str = f"{result['auroc']:.4f}" if result["auroc"] is not None else "N/A"
        print(f"  {result['fold']:5d} {result['n_train']:>8,} {result['n_test']:>7,} "
              f"{result['n_pos_train']:>9,} {result['n_pos_test']:>8,} "
              f"{auroc_str:>7s} {result['status']}")

        if result["status"] == "OK" and result["probas"] is not None:
            all_probas.extend(result["probas"])
            all_y_test.extend(result["y_test"])

    # Pooled evaluation
    all_probas = np.array(all_probas)
    all_y_test = np.array(all_y_test)
    total_pos  = int(all_y_test.sum())

    print(f"\n  Pooled test observations: {len(all_y_test):,} | Positive: {total_pos}")

    if total_pos < MIN_POSITIVE_OBSERVATIONS:
        print(f"  INSUFFICIENT_DATA: < {MIN_POSITIVE_OBSERVATIONS} positive observations")
        return {
            "fault_id":       fault_id,
            "hypothesis":     hypothesis,
            "verdict":        "INSUFFICIENT_DATA",
            "pooled_auroc":   None,
            "ci_lower":       None,
            "ci_upper":       None,
            "mean_fold_auroc": None,
            "std_fold_auroc":  None,
            "total_pos_test":  total_pos,
            "fold_results":    fold_results,
        }

    if len(np.unique(all_y_test)) < 2:
        print(f"  INSUFFICIENT_DATA: only one class in pooled test set")
        return {
            "fault_id":       fault_id,
            "hypothesis":     hypothesis,
            "verdict":        "INSUFFICIENT_DATA",
            "pooled_auroc":   None,
            "ci_lower":       None,
            "ci_upper":       None,
            "mean_fold_auroc": None,
            "std_fold_auroc":  None,
            "total_pos_test":  total_pos,
            "fold_results":    fold_results,
        }

    pooled_auroc = float(roc_auc_score(all_y_test, all_probas))
    pooled_brier = float(brier_score_loss(all_y_test, all_probas))
    pooled_auprc = float(average_precision_score(all_y_test, all_probas))

    print(f"  Computing bootstrap CI ({BOOTSTRAP_ITERS} iterations)...")
    ci_lower, ci_upper = bootstrap_auroc_ci(all_y_test, all_probas)

    valid_fold_aurocs = [r["auroc"] for r in fold_results if r["auroc"] is not None]
    mean_fold_auroc = float(np.mean(valid_fold_aurocs)) if valid_fold_aurocs else None
    std_fold_auroc  = float(np.std(valid_fold_aurocs))  if valid_fold_aurocs else None

    config   = HYPOTHESIS_CONFIG[hypothesis]
    threshold = config["auroc_threshold"]

    # Pre-registered interpretation rules (Amendment #1, Section 2.4)
    if pooled_auroc >= threshold:
        if std_fold_auroc is not None and std_fold_auroc > 0.15:
            verdict = "CONFIRMED_UNSTABLE"  # Passes but high variance across folds
        else:
            verdict = "CONFIRMED"
    else:
        verdict = "NULL"

    ci_str = f"[{ci_lower:.4f}, {ci_upper:.4f}]" if ci_lower is not None else "[N/A]"
    print(f"\n  ── POOLED AUROC: {pooled_auroc:.4f}  95% CI: {ci_str} ──")
    print(f"  ── Brier: {pooled_brier:.4f} | AUPRC: {pooled_auprc:.4f} ──")
    print(f"  ── Mean fold AUROC: {mean_fold_auroc:.4f} ± {std_fold_auroc:.4f} ──")
    print(f"  ── VERDICT: {verdict} (threshold {threshold}) ──")

    return {
        "fault_id":         fault_id,
        "hypothesis":       hypothesis,
        "verdict":          verdict,
        "pooled_auroc":     pooled_auroc,
        "pooled_brier":     pooled_brier,
        "pooled_auprc":     pooled_auprc,
        "ci_lower":         ci_lower,
        "ci_upper":         ci_upper,
        "mean_fold_auroc":  mean_fold_auroc,
        "std_fold_auroc":   std_fold_auroc,
        "total_pos_test":   total_pos,
        "n_valid_folds":    len(valid_fold_aurocs),
        "fold_aurocs":      json.dumps([r["auroc"] for r in fold_results]),
        "fold_pos_counts":  json.dumps([r["n_pos_test"] for r in fold_results]),
        "fold_results":     fold_results,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(all_fault_results, hypothesis):
    config    = HYPOTHESIS_CONFIG[hypothesis]
    threshold = config["auroc_threshold"]
    min_faults = config["min_faults"]

    print("\n" + "="*70)
    print(f"{config['name']} FINAL SUMMARY")
    print(f"Amendment #1 protocol (commit 496ebf1)")
    print("="*70)

    confirmed   = []
    unstable    = []
    null_faults = []
    insufficient = []

    for r in all_fault_results:
        fid     = r["fault_id"]
        verdict = r["verdict"]
        auroc   = r.get("pooled_auroc")
        ci_l    = r.get("ci_lower")
        ci_u    = r.get("ci_upper")

        auroc_str = f"{auroc:.4f}" if auroc is not None else "N/A   "
        ci_str    = f"[{ci_l:.4f},{ci_u:.4f}]" if ci_l is not None else "[N/A        ]"

        print(f"  {fid:25s} AUROC={auroc_str}  CI={ci_str}  [{verdict}]")

        if verdict == "CONFIRMED":
            confirmed.append(fid)
        elif verdict == "CONFIRMED_UNSTABLE":
            unstable.append(fid)
        elif verdict == "NULL":
            null_faults.append(fid)
        else:
            insufficient.append(fid)

    n_confirmed = len(confirmed) + len(unstable)
    print(f"\nFaults confirmed: {n_confirmed} of 5  (required: {min_faults})")

    if n_confirmed >= min_faults:
        print(f"\n✓ {config['name']} CONFIRMED — {n_confirmed} systems >= {threshold}")
        if unstable:
            print(f"  NOTE: {', '.join(unstable)} confirmed but high fold variance (>0.15 std)")
    else:
        print(f"\n✗ {config['name']} NULL — {n_confirmed} systems >= {threshold} (need {min_faults})")

    if insufficient:
        print(f"  Insufficient data: {', '.join(insufficient)}")

    print("="*70)


def save_results(client, all_fault_results, hypothesis):
    config = HYPOTHESIS_CONFIG[hypothesis]
    table_out = f"{PROJECT}.{config['result_table']}"

    rows = []
    for r in all_fault_results:
        row = {k: v for k, v in r.items() if k != "fold_results"}
        row["run_timestamp"]    = datetime.utcnow().isoformat()
        row["prereg_commit"]    = "f172953"
        row["amendment_commit"] = "496ebf1"
        rows.append(row)

    df = pd.DataFrame(rows)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, table_out, job_config=job_config)
    job.result()
    print(f"\nResults saved to {table_out}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Project Sentinel Walk-Forward Engine")
    parser.add_argument("--hypothesis", choices=["h1", "h2", "h3", "h4"], default="h1",
                        help="Which hypothesis to evaluate (default: h1)")
    parser.add_argument("--fault", default=None,
                        help="Run single fault system only (optional)")
    args = parser.parse_args()

    hypothesis = args.hypothesis
    config     = HYPOTHESIS_CONFIG[hypothesis]

    print("="*70)
    print(f"Project Sentinel — Walk-Forward Engine")
    print(f"Hypothesis:  {config['name']} — {config['description']}")
    print(f"Protocol:    Amendment #1 (496ebf1) — 10-fold expanding window")
    print(f"Threshold:   AUROC >= {config['auroc_threshold']} in >= {config['min_faults']} of 5 systems")
    print(f"Timestamp:   {datetime.utcnow().isoformat()}")
    print("="*70)

    client = bigquery.Client(project=PROJECT)

    fault_query = """
    SELECT fault_id FROM `synexis-project-sentinel.sentinel_features.fault_systems`
    ORDER BY priority, fault_id
    """
    fault_ids = [row.fault_id for row in client.query(fault_query).result()]

    if args.fault:
        fault_ids = [f for f in fault_ids if f == args.fault]
        if not fault_ids:
            print(f"ERROR: fault '{args.fault}' not found")
            return

    print(f"\nFault systems: {fault_ids}\n")

    all_fault_results = []

    for fault_id in fault_ids:
        print(f"\n{'─'*60}")
        print(f"Processing: {fault_id}")
        label_col_expected = FAULT_LABEL_COL.get(fault_id, "label_7d")
        threshold_str = "M>=6.0" if "m60" in label_col_expected else "M>=6.5"
        print(f"Label threshold: {threshold_str} (Amendment #1)")
        print('─'*60)

        df, label_col, features = load_fault_data_simple(client, config, fault_id)

        if df is None or len(df) == 0:
            print(f"  No data — skipping")
            continue

        if not features:
            print(f"  No features available — skipping. Build feature table first.")
            continue

        result = run_walk_forward(df, features, label_col, fault_id, hypothesis)
        all_fault_results.append(result)

    if not all_fault_results:
        print("\nNo results to save.")
        return

    save_results(client, all_fault_results, hypothesis)
    print_summary(all_fault_results, hypothesis)


if __name__ == "__main__":
    main()
