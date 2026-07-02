"""Pipeline integrity tests. Run from Backend/:
    ../venv/Scripts/python.exe -m pytest test_pipeline.py -q
"""
import pandas as pd
import numpy as np

from features import PREDICTIVE_FEATURES
from scraper import engineer_features


def _synthetic_logs():
    """Two teams, one season, 6 games against each other on known dates.
    PTS values are chosen so rolling means are easy to verify by hand."""
    rows = []
    dates = pd.date_range('2024-01-01', periods=6, freq='3D')
    for i, date in enumerate(dates):
        game_id = f"002240000{i}"
        # Team 1 at home ("vs."), Team 2 away ("@")
        for team_id, matchup, pts, opp_pts in [
            (1, 'AAA vs. BBB', 100 + i * 10, 90 + i * 5),
            (2, 'BBB @ AAA', 90 + i * 5, 100 + i * 10),
        ]:
            rows.append({
                'GAME_DATE': date, 'GAME_ID': game_id, 'TEAM_ID': team_id,
                'SEASON_STR': '2023-24', 'MATCHUP': matchup, 'WL': 'W' if pts > opp_pts else 'L',
                'PTS': pts, 'FGM': 40, 'FG3M': 10, 'FGA': 90,
                'FTA': 20, 'OREB': 10, 'MIN': 240,
                'PLUS_MINUS': pts - opp_pts, 'AST': 25, 'REB': 45, 'TOV': 12,
                'MISSING_PLAYER_VALUE': 0, 'MISSING_USAGE_PCT': 0, 'ELO': 1500,
            })
    return pd.DataFrame(rows)


def test_no_lookahead_leakage():
    """The rolling features for game t must be computed ONLY from games before t.
    This is the core guarantee the whole betting model rests on."""
    df = engineer_features(_synthetic_logs())
    team1 = df[df['TEAM_ID'] == 1].sort_values('GAME_DATE')

    # Team 1 scored 100, 110, 120, ... (unique values, so PTS identifies the game).
    # For every surviving row, PTS_roll_5 must equal the mean of the up-to-5
    # STRICTLY PRIOR games — never including the current game's own score.
    full_history = [100 + i * 10 for i in range(6)]
    for _, row in team1.iterrows():
        game_num = full_history.index(row['PTS'])
        expected = np.mean(full_history[max(0, game_num - 5):game_num])
        assert abs(row['PTS_roll_5'] - expected) < 1e-9, (
            f"PTS_roll_5 at game {game_num} is {row['PTS_roll_5']}, "
            f"expected {expected} (mean of prior games only) — lookahead leak!"
        )


def test_all_features_exist_after_engineering():
    """Every feature the models train/serve on must be produced by the pipeline
    (except those merged in earlier stages: MISSING_PLAYER_VALUE, ELO and their
    _opp variants come from other functions, but must still be present)."""
    df = engineer_features(_synthetic_logs())
    missing = [f for f in PREDICTIVE_FEATURES if f not in df.columns]
    assert missing == [], f"Pipeline no longer produces: {missing}"


def test_home_flag():
    df = engineer_features(_synthetic_logs())
    assert set(df[df['TEAM_ID'] == 1]['is_home']) == {1}
    assert set(df[df['TEAM_ID'] == 2]['is_home']) == {0}
