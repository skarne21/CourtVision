console.log("🏀 CourtVision Pro Extension Loaded!");

// Fixed Abbreviation Dictionary
const teamAbbreviations = {
  "Boston Celtics": "BOS",
  "Brooklyn Nets": "BKN",
  "New York Knicks": "NYK",
  "Philadelphia 76ers": "PHI",
  "Toronto Raptors": "TOR",
  "Chicago Bulls": "CHI",
  "Cleveland Cavaliers": "CLE",
  "Detroit Pistons": "DET",
  "Indiana Pacers": "IND",
  "Milwaukee Bucks": "MIL",
  "Atlanta Hawks": "ATL",
  "Charlotte Hornets": "CHA",
  "Miami Heat": "MIA",
  "Orlando Magic": "ORL",
  "Washington Wizards": "WAS",
  "Denver Nuggets": "DEN",
  "Minnesota Timberwolves": "MIN",
  "Oklahoma City Thunder": "OKC",
  "Portland Trail Blazers": "POR",
  "Utah Jazz": "UTA",
  "Golden State Warriors": "GSW",
  "LA Clippers": "LAC",
  "Los Angeles Lakers": "LAL",
  "Phoenix Suns": "PHX",
  "Sacramento Kings": "SAC",
  "Dallas Mavericks": "DAL",
  "Houston Rockets": "HOU",
  "Memphis Grizzlies": "MEM",
  "New Orleans Pelicans": "NOP",
  "San Antonio Spurs": "SAS",
};

// Map Kalshi's location names to abbreviations
const locationToAbbrev = {
  Atlanta: "ATL",
  Boston: "BOS",
  Brooklyn: "BKN",
  Charlotte: "CHA",
  Chicago: "CHI",
  Cleveland: "CLE",
  Dallas: "DAL",
  Denver: "DEN",
  Detroit: "DET",
  "Golden State": "GSW",
  Houston: "HOU",
  Indiana: "IND",
  "LA Clippers": "LAC",
  Clippers: "LAC",
  "Los Angeles Clippers": "LAC",
  "Los Angeles C": "LAC",
  "LA Lakers": "LAL",
  Lakers: "LAL",
  "Los Angeles Lakers": "LAL",
  "Los Angeles L": "LAL",
  Memphis: "MEM",
  Miami: "MIA",
  Milwaukee: "MIL",
  Minnesota: "MIN",
  "New Orleans": "NOP",
  "New York": "NYK",
  "Oklahoma City": "OKC",
  Orlando: "ORL",
  Philadelphia: "PHI",
  Phoenix: "PHX",
  Portland: "POR",
  Sacramento: "SAC",
  "San Antonio": "SAS",
  Toronto: "TOR",
  Utah: "UTA",
  Washington: "WAS",
};

// Reverse Lookup to get the full name from the API's abbreviation
const fullTeamNames = Object.fromEntries(
  Object.entries(teamAbbreviations).map(([name, abbrev]) => [abbrev, name]),
);

// Cache predictions so we don't request the same game twice
// Key format: "AWAY@HOME" for moneyline, "AWAY@HOME:spread:5.5" for spread, etc.
const predictionCache = {};

// Detect whether the current page is a spread or total market, and extract the line.
// Returns { type: "moneyline"|"spread"|"total", line: number|null, spreadTeam: string|null }
function detectMarketContext(pageText) {
  const spreadMatch = pageText.match(
    /([A-Za-z\s]+?)\s+wins by over\s+(\d+\.?\d*)\s+points/i,
  );
  const totalMatch = pageText.match(/Over\s+(\d+\.?\d*)\s+points scored/i);
  if (spreadMatch) {
    return {
      type: "spread",
      line: parseFloat(spreadMatch[2]),
      spreadTeam: spreadMatch[1].trim(),
    };
  }
  if (totalMatch) {
    return { type: "total", line: parseFloat(totalMatch[1]), spreadTeam: null };
  }
  return { type: "moneyline", line: null, spreadTeam: null };
}

// Try to resolve a partial team name (from Kalshi's spread text) to a known abbreviation.
function findTeamAbbrev(teamStr) {
  const s = teamStr.trim();
  if (locationToAbbrev[s]) return locationToAbbrev[s];
  for (const [loc, abbrev] of Object.entries(locationToAbbrev)) {
    if (s.includes(loc) || loc.includes(s)) return abbrev;
  }
  for (const [name, abbrev] of Object.entries(teamAbbreviations)) {
    if (s.includes(name) || name.includes(s)) return abbrev;
  }
  return null;
}

