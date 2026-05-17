#!/usr/bin/env python3
"""
H1-IQR Walk-Forward Validation — Project Sentinel
Tests moving IQR TEC baseline against seismic-only baseline
Amendment #9 v3 | osf.io/8hvf6
Pre-registered before execution
"""
import argparse, json, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score
from sklearn.preprocessing import StandardScaler
from sklearn.utils import resample
import xgboost as xgb
warnings.filterwarnings("ignore")

PROJECT       = "synexis-project-sentinel"
FEATURE_TABLE = "sentinel_features.h1_iqr_features_daily"
RESULT_TABLE  = "sentinel_eval.h1_iqr_wf_results"

PREREGISTERED_FAULTS = [
    "japan_trench", "cascadia", "central_chile",
    "north_anatolian", "sumatra_andaman"
]

# Pre-registered thresholds (identical to H1-H4)
H1_IQR_AUROC_THRESHOLD = 0.65
H1_IQR_DELTA_THRESHOLD = 0.03
H1_IQR_MIN_FAULTS      = 3
BOOTSTRAP_ITERS        = 1000
MIN_POS_TRAIN          = 3
MIN_POS_TEST_POOL      = 5

# Walk-forward folds — identical to H1-H4
FOLDS = [
    {"train_end":"2015-12-31","test_start":"2016-01-01","test_end":"2016-12-31","fold":1},
    {"train_end":"2016-12-31","test_start":"2017-01-01","test_end":"2017-12-31","fold":2},
    {"train_end":"2017-12-31","test_start":"2018-01-01","test_end":"2018-12-31","fold":3},
    {"train_end":"2018-12-31","test_start":"2019-01-01","test_end":"2019-12-31","fold":4},
    {"train_end":"2019-12-31","test_start":"2020-01-01","test_end":"2020-12-31","fold":5},
    {"train_end":"2020-12-31","test_start":"2021-01-01","test_end":"2021-12-31","fold":6},
    {"train_end":"2021-12-31","test_start":"2022-01-01","test_end":"2022-12-31","fold":7},
    {"train_end":"2022-12-31","test_start":"2023-01-01","test_end":"2023-12-31","fold":8},
    {"train_end":"2023-12-31","test_start":"2024-01-01","test_end":"2024-12-31","fold":9},
    {"train_end":"2024-12-31","test_start":"2025-01-01","test_end":"2025-12-31","fold":10},
]

# IQR-specific TEC features (H1-IQR signal stream)
IQR_FEATURES = [
    "tec_iqr_anomaly",
    "tec_iqr_anomaly_lag1d",
    "tec_iqr_anomaly_lag3d",
    "tec_iqr_anomaly_lag5d",
    "tec_iqr_anomaly_lag7d",
    "tec_iqr_anomaly_flag",
    "tec_iqr_flag_lag1d",
    "tec_iqr_flag_lag3d",
    "tec_iqr_flag_lag5d",
    "tec_iqr_flag_lag7d",
    "tec_iqr_anomaly_count_7d",
    "tec_iqr_anomaly_count_14d",
    "tec_iqr_anomaly_max_7d",
    "iqr_width_27d",
    "f107_27d_mean",       # solar cycle covariate (pre-registered)
    "storm_day",           # space weather flag covariate
]

# Seismic-only baseline features (identical to H1-H4 seismic set)
SEISMIC_FEATURES = [
    "b_value_90d",
    "mean_mag_90d",
    "event_count_90d",
    "quiescence_z_stat",
    "baseline_365d_mean",
    "foreshock_rate_z",
    "event_count_7d",
    "baseline_30d_mean",
]

# Full feature set: IQR + seismic
ALL_FEATURES = IQR_FEATURES + SEISMIC_FEATURES

XGB_PARAMS = {
    "n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
    "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 5,
    "eval_metric": "auc", "random_state": 42,
    "tree_method": "hist", "verbosity": 0
}


def get_available_columns(client, table_path):
    dataset, table = table_path.split(".")
    query = (f"SELECT column_name FROM `{PROJECT}.{dataset}.INFORMATION_SCHEMA.COLUMNS` "
             f"WHERE table_name = '{table}'")
    try:
        return [row.column_name for row in client.query(query).result()]
    except Exception as e:
        print(f"  WARNING: {e}")
        return []


