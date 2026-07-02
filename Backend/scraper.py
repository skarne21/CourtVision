import pandas as pd
from nba_api.stats.endpoints import leaguegamelog
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit, PredefinedSplit
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from xgboost import XGBClassifier, XGBRegressor
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
import numpy as np
import joblib
import sqlite3
import time # ADD THIS to the top of your imports
import sys
sys.stdout.reconfigure(encoding='utf-8')  # Windows cp1252 console chokes on → / emoji in prints


def fetch_multiple_seasons(seasons=["2021-22", "2022-23", "2023-24"]):
    """
    Loops through multiple years to build a massive historical dataset.
    """
    all_seasons_data = []
    
    for season in seasons:
        print(f"Fetching data for the {season} Regular Season...")
        try:
            game_log = leaguegamelog.LeagueGameLog(
                season=season, 
                season_type_all_star="Regular Season"
            )
            df = game_log.get_data_frames()[0]
            
            # Tag the data with the season string so we can group it later
            df['SEASON_STR'] = season 
            all_seasons_data.append(df)
            
            # Sleep for 1 second so the NBA API doesn't block us for spamming
            time.sleep(1) 
            
        except Exception as e:
            print(f"An error occurred while fetching {season}: {e}")
            
    # Combine all the individual season dataframes into one giant dataframe
    return pd.concat(all_seasons_data, ignore_index=True)

def fetch_multiple_seasons_players(seasons=["2021-22", "2022-23", "2023-24"]):
    """
    Loops through multiple years to build a massive historical dataset for PLAYERS.
    """
    all_seasons_data = []
    
    for season in seasons:
        print(f"Fetching PLAYER data for the {season} Regular Season...")
        try:
            game_log = leaguegamelog.LeagueGameLog(
                season=season, 
                season_type_all_star="Regular Season",
                player_or_team_abbreviation='P'
            )
            df = game_log.get_data_frames()[0]
            
            # Tag the data with the season string so we can group it later
            df['SEASON_STR'] = season 
            all_seasons_data.append(df)
            
            # Sleep for 1 second so the NBA API doesn't block us for spamming
            time.sleep(1) 
            
        except Exception as e:
            print(f"An error occurred while fetching {season}: {e}")
            
    # Combine all the individual season dataframes into one giant dataframe
    return pd.concat(all_seasons_data, ignore_index=True)

def engineer_missing_player_value(df_players, team_game_logs):
    print("\nCalculating MISSING_PLAYER_VALUE...")
    df_players = df_players.copy()
    df_players['GAME_DATE'] = pd.to_datetime(df_players['GAME_DATE'])
    df_players = df_players.sort_values(by=['GAME_DATE'])
    
    # Calculate base PRA
    df_players['PRA'] = df_players['PTS'] + df_players['REB'] + df_players['AST']
    
    # Safely convert MIN to numeric (some endpoints return "MM:SS" strings)
    df_players['MIN'] = pd.to_numeric(df_players['MIN'].astype(str).str.split(':').str[0], errors='coerce').fillna(0)
    
    # 1. Calculate Rolling 10-Game Averages for Every Player
    # Include SEASON_STR in groupby to prevent cross-season leakage
    df_players['ROLLING_PRA'] = df_players.groupby(['SEASON_STR', 'PLAYER_ID'])['PRA'].transform(
        lambda x: x.shift(1).rolling(window=10, min_periods=1).mean()
    )
    df_players['ROLLING_MIN'] = df_players.groupby(['SEASON_STR', 'PLAYER_ID'])['MIN'].transform(
        lambda x: x.shift(1).rolling(window=10, min_periods=1).mean()
    )
    
    # 2. Define the "Core Rotation" for a team going into a game (>12 mins)
    core_rotation = df_players[df_players['ROLLING_MIN'] > 12].copy()
    
    # 3. Create a master list of all expected players for every team, every game
    game_team_missing_value = []
    
    # Group by season and team to iterate through their schedule chronologically
    seasons = core_rotation['SEASON_STR'].unique()
    
    for season in seasons:
        season_data = core_rotation[core_rotation['SEASON_STR'] == season]
        teams = season_data['TEAM_ID'].unique()
        
        for team in teams:
            team_data = season_data[season_data['TEAM_ID'] == team].sort_values('GAME_DATE')
            games = team_data['GAME_ID'].unique()
            
            # Keep a running list of recent active players for the team
            recent_roster = {} 
            
            for game in games:
                current_game_data = team_data[team_data['GAME_ID'] == game]
                players_who_played = current_game_data['PLAYER_ID'].tolist()
                
                missing_pra_total = 0
                
                for player_id, expected_pra in recent_roster.items():
                    if player_id not in players_who_played:
                        missing_pra_total += expected_pra
                
                game_team_missing_value.append({
                    'GAME_ID': game,
                    'TEAM_ID': team,
                    'MISSING_PLAYER_VALUE': missing_pra_total
                })
                
                recent_roster = dict(zip(current_game_data['PLAYER_ID'], current_game_data['ROLLING_PRA']))

    # 4. Convert to DataFrame and merge with your existing Team Game Logs
    df_missing = pd.DataFrame(game_team_missing_value)
    
    team_game_logs = pd.merge(team_game_logs, df_missing, on=['GAME_ID', 'TEAM_ID'], how='left')
    team_game_logs['MISSING_PLAYER_VALUE'] = team_game_logs['MISSING_PLAYER_VALUE'].fillna(0)
    
    return team_game_logs, df_players

