from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from typing import Optional
import joblib
import sqlite3
import pandas as pd
import xgboost as xgb
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from scipy import stats as scipy_stats
from live_injuries import get_live_injuries
from features import PREDICTIVE_FEATURES, LIVE_FEATURES
import time

app = FastAPI()

# Enable CORS so the Chrome Extension can talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Moneyline classifier (calibrated)
model = joblib.load('nba_model_calibrated.joblib')

# Regression models — loaded once at startup, fallback gracefully if not yet trained
try:
    model_spread = joblib.load('model_spread.joblib')
    model_total  = joblib.load('model_total.joblib')
    _meta        = joblib.load('model_metadata.joblib')
    SPREAD_SIGMA = _meta['spread_sigma']
    TOTAL_SIGMA  = _meta['total_sigma']
    print(f"Spread model loaded (sigma={SPREAD_SIGMA:.2f} pts)")
    print(f"Total  model loaded (sigma={TOTAL_SIGMA:.2f} pts)")
except FileNotFoundError:
    model_spread = None
    model_total  = None
    SPREAD_SIGMA = 12.0
    TOTAL_SIGMA  = 12.0
    print("Warning: spread/total models not found — run scraper.py to generate them.")

# PREDICTIVE_FEATURES imported from features.py — the single source of truth
# shared with scraper.py so training and serving can never drift apart.

# Every /predict call is logged here so backtest.py and the future dashboard can
# join "what did the model say at the time" against real bets and outcomes.
def init_prediction_log():
    conn = sqlite3.connect('nba_data.db')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prediction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            market_type TEXT NOT NULL,
            line REAL,
            model_pick TEXT,
            model_prob_pct REAL,
            predicted_value REAL,
            market_prob_pct REAL
        )
    """)
    try:
        conn.execute("ALTER TABLE prediction_log ADD COLUMN spread_team TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    conn.close()

init_prediction_log()

def log_prediction(response: dict, market_prob=None) -> dict:
    """Insert one row per prediction. Never lets a logging failure break /predict."""
    try:
        predicted_value = response.get('predicted_margin')
        if predicted_value is None:
            predicted_value = response.get('predicted_total')
        home, away = response['matchup'].split(' @ ')[1], response['matchup'].split(' @ ')[0]
        conn = sqlite3.connect('nba_data.db')
        conn.execute(
            "INSERT INTO prediction_log (ts, home_team, away_team, market_type, line, model_pick, model_prob_pct, predicted_value, market_prob_pct, spread_team) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec='seconds'),
                home,
                away,
                response.get('market_type'),
                response.get('line'),
                response.get('predicted_winner') or response.get('recommendation'),
                response.get('win_probability'),
                predicted_value,
                market_prob,
                response.get('spread_team'),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ prediction_log write failed: {e}")
    return response

def get_shap_contributions(booster, input_df, top_n=3):
    dmat = xgb.DMatrix(input_df, feature_names=list(input_df.columns))
    contribs = booster.predict(dmat, pred_contribs=True)
    shap_vals = contribs[0][:-1]  # drop bias term
    pairs = sorted(zip(input_df.columns, shap_vals), key=lambda x: abs(x[1]), reverse=True)
    return [{"feature": f, "impact": round(float(v), 4)} for f, v in pairs[:top_n]]

# Global cache so we don't spam ESPN on multi-game pages
last_scrape_time = 0
cached_injuries_df = None

def get_latest_team_stats(team_abbrev: str):
    """Queries the SQLite DB for the team's most recent game/stats."""
    conn = sqlite3.connect('nba_data.db')
    # Grab the absolute most recent row of data for this specific team
    query = "SELECT * FROM team_stats WHERE TEAM_ABBREVIATION = ? ORDER BY GAME_DATE DESC LIMIT 1"
    df = pd.read_sql(query, conn, params=(team_abbrev,))
    conn.close()
    
    if df.empty:
        raise ValueError(f"Team {team_abbrev} not found in database.")
    return df

@app.get("/")
def read_root():
    return {"status": "CourtVision API is running live!"}