def load_fault_data(client, fault_id):
    available     = get_available_columns(client, FEATURE_TABLE)
    full_feats    = [f for f in ALL_FEATURES     if f in available]
    seismic_feats = [f for f in SEISMIC_FEATURES if f in available]
    feat_select   = ", ".join(f"f.{col}" for col in full_feats)

    query = f"""
    SELECT f.fault_id, f.date_val, f.label, f.max_upcoming_magnitude,
           {feat_select}
    FROM `{PROJECT}.{FEATURE_TABLE}` f
    WHERE f.fault_id = '{fault_id}'
      AND f.date_val >= '2001-01-01'
      AND f.label IS NOT NULL
    ORDER BY f.date_val
    """
    df = client.query(query).to_dataframe()
    df["date_val"] = pd.to_datetime(df["date_val"])

    iqr_a  = [f for f in IQR_FEATURES     if f in available]
    seis_a = [f for f in SEISMIC_FEATURES if f in available]
    print(f"  Loaded {len(df):,} rows | IQR feats:{len(iqr_a)} "
          f"Seismic feats:{len(seis_a)} | Pos rate: "
          f"{df['label'].mean():.4f} ({int(df['label'].sum())} pos)")
    return df, full_feats, seismic_feats


def run_fold(df, features, fold_spec):
    train_end  = pd.Timestamp(fold_spec["train_end"])
    test_start = pd.Timestamp(fold_spec["test_start"])
    test_end   = pd.Timestamp(fold_spec["test_end"])

    train = df[df["date_val"] <= train_end].copy()
    test  = df[(df["date_val"] >= test_start) & (df["date_val"] <= test_end)].copy()

    train[features] = train[features].fillna(0)
    test[features]  = test[features].fillna(0)

    y_train = train["label"].values
    y_test  = test["label"].values

    base = {
        "fold": fold_spec["fold"], "n_train": len(train), "n_test": len(test),
        "n_pos_train": int(y_train.sum()), "n_pos_test": int(y_test.sum()),
        "auroc": None, "brier": None, "probas": None, "y_test": y_test.tolist()
    }

    if int(y_train.sum()) < MIN_POS_TRAIN:
        base["status"] = "SKIP_INSUFFICIENT_TRAIN"; return base
    if len(np.unique(y_test)) < 2:
        base["status"] = "SKIP_NO_TEST_POSITIVES"; return base

    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(train[features].values)
    X_test_s  = scaler.transform(test[features].values)

    pos_rate = y_train.mean()
    params   = XGB_PARAMS.copy()
    params["scale_pos_weight"] = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0

    model = xgb.XGBClassifier(**params)
    model.fit(X_train_s, y_train, verbose=False)
    probas = model.predict_proba(X_test_s)[:, 1]

    base["status"] = "OK"
    base["auroc"]  = float(roc_auc_score(y_test, probas))
    base["brier"]  = float(brier_score_loss(y_test, probas))
    base["probas"] = probas.tolist()
    return base


def bootstrap_ci(y_true, y_score, n_iter=BOOTSTRAP_ITERS, ci=0.95):
    if len(np.unique(y_true)) < 2: return None, None
    alpha  = 1 - ci
    aurocs = []
    n      = len(y_true)
    for _ in range(n_iter):
        idx = resample(np.arange(n), random_state=None)
        yb, sb = y_true[idx], y_score[idx]
        if len(np.unique(yb)) < 2: continue
        aurocs.append(roc_auc_score(yb, sb))
    if len(aurocs) < 100: return None, None
    return (float(np.percentile(aurocs, alpha / 2 * 100)),
            float(np.percentile(aurocs, (1 - alpha / 2) * 100)))


