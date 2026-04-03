import pandas as pd
from nba_api.stats.endpoints import leaguegamelog
from sklearn.model_selection import train_test_split, GridSearchCV
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score, classification_report
import joblib
import sqlite3
import time # ADD THIS to the top of your imports


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
    
    return team_game_logs

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
    # 1. Fetch 3 years of data instead of 1
    seasons_to_pull = ["2021-22", "2022-23", "2023-24"]
    nba_df = fetch_multiple_seasons(seasons_to_pull)
    players_df = fetch_multiple_seasons_players(seasons_to_pull)
    
    if not nba_df.empty:
        # Run the entire feature engineering pipeline
        # First, calculate missing player value and merge it to the raw team logs
        nba_df = engineer_missing_player_value(players_df, nba_df)
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

        # --- Step 3: The Chronological Train/Test Split ---
        # We split the data chronologically to simulate real-world prediction.
        # shuffle=False is critical for time-series/sports data!
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

        print(f"\nTraining model on {len(X_train)} games, testing on {len(X_test)} games.")

        # --- Step 4 & 2: Train an Advanced Model (XGBoost + GridSearchCV) ---
        print("\nFinding the best hyperparameters for XGBoost...")
        param_grid = {
            'n_estimators': [100, 200, 300],
            'learning_rate': [0.01, 0.05, 0.1],
            'max_depth': [3, 4, 5],
            'subsample': [0.8, 1.0] # Helps prevent overfitting
        }
        
        xgb = XGBClassifier(random_state=42, eval_metric='logloss')
        grid_search = GridSearchCV(estimator=xgb, param_grid=param_grid, cv=3, scoring='accuracy', n_jobs=-1)
        grid_search.fit(X_train, y_train)
        
        print(f"Best Parameters Found: {grid_search.best_params_}")
        model = grid_search.best_estimator_ # Use the best model found

        # Make predictions on the unseen test data
        predictions = model.predict(X_test)

        # Evaluate the model's performance
        print("\n--- Model Evaluation ---")
        print(f"Model Accuracy on Test Set: {accuracy_score(y_test, predictions):.2%}")
        print("\nClassification Report:")
        print(classification_report(y_test, predictions, target_names=['Loss', 'Win']))

        # --- Step 1: Check Under the Hood (Feature Importances) ---
        # Create a DataFrame of feature importances
        feature_importances = pd.DataFrame({
            'Feature': X.columns,
            'Importance': model.feature_importances_
        }).sort_values(by='Importance', ascending=False)
        
        print("\n--- Feature Importances ---")
        print(feature_importances.head(10))

        # --- NEW CODE: Save Model and Data ---
        print("\n--- Saving Assets ---")
        
        # 1. Save the trained Random Forest model
        joblib.dump(model, 'nba_model.joblib')
        print("Model saved as 'nba_model.joblib'")

        # 2. Save the cleaned dataframe to a local SQLite database
        conn = sqlite3.connect('nba_data.db')
        featured_df.to_sql('team_stats', conn, if_exists='replace', index=False)
        conn.close()
        print("Data saved to local database 'nba_data.db'")

    else:
        print("\nFailed to retrieve data.")