def engineer_elo(df):
    print("\nCalculating Pre-Game Elo Ratings...")
    df = df.copy()
    
    # Extract unique games chronologically
    games = df[['GAME_DATE', 'GAME_ID', 'TEAM_ID', 'WL', 'MATCHUP']].drop_duplicates()
    games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE'])
    games = games.sort_values(by=['GAME_DATE', 'GAME_ID'])
    
    # Isolate home and away teams
    home_teams = games[games['MATCHUP'].str.contains('vs.')].copy()
    away_teams = games[games['MATCHUP'].str.contains('@')].copy()
    
    matchups = pd.merge(home_teams, away_teams, on='GAME_ID', suffixes=('_home', '_away'))
    matchups = matchups.sort_values(by='GAME_DATE_home')
    
    elo_dict = {}
    home_elos, away_elos = [], []
    
    for idx, row in matchups.iterrows():
        home_id, away_id = row['TEAM_ID_home'], row['TEAM_ID_away']
        
        # Initialize teams at 1500 Elo
        if home_id not in elo_dict: elo_dict[home_id] = 1500
        if away_id not in elo_dict: elo_dict[away_id] = 1500
        
        home_elos.append(elo_dict[home_id])
        away_elos.append(elo_dict[away_id])
        
        # Calculate updated Elos using K=20 and a 100-point Home Court Advantage adjustment
        home_win = 1 if row['WL_home'] == 'W' else 0
        away_win = 1 if row['WL_away'] == 'W' else 0
        
        exp_home = 1 / (1 + 10**((elo_dict[away_id] - (elo_dict[home_id] + 100)) / 400))
        exp_away = 1 / (1 + 10**(((elo_dict[home_id] + 100) - elo_dict[away_id]) / 400))
        
        elo_dict[home_id] += 20 * (home_win - exp_home)
        elo_dict[away_id] += 20 * (away_win - exp_away)
        
    matchups['ELO_home'], matchups['ELO_away'] = home_elos, away_elos
    home_melt = matchups[['GAME_ID', 'TEAM_ID_home', 'ELO_home']].rename(columns={'TEAM_ID_home': 'TEAM_ID', 'ELO_home': 'ELO'})
    away_melt = matchups[['GAME_ID', 'TEAM_ID_away', 'ELO_away']].rename(columns={'TEAM_ID_away': 'TEAM_ID', 'ELO_away': 'ELO'})
    
    return pd.merge(df, pd.concat([home_melt, away_melt]), on=['GAME_ID', 'TEAM_ID'], how='left').fillna({'ELO': 1500})

