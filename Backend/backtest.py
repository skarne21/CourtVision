"""Backtest the calibrated moneyline model on its chronological hold-out window.

Evaluates only games dated on/after ml_test_start (saved by scraper.py) — games
neither the model nor the calibration layer ever saw. One row per game (home
perspective). Outputs betting-grade metrics and a calibration reliability diagram.

Run from Backend/ after scraper.py:
    ../venv/Scripts/python.exe backtest.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')  # Windows cp1252 console gotcha

import sqlite3
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.calibration import calibration_curve
import matplotlib
matplotlib.use('Agg')  # no display needed, just write the PNG
import matplotlib.pyplot as plt

from features import PREDICTIVE_FEATURES

model = joblib.load('nba_model_calibrated.joblib')
meta = joblib.load('model_metadata.joblib')
test_start = meta.get('ml_test_start')
if test_start is None:
    sys.exit("model_metadata.joblib has no 'ml_test_start' — re-run scraper.py (with the chronological-split fix) first.")

conn = sqlite3.connect('nba_data.db')
df = pd.read_sql('SELECT * FROM team_stats', conn)
conn.close()
df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])

# Home rows only → one row per game; predict_proba[:, 1] is P(home win).
test = df[(df['GAME_DATE'] >= pd.to_datetime(test_start)) & (df['is_home'] == 1)].sort_values(['GAME_DATE', 'GAME_ID'])
if test.empty:
    sys.exit(f"No games on/after {test_start} in nba_data.db — DB and models out of sync? Re-run scraper.py.")

X = test[PREDICTIVE_FEATURES].astype(float)
y = (test['WL'] == 'W').astype(int).values
p = model.predict_proba(X)[:, 1]

brier = brier_score_loss(y, p)
ll = log_loss(y, p)
frac_pos, mean_pred = calibration_curve(y, p, n_bins=10)
ece = float(np.mean(np.abs(frac_pos - mean_pred)))
hit_rate = float(np.mean((p >= 0.5) == y))
home_base = float(np.mean(y))

print("=== CourtVision Moneyline Backtest (held-out games only) ===")
print(f"Window     : {test['GAME_DATE'].min().date()} → {test['GAME_DATE'].max().date()}  ({len(test)} games)")
print(f"Brier      : {brier:.4f}   (random = 0.25, lower is better)")
print(f"Log loss   : {ll:.4f}   (random = 0.693, lower is better)")
print(f"ECE        : {ece:.4f}   (perfect calibration = 0.00)")
print(f"Hit rate   : {hit_rate:.1%}  (always-pick-home baseline = {home_base:.1%})")
print("\nNote: profitability (ROI/CLV) requires market prices for these games.")
print("Live edges are captured in the prediction_log table as the extension runs;")
print("real ROI vs. your actual Kalshi fills lands in the final dashboard phase.")

# Reliability diagram + prediction histogram
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 8), height_ratios=[3, 1], sharex=True)
ax1.plot([0, 1], [0, 1], 'k--', label='Perfect calibration')
ax1.plot(mean_pred, frac_pos, 'o-', color='#10b981', label='CourtVision')
ax1.set_ylabel('Actual home-win rate')
ax1.set_title(f'Calibration — {len(test)} held-out games ({test["GAME_DATE"].min().date()} → {test["GAME_DATE"].max().date()})\n'
              f'Brier {brier:.4f} | Log loss {ll:.4f} | ECE {ece:.4f}')
ax1.legend()
ax1.grid(alpha=0.3)
ax2.hist(p, bins=20, range=(0, 1), color='#38bdf8', edgecolor='black')
ax2.set_xlabel('Predicted P(home win)')
ax2.set_ylabel('Games')
fig.tight_layout()
fig.savefig('backtest_calibration.png', dpi=150)
print("\nSaved: backtest_calibration.png")
