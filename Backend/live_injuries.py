import pandas as pd
import requests
from io import StringIO

def get_live_injuries():
    """
    Scrapes the live NBA injury report from ESPN instead of Basketball Reference.
    Returns a DataFrame containing injured players.
    """
    url = "https://www.espn.com/nba/injuries"
    
    # Headers simulate a real browser to prevent the site from blocking us
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # Parse the HTML tables from the text response
        tables = pd.read_html(StringIO(response.text))
        
        # ESPN creates a separate table for every NBA team.
        # We use pd.concat to merge all these tables into one massive list.
        df = pd.concat(tables, ignore_index=True)
        
        # Rename ESPN's 'NAME' column to match what our database uses
        if 'NAME' in df.columns:
            df = df.rename(columns={'NAME': 'PLAYER_NAME'})
        
        return df
    except Exception as e:
        print(f"Failed to scrape injuries: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    print("Fetching live injury report from ESPN...")
    injuries_df = get_live_injuries()
    print(injuries_df.head(15)) # Print the first 15 rows to test it