#!/usr/bin/env python3
"""
phase1_model.py
===============
Builds baseline and environmental models for Phase 1.
Train set only for fitting. Validate set for model selection.
Test set untouched.

Pre-registration thresholds:
  Null:            AUROC < 0.52, Brier Skill <= 0.00
  Weak signal:     AUROC 0.52-0.58, Brier Skill 0.00-0.02
  Meaningful:      AUROC >= 0.58, Brier Skill > 0.02
"""

import json
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

PROJECT = "synexis-project-sentinel"

# ── Load data ────────────────────────────────────────────────────────────────

print("Loading phase1_dataset from BigQuery...")
client = bigquery.Client(project=PROJECT)

df = client.query("""
    SELECT *
    FROM `synexis-project-sentinel.sentinel_eval.phase1_dataset`
""").to_dataframe()

print(f"  Total rows: {len(df)}")
print(f"  Columns: {list(df.columns)}")

train = df[df.split == "train"].copy()
val   = df[df.split == "validate"].copy()
test  = df[df.split == "test"].copy()

print(f"  Train: {len(train)} rows, {train.y_m60_next7d.mean():.4f} positive rate")
print(f"  Val:   {len(val)} rows, {val.y_m60_next7d.mean():.4f} positive rate")
print(f"  Test:  {len(test)} rows — NOT TOUCHED")

# ── Helper functions ─────────────────────────────────────────────────────────

def brier_skill(y_true, y_pred, y_ref):
    """Brier Skill Score vs reference prediction."""
    bs_model = brier_score_loss(y_true, y_pred)
    bs_ref   = brier_score_loss(y_true, y_ref)
    return 1 - bs_model / bs_ref if bs_ref > 0 else 0.0

def evaluate(name, y_true, y_pred, y_ref):
    auroc = roc_auc_score(y_true, y_pred)
    bs    = brier_score_loss(y_true, y_pred)
    bss   = brier_skill(y_true, y_pred, y_ref)
    print(f"\n  {name}")
    print(f"    AUROC:       {auroc:.4f}")
    print(f"    Brier:       {bs:.4f}")
    print(f"    Brier Skill: {bss:.4f}")
    return {"model": name, "auroc": auroc, "brier": bs, "brier_skill": bss}

# ── Baseline 1: Climatological ───────────────────────────────────────────────
# For each region, use its long-run positive rate from the train set.

print("\n── Baseline 1: Climatological (regional base rate) ──")
regional_rate = train.groupby("region_key")["y_m60_next7d"].mean().to_dict()
global_rate   = train["y_m60_next7d"].mean()

val["pred_clim"] = val["region_key"].map(regional_rate).fillna(global_rate)

# Reference for BSS: always predict global mean
val["pred_global"] = global_rate

results = []
results.append(evaluate(
    "Climatological (val)",
    val["y_m60_next7d"],
    val["pred_clim"],
    val["pred_global"]
))

# ── Baseline 2: Persistence ──────────────────────────────────────────────────
# Use count_m6_30d (M6+ in past 30 days) as a proxy for persistence.
# Normalize to [0,1] range.

print("\n── Baseline 2: Persistence (30d M6 count) ──")
max_count = train["count_m6_30d"].max()
val["pred_persist"] = (val["count_m6_30d"] / max(max_count, 1)).clip(0, 1)

results.append(evaluate(
    "Persistence 30d (val)",
    val["y_m60_next7d"],
    val["pred_persist"],
    val["pred_global"]
))

# ── Environmental features ───────────────────────────────────────────────────

ENV_FEATURES = [
    "kp_max", "kp_mean",
    "sw_speed_mean", "sw_density_mean", "sw_bz_min",
    "xray_max", "electron_flux_max",
    "has_cme", "has_sep",
]

SEISMIC_FEATURES = [
    "count_m4_30d", "count_m5_30d", "count_m6_30d",
    "max_mag_30d", "count_m4_7d", "count_m5_7d",
]

ALL_FEATURES = ENV_FEATURES + SEISMIC_FEATURES

def prep_X(df, features):
    X = df[features].copy()
    # Fill NULLs with median from train
    for col in features:
        X[col] = X[col].fillna(X[col].median())
    return X.astype(float)

# ── Model 1: Environmental only ──────────────────────────────────────────────

print("\n── Model 1: XGBoost — Environmental features only ──")

X_train_env = prep_X(train, ENV_FEATURES)
X_val_env   = prep_X(val,   ENV_FEATURES)
y_train     = train["y_m60_next7d"].astype(int)
y_val       = val["y_m60_next7d"].astype(int)

scale_pos = (y_train == 0).sum() / (y_train == 1).sum()

model_env = xgb.XGBClassifier(
    n_estimators=200,
    max_depth=4,
    learning_rate=0.05,
    scale_pos_weight=scale_pos,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    eval_metric="logloss",
    verbosity=0,
)
model_env.fit(
    X_train_env, y_train,
    eval_set=[(X_val_env, y_val)],
    verbose=False,
)

val["pred_env"] = model_env.predict_proba(X_val_env)[:, 1]
results.append(evaluate(
    "XGBoost Environmental only (val)",
    y_val,
    val["pred_env"],
    val["pred_global"]
))

# Feature importance
imp = dict(zip(ENV_FEATURES, model_env.feature_importances_))
print("  Feature importances:")
for k, v in sorted(imp.items(), key=lambda x: -x[1]):
    print(f"    {k:25s}: {v:.4f}")

# ── Model 2: Environmental + Seismic ─────────────────────────────────────────

print("\n── Model 2: XGBoost — Environmental + Seismic features ──")

X_train_all = prep_X(train, ALL_FEATURES)
X_val_all   = prep_X(val,   ALL_FEATURES)

model_all = xgb.XGBClassifier(
    n_estimators=200,
    max_depth=4,
    learning_rate=0.05,
    scale_pos_weight=scale_pos,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    eval_metric="logloss",
    verbosity=0,
)
model_all.fit(
    X_train_all, y_train,
    eval_set=[(X_val_all, y_val)],
    verbose=False,
)

val["pred_all"] = model_all.predict_proba(X_val_all)[:, 1]
results.append(evaluate(
    "XGBoost Env+Seismic (val)",
    y_val,
    val["pred_all"],
    val["pred_global"]
))

imp2 = dict(zip(ALL_FEATURES, model_all.feature_importances_))
print("  Feature importances:")
for k, v in sorted(imp2.items(), key=lambda x: -x[1]):
    print(f"    {k:25s}: {v:.4f}")

# ── Summary ───────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("  VALIDATION SET SUMMARY")
print("="*60)
print(f"  {'Model':<35} {'AUROC':>8} {'BrierSkill':>12}")
print(f"  {'-'*55}")
for r in results:
    print(f"  {r['model']:<35} {r['auroc']:>8.4f} {r['brier_skill']:>12.4f}")

print("\n── Pre-registration thresholds ──")
print("  Null:        AUROC < 0.52,  Brier Skill <= 0.00")
print("  Weak signal: AUROC 0.52-0.58, Brier Skill 0.00-0.02")
print("  Meaningful:  AUROC >= 0.58, Brier Skill > 0.02")

# Save results
with open("model_results_val.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nResults saved to model_results_val.json")
