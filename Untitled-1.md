🏀 CourtVision Project Notes: Progress So Far
1. Environment & Architecture setup
Virtual Environment: Initialized a Python venv to keep dependencies isolated.
Tech Stack:
Data & APIs: nba_api, pandas
Machine Learning: scikit-learn, xgboost
Backend Server: fastapi, uvicorn
Database & Persistence: sqlite3, joblib
2. Data Ingestion Pipeline (scraper.py)
Multi-Season Fetching: Configured the nba_api to automatically loop through and pull historical League Game Logs for multiple seasons (2021-22, 2022-23, 2023-24).
Team & Player Logs: The scraper pulls both team-level box scores and individual player-level box scores to allow for deep, contextual feature engineering.
Rate Limiting: Added time.sleep(1) between API calls to prevent the IP address from being blocked by the NBA.
3. Advanced Feature Engineering
Lookahead Bias Prevention: Implemented strict chronological sorting and pandas .shift(1) logic. This ensures the model only uses data that was available prior to a game's tip-off.
Cross-Season Bleed Prevention: Grouped rolling averages by SEASON_STR so that a team's stats from April don't falsely inflate their stats in October of the next season.
Contextual Metrics:
is_home: Binary flag for home-court advantage.
days_rest & rest_differential: Calculated fatigue based on days between games.
Rolling Box Score Averages: Built 5-game and 10-game rolling averages for advanced stats including PTS, PTS_allowed, eFG (Effective Field Goal %), PLUS_MINUS, AST, REB, and TOV.
Missing Player Value (The Custom Edge):
Built an engine that tracks the 10-game rolling PRA (Points + Rebounds + Assists) of rotation players (averaging >12 mins).
Dynamically calculates exactly how much production a team is missing if a key player sits out.
Pre-Game Elo Ratings:
Implemented a chronological Elo system starting teams at 1500.
Includes a 100-point adjustment for home-court advantage.
Provides the model with a "True Baseline Strength" metric to contrast against short-term rolling momentum.
4. Machine Learning Model
Algorithm Upgrade: Upgraded from a basic Random Forest to an industry-standard XGBoost Classifier (XGBClassifier), optimized for tabular sports data.
Chronological Split: Used train_test_split with shuffle=False to strictly train on older games and test on newer games, simulating a real betting environment.
Hyperparameter Tuning: Implemented GridSearchCV to automatically test dozens of tree depths, learning rates, and estimators to find the mathematically perfect configuration.
Feature Importances: Configured the script to print out which features the model values most (revealing that PLUS_MINUS_roll_10, is_home, and our custom MISSING_PLAYER_VALUE are driving the predictions).
5. Data Persistence & Backend API (api.py)
Local Database: The data pipeline automatically saves the final, cleaned DataFrame to a local SQLite database (nba_data.db) at the end of every run.
Model Saving: The fully trained XGBoost model is serialized and saved as nba_model.joblib.
FastAPI Server: Built a lightning-fast web server that loads the model into memory upon startup.
The /predict Endpoint:
Accepts home_team and away_team parameters.
Dynamically queries nba_data.db to retrieve the absolute latest Elos, rolling averages, and Missing Player Values for both teams.
Constructs a live feature array, feeds it to the XGBoost model, and returns a JSON response containing the Predicted Winner and the Win Probability (Confidence %).
📝 Project Notes: CourtVision Pro (Phase 2 - API & Frontend)
1. Backend API Hardening (api.py)
CORS Configuration: Added CORSMiddleware to the FastAPI app. This was a critical step to allow the Chrome Extension (which runs on kalshi.com) to communicate securely with the local server (127.0.0.1:8000) without getting blocked by the browser.
XGBoost Data Type Fixes: Pandas DataFrames default to "object" types when built dynamically. We added a crucial input_data.astype(float) cast before feeding the data into the model to prevent XGBoost from crashing.
JSON Serialization Fix: XGBoost outputs predictions as numpy.float32 types, which FastAPI cannot natively convert to JSON. We wrapped the model outputs in standard Python int() and float() functions to successfully send the data back to the extension.
2. Chrome Extension Setup (manifest.json & content.js)
Manifest Configuration: Created a V3 manifest file granting the extension permission to run on https://kalshi.com/* and fetch data from http://127.0.0.1:8000/*.
Page Scanner: Implemented a setInterval loop that runs every 3 seconds to scan the DOM (document.body.innerText) for specific matchup text, ensuring the extension catches dynamic page loads typical of React-based sites like Kalshi.
Data Fetching: Built the asynchronous getPrediction(awayTeam, homeTeam) function to ping the local Python API and handle the returned JSON payload.
3. Advanced UI Injection (The CourtVision Card)
Data Translation: Wrote logic to translate the raw win probability into actionable betting metrics:
American Implied Odds: Added a math formula to convert the probability percentage into American odds (e.g., -150, +120) so you can directly compare the AI's line with Kalshi's price.
Confidence Tiers: Implemented dynamic color-coding—Green for "Locks" (>70%), Yellow for "Leans" (>60%), and Red for "Toss-Ups" (<60%).
Widget Rendering: Replaced the basic text badge with a modern, dark-mode CSS card containing flexbox layouts, borders, and emojis.
Z-Index & Fixed Positioning: Updated the injection strategy from .prepend() to appending a position: fixed element with a z-index of 999999 directly to the document.body. This solved the issue where Kalshi's sticky headers and complex layouts were hiding the injected card.
4. Version Control
Successfully initialized an empty GitHub repository, linked the local origin, resolved authentication/cred-manager issues, and pushed the complete end-to-end pipeline (Scraper, XGBoost Model, FastAPI Backend, and Chrome Extension Frontend) to the main branch.


