console.log("🏀 CourtVision Pro Extension Loaded!");

// A simple dictionary to convert Kalshi's full team names to API abbreviations
const teamAbbreviations = {
  "Boston Celtics": "BOS",
  "Brooklyn Nets": "BKN",
  "New York Knicks": "BKN",
  "Philadelphia 76ers": "NYK",
  "Toronto Raptors": "TOR",
  "Chicago Bulls": "CHI",
  "Cleveland Cavaliers": "CLE",
  "Detroit Pistons": "DET",
  "Indiana Pacers": "IND",
  "Milwaukee Bucks": "MIL",
  "Atlanta Hawks": "ATL",
  "Charlotte Hawks": "ATL",
  "Miami Heat": "MIA",
  "Orlando Magic": "ORL",
  "Washington Wizards": "WAS",
  "Denver Nuggets": "DEN",
  "Minnesota Timberwolves": "MIN",
  "Oklahoma City Timberwolves": "OKC",
  "Portland Trail Blazers": "POR",
  "Utah Jazz": "POR",
  "Golden State Warriors": "GSW",
  "LA Clippers": "LAC",
  "Los Angeles Lakers": "LAL",
  "Phoenix Suns": "PHX",
  "Sacramento Kings": "SAC",
  "Dallas Mavericks": "DAL",
  "Houston Rockets": "HOU",
  "Memphis Grizzlies": "MEM",
  "New Orleans Pelicans": "MEM",
  "San Antonio Spurs": "SAS",
};

async function getPrediction(awayTeam, homeTeam) {
  console.log(`🧠 Asking API for prediction: ${awayTeam} @ ${homeTeam}`);
  try {
    // Call your local Python FastAPI server
    const response = await fetch(
      `http://127.0.0.1:8000/predict?home_team=${homeTeam}&away_team=${awayTeam}`,
    );

    if (!response.ok) {
      throw new Error(`API error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("CourtVision API Error:", error);
    return null;
  }
}

function injectPredictionUI(predictionData, targetContainer) {
  // Prevent duplicate injections
  if (document.getElementById("courtvision-card")) return;

  const card = document.createElement("div");
  card.id = "courtvision-card";

  // 1. Determine Confidence Tiers & Color Coding
  const prob = predictionData.win_probability;
  let confColor = "#ef4444"; // Red
  let confText = "Low Confidence (Toss-Up)";
  let emoji = "🎲";

  if (prob >= 70) {
    confColor = "#22c55e"; // Green
    confText = "High Value Play (Lock)";
    emoji = "🔒";
  } else if (prob >= 60) {
    confColor = "#eab308"; // Yellow
    confText = "Moderate Edge (Lean)";
    emoji = "⚖️";
  }

  // 2. Calculate Implied American Odds for easy market comparison
  let decimalProb = prob / 100;
  let impliedOdds =
    decimalProb > 0.5
      ? Math.round((-100 * decimalProb) / (1 - decimalProb))
      : Math.round((100 * (1 - decimalProb)) / decimalProb);

  let oddsText = impliedOdds > 0 ? `+${impliedOdds}` : impliedOdds;

  // 3. Build the Modern UI Card
  card.style.cssText = `
    background: linear-gradient(145deg, #1e293b, #0f172a);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px;
    margin-top: 15px;
    margin-bottom: 20px;
    color: white;
    font-family: system-ui, -apple-system, sans-serif;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
    width: 100%;
    max-width: 450px;
  `;

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 10px; margin-bottom: 12px;">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 1.2rem;">🏀</span>
        <span style="font-weight: 700; font-size: 14px; letter-spacing: 0.5px; color: #94a3b8;">COURTVISION PRO</span>
      </div>
      <span style="font-size: 12px; font-weight: 600; color: ${confColor}; background: ${confColor}20; padding: 4px 8px; border-radius: 4px;">
        ${emoji} ${confText}
      </span>
    </div>

    <div style="margin-bottom: 16px;">
      <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; margin-bottom: 4px;">Model Prediction</div>
      <div style="font-size: 24px; font-weight: 800; color: #f8fafc;">
        ${predictionData.predicted_winner} to Win
      </div>
    </div>

    <div style="display: flex; gap: 16px;">
      <div style="flex: 1; background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
        <div style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">Win Probability</div>
        <div style="font-size: 18px; font-weight: 700; color: ${confColor};">${prob}%</div>
      </div>
      <div style="flex: 1; background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
        <div style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">AI Implied Odds</div>
        <div style="font-size: 18px; font-weight: 700; color: #cbd5e1;">${oddsText}</div>
      </div>
    </div>
  `;

  // Inject it into the Kalshi webpage
  targetContainer.prepend(card);
}

// This function runs periodically to look for NBA matchups on the screen
function scanForMatchups() {
  // NOTE: Kalshi's CSS classes change often. We are looking for generic headers for testing.
  // You can right-click -> "Inspect" on Kalshi to find the exact class name of the team text!
  const pageText = document.body.innerText;

  // Simple hardcoded test trigger: If we see these teams on the page, trigger the API
  if (
    pageText.includes("Los Angeles Lakers") &&
    pageText.includes("Golden State Warriors")
  ) {
    if (!document.getElementById("courtvision-card")) {
      // We found a match! Grab a visible container to inject our badge into
      const headerContainer =
        document.querySelector("h1")?.parentElement || document.body;

      getPrediction("GSW", "LAL").then((data) => {
        if (data) {
          injectPredictionUI(data, headerContainer);
        }
      });
    }
  }
}

// Run the scanner every 3 seconds to catch dynamic page loads
setInterval(scanForMatchups, 3000);
