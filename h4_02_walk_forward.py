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
PROJECT = "synexis-project-sentinel"
FEATURE_TABLE = "sentinel_features.h4_features_final"
RESULT_TABLE = "sentinel_eval.h4_wf_results"
PREREGISTERED_FAULTS = ["japan_trench","cascadia","central_chile","north_anatolian","sumatra_andaman"]
EXPLORATORY_FAULTS = ["hayward"]
H4_AUROC_THRESHOLD = 0.65
H4_DELTA_THRESHOLD = 0.03
H4_MIN_FAULTS = 3
BOOTSTRAP_ITERS = 1000
MIN_POS_TRAIN = 3
MIN_POS_TEST_POOL = 5
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
H1_FEATURES = ["b_value_90d","mean_mag_90d","event_count_90d","quiescence_z_stat",
               "baseline_365d_mean","foreshock_rate_z","event_count_7d","baseline_30d_mean"]
H2_FEATURES = ["z_fp","z_east","z_north","z_up","z_fp_std",
               "z_fp_3d_mean","z_fp_7d_mean","z_fp_14d_mean","z_fp_30d_mean",
               "z_fp_7d_std","z_fp_14d_std","z_fp_30d_std",
               "z_fp_7d_max_abs","z_fp_14d_max_abs","z_fp_30d_max_abs",
               "z_fp_delta_3d","z_fp_delta_7d","z_fp_delta_14d",
               "z_up_7d_mean","z_up_14d_mean","z_up_30d_mean",
               "z_fp_std_7d_mean","z_fp_std_14d_mean",
               "n_stations_7d_mean","n_stations_30d_mean"]
H3_FEATURES = ["tec_delta_fullday","tec_delta_nighttime","tec_lssi",
               "tec_delta_lag1d","tec_delta_lag3d","tec_delta_lag5d",
               "tec_delta_lag7d","tec_nighttime_lag5d"]
GEO_FEATURES = ["kp_max","kp_mean","ap_daily","f107","dst_min","dst_mean",
                "z_kp_max","z_kp_mean","z_ap","z_dst_min",
                "storm_flag_kp5","storm_flag_dst50",
                "kp_storm_days_7d","kp_max_7d_mean","dst_min_7d_mean",
                "dst_recovery_7d","f107_27d_mean",
                
                ]
ALL_FEATURES = H1_FEATURES + H2_FEATURES + H3_FEATURES + GEO_FEATURES
XGB_PARAMS = {"n_estimators":300,"max_depth":4,"learning_rate":0.05,
              "subsample":0.8,"colsample_bytree":0.8,"min_child_weight":5,
              "eval_metric":"auc","random_state":42,"tree_method":"hist","verbosity":0}

def get_available_columns(client, table_path):
    dataset, table = table_path.split(".")
    query = f"SELECT column_name FROM `{PROJECT}.{dataset}.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = '{table}'"
    try:
        return [row.column_name for row in client.query(query).result()]
    except Exception as e:
        print(f"  WARNING: {e}")
        return []

