#!/usr/bin/env python3
"""
phase1_model_v2.py — adds probability calibration and correct Brier scoring
"""

import json
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb

PROJECT = "synexis-project-sentinel"

print("Loading data...")
client = bigquery.Client(project=PROJECT)
df = client.query("""
    SELECT * FROM `synexis-project-sentinel.sentinel_eval.phase1_dataset`
""").to_dataframe()

train = df[df.split == "train"].copy().reset_index(drop=True)
val   = df[df.split == "validate"].copy().reset_index(drop=True)

y_train = train["y_m60_next7d"].astype(int)
y_val   = val["y_m60_next7d"].astype(int)

global_rate   = y_train.mean()
regional_rate = train.groupby("region_key")["y_m60_next7d"].mean().to_dict()

print(f"  Train: {len(train):,}  Val: {len(val):,}  Base rate: {global_rate:.4f}")

def bss(y_true, y_pred, base_rate):
    bs_m = brier_score_loss(y_true, y_pred)
    bs_r = brier_score_loss(y_true, np.full(len(y_true), base_rate))
    return 1 - bs_m / bs_r

def report(name, y_true, y_pred, base_rate):
    auroc = roc_auc_score(y_true, y_pred)
    bs    = brier_score_loss(y_true, y_pred)
    skill = bss(y_true, y_pred, base_rate)
    print(f"  {name:<40} AUROC={auroc:.4f}  BS={bs:.4f}  BSS={skill:+.4f}")
    return {"model": name, "auroc": round(auroc,4),
            "brier": round(bs,4), "brier_skill": round(skill,4)}

results = []
print("\n── Baselines ──")

# Climatological
pred_clim = val["region_key"].map(regional_rate).fillna(global_rate).values
results.append(report("Climatological", y_val, pred_clim, global_rate))

# Persistence
max_c = train["count_m6_30d"].max()
pred_persist = (val["count_m6_30d"] / max(max_c,1)).clip(0,1).values
results.append(report("Persistence 30d", y_val, pred_persist, global_rate))

# Global mean (reference floor)
pred_mean = np.full(len(y_val), global_rate)
results.append(report("Global mean (floor)", y_val, pred_mean, global_rate))

ENV = ["kp_max","kp_mean","sw_speed_mean","sw_density_mean",
       "sw_bz_min","xray_max","electron_flux_max","has_cme","has_sep"]
SES = ["count_m4_30d","count_m5_30d","count_m6_30d",
       "max_mag_30d","count_m4_7d","count_m5_7d"]

def prep(df, cols, medians=None):
    X = df[cols].copy().astype(float)
    if medians is None:
        medians = X.median()
    return X.fillna(medians).values, medians

scale_pos = (y_train==0).sum() / (y_train==1).sum()

def fit_xgb(X_tr, y_tr, X_va):
    base = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        scale_pos_weight=scale_pos, subsample=0.8,
        colsample_bytree=0.8, random_state=42,
        eval_metric="logloss", verbosity=0,
    )
    # Calibrate with isotonic regression on a held-out fold
    cal = CalibratedClassifierCV(base, method="isotonic", cv=3)
    cal.fit(X_tr, y_tr)
    return cal.predict_proba(X_va)[:, 1]

print("\n── XGBoost models (with isotonic calibration) ──")

# Env only
X_tr_env, med_env = prep(train, ENV)
X_va_env, _       = prep(val,   ENV, med_env)
pred_env = fit_xgb(X_tr_env, y_train, X_va_env)
results.append(report("XGBoost Env only (calibrated)", y_val, pred_env, global_rate))

# Env + Seismic
X_tr_all, med_all = prep(train, ENV+SES)
X_va_all, _       = prep(val,   ENV+SES, med_all)
pred_all = fit_xgb(X_tr_all, y_train, X_va_all)
results.append(report("XGBoost Env+Seismic (calibrated)", y_val, pred_all, global_rate))

# Seismic only (to isolate environmental contribution)
X_tr_ses, med_ses = prep(train, SES)
X_va_ses, _       = prep(val,   SES, med_ses)
pred_ses = fit_xgb(X_tr_ses, y_train, X_va_ses)
results.append(report("XGBoost Seismic only (calibrated)", y_val, pred_ses, global_rate))

print("\n" + "="*60)
print("  FINAL SUMMARY — VALIDATION SET")
print("="*60)
print(f"  {'Model':<42} {'AUROC':>7} {'BSS':>8}")
print(f"  {'-'*57}")
for r in results:
    print(f"  {r['model']:<42} {r['auroc']:>7.4f} {r['brier_skill']:>+8.4f}")

print("\n── Pre-registration thresholds (environmental model) ──")
print("  Null:        AUROC < 0.52")
print("  Weak signal: AUROC 0.52-0.58")
print("  Meaningful:  AUROC >= 0.58")

env_result = [r for r in results if "Env only" in r["model"]][0]
auroc = env_result["auroc"]
if auroc < 0.52:
    verdict = "NULL — no environmental signal detected"
elif auroc < 0.58:
    verdict = "WEAK SIGNAL — marginal, requires replication"
else:
    verdict = "MEANINGFUL SIGNAL — exceeds pre-registered threshold"
print(f"\n  Environmental model verdict: {verdict}")
print(f"  AUROC = {auroc:.4f}")

with open("model_results_v2.json","w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to model_results_v2.json")
