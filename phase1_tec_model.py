#!/usr/bin/env python3
"""
phase1_tec_model.py — adds TEC features to Phase 1 XGBoost evaluation
Extends phase1_model_v2.py results; does not modify pre-registered models.
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
scale_pos = (y_train==0).sum() / (y_train==1).sum()

print(f"  Train: {len(train):,}  Val: {len(val):,}  Base rate: {global_rate:.4f}")
print(f"  TEC coverage train: {train['tec_global_mean'].notna().sum():,} / {len(train):,}")
print(f"  TEC coverage val:   {val['tec_global_mean'].notna().sum():,} / {len(val):,}")

def bss(y_true, y_pred, base_rate):
    bs_m = brier_score_loss(y_true, y_pred)
    bs_r = brier_score_loss(y_true, np.full(len(y_true), base_rate))
    return 1 - bs_m / bs_r

def report(name, y_true, y_pred):
    auroc = roc_auc_score(y_true, y_pred)
    bs    = brier_score_loss(y_true, y_pred)
    skill = bss(y_true, y_pred, global_rate)
    print(f"  {name:<45} AUROC={auroc:.4f}  BS={bs:.4f}  BSS={skill:+.4f}")
    return {"model": name, "auroc": round(auroc,4),
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
    return cal.predict_proba(X_va)[:,1]

ENV = ["kp_max","kp_mean","sw_speed_mean","sw_density_mean",
       "sw_bz_min","xray_max","electron_flux_max","has_cme","has_sep"]
TEC = ["tec_global_mean","tec_anomaly_zscore"]
SES = ["count_m4_30d","count_m5_30d","count_m6_30d",
       "max_mag_30d","count_m4_7d","count_m5_7d"]

results = []
print("\n── Reference baselines ──")
pred_clim = val["region_key"].map(regional_rate).fillna(global_rate).values
results.append(report("Climatological baseline", y_val, pred_clim))
pred_mean = np.full(len(y_val), global_rate)
results.append(report("Global mean (floor)", y_val, pred_mean))

print("\n── Environmental models ──")
# Env only (pre-registered, reproduced for reference)
X_tr_env, med_env = prep(train, ENV)
X_va_env, _       = prep(val,   ENV, med_env)
pred_env = fit_xgb(X_tr_env, y_train, X_va_env)
results.append(report("XGBoost Env only (pre-registered)", y_val, pred_env))

# TEC only
X_tr_tec, med_tec = prep(train, TEC)
X_va_tec, _       = prep(val,   TEC, med_tec)
pred_tec = fit_xgb(X_tr_tec, y_train, X_va_tec)
results.append(report("XGBoost TEC only", y_val, pred_tec))

# Env + TEC
X_tr_et, med_et = prep(train, ENV+TEC)
X_va_et, _      = prep(val,   ENV+TEC, med_et)
pred_et = fit_xgb(X_tr_et, y_train, X_va_et)
results.append(report("XGBoost Env + TEC", y_val, pred_et))

# Env + TEC + Seismic (kitchen sink)
X_tr_all, med_all = prep(train, ENV+TEC+SES)
X_va_all, _       = prep(val,   ENV+TEC+SES, med_all)
pred_all = fit_xgb(X_tr_all, y_train, X_va_all)
results.append(report("XGBoost Env + TEC + Seismic", y_val, pred_all))

# TEC + Seismic (isolate TEC lift over seismic)
X_tr_ts, med_ts = prep(train, TEC+SES)
X_va_ts, _      = prep(val,   TEC+SES, med_ts)
pred_ts = fit_xgb(X_tr_ts, y_train, X_va_ts)
results.append(report("XGBoost TEC + Seismic", y_val, pred_ts))

# Seismic only (reference)
X_tr_ses, med_ses = prep(train, SES)
X_va_ses, _       = prep(val,   SES, med_ses)
pred_ses = fit_xgb(X_tr_ses, y_train, X_va_ses)
results.append(report("XGBoost Seismic only (reference)", y_val, pred_ses))

print("\n" + "="*65)
print("  SUMMARY — VALIDATION SET (2019-2022)")
print("="*65)
print(f"  {'Model':<47} {'AUROC':>7} {'BSS':>8}")
print(f"  {'-'*62}")
for r in results:
    print(f"  {r['model']:<47} {r['auroc']:>7.4f} {r['brier_skill']:>+8.4f}")

# Key comparison: does TEC add lift over Seismic alone?
tec_ses = [r for r in results if r["model"] == "XGBoost TEC + Seismic"][0]["auroc"]
ses_only = [r for r in results if r["model"] == "XGBoost Seismic only (reference)"][0]["auroc"]
tec_lift = tec_ses - ses_only
print(f"\n  TEC lift over seismic-only: {tec_lift:+.4f} AUROC")
if abs(tec_lift) < 0.002:
    print("  Verdict: TEC adds no discriminative lift over seismic history")
elif tec_lift > 0:
    print("  Verdict: TEC adds marginal positive lift — warrants Phase 2 investigation")
else:
    print("  Verdict: TEC slightly degrades seismic model — noise contribution")

with open("tec_model_results.json","w") as f:
    json.dump(results, f, indent=2)
print("\nSaved: tec_model_results.json")