def load_fault_data(client, fault_id):
    available     = get_available_columns(client, FEATURE_TABLE)
    full_feats    = [f for f in ALL_FEATURES if f in available]
    seismic_feats = [f for f in H1_FEATURES  if f in available]
    feat_select   = ", ".join(f"f.{col}" for col in full_feats)
    query = f"""
    SELECT f.fault_id, f.date_val, f.split_type, f.wf_fold,
           f.is_exploratory, f.has_h2, f.has_h3, f.has_geo,
           f.label, f.label_7d, f.max_upcoming_magnitude, {feat_select}
    FROM `{PROJECT}.{FEATURE_TABLE}` f
    WHERE f.fault_id = '{fault_id}'
      AND f.date_val >= '2001-01-01'
      AND f.label IS NOT NULL
    ORDER BY f.date_val
    """
    df = client.query(query).to_dataframe()
    df["date_val"] = pd.to_datetime(df["date_val"])
    h2a = [f for f in H2_FEATURES  if f in available]
    h3a = [f for f in H3_FEATURES  if f in available]
    ga  = [f for f in GEO_FEATURES if f in available]
    print(f"  Loaded {len(df):,} rows")
    print(f"  Features H1:{len(seismic_feats)} H2:{len(h2a)} H3:{len(h3a)} Geo:{len(ga)} Total:{len(full_feats)}")
    print(f"  Positive rate: {df['label'].mean():.4f} ({int(df['label'].sum())} pos)")
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
    base = {"fold":fold_spec["fold"],"n_train":len(train),"n_test":len(test),
            "n_pos_train":int(y_train.sum()),"n_pos_test":int(y_test.sum()),
            "auroc":None,"brier":None,"probas":None,"y_test":y_test.tolist()}
    if int(y_train.sum()) < MIN_POS_TRAIN:
        base["status"] = "SKIP_INSUFFICIENT_TRAIN"; return base
    if len(np.unique(y_test)) < 2:
        base["status"] = "SKIP_NO_TEST_POSITIVES"; return base
    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(train[features].values)
    X_test_s  = scaler.transform(test[features].values)
    pos_rate  = y_train.mean()
    params    = XGB_PARAMS.copy()
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
    alpha = 1 - ci
    aurocs = []
    n = len(y_true)
    for _ in range(n_iter):
        idx = resample(np.arange(n), random_state=None)
        yb, sb = y_true[idx], y_score[idx]
        if len(np.unique(yb)) < 2: continue
        aurocs.append(roc_auc_score(yb, sb))
    if len(aurocs) < 100: return None, None
    return float(np.percentile(aurocs, alpha/2*100)), float(np.percentile(aurocs, (1-alpha/2)*100))

def run_walk_forward(df, features, fault_id):
    print(f"    Fold  TrainN   TestN PosTr PosTe   AUROC Status")
    print(f"    " + "-"*55)
    fold_results = []
    all_probas, all_y = [], []
    for fold_spec in FOLDS:
        r = run_fold(df, features, fold_spec)
        fold_results.append(r)
        as_ = f"{r['auroc']:.4f}" if r["auroc"] is not None else "  N/A "
        print(f"    {r['fold']:>4} {r['n_train']:>7,} {r['n_test']:>6,} {r['n_pos_train']:>5} {r['n_pos_test']:>5} {as_:>7} {r['status']}")
        if r["status"] == "OK" and r["probas"]:
            all_probas.extend(r["probas"]); all_y.extend(r["y_test"])
    all_probas = np.array(all_probas); all_y = np.array(all_y)
    total_pos = int(all_y.sum())
    print(f"    Pooled: {len(all_y):,} obs | {total_pos} positive")
    empty = {"verdict":None,"pooled_auroc":None,"ci_lower":None,"ci_upper":None,
             "pooled_brier":None,"pooled_auprc":None,"mean_fold_auroc":None,
             "std_fold_auroc":None,"total_pos_test":total_pos,"n_valid_folds":0,
             "fold_aurocs":json.dumps([r["auroc"] for r in fold_results]),
             "fold_pos_counts":json.dumps([r["n_pos_test"] for r in fold_results])}
    if total_pos < MIN_POS_TEST_POOL or len(np.unique(all_y)) < 2:
        empty["verdict"] = "INSUFFICIENT_DATA"; return empty
    pooled_auroc = float(roc_auc_score(all_y, all_probas))
    pooled_brier = float(brier_score_loss(all_y, all_probas))
    pooled_auprc = float(average_precision_score(all_y, all_probas))
    print(f"    Computing bootstrap CI ({BOOTSTRAP_ITERS} iterations)...")
    ci_lower, ci_upper = bootstrap_ci(all_y, all_probas)
    valid = [r["auroc"] for r in fold_results if r["auroc"] is not None]
    mfa = float(np.mean(valid)) if valid else None
    sfa = float(np.std(valid))  if valid else None
    ci_str = f"[{ci_lower:.4f},{ci_upper:.4f}]" if ci_lower else "[N/A]"
    print(f"    AUROC:{pooled_auroc:.4f} CI:{ci_str} Brier:{pooled_brier:.4f} AUPRC:{pooled_auprc:.4f}")
    if mfa: print(f"    Mean fold AUROC:{mfa:.4f} +/-{sfa:.4f}")
    return {"verdict":None,"pooled_auroc":pooled_auroc,"pooled_brier":pooled_brier,
            "pooled_auprc":pooled_auprc,"ci_lower":ci_lower,"ci_upper":ci_upper,
            "mean_fold_auroc":mfa,"std_fold_auroc":sfa,"total_pos_test":total_pos,
            "n_valid_folds":len(valid),
            "fold_aurocs":json.dumps([r["auroc"] for r in fold_results]),
            "fold_pos_counts":json.dumps([r["n_pos_test"] for r in fold_results])}