async function getPrediction(
  awayTeam,
  homeTeam,
  marketType = "moneyline",
  line = null,
  spreadTeam = null,
) {
  console.log(
    `🧠 Asking API: ${awayTeam} @ ${homeTeam} [${marketType}${line != null ? " " + line : ""}]`,
  );
  try {
    let url = `http://127.0.0.1:8000/predict?home_team=${homeTeam}&away_team=${awayTeam}&market_type=${marketType}`;
    if (line != null) url += `&line=${line}`;
    if (spreadTeam != null)
      url += `&spread_team=${encodeURIComponent(spreadTeam)}`;

    const response = await fetch(url);
    if (!response.ok) {
      let errorDetail = "Unknown Error";
      try {
        const errData = await response.json();
        errorDetail = errData.detail || errorDetail;
      } catch (e) {}
      throw new Error(
        `API error! status: ${response.status}, Detail: ${errorDetail}`,
      );
    }
    return await response.json();
  } catch (error) {
    console.error("CourtVision API Error:", error);
    return null;
  }
}

function removeSingleCard() {
  const el = document.getElementById("courtvision-card");
  if (el) el.remove();
}

function removeSidebar() {
  const el = document.getElementById("courtvision-sidebar");
  if (el) el.remove();
}

function injectPredictionCard(
  targetContainer,
  predictionData,
  marketTargetTeamName,
) {
  let card = document.getElementById("courtvision-card");
  if (card) {
    // If the card is already showing THIS matchup, do nothing.
    if (card.dataset.matchup === predictionData.matchup) return;
    // Otherwise, the user clicked a new game, so remove the old card
    card.remove();
  }

  const aiWinProb = predictionData.win_probability;
  const marketProb = predictionData.marketProb || "--";
  const mtype = predictionData.market_type || "moneyline";

  // Edge calculation (shared across all market types)
  const aiProbFloat = parseFloat(aiWinProb);
  const marketProbFloat = parseFloat(marketProb) || 0;
  let edgeHtml = "";
  if (marketProbFloat > 0) {
    const edge = aiProbFloat - marketProbFloat;
    const edgeColor = edge > 5 ? "#10b981" : edge > 0 ? "#f59e0b" : "#ef4444";
    const edgeLabel =
      edge > 5
        ? "HIGH CONFIDENCE"
        : edge > 0
          ? "MEDIUM CONFIDENCE"
          : "LOW/NO EDGE";
    edgeHtml = `
      <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #1e293b; text-align: center;">
        <span style="font-size: 11px; color: #94a3b8;">EXPECTED VALUE:</span>
        <span style="font-size: 13px; font-weight: bold; color: ${edgeColor}; margin-left: 6px;">${edge > 0 ? "+" : ""}${edge.toFixed(1)}% EDGE (${edgeLabel})</span>
      </div>`;
  }

  // Build market-specific body copy
  let headerLabel,
    bodyHtml,
    recHtml = "";
  if (mtype === "spread") {
    const spreadTeamFull =
      fullTeamNames[predictionData.spread_team] || predictionData.spread_team;
    const parts = predictionData.matchup.split(" @ ");
    const otherAbbrev = predictionData.spread_team === parts[0] ? parts[1] : parts[0];
    const otherFull = fullTeamNames[otherAbbrev] || otherAbbrev;
    const aiCoverTeam = aiProbFloat >= 50 ? spreadTeamFull : otherFull;
    const projMargin = predictionData.predicted_margin;
    const recColor =
      predictionData.recommendation === "YES" ? "#10b981" : "#ef4444";
    headerLabel = "CourtVision Spread Analysis";
    bodyHtml = `<b>${aiCoverTeam}</b> covers the <b>${predictionData.line}</b> pt spread<br>
                   <span style="font-size:13px;color:#94a3b8;">Projected margin: ${projMargin > 0 ? "+" : ""}${projMargin} pts</span>`;
    recHtml = `<div style="text-align:center;margin-top:8px;">
                     <span style="font-size:18px;font-weight:900;color:${recColor};">${predictionData.recommendation}</span>
                     <span style="font-size:11px;color:#94a3b8;margin-left:6px;">(Cover ${predictionData.recommendation === "YES" ? "likely" : "unlikely"})</span>
                   </div>`;
  } else if (mtype === "total") {
    const recColor =
      predictionData.recommendation === "YES" ? "#10b981" : "#ef4444";
    headerLabel = "CourtVision Total Analysis";
    bodyHtml = `Projected total: <b>${predictionData.predicted_total} pts</b><br>
                   <span style="font-size:13px;color:#94a3b8;">Line: ${predictionData.line} pts</span>`;
    recHtml = `<div style="text-align:center;margin-top:8px;">
                     <span style="font-size:18px;font-weight:900;color:${recColor};">${predictionData.recommendation === "YES" ? "OVER" : "UNDER"}</span>
                     <span style="font-size:11px;color:#94a3b8;margin-left:6px;">(${predictionData.recommendation === "YES" ? "Over" : "Under"} likely)</span>
                   </div>`;
  } else {
    const predictedFullName =
      fullTeamNames[predictionData.predicted_winner] ||
      predictionData.predicted_winner;
    headerLabel = "CourtVision AI Insight";
    bodyHtml = `The model projects the <b>${predictedFullName}</b> to win this matchup.`;
  }

  // Build both-sides labels and complementary probabilities
  const side2AiProb   = (100 - aiProbFloat).toFixed(2);
  const side2MktProb  = marketProbFloat > 0 ? (100 - marketProbFloat).toFixed(0) + "%" : "--";
  let side1Label, side2Label;
  if (mtype === "spread") {
    const spreadTeamFull = fullTeamNames[predictionData.spread_team] || predictionData.spread_team;
    const parts = predictionData.matchup.split(" @ ");
    const otherAbbrev = predictionData.spread_team === parts[0] ? parts[1] : parts[0];
    const otherFull   = fullTeamNames[otherAbbrev] || otherAbbrev;
    side1Label = `${spreadTeamFull} covers`;
    side2Label = `${otherFull} covers`;
  } else if (mtype === "total") {
    side1Label = `Over ${predictionData.line}`;
    side2Label = `Under ${predictionData.line}`;
  } else {
    const winnerFull = fullTeamNames[predictionData.predicted_winner] || predictionData.predicted_winner;
    const parts = predictionData.matchup.split(" @ ");
    const loserAbbrev = predictionData.predicted_winner === parts[0] ? parts[1] : parts[0];
    const loserFull   = fullTeamNames[loserAbbrev] || loserAbbrev;
    side1Label = winnerFull;
    side2Label = loserFull;
  }

  const probTableHtml = `
    <div style="background:#1e293b;padding:10px 12px;border-radius:6px;">
      <div style="display:grid;grid-template-columns:1fr 56px 64px;gap:4px;align-items:center;font-size:10px;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.4px;">
        <span></span><span style="text-align:right;">MARKET</span><span style="text-align:right;">AI PROB</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 56px 64px;gap:4px;align-items:center;margin-bottom:4px;">
        <span style="font-size:12px;color:#f8fafc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${side1Label}</span>
        <span style="font-size:15px;font-weight:600;color:#cbd5e1;text-align:right;">${marketProb}</span>
        <span style="font-size:15px;font-weight:700;color:#10b981;text-align:right;">${aiWinProb}%</span>
      </div>
      <div style="border-top:1px solid #334155;margin:5px 0;"></div>
      <div style="display:grid;grid-template-columns:1fr 56px 64px;gap:4px;align-items:center;">
        <span style="font-size:12px;color:#f8fafc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${side2Label}</span>
        <span style="font-size:15px;font-weight:600;color:#cbd5e1;text-align:right;">${side2MktProb}</span>
        <span style="font-size:15px;font-weight:700;color:#10b981;text-align:right;">${side2AiProb}%</span>
      </div>
    </div>`;

  // Build the card
  card = document.createElement("div");
  card.id = "courtvision-card";
  card.dataset.matchup = predictionData.matchup;
  card.style.cssText = `
    position: fixed; top: 80px; right: 20px; z-index: 999999;
    background: linear-gradient(145deg, #1e293b, #0f172a);
    border: 1px solid #334155; border-radius: 12px; padding: 16px;
    color: white; font-family: system-ui, -apple-system, sans-serif;
    box-shadow: 0 10px 25px rgba(0,0,0,0.5); width: 370px;
  `;
  card.innerHTML = `
    <div style="display:flex;gap:12px;margin-bottom:8px;font-family:sans-serif;">
      <div style="flex:1;background:#0f172a;padding:12px;border-radius:8px;border:1px solid #1e293b;">
        <div style="font-size:12px;font-weight:bold;color:#38bdf8;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">${headerLabel}</div>
        <div style="font-size:15px;color:#f8fafc;margin-bottom:12px;line-height:1.5;">${bodyHtml}</div>
        ${probTableHtml}
        ${recHtml}
        ${edgeHtml}
      </div>
    </div>
  `;

  // Using appendChild to keep it floating
  targetContainer.appendChild(card);
}