🧠 The Backend (Python, FastAPI, XGBoost)
Data Pipeline & Model Training (scraper.py)
Scrapes multiple seasons of historical NBA game and player data using the nba_api.
Feature Engineering: Calculates advanced metrics to prevent look-ahead bias, including:
5-game and 10-game rolling averages (Points, eFG%, Rebounds, Assists, etc.).
Dynamic pre-game Elo ratings for both teams.
Rest differential (calculating actual days of rest between games).
MISSING_PLAYER_VALUE: Calculates the expected PRA (Points + Rebounds + Assists) deficit based on which core rotation players are missing from a game.
Trains an XGBoost Classifier using GridSearchCV to find the best hyperparameters.
Saves the trained model to nba_model.joblib and the latest team/player stats to an SQLite database (nba_data.db).
Live Injury Adjustments (live_injuries.py)
Scrapes ESPN's live NBA injury report to see who is currently listed as "Out".
The API (api.py)
Runs a local FastAPI server that the Chrome Extension communicates with.
When queried for a matchup, it fetches the latest team stats from the SQLite DB.
Cross-references the ESPN injury scrape with the team's latest player stats to dynamically subtract PRA for currently injured players.
Feeds the real-time adjusted data into the XGBoost model and returns the predicted winner and AI confidence percentage.

💻 The Frontend (Chrome Extension - content.js)
Matchup Detection: Scans the Kalshi web page text globally for the pattern [City] at [City] (e.g., "Boston at New York") to identify all active NBA betting markets on the screen.
Dynamic UI Injection:
Single Game Mode: If you are on a specific market page, it injects a floating courtvision-card showing a direct comparison between the AI Probability and the Market Probability.
Main Feed Mode: If you are on the main Kalshi feed, it aggregates all games and injects a courtvision-sidebar, ranking the matchups by AI edge.
The Smart DOM Traverser (getMarketProbFromDOM)
Extracts the live Kalshi market odds directly from the webpage's HTML to compare against the AI.
Recent Fix 1 (Deep Traversal): Increased the DOM tree traversal limit from 5 to 8 levels up to ensure the script finds the parent container holding both the team name and the odds.
Recent Fix 2 (Single Game Layout): Added logic to explicitly target the h2.typ-headline-x10 element, which neatly holds the large percentage value on single market pages.
Recent Fix 3 (Main Feed Layout): Added logic to target the span.tabular-nums class on the main feed page. Because Kalshi omits the % sign in the raw HTML text here, the script manually appends it.
Recent Fix 4 (The Multiplier Trap): Fixed a bug where the script was accidentally scraping Kalshi's decimal payout multipliers (like 1.83x) instead of the implied percentage. Updated the logic to use querySelectorAll, iterate backward through the row's numbers, and ignore any values containing a decimal (.) or an x, successfully isolating the clean integer percentage.


Here are two scenarios to show why Edge is more important than just picking the winner:
Scenario A: The Great Bet (Positive Edge)
Kalshi Price: 50¢ (50% implied probability)
CourtVision AI: Says the Lakers have a 65% chance of winning.
The Math: 65% - 50% = +15% Edge.
The Verdict: You are buying something for 50 cents that your AI thinks is actually worth 65 cents. The extension lights up Green. You make this bet every time.
Scenario B: The Trap Bet (Negative Edge)
Kalshi Price: 90¢ (90% implied probability)
CourtVision AI: Says the Celtics are an amazing team and have an 85% chance of winning.
The Math: 85% - 90% = -5% Edge.
The Verdict: Even though the AI thinks the Celtics will probably win the game, the market is overpricing them. You are paying 90 cents for something only worth 85 cents. Over the long run, making bets like this will drain your bank account. The extension lights up Red. You skip this bet.