def evaluate_fault(client, fault_id, is_exploratory):
    tag = "EXPLORATORY" if is_exploratory else "PRE-REGISTERED"
    print(f"\n{'='*65}\nFault: {fault_id}  [{tag}]\n{'='*65}")
    df, full_feats, seismic_feats = load_fault_data(client, fault_id)
    if df is None or len(df) == 0:
        print("  No data"); return None
    print(f"\n  [FULL MODEL] {len(full_feats)} features")
    full_r = run_walk_forward(df, full_feats, fault_id)
    print(f"\n  [SEISMIC_ONLY] {len(seismic_feats)} features")
    seis_r = run_walk_forward(df, seismic_feats, fault_id)
    full_auroc = full_r.get("pooled_auroc")
    seis_auroc = seis_r.get("pooled_auroc")
    delta = None
    if full_auroc is not None and seis_auroc is not None:
        delta = full_auroc - seis_auroc
        print(f"\n  Delta: {delta:+.4f} | Need AUROC>={H4_AUROC_THRESHOLD} AND delta>=+{H4_DELTA_THRESHOLD}")
        if is_exploratory:
            verdict = "EXPLORATORY"
        else:
            if full_auroc >= H4_AUROC_THRESHOLD and delta >= H4_DELTA_THRESHOLD:
                std = full_r.get("std_fold_auroc") or 0
                verdict = "CONFIRMED_UNSTABLE" if std > 0.15 else "CONFIRMED"
            else:
                verdict = "NULL"
                reasons = []
                if full_auroc < H4_AUROC_THRESHOLD:
                    reasons.append(f"AUROC {full_auroc:.4f}<{H4_AUROC_THRESHOLD}")
                if delta < H4_DELTA_THRESHOLD:
                    reasons.append(f"delta {delta:+.4f}<+{H4_DELTA_THRESHOLD}")
                print(f"  NULL: {' | '.join(reasons)}")
    else:
        verdict = "INSUFFICIENT_DATA"
    print(f"  >> VERDICT: {verdict}")
    return {"fault_id":fault_id,"is_exploratory":1 if is_exploratory else 0,
            "hypothesis":"h4","verdict":verdict,
            "full_pooled_auroc":full_auroc,"full_ci_lower":full_r.get("ci_lower"),
            "full_ci_upper":full_r.get("ci_upper"),"full_pooled_brier":full_r.get("pooled_brier"),
            "full_pooled_auprc":full_r.get("pooled_auprc"),
            "full_mean_fold_auroc":full_r.get("mean_fold_auroc"),
            "full_std_fold_auroc":full_r.get("std_fold_auroc"),
            "full_n_valid_folds":full_r.get("n_valid_folds"),
            "full_fold_aurocs":full_r.get("fold_aurocs"),
            "full_fold_pos_counts":full_r.get("fold_pos_counts"),
            "seismic_pooled_auroc":seis_auroc,
            "seismic_mean_fold_auroc":seis_r.get("mean_fold_auroc"),
            "seismic_fold_aurocs":seis_r.get("fold_aurocs"),
            "auroc_delta":delta,"total_pos_test":full_r.get("total_pos_test"),
            "run_timestamp":datetime.utcnow().isoformat(),
            "prereg_commit":"f172953","amendment_commit":"496ebf1",
            "exploratory_commit":"ca051fb"}