function injectSidebar(targetContainer, rankingData) {
  let sidebar = document.getElementById("courtvision-sidebar");

  // If the sidebar doesn't exist, create it
  if (!sidebar) {
    // Inject custom CSS for hover effects if not already present
    if (!document.getElementById("courtvision-styles")) {
      const style = document.createElement("style");
      style.id = "courtvision-styles";
      style.textContent = `
        .cv-game-card {
          margin-bottom: 10px; padding: 10px; background: #1e293b; border-radius: 6px; border-left: 4px solid #10b981;
          transition: background 0.2s, transform 0.1s;
          display: block; color: inherit;
        }
        .cv-game-card:hover {
          background: #334155; transform: translateX(4px);
        }
      `;
      document.head.appendChild(style);
    }

    sidebar = document.createElement("div");
    sidebar.id = "courtvision-sidebar";
    sidebar.style.cssText = `
      position: fixed;
      top: 80px;
      right: 20px;
      z-index: 999999;
      background: linear-gradient(145deg, #1e293b, #0f172a);
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 16px;
      color: white;
      font-family: system-ui, -apple-system, sans-serif;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
      width: 360px; /* Made slightly wider to fit both probabilities */
    `;
    targetContainer.appendChild(sidebar);
  }

  // Generate list items for every game, sorted by highest AI probability
  const listHtml = rankingData
    .map((data) => {
      // Convert "AWAY @ HOME" to full team names
      const parts = data.matchup.split(" @ ");
      const fullAway = fullTeamNames[parts[0]] || parts[0];
      const fullHome = fullTeamNames[parts[1]] || parts[1];

      // Phase 5: Edge Calculation for Sidebar
      const aiProb = parseFloat(data.win_probability);
      const marketProbVal = parseFloat(data.marketProb) || 0;
      let edgeColor = "#94a3b8";
      let edgeStr = "";
      let borderStyle = "4px solid #334155";

      if (marketProbVal > 0) {
        const edge = aiProb - marketProbVal;
        if (edge > 5) {
          edgeColor = "#10b981";
          borderStyle = "4px solid #10b981";
          edgeStr = `+${edge.toFixed(1)}% Edge`;
        } else if (edge > 0) {
          edgeColor = "#f59e0b";
          borderStyle = "4px solid #f59e0b";
          edgeStr = `+${edge.toFixed(1)}% Edge`;
        } else {
          edgeColor = "#ef4444";
          borderStyle = "4px solid #ef4444";
          edgeStr = `${edge.toFixed(1)}% Edge`;
        }
      }

      return `
    <div class="cv-game-card" style="border-left: ${borderStyle}">
      <div style="font-size: 12px; color: #94a3b8; margin-bottom: 4px; display: flex; justify-content: space-between;">
        <span>${fullAway} @ ${fullHome}</span>
        <span style="color: ${edgeColor}; font-weight: 700;">${edgeStr}</span>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 15px; font-weight: bold; color: #f8fafc; max-width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${fullTeamNames[data.predicted_winner] || data.predicted_winner}</span>
        <div style="display: flex; gap: 12px; align-items: center;">
          <div style="text-align: right;">
            <div style="font-size: 10px; color: #94a3b8;">MARKET</div>
            <div style="font-size: 14px; font-weight: 600; color: #cbd5e1;">${data.marketProb || "--"}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 10px; color: #94a3b8;">AI PROB</div>
            <div style="font-size: 14px; font-weight: 700; color: #10b981;">${data.win_probability}%</div>
          </div>
        </div>
      </div>
    </div>
  `;
    })
    .join("");

  // Only re-render if the content actually changed to avoid flickering
  if (sidebar.dataset.lastHtml === listHtml) return;
  sidebar.dataset.lastHtml = listHtml;

  // Save the current scroll position so we don't snap to the top
  const scrollContainer = sidebar.querySelector("#cv-scroll-box");
  const currentScroll = scrollContainer ? scrollContainer.scrollTop : 0;

  // Update the inner HTML cleanly
  sidebar.innerHTML = `
    <div style="font-size: 13px; font-weight: bold; color: #38bdf8; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;">🔥 CourtVision Top Edges</div>
    <div id="cv-scroll-box" style="max-height: 500px; overflow-y: auto; padding-right: 4px;">
      ${listHtml}
    </div>
  `;

  // Restore the scroll position
  sidebar.querySelector("#cv-scroll-box").scrollTop = currentScroll;
}