def resolve_prediction(row, games):
    """Match a logged prediction to its game's final score and grade the pick.
    Returns (result_str, correct_bool_or_None). Games are matched on the home
    team + the calendar date the prediction was made (predictions are pre-game,
    same-day)."""
    g = games[(games['TEAM_ABBREVIATION'] == row['home_team']) & (games['gdate'] == row['ts'][:10])]
    if g.empty:
        return "pending", None
    g = g.iloc[0]
    home_won = g['WL'] == 'W'
    margin = g['PTS'] - g['PTS_allowed']
    total = g['PTS'] + g['PTS_allowed']

    if row['market_type'] == 'moneyline':
        correct = (row['model_pick'] == row['home_team']) == home_won
        return f"{'W' if home_won else 'L'} (home {int(margin):+d})", correct
    if row['market_type'] == 'spread' and row['line'] is not None:
        covering_margin = margin if row['spread_team'] == row['home_team'] else -margin
        covered = covering_margin > row['line']
        correct = (row['model_pick'] == 'YES') == covered
        return f"{'covered' if covered else 'missed'} ({covering_margin:+.0f} vs {row['line']})", correct
    if row['market_type'] == 'total' and row['line'] is not None:
        over = total > row['line']
        correct = (row['model_pick'] == 'YES') == over
        return f"{'over' if over else 'under'} ({total:.0f} vs {row['line']})", correct
    return "pending", None

@app.get("/dashboard")
def dashboard():
    conn = sqlite3.connect('nba_data.db')
    log = pd.read_sql("SELECT * FROM prediction_log ORDER BY ts DESC", conn)
    games = pd.read_sql("SELECT GAME_DATE, TEAM_ABBREVIATION, WL, PTS, PTS_allowed FROM team_stats WHERE is_home = 1", conn)
    conn.close()
    games['gdate'] = games['GAME_DATE'].astype(str).str[:10]

    # One row per market: keep only the most recent prediction for each
    # game+market (the extension re-polls the same matchup many times).
    log = log.drop_duplicates(subset=['home_team', 'away_team', 'market_type', 'line'], keep='first')

    results = [resolve_prediction(row, games) for _, row in log.iterrows()]
    log = log.assign(result=[r[0] for r in results], correct=[r[1] for r in results])
    resolved = log[log['correct'].notna()]

    n_correct = int(resolved['correct'].sum()) if not resolved.empty else 0
    hit = f"{n_correct}/{len(resolved)} ({n_correct/len(resolved):.0%})" if not resolved.empty else "—"
    with_mkt = log[log['market_prob_pct'].notna()]
    avg_edge = f"{(with_mkt['model_prob_pct'] - with_mkt['market_prob_pct']).mean():+.1f}%" if not with_mkt.empty else "—"

    def stat_card(label, value):
        return (f"<div style='background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px 20px;'>"
                f"<div style='font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;'>{label}</div>"
                f"<div style='font-size:22px;font-weight:700;color:#38bdf8;margin-top:4px;'>{value}</div></div>")

    def fmt_row(r):
        line_txt = "" if pd.isna(r['line']) else f" {r['line']}"
        mkt = "—" if pd.isna(r['market_prob_pct']) else f"{r['market_prob_pct']:.0f}%"
        if r['correct'] is None or pd.isna(r['correct']):
            mark, color = "·", "#94a3b8"
        elif r['correct']:
            mark, color = "✓", "#10b981"
        else:
            mark, color = "✗", "#ef4444"
        return (f"<tr><td style='padding:6px;'>{r['ts'][:16].replace('T', ' ')}</td>"
                f"<td>{r['away_team']} @ {r['home_team']}</td>"
                f"<td>{r['market_type']}{line_txt}</td>"
                f"<td>{r['model_pick']}</td><td>{r['model_prob_pct']:.1f}%</td>"
                f"<td>{mkt}</td><td>{r['result']}</td>"
                f"<td style='color:{color};font-weight:700;'>{mark}</td></tr>")

    rows_html = "".join(fmt_row(r) for _, r in log.head(50).iterrows())

    html = f"""<!doctype html><html><head><title>CourtVision Dashboard</title></head>
    <body style="background:#0f172a;color:#f8fafc;font-family:system-ui,sans-serif;margin:0;padding:32px;">
      <h1 style="color:#38bdf8;font-size:20px;text-transform:uppercase;letter-spacing:1px;">🏀 CourtVision — Prediction Monitor</h1>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin:20px 0;">
        {stat_card('Predictions logged', len(log))}
        {stat_card('Resolved', len(resolved))}
        {stat_card('Pick hit rate', hit)}
        {stat_card('Avg edge at prediction', avg_edge)}
      </div>
      <table style="border-collapse:collapse;width:100%;font-size:13px;">
        <tr style="color:#94a3b8;text-align:left;">
          <th style="padding:6px;">Time</th><th>Matchup</th><th>Market</th><th>Pick</th>
          <th>Model %</th><th>Market %</th><th>Result</th><th></th></tr>
        {rows_html or '<tr><td colspan="8" style="padding:20px;color:#94a3b8;">No predictions logged yet — browse Kalshi with the extension loaded.</td></tr>'}
      </table>
    </body></html>"""
    return HTMLResponse(html)