def run_walk_forward(df, features, fault_id, label):
    print(f"\n  [{label}] {len(features)} features")
    print(f"    {'Fold':>4} {'TrainN':>7} {'TestN':>6} {'PosTr':>5} {'PosTe':>5} {'AUROC':>7} Status")
    print(f"    " + "-" * 50)

    fold_results = []
    all_probas, all_y = [], []

    for fold_spec in FOLDS:
        r = run_fold(df, features, fold_spec)
        fold_results.append(r)
        as_ = f"{r['auroc']:.4f}" if r["auroc"] is not None else "  N/A "
        print(f"    {r['fold']:>4} {r['n_train']:>7,} {r['n_test']:>6,} "
              f"{r['n_pos_train']:>5} {r['n_pos_test']:>5} {as_:>7} {r['status']}")
        if r["status"] == "OK" and r["probas"]:
            all_probas.extend(r["probas"])
            all_y.extend(r["y_test"])

    all_probas = np.array(all_probas)
    all_y      = np.array(all_y)
    total_pos  = int(all_y.sum())

    empty = {
        "verdict": None, "pooled_auroc": None, "ci_lower": None,
        "ci_upper": None, "pooled_brier": None, "pooled_auprc": None,
        "mean_fold_auroc": None, "std_fold_auroc": None,
        "total_pos_test": total_pos, "n_valid_folds": 0,
        "fold_aurocs": json.dumps([r.get("auroc") for r in fold_results]),
        "fold_pos_counts": json.dumps([r["n_pos_test"] for r in fold_results])
    }

    if total_pos < MIN_POS_TEST_POOL or len(np.unique(all_y)) < 2:
        empty["verdict"] = "INSUFFICIENT_DATA"
        return empty

    pooled_auroc = float(roc_auc_score(all_y, all_probas))
    pooled_brier = float(brier_score_loss(all_y, all_probas))
    pooled_auprc = float(average_precision_score(all_y, all_probas))

    print(f"    Pooled: {len(all_y):,} obs | {total_pos} positive")
    print(f"    Computing bootstrap CI ({BOOTSTRAP_ITERS} iterations)...")
    ci_lower, ci_upper = bootstrap_ci(all_y, all_probas)

    valid = [r["auroc"] for r in fold_results if r["auroc"] is not None]
    mfa   = float(np.mean(valid)) if valid else None
    sfa   = float(np.std(valid))  if valid else None
    ci_str = f"[{ci_lower:.4f},{ci_upper:.4f}]" if ci_lower else "[N/A]"
    print(f"    AUROC:{pooled_auroc:.4f} CI:{ci_str} Brier:{pooled_brier:.4f} AUPRC:{pooled_auprc:.4f}")

    return {
        "verdict": None, "pooled_auroc": pooled_auroc,
        "pooled_brier": pooled_brier, "pooled_auprc": pooled_auprc,
        "ci_lower": ci_lower, "ci_upper": ci_upper,
        "mean_fold_auroc": mfa, "std_fold_auroc": sfa,
        "total_pos_test": total_pos, "n_valid_folds": len(valid),
        "fold_aurocs": json.dumps([r.get("auroc") for r in fold_results]),
        "fold_pos_counts": json.dumps([r["n_pos_test"] for r in fold_results])
    }