1. Advanced Team & Lineup Metrics
Basketball is a game of synergy, not just isolated individual performances.
The Four Factors: Effective Field Goal Percentage (eFG%), Turnover Rate (TOV%), Offensive Rebound Rate (OREB%), and Free Throw Rate (FTR). These four metrics dictate the mathematical foundation of winning.
5-Man Unit Net Ratings: Instead of looking at overall team stats, feed the model the net rating (offensive rating minus defensive rating) of the specific 5-man lineups expected to play.
Pace and Positional Matchups: A team that plays at a high pace against a bottom-tier transition defense is a strong signal.
2. Real-Time Availability & Usage Shifts
Injury Impact Modeling: Binary "playing/not playing" injury reports are a good start, but the AI needs to know where that production goes. If a high-usage player is ruled out, feed the model the historical performance of the secondary players whose usage rates will spike in their absence.
Rest Disparity: This is a massive variable in the NBA. Categorize rest advantages (e.g., Team A is on the second night of a back-to-back with travel, while Team B has had two days of rest at home).
3. Spatiotemporal & Tracking Data
If you can get access to optical tracking data (like Second Spectrum or NBA Advanced Stats), this is where models leap ahead of the public.
Distance Traveled & Speed: Cumulative player load over the last five games can predict regression due to dead legs.
Play-Type Efficiency: How well a team guards the pick-and-roll versus how frequently the opposing team runs it. If Team A scores 1.1 points per possession on isolation plays, and Team B is dead last in isolation defense, that creates a highly predictive feature.
4. Market and Off-Court Data
If the goal is to find value in predictive markets, the market itself is data.
Line Movement: Tracking the opening line versus the current line can indicate where "sharp" money is flowing.
Referee Tendencies: Believe it or not, some referee crews historically call more fouls (favoring teams with high Free Throw Rates) or suppress home-court advantage.
The "Curse of Dimensionality" Warning
While it is tempting to feed an AI everything, throwing too much raw, uncurated data at a model can lead to overfitting—where it memorizes past noise rather than learning the actual game. The secret is feature engineering: creating a calculated column like Rest_Advantage_Delta is infinitely more powerful for a model than just feeding it raw dates and times to figure it out on its own.