def print_final_summary(all_results):
    print(f"\n{'='*65}\nH4 FINAL SUMMARY | f172953 | 496ebf1\n{'='*65}")
    prereg = [r for r in all_results if not r["is_exploratory"]]
    explor = [r for r in all_results if r["is_exploratory"]]
    confirmed = []
    for r in prereg:
        fa=r["full_pooled_auroc"]; sa=r["seismic_pooled_auroc"]; d=r["auroc_delta"]
        fa_s=f"{fa:.4f}" if fa else "N/A"
        sa_s=f"{sa:.4f}" if sa else "N/A"
        d_s=f"{d:+.4f}" if d else "N/A"
        print(f"  {r['fault_id']:25s} AUROC={fa_s} Seismic={sa_s} Delta={d_s} [{r['verdict']}]")
        if r["verdict"] in ("CONFIRMED","CONFIRMED_UNSTABLE"):
            confirmed.append(r["fault_id"])
    n = len(confirmed)
    print(f"\n  Confirmed: {n}/5 (need {H4_MIN_FAULTS})")
    print(f"  >> H4 {'CONFIRMED' if n>=H4_MIN_FAULTS else 'NULL'}")
    if explor:
        print(f"\n  EXPLORATORY (ca051fb):")
        for r in explor:
            fa=r["full_pooled_auroc"]; d=r["auroc_delta"]
            fa_s=f"{fa:.4f}" if fa else "N/A"
            d_s=f"{d:+.4f}" if d else "N/A"
            print(f"  {r['fault_id']:25s} AUROC={fa_s} Delta={d_s} [EXPLORATORY]")
    print("="*65)

def save_results(client, all_results):
    if not all_results:
        print("No results."); return
    df = pd.DataFrame(all_results)
    job = client.load_table_from_dataframe(
        df, f"{PROJECT}.{RESULT_TABLE}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"))
    job.result()
    print(f"Results saved to {PROJECT}.{RESULT_TABLE}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", default=None)
    parser.add_argument("--exploratory-only", action="store_true")
    parser.add_argument("--preregistered-only", action="store_true")
    args = parser.parse_args()
    print(f"{'='*65}\nProject Sentinel H4 Walk-Forward | {datetime.utcnow().isoformat()}")
    print(f"Pass: AUROC>={H4_AUROC_THRESHOLD} AND delta>=+{H4_DELTA_THRESHOLD} in >={H4_MIN_FAULTS}/5 zones\n{'='*65}")
    client = bigquery.Client(project=PROJECT)
    if args.fault:
        fault_list = [(args.fault, args.fault in EXPLORATORY_FAULTS)]
    elif args.exploratory_only:
        fault_list = [(f,True) for f in EXPLORATORY_FAULTS]
    elif args.preregistered_only:
        fault_list = [(f,False) for f in PREREGISTERED_FAULTS]
    else:
        fault_list = [(f,False) for f in PREREGISTERED_FAULTS] + [(f,True) for f in EXPLORATORY_FAULTS]
    print(f"Faults: {[f for f,_ in fault_list]}")
    all_results = []
    for fault_id, is_exploratory in fault_list:
        r = evaluate_fault(client, fault_id, is_exploratory)
        if r: all_results.append(r)
    if not all_results:
        print("No results."); return
    save_results(client, all_results)
    print_final_summary(all_results)

if __name__ == "__main__":
    main()
