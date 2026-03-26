import pandas as pd
import numpy as np
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

PROJECT   = "synexis-project-sentinel"
TABLE_OUT = f"{PROJECT}.sentinel_eval.h1_results"

H1_AUROC_THRESHOLD     = 0.60
H1_MIN_FAULTS_REQUIRED = 3
RANDOM_SEED            = 42

H1_FEATURES = [
    'b_value_90d',
    'mean_mag_90d',
    'event_count_90d',
    'quiescence_z_stat',
    'baseline_365d_mean',
    'foreshock_rate_z',
    'event_count_7d',
    'baseline_30d_mean',
]

LABEL_COL = 'label_7d'

XGB_PARAMS = {
    'n_estimators': 200,
    'max_depth': 4,
    'learning_rate': 0.05,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 10,
    'eval_metric': 'auc',
    'random_state': RANDOM_SEED,
    'tree_method': 'hist',
    'verbosity': 0,
}

def load_fault_data(client, fault_id):
    query = f"""
    SELECT f.date_val, f.fault_id, f.data_split,
        f.b_value_90d, f.mean_mag_90d, f.event_count_90d,
        f.quiescence_z_stat, f.baseline_365d_mean, f.baseline_365d_std,
        f.foreshock_rate_z, f.event_count_7d, f.baseline_30d_mean,
        l.label_7d, l.label_3d, l.label_5d, l.max_upcoming_magnitude
    FROM `{PROJECT}.sentinel_features.h1_features_daily` f
    JOIN `{PROJECT}.sentinel_features.h1_labels` l
      ON f.date_val = l.date_val AND f.fault_id = l.fault_id
    WHERE f.fault_id = '{fault_id}' AND f.b_value_90d IS NOT NULL
    ORDER BY f.date_val
    """
    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} rows for {fault_id}")
    return df

def run_h1_for_fault(df, fault_id):
    results = {
        'fault_id': fault_id,
        'run_timestamp': datetime.utcnow().isoformat(),
        'pre_reg_commit': 'f172953',
        'h1_threshold': H1_AUROC_THRESHOLD,
    }

    train = df[df['data_split'] == 'train'].copy()
    val   = df[df['data_split'] == 'val'].copy()
    test  = df[df['data_split'] == 'test'].copy()

    print(f"  Split sizes — Train: {len(train):,} | Val: {len(val):,} | Test: {len(test):,}")
    print(f"  Positive rates — Train: {train[LABEL_COL].mean():.3%} | Val: {val[LABEL_COL].mean():.3%} | Test: {test[LABEL_COL].mean():.3%}")

    results['train_rows'] = len(train)
    results['val_rows']   = len(val)
    results['test_rows']  = len(test)
    results['train_positive_rate'] = float(train[LABEL_COL].mean())
    results['val_positive_rate']   = float(val[LABEL_COL].mean())
    results['test_positive_rate']  = float(test[LABEL_COL].mean())

    if train[LABEL_COL].sum() < 10:
        print(f"  WARNING: Only {int(train[LABEL_COL].sum())} positive examples — insufficient data.")
        results['h1_verdict']  = 'INSUFFICIENT_DATA'
        results['test_auroc']  = None
        results['train_auroc'] = None
        results['val_auroc']   = None
        results['feature_importances'] = '{}'
        results['features_used'] = json.dumps(H1_FEATURES)
        print(f"\n  ── H1 VERDICT for {fault_id}: INSUFFICIENT_DATA ──")
        return results

    features_to_use = [f for f in H1_FEATURES if f in df.columns]
    for split_df in [train, val, test]:
        split_df[features_to_use] = split_df[features_to_use].fillna(0)

    X_train = train[features_to_use].values
    y_train = train[LABEL_COL].values
    X_val   = val[features_to_use].values
    y_val   = val[LABEL_COL].values
    X_test  = test[features_to_use].values
    y_test  = test[LABEL_COL].values

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s   = scaler.transform(X_val)
    X_test_s  = scaler.transform(X_test)

    pos_rate = y_train.mean()
    scale_pos = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0
    params = XGB_PARAMS.copy()
    params['scale_pos_weight'] = scale_pos

    model = xgb.XGBClassifier(**params)
    model.fit(X_train_s, y_train, eval_set=[(X_val_s, y_val)], verbose=False)

    for split_name, X_s, y in [('train', X_train_s, y_train), ('val', X_val_s, y_val), ('test', X_test_s, y_test)]:
        proba = model.predict_proba(X_s)[:, 1]
        if len(np.unique(y)) < 2:
            auroc = None
            brier = None
            auprc = None
            print(f"  {split_name}: Only one class present — cannot compute AUROC")
        else:
            auroc = float(roc_auc_score(y, proba))
            brier = float(brier_score_loss(y, proba))
            auprc = float(average_precision_score(y, proba))
            print(f"  {split_name:5s} AUROC: {auroc:.4f} | Brier: {brier:.4f} | AUPRC: {auprc:.4f}")
        results[f'{split_name}_auroc'] = auroc
        results[f'{split_name}_brier'] = brier
        results[f'{split_name}_auprc'] = auprc

    importances = dict(zip(features_to_use, model.feature_importances_.tolist()))
    results['feature_importances'] = json.dumps(importances)
    results['features_used'] = json.dumps(features_to_use)

    test_auroc = results.get('test_auroc')
    if test_auroc is None:
        results['h1_verdict'] = 'INSUFFICIENT_DATA'
        verdict_str = "INSUFFICIENT_DATA (no positive labels in test set)"
    elif test_auroc >= H1_AUROC_THRESHOLD:
        results['h1_verdict'] = 'CONFIRMED'
        verdict_str = f"CONFIRMED (AUROC {test_auroc:.4f} >= {H1_AUROC_THRESHOLD})"
    else:
        results['h1_verdict'] = 'NULL'
        verdict_str = f"NULL (AUROC {test_auroc:.4f} < {H1_AUROC_THRESHOLD})"

    print(f"\n  ── H1 VERDICT for {fault_id}: {verdict_str} ──")
    return results