✅ What is ALREADY implemented in your code:
The Four Factors: You've nailed this. In scraper.py's engineer_features function, you are explicitly calculating Effective Field Goal Percentage (eFG), Turnover Rate (TOV_rate), Offensive Rebound Rate (OREB_rate), and Free Throw Rate (FTR). You're also correctly turning these into 5-game and 10-game rolling averages to feed into your PREDICTIVE_FEATURES list.
Rest Disparity: This is fully implemented. You are calculating days_rest for each team and a specific rest_differential feature in both your training data (scraper.py) and dynamically for live games (api.py).
Injury Impact Modeling (Level 1): You have a solid foundation here. You aren't just doing binary "playing/not playing"—your engineer_missing_player_value function assigns a specific numeric weight to injuries by calculating the rolling PRA (Points + Rebounds + Assists) of the players who are out.
Feature Engineering (Avoiding the Curse of Dimensionality): You've followed the advice perfectly here. Instead of feeding the model raw dates or hundreds of raw stats, you've curated exactly 25 highly calculated features (like ELO_opp, rest_differential, and shifted rolling averages to avoid lookahead bias).
❌ What is NOT YET implemented:
5-Man Unit Net Ratings: Your model currently evaluates the team as a whole using overall PLUS_MINUS_roll_5 and PLUS_MINUS_roll_10. It does not look at the specific net ratings of the 5-man lineups that will be on the floor.
Advanced Injury Usage Shifts (Level 2): While you subtract the missing PRA of injured players, you do not currently redistribute that usage to the secondary players who will step up. (e.g., If LeBron is out, Anthony Davis's projected usage/PRA should theoretically spike).
Pace and Positional Matchups: There are no features currently tracking team Pace (possessions per 48 minutes) or specific positional defensive strengths.
Spatiotemporal & Tracking Data: Your model strictly uses traditional box score data from the nba_api. You do not have optical tracking data (Distance Traveled, Speed, Pick-and-Roll efficiency vs. Isolation efficiency).
Market and Off-Court Data: You are pulling market data in your frontend Chrome Extension to compare against your AI (content.js), but you are not feeding historical line movement, sharp money metrics, or referee tendencies into your XGBoost model's training features.
1. scraper.py (The Training Pipeline)
Grabbed More Opponent Data: I updated the data-merging step to pull in the opponent's Field Goal Attempts (FGA), Free Throw Attempts (FTA), Offensive Rebounds (OREB), and Turnovers (TOV).
Calculated Advanced Metrics: Using that new data, I added the official NBA formulas for:
Pace: The estimated number of possessions a team has per game.
Offensive Rating (OFF_RTG): How many points a team scores per 100 possessions.
Defensive Rating (DEF_RTG): How many points a team allows per 100 possessions.
Added to Rolling Averages: I added these three new metrics to your stats_to_roll list, so the model now looks at a team's 5-game and 10-game rolling averages for Pace and Efficiency.
2. api.py (The Live Server)
Updated the Model's Input List: I added the new PACE, OFF_RTG, and DEF_RTG rolling averages to the PREDICTIVE_FEATURES list at the top of the file. This ensures that when the Chrome extension asks for a prediction, the API pulls these new advanced stats from your database to feed into the newly trained model.
Why did we do this?
Previously, your model only looked at PTS_roll_5 (raw points scored). The problem with raw points is that a team scoring 120 points isn't necessarily a good offensive team—they might just play incredibly fast (high Pace) and have a lot of possessions.
By switching to Offensive/Defensive Rating, your AI will no longer be tricked by fast-paced but sloppy teams, and it will properly identify slow-paced teams that are actually highly lethal and efficient.
1. Matchup Dynamics (Opponent Context)
Previously, your model had a massive blindspot: it was only looking at how good "Team A" was playing recently, but it didn't know anything about "Team B's" recent form (other than their overall Elo rating).
In scraper.py: I added logic to merge the opponent's rolling 5-game and 10-game stats (OFF_RTG, DEF_RTG, PACE, eFG, etc.) directly into the prediction row as _opp columns. Now, the XGBoost model can directly compare "Team A's Offense vs. Team B's Defense."
In api.py: I updated the live prediction logic to grab the Away Team's recent stats from the database and feed them into these new _opp columns before asking the model for a prediction.
2. Advanced Injury Usage Shifts
Previously, your model only subtracted a raw number (Missing PRA) when players were injured. But losing 30 PRA hurts a terrible offensive team way more than it hurts a powerhouse team.
In scraper.py & api.py: I introduced MISSING_USAGE_PCT. We now calculate exactly what percentage of the team's total core rotation production is missing. This gives the AI much better context on how severely an injury cripples a team's offensive structure.

Phase 9: Probability Calibration & Betting-Grade Evaluation
The Problem
XGBoost's raw predict_proba outputs were passed directly to the frontend as win probabilities. XGBoost is notoriously miscalibrated — when it says 70%, the team might only win 62% of the time. This silently breaks everything downstream: the edge calculation is wrong, and any Kelly stake derived from it is wrong.

What Changed in scraper.py
New imports:
Python
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit, PredefinedSplit
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from xgboost import XGBClassifier
from sklearn.metrics import brier_score_loss, log_loss
import numpy as np


Removed: train_test_split, accuracy_score, classification_report.
Three-way chronological split (70 / 15 / 15):
Python
n = len(X)
train_end = int(n * 0.70)
cal_end   = int(n * 0.85)

X_train, y_train = X.iloc[:train_end], y.iloc[:train_end]        # GridSearchCV
X_cal,   y_cal   = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]  # isotonic fit
X_test,  y_test  = X.iloc[cal_end:], y.iloc[cal_end:]            # final eval only


The calibration set is never seen during training. The test set is never seen during training or calibration.
GridSearchCV: TimeSeriesSplit + neg_log_loss:
Replaced cv=3, scoring='accuracy' with:
Python
tscv = TimeSeriesSplit(n_splits=5)
grid_search = GridSearchCV(xgb, param_grid, cv=tscv, scoring='neg_log_loss', n_jobs=-1)


TimeSeriesSplit guarantees every fold trains on the past and validates on the future — no forward-looking leakage. neg_log_loss optimizes for probability quality, not winner-picking accuracy.
Isotonic calibration via PredefinedSplit:
cv='prefit' was removed in newer scikit-learn. The replacement:
Python
test_fold = np.concatenate([np.full(len(X_train), -1), np.zeros(len(X_cal))])
ps = PredefinedSplit(test_fold)
X_trainval = pd.concat([X_train, X_cal])
y_trainval = pd.concat([y_train, y_cal])
best_xgb = XGBClassifier(**grid_search.best_params_, random_state=42, eval_metric='logloss')
calibrated_model = CalibratedClassifierCV(best_xgb, method='isotonic', cv=ps)
calibrated_model.fit(X_trainval, y_trainval)