def evaluate_fault(client, fault_id):
    print(f"\n{'='*65}\nFault: {fault_id}  [PRE-REGISTERED]\n{'='*65}")
    df, full_feats, seismic_feats = load_fault_data(client, fault_id)
    if df is None or len(df) == 0:
        print("  No data"); return None

    full_r   = run_walk_forward(df, full_feats,    fault_id, "FULL: IQR+Seismic")
    seis_r   = run_walk_forward(df, seismic_feats, fault_id, "SEISMIC_ONLY")

    full_auroc = full_r.get("pooled_auroc")
    seis_auroc = seis_r.get("pooled_auroc")
    delta      = None

    if full_auroc is not None and seis_auroc is not None:
        delta = full_auroc - seis_auroc
        print(f"\n  Delta: {delta:+.4f} | "
              f"Need AUROC>={H1_IQR_AUROC_THRESHOLD} AND delta>=+{H1_IQR_DELTA_THRESHOLD}")

        if full_auroc >= H1_IQR_AUROC_THRESHOLD and delta >= H1_IQR_DELTA_THRESHOLD:
            std     = full_r.get("std_fold_auroc") or 0
            verdict = "CONFIRMED_UNSTABLE" if std > 0.15 else "CONFIRMED"
        else:
            verdict = "NULL"
            reasons = []
            if full_auroc < H1_IQR_AUROC_THRESHOLD:
                reasons.append(f"AUROC {full_auroc:.4f}<{H1_IQR_AUROC_THRESHOLD}")
            if delta < H1_IQR_DELTA_THRESHOLD:
                reasons.append(f"delta {delta:+.4f}<+{H1_IQR_DELTA_THRESHOLD}")
            print(f"  NULL: {' | '.join(reasons)}")
    else:
        verdict = "INSUFFICIENT_DATA"

    print(f"  >> VERDICT: {verdict}")

    return {
        "fault_id": fault_id,
        "hypothesis": "h1_iqr",
        "verdict": verdict,
        "full_pooled_auroc":    full_auroc,
        "full_ci_lower":        full_r.get("ci_lower"),
        "full_ci_upper":        full_r.get("ci_upper"),
        "full_pooled_brier":    full_r.get("pooled_brier"),
        "full_pooled_auprc":    full_r.get("pooled_auprc"),
        "full_mean_fold_auroc": full_r.get("mean_fold_auroc"),
        "full_std_fold_auroc":  full_r.get("std_fold_auroc"),
        "full_n_valid_folds":   full_r.get("n_valid_folds"),
        "full_fold_aurocs":     full_r.get("fold_aurocs"),
        "full_fold_pos_counts": full_r.get("fold_pos_counts"),
        "seismic_pooled_auroc": seis_auroc,
        "seismic_mean_fold_auroc": seis_r.get("mean_fold_auroc"),
        "seismic_fold_aurocs":  seis_r.get("fold_aurocs"),
        "auroc_delta":          delta,
        "total_pos_test":       full_r.get("total_pos_test"),
        "run_timestamp":        datetime.utcnow().isoformat(),
        "prereg_commit":        "f172953",
        "amendment_commit":     "c8cbf9c",
    }


def print_summary(all_results):
    print(f"\n{'='*65}")
    print(f"H1-IQR FINAL SUMMARY | Amendment #9 | f172953 | c8cbf9c")
    print(f"{'='*65}")
    confirmed = []
    for r in all_results:
        fa  = r["full_pooled_auroc"]
        sa  = r["seismic_pooled_auroc"]
        d   = r["auroc_delta"]
        fa_s = f"{fa:.4f}" if fa else "N/A"
        sa_s = f"{sa:.4f}" if sa else "N/A"
        d_s  = f"{d:+.4f}" if d else "N/A"
        print(f"  {r['fault_id']:25s} AUROC={fa_s} Seismic={sa_s} "
              f"Delta={d_s} [{r['verdict']}]")
        if r["verdict"] in ("CONFIRMED", "CONFIRMED_UNSTABLE"):
            confirmed.append(r["fault_id"])
    n = len(confirmed)
    print(f"\n  Confirmed: {n}/5 (need {H1_IQR_MIN_FAULTS})")
    print(f"  >> H1-IQR {'CONFIRMED' if n >= H1_IQR_MIN_FAULTS else 'NULL'}")
    print("=" * 65)


def save_results(client, all_results):
    if not all_results: return
    df  = pd.DataFrame(all_results)
    job = client.load_table_from_dataframe(
        df, f"{PROJECT}.{RESULT_TABLE}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    )
    job.result()
    print(f"\nResults saved to {PROJECT}.{RESULT_TABLE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", default=None, help="Run single fault only")
    args = parser.parse_args()

    print(f"{'='*65}")
    print(f"Project Sentinel H1-IQR Walk-Forward | {datetime.utcnow().isoformat()}")
    print(f"Pass: AUROC>={H1_IQR_AUROC_THRESHOLD} AND delta>=+{H1_IQR_DELTA_THRESHOLD} "
          f"in >={H1_IQR_MIN_FAULTS}/5 zones")
    print(f"Amendment #9 v3 | osf.io/8hvf6")
    print(f"{'='*65}")

    client     = bigquery.Client(project=PROJECT)
    fault_list = [args.fault] if args.fault else PREREGISTERED_FAULTS
    print(f"Faults: {fault_list}")

    all_results = []
    for fault_id in fault_list:
        r = evaluate_fault(client, fault_id)
        if r: all_results.append(r)

    if not all_results:
        print("No results."); return

    save_results(client, all_results)
    print_summary(all_results)


if __name__ == "__main__":
    main()