def save_results(client, all_results):
    df = pd.DataFrame(all_results)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, TABLE_OUT, job_config=job_config)
    job.result()
    print(f"\nResults saved to {TABLE_OUT}")

def print_h1_summary(all_results):
    print("\n" + "="*60)
    print("H1 FINAL SUMMARY — Pre-registration commit f172953")
    print("="*60)
    confirmed = []
    null_faults = []
    insufficient = []
    for r in all_results:
        fid     = r['fault_id']
        verdict = r.get('h1_verdict', 'UNKNOWN')
        auroc   = r.get('test_auroc')
        auroc_str = f"{auroc:.4f}" if auroc is not None else "N/A"
        print(f"  {fid:25s} AUROC={auroc_str:7s}  [{verdict}]")
        if verdict == 'CONFIRMED':
            confirmed.append(fid)
        elif verdict == 'NULL':
            null_faults.append(fid)
        else:
            insufficient.append(fid)
    n_confirmed = len(confirmed)
    print(f"\nFaults confirmed (AUROC >= {H1_AUROC_THRESHOLD}): {n_confirmed} of 5")
    print(f"Required for H1 confirmation: {H1_MIN_FAULTS_REQUIRED} of 5")
    if n_confirmed >= H1_MIN_FAULTS_REQUIRED:
        print(f"\nH1 CONFIRMED — {n_confirmed} systems meet threshold")
    else:
        print(f"\nH1 NULL — {n_confirmed} systems meet threshold (need {H1_MIN_FAULTS_REQUIRED})")
    if insufficient:
        print(f"Insufficient test data: {', '.join(insufficient)}")
    print("="*60)

def main():
    print("Project Sentinel — H1 Analysis")
    print(f"Pre-registration commit: f172953")
    print(f"Run timestamp: {datetime.utcnow().isoformat()}")
    print(f"H1 threshold: AUROC >= {H1_AUROC_THRESHOLD} in >={H1_MIN_FAULTS_REQUIRED} of 5 fault systems\n")

    client = bigquery.Client(project=PROJECT)
    fault_query = "SELECT fault_id FROM `synexis-project-sentinel.sentinel_features.fault_systems` ORDER BY priority, fault_id"
    fault_ids = [row.fault_id for row in client.query(fault_query).result()]
    print(f"Fault systems: {fault_ids}\n")

    all_results = []
    for fault_id in fault_ids:
        print(f"\n{'─'*50}")
        print(f"Processing: {fault_id}")
        print('─'*50)
        df = load_fault_data(client, fault_id)
        if len(df) == 0:
            print(f"  No data — skipping")
            continue
        results = run_h1_for_fault(df, fault_id)
        all_results.append(results)

    save_results(client, all_results)
    print_h1_summary(all_results)

if __name__ == "__main__":
    main()