PredefinedSplit with -1 rows = training fold, 0 rows = calibration fold. The base XGBoost trains on X_train, the isotonic layer fits on X_cal. Same intent as cv='prefit', sklearn-version-safe.
Betting-grade evaluation (replaces accuracy):
Python
y_prob = calibrated_model.predict_proba(X_test)[:, 1]

brier = brier_score_loss(y_test, y_prob)      # lower better, random = 0.25
ll    = log_loss(y_test, y_prob)              # lower better, random = 0.693
fraction_of_positives, mean_predicted = calibration_curve(y_test, y_prob, n_bins=10)
ece   = float(np.mean(np.abs(fraction_of_positives - mean_predicted)))  # lower better, perfect = 0.00


Saved artifact: nba_model_calibrated.joblib (the full CalibratedClassifierCV wrapper). The old nba_model.joblib is no longer produced.

What Changed in api.py
One line:
Python
# Before
model = joblib.load('nba_model.joblib')

# After
model = joblib.load('nba_model_calibrated.joblib')


CalibratedClassifierCV exposes identical predict() and predict_proba() interfaces — nothing else in api.py needed to change.

Why It Matters
The edge displayed in the extension is AI_probability − Market_probability. If the AI says 70% when the true rate is 62%, the green badge is showing 8% of fake edge. After isotonic calibration, a stated 63% probability should historically resolve as a home team win ~63% of the time. The edge number becomes trustworthy — and so does every Kelly stake derived from it.


