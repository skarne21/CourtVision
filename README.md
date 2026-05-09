# CourtVision AI

A full-stack quantitative trading tool that identifies Expected Value (+EV) in NBA betting markets on the Kalshi prediction platform. The system combines automated data engineering, XGBoost machine learning, a FastAPI backend, and a Chrome Extension that injects real-time AI predictions directly into Kalshi's UI.

---

## How It Works

```
NBA API → scraper.py → nba_data.db → api.py → content.js → Kalshi.com
  (data)    (train)      (sqlite)    (FastAPI)  (extension)   (UI)
```

1. **`scraper.py`** pulls 5 seasons of NBA game and player data, engineers 25+ predictive features, trains a calibrated XGBoost classifier, and saves the model + stats to disk.
2. **`api.py`** loads the model and serves a `/predict` endpoint. On each request it fetches live injury data from ESPN, adjusts the feature vector in real-time, and returns a win probability.
3. **`content.js`** runs inside Chrome on Kalshi.com, scans the page for NBA matchups every 3 seconds, calls the API, extracts the live market odds from the DOM, and injects a floating prediction card showing AI probability, market probability, and edge percentage.

---

## Repository Structure

```
CourtVision/
├── Backend/
│   ├── scraper.py          # Data pipeline + model training
│   ├── api.py              # FastAPI prediction server
│   ├── live_injuries.py    # ESPN injury report scraper
│   ├── nba_data.db         # SQLite: team_stats + player_stats tables
│   └── nba_model_calibrated.joblib  # Trained + isotonic-calibrated XGBoost
└── Frontend/
    ├── manifest.json       # Chrome Extension manifest v3
    └── content.js          # DOM scanner + UI injection logic
```

---

## Setup

### Prerequisites
- Python 3.10+
- Google Chrome
- A Kalshi account

### Backend

```bash
cd Backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install fastapi uvicorn xgboost scikit-learn pandas nba_api joblib requests
```

### Train the Model

Run this once (takes ~10–15 min due to NBA API rate limiting):

```bash
python scraper.py
```

This will:
- Fetch seasons 2021-22 through 2025-26 from the NBA API
- Engineer all features and save to `nba_data.db`
- Train XGBoost with `TimeSeriesSplit` cross-validation
- Fit isotonic probability calibration on a held-out slice
- Print Brier Score, Log Loss, and ECE to the terminal
- Save `nba_model_calibrated.joblib`

### Start the API

```bash
uvicorn api:app --reload
```

The server runs at `http://127.0.0.1:8000`. Test it:

```bash
curl "http://127.0.0.1:8000/predict?home_team=LAL&away_team=BOS"
```

Expected response:
```json
{
  "matchup": "BOS @ LAL",
  "predicted_winner": "LAL",
  "win_probability": 58.34,
  "message": "Real AI prediction & Market Odds generated successfully!"
}
```

### Install the Chrome Extension

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `Frontend/` folder
5. Navigate to any NBA market on Kalshi.com — the CourtVision card will appear automatically

---

## Features Implemented

### Data Pipeline (`scraper.py`)
- **Multi-season ingestion** — 5 seasons of team and player box scores via `nba_api`
- **Lookahead bias prevention** — all rolling averages use `.shift(1)` so no game uses its own result as a feature
- **Cross-season bleed prevention** — rolling windows group by `SEASON_STR`, resetting each October
- **Pre-game Elo ratings** — dynamic team strength updated after every game with a 100-point home court adjustment (K=20)
- **Missing Player Value** — calculates the exact PRA (Points + Rebounds + Assists) deficit when core rotation players (>12 min/game) are absent
- **Rest differential** — actual days between games for each team, not a binary back-to-back flag
- **Rolling advanced stats** — 5-game and 10-game windows for: PTS, PTS_allowed, eFG%, PLUS_MINUS, AST, REB, TOV, Pace, OFF_RTG, DEF_RTG
- **Opponent context** — opponent's rolling stats included as `_opp` columns so the model sees the matchup, not just one team's form

### Machine Learning
- **Algorithm** — `XGBClassifier` (XGBoost), optimized for tabular sports data
- **Hyperparameter tuning** — `GridSearchCV` over n_estimators, learning_rate, max_depth, subsample
- **Time-series CV** — `TimeSeriesSplit(n_splits=5)` prevents look-ahead leakage during the search; scored on `neg_log_loss` not accuracy
- **Three-way chronological split** — 70% train / 15% calibration / 15% test, strictly ordered by date
- **Isotonic calibration** — `CalibratedClassifierCV(method='isotonic')` with `PredefinedSplit` ensures a stated 63% probability historically resolves as a win ~63% of the time
- **Betting-grade evaluation** — Brier Score, Log Loss, and ECE replace accuracy as training metrics