// This function runs periodically to look for NBA matchups on the screen
async function scanForMatchups() {
  const pageText = document.body.innerText;

  const locations = Object.keys(locationToAbbrev).join("|");
  // Add the "g" flag to find ALL matchups on the page globally
  const matchupRegex = new RegExp(
    `\\b(${locations}) at (${locations})\\b`,
    "g",
  );
  const matches = [...pageText.matchAll(matchupRegex)];
  console.log(`[CourtVision] regex found ${matches.length} raw matchup(s):`, matches.map(m => `${m[1]} at ${m[2]}`));

  const uniqueMatchups = [];
  const seen = new Set();

  // Extract unique games
  for (const match of matches) {
    const awayLocation = match[1];
    const homeLocation = match[2];
    const awayAbbrev = locationToAbbrev[awayLocation];
    const homeAbbrev = locationToAbbrev[homeLocation];
    const key = `${awayAbbrev}@${homeAbbrev}`;

    if (!seen.has(key)) {
      seen.add(key);
      uniqueMatchups.push({
        awayAbbrev,
        homeAbbrev,
        awayLocation,
        homeLocation,
        key,
        textIndex: match.index, // Save the exact pixel/text location of this game
      });
    }
  }

  // If we left the basketball page, hide the UI completely
  if (uniqueMatchups.length === 0) {
    removeSingleCard();
    removeSidebar();
    return;
  }

  // Detect market type (spread / total / moneyline) from the current page text.
  // Only relevant on single-market pages; the sidebar always uses moneyline.
  const isMarketPage =
    window.location.href.includes("/markets/") ||
    window.location.href.includes("/events/");

  const marketCtx = isMarketPage
    ? detectMarketContext(pageText)
    : { type: "moneyline", line: null, spreadTeam: null };

  // Resolve the spread team string (e.g. "LA Lakers") to an abbreviation if possible
  const spreadTeamAbbrev = marketCtx.spreadTeam
    ? findTeamAbbrev(marketCtx.spreadTeam) || marketCtx.spreadTeam
    : null;

  // Build a cache key that encodes the full market context so different markets on the
  // same teams don't collide (e.g. moneyline vs. spread vs. total).
  const marketSuffix =
    marketCtx.type !== "moneyline"
      ? `:${marketCtx.type}:${marketCtx.line}`
      : "";

  // Fetch predictions for any NEW games we haven't seen yet
  const fetchPromises = uniqueMatchups.map(async (m) => {
    const cacheKey = m.key + marketSuffix;
    if (!predictionCache[cacheKey]) {
      const data = await getPrediction(
        m.awayAbbrev,
        m.homeAbbrev,
        marketCtx.type,
        marketCtx.line,
        spreadTeamAbbrev,
      );
      if (data) predictionCache[cacheKey] = data;
    }
  });

  // Wait for all missing predictions to load
  await Promise.all(fetchPromises);

  // Smart DOM Traverser: Finds the exact button/box containing the team name and extracts the price
  const getMarketProbFromDOM = (
    predictedFullName,
    locationName,
    opponentName,
  ) => {
    const elements = document.querySelectorAll("*");
    for (const el of elements) {
      if (el.children.length === 0) {
        const text = el.textContent.trim();
        if (text.includes(predictedFullName) || text === locationName) {
          let parent = el.parentElement;

          // Traverse up to 8 levels to find the box holding the entire team row
          for (let i = 0; i < 8; i++) {
            if (!parent) break;

            // If the box is so big it includes the OPPONENT's name, stop! We only want this team's specific odds.
            if (
              opponentName &&
              parent.textContent.includes(opponentName) &&
              !el.textContent.includes(opponentName)
            )
              break;

            // 1. Single Game Page Target: The large percentage display (e.g., 75%)
            const percentNode = parent.querySelector("h2.typ-headline-x10");
            if (percentNode && percentNode.textContent.includes("%")) {
              return percentNode.textContent.trim();
            }

            // 2. Main Feed Page Target (Sidebar): The numbers inside the odds button
            const tabularNumNodes =
              parent.querySelectorAll("span.tabular-nums");
            if (tabularNumNodes.length > 0) {
              // Iterate backwards to check the right-most values first
              for (let j = tabularNumNodes.length - 1; j >= 0; j--) {
                let val = tabularNumNodes[j].textContent.trim();

                // Skip the payout multipliers which contain decimals or an 'x' (e.g., 1.83 or 1.83x)
                if (val.includes(".") || val.toLowerCase().includes("x")) {
                  continue;
                }

                // Kalshi leaves the % off in the HTML text here, so we add it manually
                return val.includes("%") ? val : val + "%";
              }
            }

            // 3. Fallback Target: Look for the order book price format (e.g., 55¢ or 55c)
            const priceMatch = parent.textContent.match(
              /\b([1-9][0-9]?)[¢c]\b/i,
            );
            if (priceMatch) return priceMatch[1] + "%";

            parent = parent.parentElement;
          }
        }
      }
    }
    return "--";
  };

  if (isMarketPage || uniqueMatchups.length === 1) {
    // SINGLE GAME MODE: Hide the sidebar, show the detailed card
    removeSidebar();
    let mainMatch = uniqueMatchups[0]; // Fallback to the first found game

    // If we are on a market page, find the exact game by checking the URL for the team abbreviations
    if (isMarketPage) {
      // Clean the URL to easily search for the Away+Home ticker (e.g., "INDCHA")
      const currentUrlUpper = window.location.href
        .toUpperCase()
        .replace(/[-_]/g, "");
      for (const m of uniqueMatchups) {
        if (currentUrlUpper.includes(m.awayAbbrev + m.homeAbbrev)) {
          mainMatch = m;
          break;
        }
      }
    }

    const data = predictionCache[mainMatch.key + marketSuffix];
    if (data) {
      // For moneyline, find the predicted winner's name/location for DOM prob extraction.
      // For spread/total the market prob is for the Yes contract on the line, same logic.
      const winnerAbbrev =
        data.predicted_winner || data.spread_team || mainMatch.homeAbbrev;
      const predictedFullName = fullTeamNames[winnerAbbrev] || winnerAbbrev;
      const locationName =
        winnerAbbrev === mainMatch.awayAbbrev
          ? mainMatch.awayLocation
          : mainMatch.homeLocation;
      const opponentAbbrev =
        winnerAbbrev === mainMatch.awayAbbrev
          ? mainMatch.homeAbbrev
          : mainMatch.awayAbbrev;
      const opponentFullName = fullTeamNames[opponentAbbrev] || opponentAbbrev;

      data.marketProb = getMarketProbFromDOM(
        predictedFullName,
        locationName,
        opponentFullName,
      );

      injectPredictionCard(
        document.body,
        data,
        fullTeamNames[mainMatch.homeAbbrev],
      );
    }
  } else {
    // MAIN PAGE MODE: sidebar always shows moneyline rankings
    removeSingleCard();

    const rankingData = uniqueMatchups
      .map((m) => {
        const data = predictionCache[m.key]; // sidebar is always moneyline (no suffix)
        if (data) {
          const predictedFullName =
            fullTeamNames[data.predicted_winner] || data.predicted_winner;
          const locationName =
            data.predicted_winner === m.awayAbbrev
              ? m.awayLocation
              : m.homeLocation;

          const opponentAbbrev =
            data.predicted_winner === m.awayAbbrev
              ? m.homeAbbrev
              : m.awayAbbrev;
          const opponentFullName =
            fullTeamNames[opponentAbbrev] || opponentAbbrev;

          return {
            ...data,
            marketProb: getMarketProbFromDOM(
              predictedFullName,
              locationName,
              opponentFullName,
            ),
          };
        }
        return null;
      })
      .filter((data) => data != null);

    // Sort highest probabilities to the top
    rankingData.sort((a, b) => b.win_probability - a.win_probability);

    injectSidebar(document.body, rankingData);
  }
}

// Run the scanner every 3 seconds to catch dynamic page loads
setInterval(scanForMatchups, 3000);