@app.get("/predict")
def predict_game(
    home_team: str,
    away_team: str,
    market_type: str = "moneyline",
    line: Optional[float] = None,
    spread_team: Optional[str] = None,
    market_prob: Optional[float] = None,  # market's implied % at prediction time, logged if provided
):
    global last_scrape_time, cached_injuries_df
    try:
        # 1. Fetch the latest stats for BOTH teams from our database
        home_df = get_latest_team_stats(home_team.upper())
        away_df = get_latest_team_stats(away_team.upper())
        
        # --- LIVE INJURY CALCULATION ---
        current_time = time.time()
        # Only hit ESPN if we haven't checked in the last 5 minutes (300 seconds)
        if cached_injuries_df is None or (current_time - last_scrape_time) > 300:
            print("\nFetching live injuries from ESPN...")
            cached_injuries_df = get_live_injuries()
            last_scrape_time = current_time
        else:
            print("\nUsing cached ESPN injury data...")
        
        # Safely check for both STATUS and PLAYER_NAME to avoid KeyErrors if ESPN changes layout
        out_players = []
        if cached_injuries_df is not None and not cached_injuries_df.empty:
            if 'STATUS' in cached_injuries_df.columns and 'PLAYER_NAME' in cached_injuries_df.columns:
                out_players = cached_injuries_df[cached_injuries_df['STATUS'] == 'Out']['PLAYER_NAME'].tolist()
            else:
                print("⚠️ Warning: ESPN injury format changed. Missing 'STATUS' or 'PLAYER_NAME'.")
        
        def get_missing_pra(team_abbrev):
            """Returns (missing_pra, missing_usage_pct) for the team's core rotation.
            Core rotation = players averaging >12 min, matching how training data
            defines MISSING_PLAYER_VALUE / MISSING_USAGE_PCT in scraper.py."""
            try:
                conn = sqlite3.connect('nba_data.db')
                query = "SELECT PLAYER_NAME, ROLLING_PRA, ROLLING_MIN FROM player_stats WHERE TEAM_ABBREVIATION = ?"
                team_players = pd.read_sql(query, conn, params=(team_abbrev,))
                conn.close()

                core = team_players[team_players['ROLLING_MIN'] > 12]
                total_pra = core['ROLLING_PRA'].sum()
                missing = core[core['PLAYER_NAME'].isin(out_players)]
                for _, player in missing.iterrows():
                    print(f"  🚨 [Live Injury] {player['PLAYER_NAME']} is OUT for {team_abbrev}. Losing {round(player['ROLLING_PRA'], 1)} PRA.")
                missing_pra = missing['ROLLING_PRA'].sum()
                usage_pct = missing_pra / total_pra if total_pra > 0 else 0.0
                return float(missing_pra), float(usage_pct)
            except Exception as e:
                print(f"⚠️ Warning: Could not fetch player stats for {team_abbrev}. Did you re-run scraper.py? Error: {e}")
                return 0.0, 0.0

        live_home_missing, live_home_usage = get_missing_pra(home_team.upper())
        live_away_missing, live_away_usage = get_missing_pra(away_team.upper())
        
        # 2. Build the feature row for the model (from the Home team's perspective)
        input_data = pd.DataFrame(columns=PREDICTIVE_FEATURES)
        
        # Calculate real days of rest instead of hardcoding
        home_last_game = pd.to_datetime(home_df['GAME_DATE'].values[0])
        away_last_game = pd.to_datetime(away_df['GAME_DATE'].values[0])
        today = pd.to_datetime(datetime.today().strftime('%Y-%m-%d'))
        
        home_rest = (today - home_last_game).days
        away_rest = (today - away_last_game).days
        
        # Set the live-computed features
        input_data.loc[0, 'is_home'] = 1
        input_data.loc[0, 'days_rest'] = home_rest
        input_data.loc[0, 'rest_differential'] = home_rest - away_rest
        input_data.loc[0, 'MISSING_PLAYER_VALUE'] = live_home_missing
        input_data.loc[0, 'MISSING_PLAYER_VALUE_opp'] = live_away_missing
        input_data.loc[0, 'MISSING_USAGE_PCT'] = live_home_usage
        input_data.loc[0, 'MISSING_USAGE_PCT_opp'] = live_away_usage
        input_data.loc[0, 'ELO'] = home_df['ELO'].values[0]
        input_data.loc[0, 'ELO_opp'] = away_df['ELO'].values[0]

        # Everything else comes straight off the teams' latest DB rows —
        # plain columns from the HOME row, '*_opp' columns from the AWAY row.
        for col in PREDICTIVE_FEATURES:
            if col in LIVE_FEATURES:
                continue
            source_df, source_col = (away_df, col[:-4]) if col.endswith('_opp') else (home_df, col)
            input_data.loc[0, col] = source_df[source_col].values[0]
            
        # Convert all columns to strictly numeric so XGBoost doesn't crash
        input_data = input_data.astype(float)

        matchup = f"{away_team.upper()} @ {home_team.upper()}"

        # ── SPREAD ───────────────────────────────────────────────────────────
        if market_type == "spread":
            if model_spread is None:
                raise HTTPException(status_code=503, detail="Spread model not loaded. Run scraper.py first.")
            if line is None:
                raise HTTPException(status_code=400, detail="'line' parameter required for spread market.")

            predicted_margin = float(model_spread.predict(input_data)[0])

            # Determine covering direction.
            # spread_team is the team Kalshi says must win by > line.
            # Model always predicts home_margin (home_pts - away_pts).
            covering = (spread_team or home_team).upper()
            if covering == home_team.upper():
                # P(home_margin > line)
                cover_prob = float(1 - scipy_stats.norm.cdf(line, loc=predicted_margin, scale=SPREAD_SIGMA))
            else:
                # P(away_margin > line)  =  P(home_margin < -line)
                cover_prob = float(scipy_stats.norm.cdf(-line, loc=predicted_margin, scale=SPREAD_SIGMA))

            return log_prediction({
                "matchup": matchup,
                "market_type": "spread",
                "line": line,
                "spread_team": covering,
                "predicted_margin": round(predicted_margin, 1),
                "win_probability": round(cover_prob * 100, 2),
                "recommendation": "YES" if cover_prob >= 0.5 else "NO",
                "message": f"Spread: {covering} covers {line:+.1f} pts with {cover_prob*100:.1f}% probability",
                "feature_contributions": get_shap_contributions(model_spread.get_booster(), input_data),
            }, market_prob)

        # ── TOTAL ─────────────────────────────────────────────────────────────
        if market_type == "total":
            if model_total is None:
                raise HTTPException(status_code=503, detail="Total model not loaded. Run scraper.py first.")
            if line is None:
                raise HTTPException(status_code=400, detail="'line' parameter required for total market.")

            predicted_total = float(model_total.predict(input_data)[0])
            # P(actual_total > line)
            over_prob = float(1 - scipy_stats.norm.cdf(line, loc=predicted_total, scale=TOTAL_SIGMA))

            return log_prediction({
                "matchup": matchup,
                "market_type": "total",
                "line": line,
                "predicted_total": round(predicted_total, 1),
                "win_probability": round(over_prob * 100, 2),
                "recommendation": "YES" if over_prob >= 0.5 else "NO",
                "message": f"Total: projected {predicted_total:.1f} pts vs line {line} ({over_prob*100:.1f}% over)",
                "feature_contributions": get_shap_contributions(model_total.get_booster(), input_data),
            }, market_prob)

        # ── MONEYLINE (default) ───────────────────────────────────────────────
        prediction    = int(model.predict(input_data)[0])
        probabilities = model.predict_proba(input_data)[0]

        predicted_winner = home_team.upper() if prediction == 1 else away_team.upper()
        confidence = float(probabilities[1]) if prediction == 1 else float(probabilities[0])

        xgb_model = model.calibrated_classifiers_[0].estimator
        return log_prediction({
            "matchup": matchup,
            "market_type": "moneyline",
            "predicted_winner": predicted_winner,
            "win_probability": round(confidence * 100, 2),
            "feature_contributions": get_shap_contributions(xgb_model.get_booster(), input_data),
            "message": "Real AI prediction & Market Odds generated successfully!",
        }, market_prob)
        
    except Exception as e:
        # Print the exact error to the terminal so we can see what broke
        print(f"API CRASHED: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))