### Backend API (`api.py`)
- **FastAPI** with CORS enabled for cross-origin requests from the Chrome Extension
- **Live injury integration** — scrapes ESPN's NBA injury report on startup and caches for 5 minutes
- **Dynamic rest calculation** — computes actual days since last game at prediction time, not from stored training data
- **Real-time PRA adjustment** — cross-references live injury report against each team's player roster to subtract missing production on the fly

### Chrome Extension (`content.js`)
- **SPA-compatible scanning** — `setInterval` polls every 3 seconds to catch React-rendered page loads
- **Dual UI modes**:
  - **Single game page** — floating card showing AI probability vs. market probability, edge %, and confidence tier
  - **Main feed page** — scrollable sidebar ranking all today's games by edge with color-coded borders (green/yellow/red)
- **Live market odds extraction** — smart DOM traverser climbs up to 8 parent levels targeting `h2.typ-headline-x10` (game pages) and `span.tabular-nums` (feed pages), filtering out decimal payout multipliers
- **Edge calculation** — `AI_probability - Market_probability` displayed as +EV% with HIGH / MEDIUM / LOW/NO EDGE labels
- **Prediction cache** — results stored in memory per matchup key so repeat renders don't re-hit the API
- **Team name resolution** — full abbreviation dictionary (30 teams) with Kalshi location-name aliases for fuzzy matching

---

## The Edge Calculation

```
Market Price:  53¢  →  53% implied probability
AI Prediction:       →  67% win probability
Edge:          67 - 53 = +14%  ✅  GREEN  (bet)

Market Price:  88¢  →  88% implied probability
AI Prediction:       →  82% win probability
Edge:          82 - 88 = -6%   🔴  RED   (skip)
```

Paying 88¢ for something the model values at 82¢ is a losing bet long-term even if the team usually wins. The extension surfaces this immediately.

---

## Roadmap

| Phase | Description | Status |
|---|---|---|
| 1 | Data pipeline & feature engineering | ✅ Complete |
| 2 | XGBoost moneyline classifier | ✅ Complete |
| 3 | FastAPI backend | ✅ Complete |
| 4 | Chrome Extension + Kalshi DOM injection | ✅ Complete |
| 5 | EV edge calculation + color badges | ✅ Complete |
| 9 | Probability calibration (isotonic) + betting-grade metrics | ✅ Complete |
| 8 | Spread & total XGBRegressor models + normal distribution mapping | Planned |
| 10 | Market-aware residual modeling + CLV tracking | Planned |
| 11 | SHAP explainability in API response + extension card | Planned |
| 12 | Calibration plot + daily slate dashboard + prediction logging | Planned |
| 5.2 | Kelly Criterion stake sizing in extension popup | Planned |
| 13 | Injury usage redistribution to secondary rotation | Planned |
| 6 | MLOps: DVC, Great Expectations, MLflow, drift monitoring | Planned |
| 7 | Docker + Google Cloud Run + Redis caching + auth + rate limiting | Planned |

---

## Key Design Decisions

**Why isotonic calibration?**
XGBoost's raw `predict_proba` outputs are systematically miscalibrated — "70%" often means 62% historically. Every downstream calculation (edge %, Kelly stake) compounds this error. Isotonic calibration fits a monotonic correction curve on a held-out chronological slice, aligning stated probabilities with observed win rates.

**Why `neg_log_loss` instead of accuracy for GridSearchCV?**
Accuracy only cares whether the model picks the right winner at 50%. A model that says 51% on every game would score high accuracy but is useless for betting. Log loss penalizes confident wrong answers and rewards well-calibrated probabilities — what actually matters for EV.

**Why Elo + rolling stats together?**
Elo captures long-run team quality (who is a 55-win team vs. a 30-win team). Rolling stats capture short-run form (who is hot or cold right now). A team with high Elo but poor recent form (key injuries, fatigue) is exactly where market inefficiencies appear. The model needs both signals.

**Why not accuracy as a success metric?**
NBA home teams win ~57% of games. A model that predicts "home team wins" for every game achieves 57% accuracy while being completely useless. The Brier Score rewards calibrated probabilities; ECE directly measures whether the stated confidence matches reality.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Data | `nba_api`, `pandas`, `sqlite3` |
| ML | `xgboost`, `scikit-learn` |
| Backend | `FastAPI`, `uvicorn`, `joblib` |
| Injury data | `requests` (ESPN scraper) |
| Frontend | Chrome Extension (Manifest V3), vanilla JavaScript |
| Storage | SQLite (`nba_data.db`), `.joblib` model artifact |