def engineer_features(df):
    """
    Cleans data and creates predictive features like rolling averages and rest context.
    This function implements the full data transformation pipeline.
    """
    print("\nStarting feature engineering pipeline...")
        
    # Make a copy to avoid modifying the original DataFrame passed to the function
    df = df.copy()

    # --- Task 1: Basic Formatting & Sorting ---
    df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
    # Sort by game date, then by game ID, to handle days with multiple games consistently.
    df = df.sort_values(by=['GAME_DATE', 'GAME_ID']).reset_index(drop=True)

    # --- Task 2: Engineer the "Home/Away" Feature ---
    df['is_home'] = df['MATCHUP'].str.contains('vs.').astype(int)

    # --- Task 3: Calculate Opponent Stats & Rest ---
    # To calculate differentials (like rest) and opponent stats (like points allowed),
    # we need to merge the dataframe with itself on GAME_ID.
    
    # First, calculate days_rest for each team individually
    df = df.sort_values(by=['TEAM_ID', 'GAME_DATE']) # Sort for per-team calculations
    df['days_rest'] = df.groupby('TEAM_ID')['GAME_DATE'].diff().dt.days
    df['days_rest'] = df['days_rest'].fillna(8) # Assume 8 days rest for the first game of the season

    # Prepare a slim version of the dataframe for merging opponent stats
    opponent_stats = df[['GAME_ID', 'TEAM_ID', 'days_rest', 'PTS', 'MISSING_PLAYER_VALUE', 'ELO']].copy()
    
    # Merge to get opponent data on the same row
    df = pd.merge(df, opponent_stats, on='GAME_ID', suffixes=('', '_opp'))
    
    # Filter out rows where a team is matched with itself
    df = df[df['TEAM_ID'] != df['TEAM_ID_opp']]
    
    # Now, create the differential and opponent-based features
    df['rest_differential'] = df['days_rest'] - df['days_rest_opp']
    df.rename(columns={'PTS_opp': 'PTS_allowed'}, inplace=True)
    
    # Clean up merge helper columns
    df = df.drop(columns=['TEAM_ID_opp', 'days_rest_opp'])

    # --- Task 4 & 5: Compute Rolling Averages (with Lookahead Bias Prevention) ---
    # Re-sort to ensure calculations are chronological per team
    df = df.sort_values(by=['TEAM_ID', 'GAME_DATE']).reset_index(drop=True)

    # Calculate Effective Field Goal Percentage
    df['eFG'] = (df['FGM'] + 0.5 * df['FG3M']) / df['FGA']
    df['eFG'] = df['eFG'].fillna(0) # Handle cases with 0 field goal attempts

    # Define the stats we want to create rolling averages for
    stats_to_roll = ['PTS', 'PTS_allowed', 'eFG', 'PLUS_MINUS', 'AST', 'REB', 'TOV']
    
    # This combined operation is crucial:
    # 1. It groups by team.
    # 2. It calculates the rolling average over a window.
    # 3. It SHIFTS the result by 1. This means the data for today's game is the
    #    rolling average from the N games ending in YESTERDAY's game. This
    #    is the correct way to prevent lookahead bias.
    # Update the groupby to include SEASON_STR so rolling stats reset every October
    for window in [5, 10]:
        for stat in stats_to_roll:
            col_name = f'{stat}_roll_{window}'
            df[col_name] = df.groupby(['SEASON_STR', 'TEAM_ID'])[stat].transform(
                lambda x: x.rolling(window=window, min_periods=1).mean().shift(1)
            )

    # --- Task 6 & Final Cleanup ---
    # Drop the original matchup string and any rows with NaN from the rolling calcs
    df = df.drop(columns=['MATCHUP'])
    df = df.dropna()
    
    print("Feature engineering complete.")
    return df

