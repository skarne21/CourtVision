from fastapi import FastAPI, HTTPException
import joblib
import sqlite3
import pandas as pd
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS so the Chrome Extension can talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows requests from any website (like Kalshi)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the model once when the server starts
model = joblib.load('nba_model.joblib')

# These are the exact features our model was trained on in scraper.py
PREDICTIVE_FEATURES = [
    'is_home', 'days_rest', 'rest_differential', 'MISSING_PLAYER_VALUE', 'MISSING_PLAYER_VALUE_opp',
    'ELO', 'ELO_opp',
    'PTS_roll_5', 'PTS_allowed_roll_5', 'eFG_roll_5', 'PLUS_MINUS_roll_5', 'AST_roll_5', 'REB_roll_5', 'TOV_roll_5',
    'PTS_roll_10', 'PTS_allowed_roll_10', 'eFG_roll_10', 'PLUS_MINUS_roll_10', 'AST_roll_10', 'REB_roll_10', 'TOV_roll_10'
]

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
def predict_game(home_team: str, away_team: str):
    try:
        # 1. Fetch the latest stats for BOTH teams from our database
        home_df = get_latest_team_stats(home_team.upper())
        away_df = get_latest_team_stats(away_team.upper())
        
        # 2. Build the feature row for the model (from the Home team's perspective)
        input_data = pd.DataFrame(columns=PREDICTIVE_FEATURES)
        
        # Set contextual features (Using baseline averages for V1)
        input_data.loc[0, 'is_home'] = 1 
        input_data.loc[0, 'days_rest'] = 2 
        input_data.loc[0, 'rest_differential'] = 0 
        input_data.loc[0, 'MISSING_PLAYER_VALUE'] = home_df['MISSING_PLAYER_VALUE'].values[0]
        input_data.loc[0, 'MISSING_PLAYER_VALUE_opp'] = away_df['MISSING_PLAYER_VALUE'].values[0]
        input_data.loc[0, 'ELO'] = home_df['ELO'].values[0]
        input_data.loc[0, 'ELO_opp'] = away_df['ELO'].values[0]
        
        # Map the 5-game and 10-game rolling stats from the database into our input data
        for col in PREDICTIVE_FEATURES[7:]:
            input_data.loc[0, col] = home_df[col].values[0]
            
        # CRITICAL FIX: Convert all columns to strictly numeric so XGBoost doesn't crash
        input_data = input_data.astype(float)
            
        # 3. Make the prediction!
        # predict() returns 1 (Win) or 0 (Loss)
        # predict_proba() returns probabilities for [prob_loss, prob_win]
        prediction = int(model.predict(input_data)[0])
        probabilities = model.predict_proba(input_data)[0]
        
        # If prediction is 1, home team wins. If 0, away team wins.
        predicted_winner = home_team.upper() if prediction == 1 else away_team.upper()
        confidence = float(probabilities[1]) if prediction == 1 else float(probabilities[0])
        
        return {
            "matchup": f"{away_team.upper()} @ {home_team.upper()}",
            "predicted_winner": predicted_winner, 
            "win_probability": round(confidence * 100, 2), # Convert decimal to percentage
            "message": "Real AI prediction generated successfully!"
        }
        
    except Exception as e:
        # Print the exact error to the terminal so we can see what broke
        print(f"API CRASHED: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))