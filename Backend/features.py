# Single source of truth for the model input features.
# scraper.py (training) and api.py (serving) both import this list.
#
# api.py builds its input row BY NAME: the LIVE_FEATURES below are computed at
# prediction time; every other column is read off the team's latest DB row —
# plain names from the HOME team's row, '*_opp' names from the AWAY team's row
# (api strips the '_opp' suffix to find the away column).
# Add/remove features here, then re-run scraper.py and restart the API.

# Computed live in api.py (rest from dates, injuries from ESPN, Elo from DB rows)
LIVE_FEATURES = [
    'is_home', 'days_rest', 'rest_differential',
    'MISSING_PLAYER_VALUE', 'MISSING_PLAYER_VALUE_opp',
    'MISSING_USAGE_PCT', 'MISSING_USAGE_PCT_opp',
    'ELO', 'ELO_opp',
]

PREDICTIVE_FEATURES = LIVE_FEATURES + [
    'PTS_roll_5', 'PTS_allowed_roll_5', 'eFG_roll_5', 'PLUS_MINUS_roll_5', 'AST_roll_5', 'REB_roll_5', 'TOV_roll_5',
    'PTS_roll_10', 'PTS_allowed_roll_10', 'eFG_roll_10', 'PLUS_MINUS_roll_10', 'AST_roll_10', 'REB_roll_10', 'TOV_roll_10',
    'PACE_roll_5', 'OFF_RTG_roll_5', 'DEF_RTG_roll_5',
    'PACE_roll_10', 'OFF_RTG_roll_10', 'DEF_RTG_roll_10',
    'OFF_RTG_roll_5_opp', 'DEF_RTG_roll_5_opp',
    'OFF_RTG_roll_10_opp', 'DEF_RTG_roll_10_opp',
]
