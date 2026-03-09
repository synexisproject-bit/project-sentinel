#!/usr/bin/env python3
"""
phase1_test_eval.py — Pre-registered test set evaluation (2023-2026)
RUN ONCE ONLY. Results are final per pre-registration commit 140f369.
"""
import json
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb
from datetime import datetime, timezone

PROJECT = "synexis-project-sentinel"
print("=" * 60)
print("  PHASE 1 TEST SET EVALUATION — RUN ONCE")
print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
print("=" * 60)

client = bigquery.Client(project=PROJECT)
df = client.query("""
    SELECT * FROM `synexis-project-sentinel.sentinel_eval.phase1_dataset`
""").to_dataframe()

train = df[df.split == "train"].copy().reset_index(drop=True)
val   = df[df.split == "validate"].copy().reset_index(drop=True)
test  = df[df.split == "test"].copy().reset_index(drop=True)

y_train = train["y_m60_next7d"].astype(int)
y_val   = val["y_m60_next7d"].astype(int)
y_test  = test["y_m60_next7d"].astype(int)

global_rate   = y_train.mean()
regional_rate = train.groupby("region_key")["y_m60_next7d"].mean().to_dict()
scale_pos     = (y_train==0).sum() / (y_train==1).sum()

print(f"\n  Train:    {len(train):,} rows  pos={y_train.mean():.4f}")
print(f"  Validate: {len(val):,} rows  pos={y_val.mean():.4f}")
print(f"  Test:     {len(test):,} rows  pos={y_test.mean():.4f}")

def bss(y_true, y_pred, base_rate):
    bs_m = brier_score_loss(y_true, y_pred)
    bs_r = brier_score_loss(y_true, np.full(len(y_true), base_rate))
    return 1 - bs_m / bs_r

def report(name, y_true, y_pred, split="test"):
    auroc = roc_auc_score(y_true, y_pred)
    bs    = brier_score_loss(y_true, y_pred)
    skill = bss(y_true, y_pred, global_rate)
    print(f"  {name:<42} AUROC={auroc:.4f}  BS={bs:.4f}  BSS={skill:+.4f}")
    return {"model": name, "split": split, "auroc": round(auroc,4),
            "brier": round(bs,4), "brier_skill": round(skill,4)}

def prep(df, cols, medians=None):
    X = df[cols].copy().astype(float)
    if medians is None:
        medians = X.median()
    return X.fillna(medians).values, medians

def fit_xgb(X_tr, y_tr, X_va):
    base = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        scale_pos_weight=scale_pos, subsample=0.8,
        colsample_bytree=0.8, random_state=42,
        eval_metric="logloss", verbosity=0,
        use_label_encoder=False)
    cal = CalibratedClassifierCV(base, method="isotonic", cv=3)
    cal.fit(X_tr, y_tr)
    return cal

ENV = ["kp_max","kp_mean","sw_speed_mean","sw_density_mean",
       "sw_bz_min","xray_max","electron_flux_max","has_cme","has_sep"]
TEC = ["tec_global_mean","tec_anomaly_zscore"]
SES = ["count_m4_30d","count_m5_30d","count_m6_30d",
       "max_mag_30d","count_m4_7d","count_m5_7d"]

results = []

print("\n── Baselines ──")
pred_clim_test = test["region_key"].map(regional_rate).fillna(global_rate).values
results.append(report("Climatological baseline", y_test, pred_clim_test))
pred_mean_test = np.full(len(y_test), global_rate)
results.append(report("Global mean (floor)", y_test, pred_mean_test))

print("\n── Pre-registered environmental model ──")
# Train on train only, evaluate on test
X_tr_env, med_env = prep(train, ENV)
X_te_env, _       = prep(test,  ENV, med_env)
model_env = fit_xgb(X_tr_env, y_train, None)
pred_env_test = model_env.predict_proba(X_te_env)[:,1]
results.append(report("XGBoost Env only (pre-registered)", y_test, pred_env_test))

print("\n── TEC model (exploratory) ──")
X_tr_tec, med_tec = prep(train, TEC)
X_te_tec, _       = prep(test,  TEC, med_tec)
model_tec = fit_xgb(X_tr_tec, y_train, None)
pred_tec_test = model_tec.predict_proba(X_te_tec)[:,1]
results.append(report("XGBoost TEC only (exploratory)", y_test, pred_tec_test))

X_tr_et, med_et = prep(train, ENV+TEC)
X_te_et, _      = prep(test,  ENV+TEC, med_et)
model_et = fit_xgb(X_tr_et, y_train, None)
pred_et_test = model_et.predict_proba(X_te_et)[:,1]
results.append(report("XGBoost Env + TEC (exploratory)", y_test, pred_et_test))

print("\n── Seismic models (reference) ──")
X_tr_ses, med_ses = prep(train, SES)
X_te_ses, _       = prep(test,  SES, med_ses)
model_ses = fit_xgb(X_tr_ses, y_train, None)
pred_ses_test = model_ses.predict_proba(X_te_ses)[:,1]
results.append(report("XGBoost Seismic only", y_test, pred_ses_test))

X_tr_all, med_all = prep(train, ENV+TEC+SES)
X_te_all, _       = prep(test,  ENV+TEC+SES, med_all)
model_all = fit_xgb(X_tr_all, y_train, None)
pred_all_test = model_all.predict_proba(X_te_all)[:,1]
results.append(report("XGBoost Env + TEC + Seismic", y_test, pred_all_test))

print("\n" + "="*65)
print("  FINAL TEST SET RESULTS — PHASE 1 COMPLETE")
print("="*65)
print(f"  {'Model':<44} {'AUROC':>7} {'BSS':>8}")
print(f"  {'-'*62}")
for r in results:
    print(f"  {r['model']:<44} {r['auroc']:>7.4f} {r['brier_skill']:>+8.4f}")

env_auroc = [r for r in results if "pre-registered" in r["model"]][0]["auroc"]
print(f"\n── Pre-registration verdict (test set) ──")
print(f"  Environmental model AUROC = {env_auroc:.4f}")
if env_auroc < 0.52:
    verdict = "NULL RESULT — H0 confirmed on held-out test set"
elif env_auroc < 0.58:
    verdict = "WEAK SIGNAL — marginal, requires replication"
else:
    verdict = "MEANINGFUL SIGNAL — exceeds pre-registered threshold"
print(f"  Verdict: {verdict}")

output = {
    "run_timestamp": datetime.now(timezone.utc).isoformat(),
    "pre_registration_commit": "140f369",
    "test_period": "2023-01-01 to 2026-12-31",
    "test_rows": len(test),
    "test_pos_rate": round(float(y_test.mean()), 4),
    "env_model_auroc": env_auroc,
    "verdict": verdict,
    "results": results
}
with open("phase1_test_results.json", "w") as f:
    json.dump(output, f, indent=2)
print("\nSaved: phase1_test_results.json")
print("\nPhase 1 evaluation complete.")