if __name__ == "__main__":
    # 1. Fetch historical data including the actual current 2025-26 season
    seasons_to_pull = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    nba_df = fetch_multiple_seasons(seasons_to_pull)
    players_df = fetch_multiple_seasons_players(seasons_to_pull)
    
    if not nba_df.empty:
        # Run the entire feature engineering pipeline
        # First, calculate missing player value and merge it to the raw team logs
        nba_df, processed_players_df = engineer_missing_player_value(players_df, nba_df)
        nba_df = engineer_elo(nba_df)
        featured_df = engineer_features(nba_df)
        
        print("\n--- Feature Engineering Complete ---")
        print(f"Original rows: {len(nba_df)}, Final rows for modeling: {len(featured_df)}")

        # --- Step 1: Define Your Target Variable (The Label) ---
        # Use the 'WL' column as the ground truth: 1 if the team won, 0 if they lost.
        featured_df['target_win'] = (featured_df['WL'] == 'W').astype(int)

        # --- Step 2: Isolate the Features ---
        # These are the pre-game stats the model will use to make a prediction.
        # We exclude post-game stats like 'PTS' or identifying info like 'GAME_DATE'.
        predictive_features = [
            'is_home', 'days_rest', 'rest_differential', 'MISSING_PLAYER_VALUE', 'MISSING_PLAYER_VALUE_opp',
            'ELO', 'ELO_opp',
            'PTS_roll_5', 'PTS_allowed_roll_5', 'eFG_roll_5', 'PLUS_MINUS_roll_5', 'AST_roll_5', 'REB_roll_5', 'TOV_roll_5',
            'PTS_roll_10', 'PTS_allowed_roll_10', 'eFG_roll_10', 'PLUS_MINUS_roll_10', 'AST_roll_10', 'REB_roll_10', 'TOV_roll_10'
        ]

        X = featured_df[predictive_features] # The data the model learns from
        y = featured_df['target_win']        # The answer key (did the team win?)

        # --- Step 3: Three-Way Chronological Split (70 / 15 / 15) ---
        # 70% train -> GridSearchCV, 15% calibration -> isotonic fit, 15% test -> final eval.
        # Strictly chronological -- no shuffle -- to prevent look-ahead leakage.
        n = len(X)
        train_end = int(n * 0.70)
        cal_end   = int(n * 0.85)

        X_train, y_train = X.iloc[:train_end],        y.iloc[:train_end]
        X_cal,   y_cal   = X.iloc[train_end:cal_end], y.iloc[train_end:cal_end]
        X_test,  y_test  = X.iloc[cal_end:],          y.iloc[cal_end:]

        print(f"\nSplit: {len(X_train)} train / {len(X_cal)} calibration / {len(X_test)} test games.")

        # --- Step 4: Train XGBoost with TimeSeriesSplit + neg_log_loss ---
        print("\nFinding the best hyperparameters for XGBoost...")
        param_grid = {
            'n_estimators': [100, 200, 300],
            'learning_rate': [0.01, 0.05, 0.1],
            'max_depth': [3, 4, 5],
            'subsample': [0.8, 1.0]
        }

        tscv = TimeSeriesSplit(n_splits=5)
        xgb = XGBClassifier(random_state=42, eval_metric='logloss')
        grid_search = GridSearchCV(estimator=xgb, param_grid=param_grid, cv=tscv, scoring='neg_log_loss', n_jobs=-1)
        grid_search.fit(X_train, y_train)

        print(f"Best Parameters Found: {grid_search.best_params_}")
        best_model = grid_search.best_estimator_

        # --- Step 5: Fit Isotonic Calibration on the held-out calibration set ---
        # PredefinedSplit tells sklearn: train base model on X_train (-1 fold),
        # fit isotonic layer on X_cal (0 fold). Equivalent to the removed cv='prefit'.
        print("\nFitting isotonic calibration layer...")
        test_fold = np.concatenate([np.full(len(X_train), -1), np.zeros(len(X_cal))])
        ps = PredefinedSplit(test_fold)
        X_trainval = pd.concat([X_train, X_cal])
        y_trainval = pd.concat([y_train, y_cal])
        best_xgb = XGBClassifier(**grid_search.best_params_, random_state=42, eval_metric='logloss')
        calibrated_model = CalibratedClassifierCV(best_xgb, method='isotonic', cv=ps)
        calibrated_model.fit(X_trainval, y_trainval)

        # --- Step 6: Betting-Grade Evaluation on the final test set ---
        y_prob = calibrated_model.predict_proba(X_test)[:, 1]

        brier = brier_score_loss(y_test, y_prob)
        ll    = log_loss(y_test, y_prob)

        fraction_of_positives, mean_predicted = calibration_curve(y_test, y_prob, n_bins=10)
        ece = float(np.mean(np.abs(fraction_of_positives - mean_predicted)))

        print("\n--- Betting-Grade Model Evaluation ---")
        print(f"Brier Score : {brier:.4f}  (lower is better, random baseline = 0.25)")
        print(f"Log Loss    : {ll:.4f}  (lower is better, random baseline = 0.693)")
        print(f"ECE         : {ece:.4f}  (lower is better, perfect calibration = 0.00)")

        # --- Feature Importances (from the underlying XGBoost model) ---
        feature_importances = pd.DataFrame({
            'Feature': X.columns,
            'Importance': best_model.feature_importances_
        }).sort_values(by='Importance', ascending=False)

        print("\n--- Feature Importances ---")
        print(feature_importances.head(10))

        # --- Save Model and Data ---
        print("\n--- Saving Assets ---")

        joblib.dump(calibrated_model, 'nba_model_calibrated.joblib')
        print("Model saved as 'nba_model_calibrated.joblib'")

        # =====================================================================
        # REGRESSION MODELS: Spread & Total (Phase 8)
        # =====================================================================
        print("\n\n=== Training Regression Models (Spread & Total) ===")

        # Filter to home-team rows only — gives one row per game with a well-defined
        # home_margin (home_pts - away_pts) and total_pts (home_pts + away_pts).
        home_df = featured_df[featured_df['is_home'] == 1].copy()
        home_df['home_margin'] = home_df['PTS'] - home_df['PTS_allowed']
        home_df['total_pts']   = home_df['PTS'] + home_df['PTS_allowed']

        X_reg      = home_df[predictive_features]
        y_spread   = home_df['home_margin']
        y_total    = home_df['total_pts']

        # 80/20 chronological split — no calibration set needed for regression
        n_reg = len(X_reg)
        split_reg = int(n_reg * 0.80)
        X_reg_train, X_reg_test   = X_reg.iloc[:split_reg],    X_reg.iloc[split_reg:]
        y_spread_train, y_spread_test = y_spread.iloc[:split_reg], y_spread.iloc[split_reg:]
        y_total_train,  y_total_test  = y_total.iloc[:split_reg],  y_total.iloc[split_reg:]

        reg_param_grid = {
            'n_estimators':  [100, 200],
            'learning_rate': [0.05, 0.1],
            'max_depth':     [3, 4],
            'subsample':     [0.8, 1.0],
        }
        tscv_reg = TimeSeriesSplit(n_splits=5)

        # --- Spread model ---
        print("\nTraining Spread Model (XGBRegressor)...")
        spread_gs = GridSearchCV(
            XGBRegressor(random_state=42),
            reg_param_grid, cv=tscv_reg,
            scoring='neg_mean_absolute_error', n_jobs=-1
        )
        spread_gs.fit(X_reg_train, y_spread_train)
        model_spread   = spread_gs.best_estimator_
        spread_preds   = model_spread.predict(X_reg_test)
        spread_sigma   = float(np.std(y_spread_test.values - spread_preds))
        spread_mae     = mean_absolute_error(y_spread_test, spread_preds)
        spread_rmse    = float(np.sqrt(mean_squared_error(y_spread_test, spread_preds)))
        print(f"Spread → MAE: {spread_mae:.2f} pts | RMSE: {spread_rmse:.2f} pts | Sigma: {spread_sigma:.2f} pts")
        print(f"Best params: {spread_gs.best_params_}")

        # --- Total model ---
        print("\nTraining Total Model (XGBRegressor)...")
        total_gs = GridSearchCV(
            XGBRegressor(random_state=42),
            reg_param_grid, cv=tscv_reg,
            scoring='neg_mean_absolute_error', n_jobs=-1
        )
        total_gs.fit(X_reg_train, y_total_train)
        model_total   = total_gs.best_estimator_
        total_preds   = model_total.predict(X_reg_test)
        total_sigma   = float(np.std(y_total_test.values - total_preds))
        total_mae     = mean_absolute_error(y_total_test, total_preds)
        total_rmse    = float(np.sqrt(mean_squared_error(y_total_test, total_preds)))
        print(f"Total  → MAE: {total_mae:.2f} pts | RMSE: {total_rmse:.2f} pts | Sigma: {total_sigma:.2f} pts")
        print(f"Best params: {total_gs.best_params_}")

        # Save regression models and their residual sigmas (needed for norm.cdf in api.py)
        joblib.dump(model_spread, 'model_spread.joblib')
        joblib.dump(model_total,  'model_total.joblib')
        joblib.dump({'spread_sigma': spread_sigma, 'total_sigma': total_sigma}, 'model_metadata.joblib')
        print("\nSaved: model_spread.joblib | model_total.joblib | model_metadata.joblib")

        # 2. Save the cleaned dataframe to a local SQLite database
        conn = sqlite3.connect('nba_data.db')
        featured_df.to_sql('team_stats', conn, if_exists='replace', index=False)
        
        # Save the absolute latest PRA for every player so our API can use it for live injuries
        print("Saving latest player PRAs for live injury calculations...")
        latest_players = processed_players_df.sort_values('GAME_DATE').groupby('PLAYER_NAME').tail(1)
        latest_players[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'ROLLING_PRA']].to_sql('player_stats', conn, if_exists='replace', index=False)
        
        conn.close()
        print("Data saved to local database 'nba_data.db'")

    else:
        print("\nFailed to retrieve data.")