Phase 8: Advanced Market Integration (Spread & Point Totals)
The Problem
The moneyline model predicts a binary winner. Spread and total markets require predicting by how much — a fundamentally different task requiring regression, not classification.
scraper.py Changes
Two new continuous target columns are derived from the same game rows:
df['home_margin'] = df['PTS'] - df['PTS_allowed'] # spread target
df['total_pts'] = df['PTS'] + df['PTS_allowed'] # total target
Two XGBRegressor models are trained on home-team rows only (is_home == 1), using the same 21 predictive features as the moneyline model but with an 80/20 chronological split and neg_MAE scoring inside GridSearchCV(TimeSeriesSplit(5)).
The residual standard deviation of each model's predictions on the test set is saved alongside the models: joblib.dump({'spread_sigma': spread_sigma, 'total_sigma': total_sigma}, 'model_metadata.joblib')
Saved artifacts: model_spread.joblib, model_total.joblib, model_metadata.joblib.
Training metrics logged:
Spread: MAE ~11 pts, RMSE ~14 pts, Sigma ~14 pts
Total: MAE ~15 pts, RMSE ~19 pts, Sigma ~19 pts
api.py Changes
All three model files are loaded at startup with graceful fallback if missing. A new market_type query parameter routes requests:
market_type | Model used | Returns
moneyline (default) | nba_model_calibrated.joblib | predicted_winner, win_probability
spread | model_spread.joblib | predicted_margin, win_probability, recommendation
total | model_total.joblib | predicted_total, win_probability, recommendation
The statistical mapping (the key insight): NBA score margins follow a roughly normal distribution. The model predicts the mean (μ), and the historical residual sigma (σ) serves as the standard deviation. scipy.stats.norm.cdf converts that distribution into a cover/over probability against the Kalshi line (X):
P(cover) = 1 - norm.cdf(line, loc=predicted_margin, scale=SPREAD_SIGMA)
P(over) = 1 - norm.cdf(line, loc=predicted_total, scale=TOTAL_SIGMA)
content.js Changes
detectMarketContext() reads the raw page text and uses regex to identify which market type is displayed and extract the line:
/([A-Za-z\s]+?)\s+wins by over\s+(\d+\.?\d*)\s+points/i // spread
/Over\s+(\d+\.?\d*)\s+points scored/i // total
The prediction cache key is extended with a market suffix so moneyline and spread predictions for the same teams never collide:
"BOS@LAL" // moneyline
"BOS@LAL:spread:5.5" // spread
The card renders market-specific UI: spread shows projected margin and YES/NO cover recommendation; total shows projected combined score and OVER/UNDER recommendation. Edge and color-coding logic is shared across all three market types.
Phase 5.2: Kelly Criterion
The Math
The Kelly Criterion computes the mathematically optimal fraction of bankroll to wager given an edge:
f* = (p - c) / (1 - c)
Where p = model's win probability (decimal) and c = Kalshi contract cost (decimal, e.g. 55¢ → 0.55). The result is capped at 25% to limit variance even when Kelly suggests a larger position.
New Files
Frontend/popup.html
Dark-themed extension popup (#0f172a background) matching the card palette. Contains a single number input for bankroll. Clicking the extension icon in Chrome's toolbar opens this popup. Styled with focus ring on the input (#38bdf8 border) and a Save button.
Frontend/popup.js
On DOMContentLoaded: reads chrome.storage.local.get('bankroll') and pre-fills the input with any previously saved value. On Save button click: writes the parsed float to chrome.storage.local.set({ bankroll: value }). Empty input writes 0, clearing the Kelly display.
manifest.json Changes
Two additions:
1. "storage" added to the permissions array — required for chrome.storage.local
2. New "action" block wires the popup: "action": { "default_popup": "popup.html", "default_title": "CourtVision Settings" }
content.js Changes
scanForMatchups() reads bankroll from storage once per scan cycle at the top of the function and passes it into injectPredictionCard() as a fourth parameter (defaults to 0).
Inside injectPredictionCard(), Kelly is computed only when three conditions hold: bankroll > 0, marketProbFloat > 0, and kelly > 0 (positive edge). The card then shows: RECOMMENDED BET: $XX.XX (X.X% of bankroll)
If bankroll is unset, a muted hint prompts the user to open the popup. If edge is zero or negative, the Kelly row is hidden entirely — Kelly never recommends betting into negative EV.
Instant update on Save: A chrome.storage.onChanged listener at the bottom of content.js fires the moment popup.js writes to storage. It clears card.dataset.matchup (bypassing the early-return deduplication guard) and immediately calls scanForMatchups() — so the card re-renders with the new stake size without waiting for the 3-second polling interval.
Phase 11: SHAP Explainability
The Problem
The card showed a probability and an edge percentage but gave no indication of why the model arrived at that number. A misprediction was completely opaque. SHAP (SHapley Additive exPlanations) assigns each feature a contribution value showing how much it pushed the prediction up or down from the baseline.
Implementation Approach
The shap Python library has no Python 3.13 wheel. XGBoost has TreeSHAP built natively into its booster via booster.predict(dmat, pred_contribs=True) — mathematically identical output, zero new dependencies.
api.py Changes
New import: import xgboost as xgb
New helper function added before the route handlers:
def get_shap_contributions(booster, input_df, top_n=3):
 dmat = xgb.DMatrix(input_df, feature_names=list(input_df.columns))
 contribs = booster.predict(dmat, pred_contribs=True)
 shap_vals = contribs[0][:-1] # drop bias term (last column)
 pairs = sorted(zip(input_df.columns, shap_vals), key=lambda x: abs(x[1]), reverse=True)
 return [{"feature": f, "impact": round(float(v), 4)} for f, v in pairs[:top_n]]
The output is the top 3 features sorted by absolute impact magnitude. Booster extraction per market type: Spread/Total: model_spread.get_booster() / model_total.get_booster(); Moneyline: model.calibrated_classifiers_[0].estimator.get_booster().
content.js Changes
FEATURE_LABELS dict added at the top of the file — maps every raw feature name to a human-readable label shown on the card (ELO → "Home Elo strength", etc.). contributionsHtml block rendered below the Kelly row inside injectPredictionCard() showing the impact value, green for positive and red for negative.



---
---

# 🤝 HANDOFF DOCUMENT — Full Project State & Continuation Guide
*(Written 2026-07-02. Read this top-to-bottom before touching anything. Everything above this line is the historical/aspirational notes — some of it is INACCURATE, see the "Notes vs. Reality" section below.)*

## 0. TL;DR — What this project is
**CourtVision** is a local NBA betting-model pipeline that feeds a Chrome extension overlaid on **kalshi.com**. Flow:
1. `Backend/scraper.py` pulls NBA box scores + player logs, engineers features, trains models, saves them + a SQLite DB.
2. `Backend/api.py` is a FastAPI server (localhost:8000) that loads the models and serves `/predict`.
3. `Frontend/` is a Chrome MV3 extension that scrapes the Kalshi page, calls the local API, and injects a card/sidebar showing the AI's probability, the **edge** vs. the market price, a Kelly stake, and SHAP feature contributions.

The core thesis: **edge = AI_probability − market_probability**. Positive edge = bet, negative = skip. That's why probability *calibration* matters more than raw accuracy.

## 1. Current working state (VERIFIED 2026-07-02)
- ✅ `scraper.py` runs clean end-to-end on Python 3.11.9. Produces: `nba_model_calibrated.joblib`, `model_spread.joblib`, `model_total.joblib`, `model_metadata.joblib`, `nba_data.db`.
- ✅ `api.py` imports and loads all models without error.
- **Model metrics (last run):** Moneyline Brier 0.2034, Log-loss 0.6114 (baseline 0.693), ECE 0.0503. Spread MAE 11.03 pts (σ=14.20). Total MAE 14.99 pts (σ=18.81).
- **Top feature importances:** ELO_opp, ELO, is_home, PLUS_MINUS_roll_10, PLUS_MINUS_roll_5, rest_differential, MISSING_PLAYER_VALUE(_opp).
- **Seasons trained on:** 2021-22 → 2025-26 (see `seasons_to_pull` in scraper.py `__main__`).

## 2. Environment setup (do this FIRST on any new device)
The venv and all model/db artifacts are **gitignored** — they do NOT come with the repo. You must rebuild them.
```bash
# From repo root. Python 3.11.x required (3.13 has no wheel for some deps).
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -r requirements.txt
```
`requirements.txt` (now committed): pandas, numpy, scikit-learn, xgboost, nba_api, fastapi, uvicorn, joblib, scipy, requests, lxml.

**Windows console gotcha (already fixed):** scraper.py prints `→` and emoji. Windows' default cp1252 console crashes on these with `UnicodeEncodeError`. Fixed at the top of scraper.py with `sys.stdout.reconfigure(encoding='utf-8')`. If you add unicode prints to `api.py` or `live_injuries.py` and hit the same crash, apply the same one-liner there.

## 3. How to run
```bash
# 1. Train models + build DB (few min: 10 NBA API calls w/ 1s sleeps + 2 GridSearches)
cd Backend && ../.venv/Scripts/python.exe scraper.py

# 2. Start the API server
cd Backend && ../.venv/Scripts/python.exe -m uvicorn api:app   # add --reload for dev

# 3. Load the extension: Chrome → Extensions → Developer mode → Load unpacked → select Frontend/
#    Then browse kalshi.com NBA markets.
```
Test the API directly: `http://127.0.0.1:8000/predict?home_team=LAL&away_team=BOS`
Params: `home_team`, `away_team` (uppercase abbrevs), `market_type` = `moneyline`(default)|`spread`|`total`, `line` (float, required for spread/total), `spread_team` (optional).

## 4. File-by-file reality
### Backend/scraper.py (the truth about what it does)
- `fetch_multiple_seasons()` / `fetch_multiple_seasons_players()` — pull team + player LeagueGameLogs, 1s sleep between calls.
- `engineer_missing_player_value()` — 10-game rolling PRA of >12-min rotation players; sums PRA of players absent vs. their recent roster. → `MISSING_PLAYER_VALUE`.
- `engineer_elo()` — chronological Elo, start 1500, K=20, +100 home-court adj. → `ELO`.
- `engineer_features()` — is_home, days_rest, rest_differential, PTS_allowed (opp merge), **eFG only** (NOT the other Four Factors), and 5/10-game rolling means of `['PTS','PTS_allowed','eFG','PLUS_MINUS','AST','REB','TOV']`, shift(1) + grouped by SEASON_STR to kill lookahead + cross-season bleed.
- `__main__` — 21 predictive features; 70/15/15 chronological split; GridSearchCV(TimeSeriesSplit(5), neg_log_loss); isotonic calibration via PredefinedSplit; Brier/log-loss/ECE eval; then two XGBRegressors (spread + total) on home rows, 80/20 split, neg_MAE, residual σ saved to metadata.
- **THE 21 FEATURES:** is_home, days_rest, rest_differential, MISSING_PLAYER_VALUE, MISSING_PLAYER_VALUE_opp, ELO, ELO_opp, then PTS/PTS_allowed/eFG/PLUS_MINUS/AST/REB/TOV each × roll_5 and roll_10.

### Backend/api.py
- Loads calibrated moneyline + spread + total models (graceful fallback if regression models missing).
- `/predict` builds a home-perspective feature row from the DB, does live ESPN injury adjustment (5-min cache), routes by `market_type`.
- Spread/total use `scipy.stats.norm.cdf(line, loc=prediction, scale=σ)` to turn a point prediction into a cover/over probability.
- `get_shap_contributions()` — native XGBoost TreeSHAP (`booster.predict(dmat, pred_contribs=True)`), top-3 features. (The `shap` pip package is NOT used — no 3.13 wheel — this is the zero-dependency equivalent.)
- **Known SQL smell (not yet fixed):** team queries use f-string interpolation of the team abbrev into SQL. Low risk (abbrevs are `.upper()`'d, come from our own extension), but it's a latent injection pattern — parameterize if you ever accept external input.

### Backend/live_injuries.py
- Scrapes `espn.com/nba/injuries` via `pd.read_html` (needs `lxml`), renames NAME→PLAYER_NAME, returns concatenated table. api.py filters STATUS=='Out'.

### Frontend/ (all present & matching the notes)
- `manifest.json` — MV3, matches kalshi.com, permissions activeTab+storage, popup action.
- `content.js` — 3s setInterval scan, matchup regex `[City] at [City]`, `detectMarketContext()` for spread/total lines, `getMarketProbFromDOM()` DOM traverser (the "Multiplier Trap" fix etc.), single-game card + main-feed `courtvision-sidebar`, Kelly calc (cap 25%), `FEATURE_LABELS` for SHAP display.
- `popup.html` / `popup.js` — bankroll input → `chrome.storage.local`; onChanged listener re-renders card instantly.

## 5. ⚠️ NOTES vs. REALITY — what the notes above CLAIM but the code does NOT do
The historical notes (especially the "1. scraper.py / Grabbed More Opponent Data", "Matchup Dynamics", "Advanced Injury Usage Shifts" sections, and the "✅ ALREADY implemented" checklist) describe work that is **NOT in the current codebase**. Treat these as reverted/aspirational, NOT done:
1. **Four Factors** — notes claim TOV_rate, OREB_rate, FTR are computed. **FALSE** — only `eFG` exists.
2. **Pace / OFF_RTG / DEF_RTG** — claimed added to rolling stats & features. **NOT PRESENT.**
3. **Opponent `_opp` rolling columns** (OFF_RTG_opp, DEF_RTG_opp, PACE_opp, eFG_opp, etc.) — **NOT PRESENT.** Only `ELO_opp` and `MISSING_PLAYER_VALUE_opp` exist.
4. **MISSING_USAGE_PCT** — **NOT PRESENT** anywhere.
5. **Feature count** — notes say "exactly 25 features"; the code has **21**. (The Phase 8 note correctly says 21 — the two notes contradict each other.)
6. `nba_model.joblib` (old, uncalibrated) still sits in Backend/ unused — safe to delete anytime.

## 6. Roadmap — assessed for value (which "phantom" features are worth building)
The model is already reasonably calibrated (log-loss 0.61 vs 0.69 baseline). NBA outcomes cap ~65-70% predictable, so marginal features risk overfitting. Ranked:
1. **Pace / OFF_RTG / DEF_RTG (team + opponent) — WORTH IT, do this first.** Raw `PTS_roll` conflates pace with efficiency; points-per-100-possessions is genuinely more predictive. Compute possessions from FGA/FTA/OREB/TOV (already in the team log). Highest payoff.
2. **Opponent rolling stats — only add OFF_RTG_opp/DEF_RTG_opp** (from #1), not all of them — ELO_opp already proxies overall opponent strength; full `_opp` set nearly doubles feature count (dimensionality risk).
3. **MISSING_USAGE_PCT — cheap, minor.** Normalize missing PRA by team total. Do it while touching the injury code, not standalone.
4. **Four Factors (TOV%/OREB%/FTR) — skip for now.** eFG already carries most of the signal.
5. **5-man lineup net ratings, tracking data, line movement, ref tendencies — skip.** High effort, fragile, need data/lineups you can't get at inference time from the Kalshi page.
**Recommended next PR:** implement #1 + #3 together (they touch the same merge/rolling code in scraper.py AND the PREDICTIVE_FEATURES list + input-build loop in api.py — keep the two feature lists in sync or the API will crash on a column mismatch).

## 7. Critical invariant when adding/removing features
`scraper.py`'s `predictive_features` and `api.py`'s `PREDICTIVE_FEATURES` **must be identical and in the same order.** The API builds its input row positionally (`for col in PREDICTIVE_FEATURES[7:]`). If they drift, XGBoost gets wrong/missing columns and `/predict` 500s. After ANY feature change: edit both lists, re-run scraper.py (regenerates models + DB schema), restart the API.

## 8. Git / artifacts
- **Committed:** source (`scraper.py`, `api.py`, `live_injuries.py`, Frontend/*), `requirements.txt`, README, these notes.
- **Gitignored (rebuild locally, never pushed):** `.venv/`, `*.joblib`, `nba_data.db`, `.env`. `nba_data.db` is tracked from an earlier commit but treat it as regenerable — don't rely on the pushed copy being current.
- Remote: `github.com/skarne21/CourtVision`, branch `main`.

## 9. Where the last conversation left off
Diagnosed that the API couldn't start (it loads `nba_model_calibrated.joblib`, but only the stale `nba_model.joblib` was on disk — scraper had never been re-run since the Phase 8/9 rewrite). Fixed by: creating the venv, adding `requirements.txt`, fixing the cp1252 print crash, and re-running scraper.py to regenerate all four artifacts. Verified API imports clean. **Next suggested step:** implement roadmap item #1+#3 (Pace/OFF_RTG/DEF_RTG + MISSING_USAGE_PCT), or reconcile/delete the inaccurate notes in the sections above this handoff.
