from fastapi import FastAPI, HTTPException
from typing import Optional
import joblib
import sqlite3
import pandas as pd
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from scipy import stats as scipy_stats
from live_injuries import get_live_injuries
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

# These are the exact features our model was trained on in scraper.py
PREDICTIVE_FEATURES = [
    'is_home', 'days_rest', 'rest_differential', 'MISSING_PLAYER_VALUE', 'MISSING_PLAYER_VALUE_opp',
    'ELO', 'ELO_opp',
    'PTS_roll_5', 'PTS_allowed_roll_5', 'eFG_roll_5', 'PLUS_MINUS_roll_5', 'AST_roll_5', 'REB_roll_5', 'TOV_roll_5',
    'PTS_roll_10', 'PTS_allowed_roll_10', 'eFG_roll_10', 'PLUS_MINUS_roll_10', 'AST_roll_10', 'REB_roll_10', 'TOV_roll_10'
]

# Global cache so we don't spam ESPN on multi-game pages
last_scrape_time = 0
cached_injuries_df = None

def get_latest_team_stats(team_abbrev: str):
    """Queries the SQLite DB for the team's most recent game/stats."""
    conn = sqlite3.connect('nba_data.db')
    # Grab the absolute most recent row of data for this specific team
    query = f"SELECT * FROM team_stats WHERE TEAM_ABBREVIATION = '{team_abbrev}' ORDER BY GAME_DATE DESC LIMIT 1"
    df = pd.read_sql(query, conn)
    conn.close()
    
    if df.empty:
        raise ValueError(f"Team {team_abbrev} not found in database.")
    return df

@app.get("/")
def read_root():
    return {"status": "CourtVision API is running live!"}

@app.get("/predict")
def predict_game(
    home_team: str,
    away_team: str,
    market_type: str = "moneyline",
    line: Optional[float] = None,
    spread_team: Optional[str] = None,
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
            try:
                conn = sqlite3.connect('nba_data.db')
                query = f"SELECT PLAYER_NAME, ROLLING_PRA FROM player_stats WHERE TEAM_ABBREVIATION = '{team_abbrev}'"
                team_players = pd.read_sql(query, conn)
                conn.close()
                
                missing_pra = 0
                for _, player in team_players.iterrows():
                    if player['PLAYER_NAME'] in out_players:
                        print(f"  🚨 [Live Injury] {player['PLAYER_NAME']} is OUT for {team_abbrev}. Losing {round(player['ROLLING_PRA'], 1)} PRA.")
                        missing_pra += player['ROLLING_PRA']
                return missing_pra
            except Exception as e:
                print(f"⚠️ Warning: Could not fetch player stats for {team_abbrev}. Did you re-run scraper.py? Error: {e}")
                return 0
            
        live_home_missing = get_missing_pra(home_team.upper())
        live_away_missing = get_missing_pra(away_team.upper())
        
        # 2. Build the feature row for the model (from the Home team's perspective)
        input_data = pd.DataFrame(columns=PREDICTIVE_FEATURES)
        
        # Calculate real days of rest instead of hardcoding
        home_last_game = pd.to_datetime(home_df['GAME_DATE'].values[0])
        away_last_game = pd.to_datetime(away_df['GAME_DATE'].values[0])
        today = pd.to_datetime(datetime.today().strftime('%Y-%m-%d'))
        
        home_rest = (today - home_last_game).days
        away_rest = (today - away_last_game).days
        
        # Set contextual features
        input_data.loc[0, 'is_home'] = 1 
        input_data.loc[0, 'days_rest'] = home_rest 
        input_data.loc[0, 'rest_differential'] = home_rest - away_rest 
        input_data.loc[0, 'MISSING_PLAYER_VALUE'] = live_home_missing
        input_data.loc[0, 'MISSING_PLAYER_VALUE_opp'] = live_away_missing
        input_data.loc[0, 'ELO'] = home_df['ELO'].values[0]
        input_data.loc[0, 'ELO_opp'] = away_df['ELO'].values[0]
        
        # Map the 5-game and 10-game rolling stats from the database into our input data
        for col in PREDICTIVE_FEATURES[7:]:
            input_data.loc[0, col] = home_df[col].values[0]
            
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

            return {
                "matchup": matchup,
                "market_type": "spread",
                "line": line,
                "spread_team": covering,
                "predicted_margin": round(predicted_margin, 1),
                "win_probability": round(cover_prob * 100, 2),
                "recommendation": "YES" if cover_prob >= 0.5 else "NO",
                "message": f"Spread: {covering} covers {line:+.1f} pts with {cover_prob*100:.1f}% probability",
            }

        # ── TOTAL ─────────────────────────────────────────────────────────────
        if market_type == "total":
            if model_total is None:
                raise HTTPException(status_code=503, detail="Total model not loaded. Run scraper.py first.")
            if line is None:
                raise HTTPException(status_code=400, detail="'line' parameter required for total market.")

            predicted_total = float(model_total.predict(input_data)[0])
            # P(actual_total > line)
            over_prob = float(1 - scipy_stats.norm.cdf(line, loc=predicted_total, scale=TOTAL_SIGMA))

            return {
                "matchup": matchup,
                "market_type": "total",
                "line": line,
                "predicted_total": round(predicted_total, 1),
                "win_probability": round(over_prob * 100, 2),
                "recommendation": "YES" if over_prob >= 0.5 else "NO",
                "message": f"Total: projected {predicted_total:.1f} pts vs line {line} ({over_prob*100:.1f}% over)",
            }

        # ── MONEYLINE (default) ───────────────────────────────────────────────
        prediction    = int(model.predict(input_data)[0])
        probabilities = model.predict_proba(input_data)[0]

        predicted_winner = home_team.upper() if prediction == 1 else away_team.upper()
        confidence = float(probabilities[1]) if prediction == 1 else float(probabilities[0])

        return {
            "matchup": matchup,
            "market_type": "moneyline",
            "predicted_winner": predicted_winner,
            "win_probability": round(confidence * 100, 2),
            "message": "Real AI prediction & Market Odds generated successfully!",
        }
        
    except Exception as e:
        # Print the exact error to the terminal so we can see what broke
        print(f"API CRASHED: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))