// ══════════════════════════════════════════════════════
//  GLOBALER STATE
// ══════════════════════════════════════════════════════
const API = '';
let currentDate = new Date().toISOString().slice(0, 10);
let teamNames = [];

// Auto-Refresh State
let _autoRefreshTimer = null;
let _lastScoresLoad   = null;
let _nextRefreshAt    = null;

// ══════════════════════════════════════════════════════
//  NAVIGATION
// ══════════════════════════════════════════════════════
function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  document.getElementById('nav-' + id).classList.add('active');

  const loaders = {
    standings: loadStandings,
    scores: loadScores,
    bets: loadBetsDashboard,
  };
  if (loaders[id]) loaders[id]();
}

// ══════════════════════════════════════════════════════
//  FETCH HELPER
// ══════════════════════════════════════════════════════
async function apiFetch(url) {
  const res = await fetch(API + url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function errorHtml(msg) {
  return `<div class="error-msg">⚠ ${msg}</div>`;
}
function loadingHtml(text = 'Lade Daten...') {
  return `<div class="loading"><div class="spinner"></div>${text}</div>`;
}

// ══════════════════════════════════════════════════════
//  AUTO-REFRESH SYSTEM
// ══════════════════════════════════════════════════════

// NBA Spielzeiten (MEZ): typisch 01:00–07:00 Uhr.
// Außerhalb dieser Zeiten wird kein automatischer Refresh ausgelöst
// um API-Limits (Free Tier) zu schonen. Scores-Only – Odds nie automatisch.
const GAME_HOURS = { start: 1, end: 7 };
const SCORES_REFRESH_MS = 5 * 60 * 1000; // 5 min während laufender Spiele

function isGameTime() {
  const h = new Date().getHours();
  return h >= GAME_HOURS.start && h < GAME_HOURS.end;
}

function msUntilNextGameTime() {
  const next = new Date();
  next.setHours(GAME_HOURS.start, 0, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  return next - new Date();
}

function scheduleScoresRefresh() {
  if (_autoRefreshTimer) clearTimeout(_autoRefreshTimer);
  _nextRefreshAt = null;
  if (isGameTime()) {
    _nextRefreshAt = Date.now() + SCORES_REFRESH_MS;
    _autoRefreshTimer = setTimeout(() => {
      loadScores(true).catch(() => {}).finally(scheduleScoresRefresh);
    }, SCORES_REFRESH_MS);
  } else {
    // Schläft bis 01:00 MEZ, dann erste Aktualisierung
    _autoRefreshTimer = setTimeout(scheduleScoresRefresh, msUntilNextGameTime());
  }
  updateRefreshStatus();
}

function updateRefreshStatus() {
  const el = document.getElementById('refresh-status');
  if (!el) return;
  if (!_lastScoresLoad) { el.textContent = ''; return; }
  const lastStr = _lastScoresLoad.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  if (!isGameTime()) {
    el.textContent = `↻ ${lastStr} · keine Spiele`;
    return;
  }
  const nextMs  = _nextRefreshAt ? Math.max(0, _nextRefreshAt - Date.now()) : 0;
  const nextMin = nextMs < 90000 ? '<1' : Math.round(nextMs / 60000);
  el.textContent = `↻ ${lastStr} · nächste in ${nextMin} min`;
}

// ══════════════════════════════════════════════════════
//  STANDINGS
// ══════════════════════════════════════════════════════
async function loadStandings() {
  const el = document.getElementById('standings-content');
  el.innerHTML = loadingHtml('Lade Standings...');
  try {
    const teams = await apiFetch('/api/standings');
    teamNames = teams.map(t => t.name);
    updateTeamList();

    const rows = teams.map((t, i) => {
      const wr = t.win_rate * 100;
      const fill = wr > 60 ? 'var(--green)' : wr > 45 ? 'var(--blue)' : 'var(--red)';
      const pd = t.pt_diff > 0 ? `+${t.pt_diff}` : t.pt_diff;
      return `
      <tr>
        <td class="rank">${i + 1}</td>
        <td class="team-name">${t.name}</td>
        <td><span style="color:var(--text1);font-weight:600">${t.wins}</span> – <span style="color:var(--text3)">${t.losses}</span></td>
        <td>
          <div class="wr-bar">
            <div class="wr-track"><div class="wr-fill" style="width:${wr}%;background:${fill}"></div></div>
            <div class="wr-pct">${wr.toFixed(0)}%</div>
          </div>
        </td>
        <td class="highlight">${t.pts}</td>
        <td class="${t.pt_diff >= 0 ? 'green' : 'red'}">${pd}</td>
        <td>${(t.home_wr * 100).toFixed(0)}%</td>
        <td>${(t.away_wr * 100).toFixed(0)}%</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th>#</th><th>Team</th><th>W–L</th><th style="min-width:160px">Win%</th>
        <th>Ø Pts</th><th>Diff</th><th>Heim</th><th>Ausw.</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
}

// ══════════════════════════════════════════════════════
//  SCORES
// ══════════════════════════════════════════════════════
function initScores() {
  document.getElementById('date-display').textContent = formatDate(currentDate);
  document.getElementById('scores-sub').textContent = currentDate === new Date().toISOString().slice(0, 10) ? 'Heute' : currentDate;
}

function changeDate(delta) {
  const d = new Date(currentDate);
  d.setDate(d.getDate() + delta);
  currentDate = d.toISOString().slice(0, 10);
  document.getElementById('date-display').textContent = formatDate(currentDate);
  document.getElementById('scores-sub').textContent = currentDate;
  loadScores();
}

function formatDate(s) {
  const d = new Date(s + 'T12:00:00');
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: 'short', year: 'numeric' });
}

function buildGameCard(g) {
  const haScore    = g.home_score > 0 || g.away_score > 0;
  const scoreHtml  = haScore
    ? `${g.home_score} <span style="color:var(--text3)">–</span> ${g.away_score}`
    : `<span style="color:var(--text3);font-size:22px">${g.date?.slice(11, 16) || '–'}</span>`;
  const statusClass = g.is_live ? 'live-s' : g.is_final ? 'final-s' : 'sched-s';
  const statusText  = g.is_live ? '● LIVE' : g.is_final ? '✓ FINAL' : '◷ GEPLANT';
  const winMark = side => g.winner && g.winner.includes(side) ? '<span class="winner-mark"> ★</span>' : '';
  const homeAbbr  = abbr(g.home);
  const awayAbbr  = abbr(g.away);
  const gameDate  = g.date?.slice(0, 10) || currentDate;

  return `
  <div id="game-card-${g.id}" class="game-card ${g.is_live ? 'live' : ''}" onclick="quickPredict('${g.home}','${g.away}')">
    <div class="game-status ${statusClass}">${statusText}</div>
    <button class="game-refresh-btn" title="Spiel aktualisieren"
      onclick="event.stopPropagation();refreshGame(${g.id},'${gameDate}',this)">↻</button>
    <div class="game-matchup">
      <div class="game-team">
        <div class="team-abbr">${homeAbbr}${winMark(g.home)}</div>
        <div class="team-full">${g.home}</div>
      </div>
      <div class="game-score">${scoreHtml}</div>
      <div class="game-team">
        <div class="team-abbr">${awayAbbr}${winMark(g.away)}</div>
        <div class="team-full">${g.away}</div>
      </div>
    </div>
    <div class="game-time">Auf KI-Vorhersage klicken</div>
  </div>`;
}

async function refreshGame(gameId, gameDate, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
  try {
    const games = await apiFetch(`/api/scores?date=${gameDate}`);
    const game  = games.find(g => g.id === gameId);
    if (game) {
      const card = document.getElementById(`game-card-${gameId}`);
      if (card) card.outerHTML = buildGameCard(game);
    } else {
      if (btn) { btn.disabled = false; btn.textContent = '↻'; }
    }
  } catch {
    if (btn) { btn.disabled = false; btn.textContent = '↻'; }
  }
}

async function loadScores(silent = false) {
  const el = document.getElementById('scores-content');
  if (!silent) el.innerHTML = loadingHtml('Lade Spiele...');
  try {
    const games = await apiFetch(`/api/scores?date=${currentDate}`);
    _lastScoresLoad = new Date();
    scheduleScoresRefresh();
    if (!games.length) {
      el.innerHTML = `<div class="empty-msg"><div class="empty-icon">📅</div><div class="empty-text">Keine Spiele an diesem Tag</div></div>`;
      return;
    }
    el.innerHTML = `<div class="games-grid">${games.map(buildGameCard).join('')}</div>`;
  } catch (e) {
    if (!silent) el.innerHTML = errorHtml(e.message);
  }
}

function abbr(name) {
  const map = {
    'Los Angeles Lakers': 'LAL', 'Boston Celtics': 'BOS', 'Golden State Warriors': 'GSW',
    'Miami Heat': 'MIA', 'Chicago Bulls': 'CHI', 'Brooklyn Nets': 'BKN', 'New York Knicks': 'NYK',
    'Milwaukee Bucks': 'MIL', 'Phoenix Suns': 'PHX', 'Denver Nuggets': 'DEN',
    'Philadelphia 76ers': 'PHI', 'Toronto Raptors': 'TOR', 'Dallas Mavericks': 'DAL',
    'Los Angeles Clippers': 'LAC', 'San Antonio Spurs': 'SAS', 'Oklahoma City Thunder': 'OKC',
    'Utah Jazz': 'UTA', 'Atlanta Hawks': 'ATL', 'Cleveland Cavaliers': 'CLE',
    'Detroit Pistons': 'DET', 'Minnesota Timberwolves': 'MIN', 'Indiana Pacers': 'IND',
    'Charlotte Hornets': 'CHA', 'Washington Wizards': 'WAS', 'Orlando Magic': 'ORL',
    'Portland Trail Blazers': 'POR', 'Memphis Grizzlies': 'MEM', 'New Orleans Pelicans': 'NOP',
    'Sacramento Kings': 'SAC', 'Houston Rockets': 'HOU',
  };
  return map[name] || name.split(' ').map(w => w[0]).join('').slice(0, 3).toUpperCase();
}

function quickPredict(home, away) {
  document.getElementById('pred-home').value = home;
  document.getElementById('pred-away').value = away;
  showPage('predict');
  setTimeout(() => runPrediction(), 100);
}

// ══════════════════════════════════════════════════════
//  PREDICT
// ══════════════════════════════════════════════════════
function predInputChanged() {
  const h = document.getElementById('pred-home').value.trim();
  const a = document.getElementById('pred-away').value.trim();
  document.getElementById('pred-btn').disabled = !h || !a;
}

async function runPrediction() {
  const home = document.getElementById('pred-home').value.trim();
  const away = document.getElementById('pred-away').value.trim();
  const mode = document.getElementById('pred-mode').value;
  if (!home || !away) return;

  const resultEl = document.getElementById('predict-result');
  resultEl.className = 'predict-result show';
  resultEl.innerHTML = `<div class="card">${loadingHtml('Berechne Vorhersage...')}</div>`;

  try {
    const r = await fetch(API + '/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ home, away, ml: mode === 'ml' })
    });
    const d = await r.json();
    if (d.error) { resultEl.innerHTML = `<div class="card">${errorHtml(d.error)}</div>`; return; }
    renderPrediction(d, resultEl);
  } catch (e) {
    resultEl.innerHTML = `<div class="card">${errorHtml(e.message)}</div>`;
  }
}

function renderPrediction(d, el) {
  const homeProb = d.ml_home_prob ?? d.rule_home_prob;
  const awayProb = 1 - homeProb;
  const hPct = (homeProb * 100).toFixed(1);
  const aPct = (awayProb * 100).toFixed(1);

  const mlColor = '#ff5f1f';
  const ruleColor = '#1e90ff';
  const oddsColor = '#ffc107';

  const mlWinner = d.ml_predicted_winner === 'home' ? d.home : d.away;
  const ruleWinner = d.rule_predicted_winner === 'home' ? d.home : d.away;
  const oddsWinner = d.odds_home_prob ? (d.odds_home_prob >= 0.5 ? d.home : d.away) : null;

  const methods = [
    { label: 'ML-MODELL', color: mlColor, winner: mlWinner, hp: d.ml_home_prob, ap: d.ml_away_prob, available: d.ml_home_prob !== null },
    { label: 'REGELMODELL', color: ruleColor, winner: ruleWinner, hp: d.rule_home_prob, ap: d.rule_away_prob, available: true },
    { label: 'WETTQUOTEN', color: oddsColor, winner: oddsWinner, hp: d.odds_home_prob, ap: d.odds_away_prob, available: d.odds_home_prob !== null, raw: d.odds_home_raw ? `${d.odds_home_raw} / ${d.odds_away_raw}` : null },
  ];

  const probBars = methods.map(m => {
    if (!m.available) return `
      <div class="prob-row">
        <div class="prob-label">
          <div class="prob-method" style="color:${m.color}">${m.label}</div>
          <div style="font-size:12px;color:var(--text3);font-family:var(--mono)">nicht verfügbar</div>
        </div>
      </div>`;
    const hp = (m.hp * 100).toFixed(1);
    const ap = (m.ap * 100).toFixed(1);
    return `
      <div class="prob-row">
        <div class="prob-label">
          <div class="prob-method" style="color:${m.color}">${m.label}${m.raw ? ` · ${m.raw}` : ''}</div>
          <div class="prob-values">
            <span style="color:var(--blue2)">${d.home} ${hp}%</span>
            <span style="color:var(--text3)">vs</span>
            <span style="color:var(--orange2)">${d.away} ${ap}%</span>
          </div>
        </div>
        <div class="prob-track">
          <div class="prob-home" style="width:${hp}%;background:linear-gradient(90deg,var(--blue),var(--blue2));font-size:${hp > 15 ? '13px' : '0'}px;">${hp}%</div>
          <div class="prob-away" style="width:${ap}%;background:linear-gradient(90deg,var(--orange),var(--orange2));font-size:${ap > 15 ? '13px' : '0'}px;">${ap}%</div>
        </div>
      </div>`;
  }).join('');

  let factorsHtml = '';
  if (d.factors && Object.keys(d.factors).length) {
    const rows = Object.entries(d.factors).map(([k, v]) => {
      const pct = (v * 100).toFixed(0);
      const col = v > 0.5 ? 'var(--blue)' : v < 0.5 ? 'var(--orange)' : 'var(--text3)';
      return `
        <div class="factor-row">
          <div class="factor-name">${k}</div>
          <div class="factor-bar-wrap"><div class="factor-bar-fill" style="width:${pct}%;background:${col}"></div></div>
          <div class="factor-val">${pct}%</div>
        </div>`;
    }).join('');
    factorsHtml = `
      <div style="margin-top:24px;">
        <div class="card-title">Einflussfaktoren (Regelmodell)</div>
        <div class="factors-grid">${rows}</div>
      </div>`;
  }

  const agree = d.agreement ?? 2;
  const consensusWinner = d.consensus === 'home' ? d.home : d.away;
  const agreeIcon = agree >= 2 ? '✅' : '⚠️';
  const agreeColor = agree >= 2 ? 'var(--green)' : 'var(--orange)';

  el.innerHTML = `
  <div class="card">
    <div class="matchup-header">
      <div class="matchup-team">
        <div class="matchup-name">${d.home}</div>
        <div class="matchup-record">Heimteam</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
        <div class="matchup-vs">VS</div>
        <div class="matchup-score">
          <span style="color:var(--blue2)">${d.home_score?.toFixed(0) ?? '–'}</span>
          <span class="score-sep">:</span>
          <span style="color:var(--orange2)">${d.away_score?.toFixed(0) ?? '–'}</span>
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono)">geschätztes Ergebnis</div>
      </div>
      <div class="matchup-team">
        <div class="matchup-name">${d.away}</div>
        <div class="matchup-record">Auswärtsteam</div>
      </div>
    </div>

    <div class="prob-section">${probBars}</div>

    <div class="consensus-box" style="border:1px solid ${agreeColor}33">
      <div class="consensus-icon">${agreeIcon}</div>
      <div>
        <div class="consensus-label">Konsens · ${agree}/3 Methoden einig</div>
        <div class="consensus-winner">${consensusWinner}</div>
        <div class="consensus-sub">${d.ml_confidence ?? ''}</div>
      </div>
    </div>

    ${factorsHtml}
  </div>`;
}

// ══════════════════════════════════════════════════════
//  COMPARE (MIT WETTEMPFEHLUNG + WETTE PLATZIEREN)
// ══════════════════════════════════════════════════════
async function loadCompare() {
  const el = document.getElementById('compare-content');
  const home = document.getElementById('cmp-home').value.trim();
  const away = document.getElementById('cmp-away').value.trim();
  el.innerHTML = loadingHtml('Lade Vergleichsdaten...');

  try {
    let url = '/api/compare';
    if (home && away) url += `?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}`;
    const entries = await apiFetch(url);

    if (!entries.length) {
      el.innerHTML = `<div class="empty-msg"><div class="empty-icon">📊</div><div class="empty-text">Keine Vergleichsdaten – ODDS_API_KEY gesetzt?</div></div>`;
      return;
    }

    // Speichere Daten global für placeBet
    window._compareEntries = entries;

    const cards = entries.map((e, idx) => {
      const hp = (e.ml_home * 100).toFixed(1);
      const ap = (e.ml_away * 100).toFixed(1);
      const ohp = (e.odds_home * 100).toFixed(1);
      const oap = (e.odds_away * 100).toFixed(1);
      const diff = (e.diff * 100).toFixed(1);
      const diffClass = e.diff > 0.10 ? 'diff-big' : 'diff-small';
      const agreeClass = e.agree ? 'agree' : 'disagree';

      // Wettempfehlung
      const rating = e.bet_rating || 'none';
      const evPct = ((e.bet_ev || 0) * 100).toFixed(1);
      const edgePct = ((e.bet_edge || 0) * 100).toFixed(1);
      const conf = e.bet_confidence || 0;
      const confColor = conf >= 60 ? 'var(--green)' : conf >= 30 ? 'var(--blue2)' : 'var(--text3)';
      const evClass = e.bet_ev > 0 ? 'positive' : e.bet_ev < 0 ? 'negative' : '';

      const betHtml = `
        <div class="bet-recommendation bet-${rating}">
          <div class="bet-header">
            <div class="bet-label bet-${rating}">${e.bet_rating_label || '⏸️ Kein Value'}</div>
            <div style="display:flex;align-items:center;gap:6px;">
              <span style="font-size:10px;color:var(--text3);font-family:var(--mono)">${conf}%</span>
              <div class="bet-confidence-bar">
                <div class="bet-confidence-fill" style="width:${conf}%;background:${confColor}"></div>
              </div>
            </div>
          </div>
          ${rating !== 'none' ? `
          <div style="margin-bottom:10px;">
            <span style="font-size:10px;color:var(--text3);font-family:var(--head);font-weight:700;letter-spacing:1px;text-transform:uppercase">Wette auf</span>
            <span class="bet-team-name" style="margin-left:6px">${e.bet_team}</span>
            <span style="font-family:var(--mono);font-size:11px;color:var(--text3);margin-left:6px">@ ${e.bet_odds_raw}</span>
          </div>` : ''}
          <div class="bet-details">
            <div class="bet-detail">
              <div class="bet-detail-label">Expected Value</div>
              <div class="bet-detail-value ${evClass}">${e.bet_ev > 0 ? '+' : ''}${evPct}%</div>
            </div>
            <div class="bet-detail">
              <div class="bet-detail-label">Edge</div>
              <div class="bet-detail-value">${e.bet_edge > 0 ? '+' : ''}${edgePct}%</div>
            </div>
            <div class="bet-detail">
              <div class="bet-detail-label">KI vs Quote</div>
              <div class="bet-detail-value">${((e.bet_ml_prob || 0) * 100).toFixed(1)}% / ${((e.bet_odds_prob || 0) * 100).toFixed(1)}%</div>
            </div>
          </div>
          ${rating !== 'none' ? `
          <button class="btn btn-primary" style="margin-top:10px;width:100%;font-size:12px;padding:8px"
            onclick="placeBetFromCompare(${idx})">
            💰 Wette platzieren (${e.bet_team} @ ${e.bet_odds_raw})
          </button>` : ''}
        </div>`;

      return `
      <div class="compare-card ${agreeClass}">
        <div class="compare-teams">${e.home} <span style="color:var(--text3)">vs</span> ${e.away}</div>
        <div class="compare-bars">
          <div class="compare-bar-row">
            <div class="compare-bar-label" style="color:var(--orange)">KI</div>
            <div class="compare-bar-track">
              <div class="prob-home" style="width:${hp}%;background:linear-gradient(90deg,var(--blue),var(--blue2));font-size:11px;">${hp}%</div>
              <div class="prob-away" style="width:${ap}%;background:linear-gradient(90deg,var(--orange),var(--orange2));font-size:11px;">${ap}%</div>
            </div>
          </div>
          <div class="compare-bar-row">
            <div class="compare-bar-label" style="color:var(--gold)">Odds</div>
            <div class="compare-bar-track">
              <div class="prob-home" style="width:${ohp}%;background:linear-gradient(90deg,#1a6b3a,var(--green));font-size:11px;">${ohp}%</div>
              <div class="prob-away" style="width:${oap}%;background:linear-gradient(90deg,#6b1a1a,#ff6b6b);font-size:11px;">${oap}%</div>
            </div>
          </div>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
          <div class="compare-diff ${diffClass}">Δ ${diff}% · ${e.indicator}</div>
          <div style="font-size:11px;color:${e.agree ? 'var(--green)' : 'var(--orange)'}">
            ${e.agree ? '✓ Einig' : '⚠ Uneinig'}
          </div>
        </div>
        ${e.odds_home_raw ? `<div style="font-size:10px;color:var(--text3);font-family:var(--mono);margin-top:6px">Quote: ${e.odds_home_raw} / ${e.odds_away_raw}</div>` : ''}
        ${betHtml}
      </div>`;
    }).join('');

    const agreeCount = entries.filter(e => e.agree).length;
    const avgDiff = entries.reduce((s, e) => s + e.diff, 0) / entries.length;
    const valueBets = entries.filter(e => e.bet_rating && e.bet_rating !== 'none').length;
    const strongBets = entries.filter(e => e.bet_rating === 'strong' || e.bet_rating === 'good').length;

    el.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px;">
      <div class="stat-badge"><div class="stat-val">${entries.length}</div><div class="stat-lbl">Spiele verglichen</div></div>
      <div class="stat-badge"><div class="stat-val" style="color:var(--green)">${agreeCount}</div><div class="stat-lbl">KI & Quoten einig</div></div>
      <div class="stat-badge"><div class="stat-val">${(avgDiff * 100).toFixed(1)}%</div><div class="stat-lbl">Ø Abweichung</div></div>
      <div class="stat-badge"><div class="stat-val" style="color:var(--orange)">${valueBets}</div><div class="stat-lbl">Value Bets${strongBets ? ` (${strongBets} stark)` : ''}</div></div>
    </div>
    ${valueBets > 0 ? `<div style="background:rgba(255,95,31,0.08);border:1px solid rgba(255,95,31,0.2);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:12px;color:var(--text2);font-family:var(--mono);">
      ⚠️ Wettempfehlungen basieren auf dem KI-Modell und garantieren keine Gewinne. Wette verantwortungsvoll.
    </div>` : ''}
    <div class="compare-row-grid">${cards}</div>`;
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
}

// ══════════════════════════════════════════════════════
//  BETTING TRACKER
// ══════════════════════════════════════════════════════

function showBetsTab(tab) {
  document.querySelectorAll('.bets-tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.bets-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('bets-tab-' + tab).style.display = 'block';
  document.getElementById('btab-' + tab).classList.add('active');

  if (tab === 'dashboard') loadBetsDashboard();
  else if (tab === 'open') loadOpenBets();
  else if (tab === 'history') loadBetsHistory();
  else if (tab === 'analytics') loadBetsAnalytics();
  else if (tab === 'versions') loadVersionComparison();
}

async function loadBetsDashboard() {
  const el = document.getElementById('bets-tab-dashboard');
  el.innerHTML = loadingHtml('Lade Statistiken...');
  try {
    const stats = await apiFetch('/api/bets/stats');

    if (stats.total_bets === 0) {
      el.innerHTML = `
        <div class="empty-msg">
          <div class="empty-icon">💰</div>
          <div class="empty-text">Noch keine Wetten platziert</div>
          <div style="color:var(--text3);margin-top:8px;font-family:var(--mono);font-size:12px">
            Gehe zu ⚖️ Quoten → Vergleichen und klicke "Wette platzieren"
          </div>
        </div>`;
      return;
    }

    const profitColor = stats.total_profit >= 0 ? 'var(--green)' : 'var(--red)';
    const roiColor = stats.roi >= 0 ? 'var(--green)' : 'var(--red)';
    const streakText = stats.current_streak > 0 ? `${stats.current_streak}W 🔥` :
      stats.current_streak < 0 ? `${Math.abs(stats.current_streak)}L ❄️` : '–';

    const ratingLabels = { strong: '🔥 Stark', good: '✅ Gut', slight: '💡 Leicht', none: '⏸️ Kein' };
    let ratingHtml = '';
    if (stats.record_by_rating) {
      ratingHtml = Object.entries(stats.record_by_rating).map(([rating, r]) => `
        <div class="rating-card">
          <div class="rating-card-title">${ratingLabels[rating] || rating}</div>
          <div style="font-family:var(--mono);font-size:13px;color:var(--text1)">${r.won}W / ${r.lost}L</div>
          <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin-top:4px">
            Profit: <span style="color:${r.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${r.profit >= 0 ? '+' : ''}${r.profit}</span>
            · ROI: ${r.roi >= 0 ? '+' : ''}${r.roi}%
          </div>
        </div>
      `).join('');
    }

    el.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:14px;margin-bottom:20px;">
        <div class="stat-badge"><div class="stat-val">${stats.won}W/${stats.lost}L</div><div class="stat-lbl">Bilanz</div></div>
        <div class="stat-badge"><div class="stat-val" style="color:${profitColor}">${stats.total_profit >= 0 ? '+' : ''}${stats.total_profit.toFixed(1)}</div><div class="stat-lbl">Profit</div></div>
        <div class="stat-badge"><div class="stat-val" style="color:${roiColor}">${stats.roi >= 0 ? '+' : ''}${stats.roi.toFixed(1)}%</div><div class="stat-lbl">ROI</div></div>
        <div class="stat-badge"><div class="stat-val">${(stats.win_rate * 100).toFixed(0)}%</div><div class="stat-lbl">Win-Rate</div></div>
        <div class="stat-badge"><div class="stat-val">${stats.avg_odds.toFixed(2)}</div><div class="stat-lbl">Ø Quote</div></div>
        <div class="stat-badge"><div class="stat-val">${streakText}</div><div class="stat-lbl">Serie</div></div>
        <div class="stat-badge"><div class="stat-val">${stats.open_bets}</div><div class="stat-lbl">Offen</div></div>
        <div class="stat-badge"><div class="stat-val">${stats.total_staked.toFixed(0)}</div><div class="stat-lbl">Gesamt gesetzt</div></div>
      </div>

      <div class="card" style="margin-bottom:16px">
        <div class="card-title">Profit nach Empfehlungsstufe</div>
        <div class="rating-breakdown">${ratingHtml || '<div style="color:var(--text3)">Noch keine Daten</div>'}</div>
      </div>

      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="resolveAllBets()">🔄 Offene Wetten auflösen</button>
        <button class="btn btn-secondary" onclick="confirmResetBets()">🗑️ Alle löschen</button>
      </div>
    `;
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
}

async function loadOpenBets() {
  const el = document.getElementById('bets-tab-open');
  el.innerHTML = loadingHtml('Lade offene Wetten...');
  try {
    const bets = await apiFetch('/api/bets?status=open');
    if (!bets.length) {
      el.innerHTML = `<div class="empty-msg"><div class="empty-icon">✅</div><div class="empty-text">Keine offenen Wetten</div></div>`;
      return;
    }
    el.innerHTML = `<div class="bets-grid">${bets.map(renderBetCard).join('')}</div>`;
  } catch (e) { el.innerHTML = errorHtml(e.message); }
}

async function loadBetsHistory(filterVersion = '') {
  const el = document.getElementById('bets-tab-history');
  el.innerHTML = loadingHtml('Lade Wett-Historie...');
  try {
    const bets = await apiFetch('/api/bets');
    if (!bets.length) {
      el.innerHTML = `<div class="empty-msg"><div class="empty-icon">📊</div><div class="empty-text">Noch keine Wetten</div></div>`;
      return;
    }

    // Alle verfügbaren Versionen für Filter-Dropdown
    const versions = [...new Set(bets.map(b => b.model_version).filter(Boolean))].sort();
    const activeFilter = filterVersion || '';
    const filtered = activeFilter ? bets.filter(b => b.model_version === activeFilter) : bets;

    const versionOpts = `<option value="">Alle Versionen (${bets.length})</option>` +
      versions.map(v => {
        const count = bets.filter(b => b.model_version === v).length;
        return `<option value="${v}" ${v === activeFilter ? 'selected' : ''}>${v} (${count})</option>`;
      }).join('');

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">
        <label style="font-size:12px;color:var(--text3)">Version:</label>
        <select onchange="loadBetsHistory(this.value)" style="min-width:200px">${versionOpts}</select>
        <span style="font-size:12px;color:var(--text3);font-family:var(--mono)">${filtered.length} Wette${filtered.length !== 1 ? 'n' : ''}</span>
      </div>
      <div class="bets-grid">${filtered.map(renderBetCard).join('')}</div>`;
  } catch (e) { el.innerHTML = errorHtml(e.message); }
}

function renderBetCard(b) {
  const profitClass = b.profit > 0 ? 'bet-profit-positive' : b.profit < 0 ? 'bet-profit-negative' : '';
  const statusClass = b.status;
  const statusLabel = b.status === 'won' ? '✓ Gewonnen' : b.status === 'lost' ? '✗ Verloren' : '◷ Offen';

  return `
    <div class="bet-card bet-${statusClass}">
      <div class="bet-card-header">
        <div class="bet-card-matchup">${b.home_team} <span style="color:var(--text3)">vs</span> ${b.away_team}</div>
        <div class="bet-card-status ${statusClass}">${statusLabel}</div>
      </div>
      <div style="font-size:12px;color:var(--orange);font-family:var(--head);font-weight:700;margin-bottom:8px">
        Wette auf: ${b.bet_on} @ ${b.odds.toFixed(2)}
      </div>
      <div class="bet-card-body">
        <div class="bet-card-stat">
          <div class="bet-card-stat-label">Einsatz</div>
          <div class="bet-card-stat-value">${b.stake.toFixed(1)}</div>
        </div>
        <div class="bet-card-stat">
          <div class="bet-card-stat-label">Edge</div>
          <div class="bet-card-stat-value">${(b.edge * 100).toFixed(1)}%</div>
        </div>
        <div class="bet-card-stat">
          <div class="bet-card-stat-label">EV</div>
          <div class="bet-card-stat-value">${(b.ev * 100).toFixed(1)}%</div>
        </div>
        <div class="bet-card-stat">
          <div class="bet-card-stat-label">Profit</div>
          <div class="bet-card-stat-value ${profitClass}">${b.status !== 'open' ? (b.profit >= 0 ? '+' : '') + b.profit.toFixed(1) : '–'}</div>
        </div>
      </div>
      ${b.actual_winner ? `
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);margin-top:6px;display:flex;gap:12px;flex-wrap:wrap">
          <span>Gewinner: ${b.actual_winner}</span>
          ${b.home_score != null && b.away_score != null
            ? `<span style="color:var(--text2)">${b.home_team} <strong style="color:var(--gold)">${b.home_score}:${b.away_score}</strong> ${b.away_team}</span>`
            : ''}
        </div>` : ''}
      <div class="bet-card-actions">
        ${b.model_version ? `<span class="bet-version-badge">${b.model_version}</span>` : ''}
        <button onclick="deleteBet(${b.id})">Löschen</button>
      </div>
    </div>`;
}

async function placeBetFromCompare(idx) {
  const e = window._compareEntries && window._compareEntries[idx];
  if (!e) { alert('Daten nicht gefunden'); return; }
  try {
    const res = await fetch(API + '/api/bets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        home_team: e.home, away_team: e.away,
        bet_on: e.bet_team, bet_side: e.bet_side,
        odds: e.bet_odds_raw, ml_prob: e.bet_ml_prob,
        odds_prob: e.bet_odds_prob, edge: e.bet_edge,
        ev: e.bet_ev, bet_rating: e.bet_rating, stake: 10.0,
      }),
    });
    const data = await res.json();
    if (data.success) {
      alert(`Wette #${data.bet_id} platziert: ${e.bet_team} @ ${e.bet_odds_raw}`);
    } else {
      alert('Fehler: ' + (data.error || 'Unbekannt'));
    }
  } catch (err) {
    alert('Fehler: ' + err.message);
  }
}

async function resolveAllBets() {
  try {
    const res = await fetch(API + '/api/bets/resolve', { method: 'POST' });
    const data = await res.json();
    alert(`Aufgelöst: ${data.resolved} (${data.won}W / ${data.lost}L)\nNoch offen: ${data.still_open}`);
    loadBetsDashboard();
  } catch (e) { alert('Fehler: ' + e.message); }
}

function confirmResetBets() {
  if (!confirm('ALLE Wetten unwiderruflich löschen?')) return;
  if (!confirm('Wirklich ALLE löschen? Das kann nicht rückgängig gemacht werden.')) return;
  fetch(API + '/api/bets/reset', { method: 'POST' })
    .then(() => loadBetsDashboard())
    .catch(e => alert('Fehler: ' + e.message));
}

async function deleteBet(id) {
  if (!confirm('Wette löschen?')) return;
  try {
    await fetch(API + '/api/bets/' + id, { method: 'DELETE' });
    const activeTab = document.querySelector('.bets-tab.active');
    if (activeTab) activeTab.click();
  } catch (e) { alert('Fehler: ' + e.message); }
}

// ══════════════════════════════════════════════════════
//  BETTING ANALYTICS
// ══════════════════════════════════════════════════════

async function loadBetsAnalytics() {
  const el = document.getElementById('bets-tab-analytics');
  el.innerHTML = loadingHtml('Berechne Analyse...');
  try {
    const a = await apiFetch('/api/bets/analytics');
    if (a.empty) {
      el.innerHTML = `<div class="empty-msg"><div class="empty-icon">📊</div><div class="empty-text">Noch keine aufgelösten Wetten für die Analyse</div></div>`;
      return;
    }

    el.innerHTML = `
      ${renderProfitChart(a.profit_history)}
      ${renderExpectedVsActual(a.expected_vs_actual, a.avg_profit_won, a.avg_profit_lost)}
      ${renderCalibration(a.calibration)}
      ${renderByRating(a.by_rating)}
      ${renderBySide(a.by_side)}
      ${renderByOddsRange(a.by_odds_range)}
      ${renderByEdgeRange(a.by_edge_range)}
      ${renderByTeam(a.by_team)}
      ${renderWeekly(a.weekly)}
      ${renderKelly(a.kelly_analysis)}
    `;
  } catch (e) { el.innerHTML = errorHtml(e.message); }
}

function renderProfitChart(history) {
  if (!history || !history.length) return '';
  const points = history.map((h, i) => {
    const x = (i / Math.max(1, history.length - 1)) * 100;
    const minY = Math.min(...history.map(p => p.cumulative));
    const maxY = Math.max(...history.map(p => p.cumulative));
    const range = maxY - minY || 1;
    const y = 100 - ((h.cumulative - minY) / range) * 100;
    return `${x},${y}`;
  }).join(' ');
  const last = history[history.length - 1];
  const color = last.cumulative >= 0 ? 'var(--green)' : 'var(--red)';
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Kumulativer Profitverlauf</div>
      <svg viewBox="-2 -5 104 110" style="width:100%;height:180px;" preserveAspectRatio="none">
        <line x1="0" y1="50" x2="100" y2="50" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2"/>
        <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
      </svg>
      <div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;color:var(--text3);margin-top:4px">
        <span>Wette #1</span>
        <span style="color:${color}">Aktuell: ${last.cumulative >= 0 ? '+' : ''}${last.cumulative}</span>
        <span>Wette #${history.length}</span>
      </div>
    </div>`;
}

function renderExpectedVsActual(eva, avgWon, avgLost) {
  if (!eva) return '';
  const diffColor = eva.difference >= 0 ? 'var(--green)' : 'var(--red)';
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Erwarteter vs Tatsächlicher Profit</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px">
        <div class="stat-badge"><div class="stat-val" style="font-size:22px">${eva.expected_profit >= 0 ? '+' : ''}${eva.expected_profit}</div><div class="stat-lbl">Erwartet (EV)</div></div>
        <div class="stat-badge"><div class="stat-val" style="font-size:22px;color:${eva.actual_profit >= 0 ? 'var(--green)' : 'var(--red)'}">${eva.actual_profit >= 0 ? '+' : ''}${eva.actual_profit}</div><div class="stat-lbl">Tatsächlich</div></div>
        <div class="stat-badge"><div class="stat-val" style="font-size:22px;color:${diffColor}">${eva.difference >= 0 ? '+' : ''}${eva.difference}</div><div class="stat-lbl">Differenz</div></div>
        <div class="stat-badge"><div class="stat-val" style="font-size:22px;color:var(--green)">+${avgWon}</div><div class="stat-lbl">Ø Gewinn/Wette</div></div>
        <div class="stat-badge"><div class="stat-val" style="font-size:22px;color:var(--red)">${avgLost}</div><div class="stat-lbl">Ø Verlust/Wette</div></div>
      </div>
    </div>`;
}

function renderCalibration(cal) {
  if (!cal || !cal.length) return '';
  const rows = cal.map(c => {
    const diffCol = Math.abs(c.diff) < 0.05 ? 'var(--green)' : Math.abs(c.diff) < 0.10 ? 'var(--gold)' : 'var(--red)';
    return `<tr>
      <td>${c.range}</td><td>${c.bets}</td>
      <td>${(c.predicted_wr * 100).toFixed(1)}%</td>
      <td style="font-weight:600">${(c.actual_wr * 100).toFixed(1)}%</td>
      <td style="color:${diffCol}">${(c.diff * 100).toFixed(1)}%</td>
    </tr>`;
  }).join('');
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Modell-Kalibrierung · KI-Wahrscheinlichkeit vs Realität</div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:12px;font-family:var(--mono)">
        Perfekt kalibriert = Diff nahe 0%. Positiv = Modell unterschätzt, Negativ = Modell überschätzt.
      </div>
      <table class="data-table"><thead><tr>
        <th>KI-Bereich</th><th>Wetten</th><th>Vorhergesagt</th><th>Tatsächlich</th><th>Diff</th>
      </tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

function renderByRating(ratings) {
  if (!ratings || !ratings.length) return '';
  const rows = ratings.map(r => `<tr>
    <td>${r.label}</td><td>${r.bets}</td><td>${r.won}W / ${r.lost}L</td>
    <td>${(r.win_rate * 100).toFixed(0)}%</td>
    <td style="color:${r.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${r.profit >= 0 ? '+' : ''}${r.profit}</td>
    <td style="color:${r.roi >= 0 ? 'var(--green)' : 'var(--red)'}">${r.roi >= 0 ? '+' : ''}${r.roi}%</td>
    <td>${r.avg_odds.toFixed(2)}</td>
    <td>${(r.avg_edge * 100).toFixed(1)}%</td>
  </tr>`).join('');
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Effektivität nach Empfehlungsstufe</div>
      <table class="data-table"><thead><tr>
        <th>Rating</th><th>Wetten</th><th>Bilanz</th><th>Win%</th><th>Profit</th><th>ROI</th><th>Ø Quote</th><th>Ø Edge</th>
      </tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

function renderBySide(sides) {
  if (!sides) return '';
  const row = (label, s) => `<tr>
    <td>${label}</td><td>${s.bets}</td><td>${s.won}W / ${s.lost}L</td>
    <td>${(s.win_rate * 100).toFixed(0)}%</td>
    <td style="color:${s.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${s.profit >= 0 ? '+' : ''}${s.profit}</td>
    <td style="color:${s.roi >= 0 ? 'var(--green)' : 'var(--red)'}">${s.roi >= 0 ? '+' : ''}${s.roi}%</td>
  </tr>`;
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Heim vs Auswärts</div>
      <table class="data-table"><thead><tr>
        <th>Seite</th><th>Wetten</th><th>Bilanz</th><th>Win%</th><th>Profit</th><th>ROI</th>
      </tr></thead><tbody>${row('🏠 Heim', sides.home)}${row('✈️ Auswärts', sides.away)}</tbody></table>
    </div>`;
}

function renderByOddsRange(ranges) {
  return renderRangeTable(ranges, 'Effektivität nach Quotenbereich', 'Quoten');
}
function renderByEdgeRange(ranges) {
  return renderRangeTable(ranges, 'Effektivität nach Edge-Bereich', 'Edge');
}

function renderRangeTable(ranges, title, rangeLabel) {
  if (!ranges || !ranges.length) return '';
  const rows = ranges.map(r => `<tr>
    <td>${r.range}</td><td>${r.bets}</td><td>${r.won}W / ${r.lost}L</td>
    <td>${r.bets ? (r.win_rate * 100).toFixed(0) + '%' : '–'}</td>
    <td style="color:${r.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${r.bets ? (r.profit >= 0 ? '+' : '') + r.profit : '–'}</td>
    <td style="color:${r.roi >= 0 ? 'var(--green)' : 'var(--red)'}">${r.bets ? (r.roi >= 0 ? '+' : '') + r.roi + '%' : '–'}</td>
  </tr>`).join('');
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">${title}</div>
      <table class="data-table"><thead><tr>
        <th>${rangeLabel}</th><th>Wetten</th><th>Bilanz</th><th>Win%</th><th>Profit</th><th>ROI</th>
      </tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

function renderByTeam(teams) {
  if (!teams || !teams.length) return '';
  const rows = teams.slice(0, 15).map(t => `<tr>
    <td class="team-name">${t.team}</td><td>${t.bets}</td><td>${t.won}W / ${t.lost}L</td>
    <td>${(t.win_rate * 100).toFixed(0)}%</td>
    <td style="color:${t.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${t.profit >= 0 ? '+' : ''}${t.profit}</td>
    <td style="color:${t.roi >= 0 ? 'var(--green)' : 'var(--red)'}">${t.roi >= 0 ? '+' : ''}${t.roi}%</td>
  </tr>`).join('');
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Profitabelste Teams</div>
      <table class="data-table"><thead><tr>
        <th>Team</th><th>Wetten</th><th>Bilanz</th><th>Win%</th><th>Profit</th><th>ROI</th>
      </tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

function renderWeekly(weeks) {
  if (!weeks || !weeks.length) return '';
  const rows = weeks.map(w => `<tr>
    <td>${w.week}</td><td>${w.bets}</td><td>${w.won}W / ${w.lost}L</td>
    <td style="color:${w.profit >= 0 ? 'var(--green)' : 'var(--red)'}">${w.profit >= 0 ? '+' : ''}${w.profit}</td>
    <td style="color:${w.roi >= 0 ? 'var(--green)' : 'var(--red)'}">${w.roi >= 0 ? '+' : ''}${w.roi}%</td>
    <td style="font-weight:600;color:${w.cumulative >= 0 ? 'var(--green)' : 'var(--red)'}">${w.cumulative >= 0 ? '+' : ''}${w.cumulative}</td>
  </tr>`).join('');
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Wöchentlicher Verlauf</div>
      <table class="data-table"><thead><tr>
        <th>Woche</th><th>Wetten</th><th>Bilanz</th><th>Profit</th><th>ROI</th><th>Kumulativ</th>
      </tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

function renderKelly(kelly) {
  if (!kelly || !kelly.entries || !kelly.entries.length) return '';
  const k = kelly;
  const kellyColor = k.kelly_total_profit >= 0 ? 'var(--green)' : 'var(--red)';
  const flatColor = k.flat_total_profit >= 0 ? 'var(--green)' : 'var(--red)';
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Kelly-Criterion · Was wäre mit optimalem Einsatz?</div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:12px;font-family:var(--mono)">
        Start-Bankroll: ${k.start_bankroll} · Kelly passt den Einsatz an die Edge an.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px">
        <div class="stat-badge">
          <div class="stat-val" style="font-size:22px;color:${kellyColor}">${k.kelly_total_profit >= 0 ? '+' : ''}${k.kelly_total_profit}</div>
          <div class="stat-lbl">Kelly Profit</div>
        </div>
        <div class="stat-badge">
          <div class="stat-val" style="font-size:22px;color:${flatColor}">${k.flat_total_profit >= 0 ? '+' : ''}${k.flat_total_profit}</div>
          <div class="stat-lbl">Flat-Stake Profit</div>
        </div>
        <div class="stat-badge">
          <div class="stat-val" style="font-size:22px">${k.end_bankroll}</div>
          <div class="stat-lbl">Kelly Bankroll</div>
        </div>
      </div>
    </div>`;
}

// ══════════════════════════════════════════════════════
//  TEAM DATALIST
// ══════════════════════════════════════════════════════
function updateTeamList() {
  const dl = document.getElementById('team-list');
  dl.innerHTML = teamNames.map(n => `<option value="${n}">`).join('');
}

// ══════════════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════════════
(async function init() {
  initScores();
  loadStandings();
  loadScores();
  setInterval(updateRefreshStatus, 30000);
})();

// ── Periode abschließen ──────────────────────────────

async function closePeriod() {
  const label = prompt('Perioden-Label (optional, z.B. "v3-endstand"):');
  if (label === null) return; // Abbruch
  const notes = prompt('Notizen (optional):') || '';

  try {
    const res = await fetch(API + '/api/bets/close-period', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: label || undefined, notes }),
    });
    const data = await res.json();
    if (data.success) {
      alert(
        `Periode #${data.period_id} abgeschlossen!\n` +
        `Label: ${data.label}\n` +
        `Wetten: ${data.bets_closed}\n` +
        `Win-Rate: ${(data.win_rate * 100).toFixed(1)}%\n` +
        `Profit: ${data.profit >= 0 ? '+' : ''}${data.profit.toFixed(2)}\n` +
        `ROI: ${data.roi.toFixed(1)}%`
      );
      loadVersionComparison();
    } else {
      alert('Fehler: ' + (data.error || 'Unbekannt'));
    }
  } catch (e) {
    alert('Fehler: ' + e.message);
  }
}

// ── Versionen laden ──────────────────────────────────

async function loadVersionComparison() {
  const el = document.getElementById('bets-tab-versions');
  if (!el) return;
  el.innerHTML = loadingHtml('Lade Versionen...');

  try {
    const [versions, periods, verRes] = await Promise.all([
      apiFetch('/api/bets/versions'),
      apiFetch('/api/bets/periods'),
      apiFetch('/api/model/version'),
    ]);

    const currentVersion = verRes.version || 'unknown';

    if (!versions.length && !periods.length) {
      el.innerHTML = `
        <div class="empty-msg">
          <div class="empty-icon">📊</div>
          <div class="empty-text">Noch keine Wetten zum Vergleichen</div>
          <div style="font-size:12px;color:var(--text3);margin-top:8px">
            Aktive Version: <code>${currentVersion}</code>
          </div>
        </div>`;
      return;
    }

    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div>
          <span style="font-size:12px;color:var(--text3);font-family:var(--mono)">
            Aktive Version: <strong>${currentVersion}</strong>
          </span>
        </div>
        <button onclick="closePeriod()">Periode abschließen</button>
      </div>

      ${versions.length ? renderVersionsTable(versions) : ''}
      ${periods.length ? renderPeriodsTable(periods) : ''}
      ${versions.length >= 2 ? renderCompareSelector(versions) : ''}
      <div id="version-compare-result"></div>
    `;
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
}


// ── Versionen-Tabelle ────────────────────────────────

function renderVersionsTable(versions) {
  const rows = versions.map(v => {
    const profitColor = v.profit >= 0 ? 'var(--green)' : 'var(--red)';
    const roiColor = v.roi >= 0 ? 'var(--green)' : 'var(--red)';
    return `
      <tr>
        <td style="font-family:var(--mono);font-size:12px;font-weight:700">${v.version}</td>
        <td>${v.bets}</td>
        <td>${v.won}W / ${v.lost}L</td>
        <td>${(v.win_rate * 100).toFixed(1)}%</td>
        <td style="color:${profitColor};font-weight:700">${v.profit >= 0 ? '+' : ''}${v.profit.toFixed(2)}</td>
        <td style="color:${roiColor}">${v.roi >= 0 ? '+' : ''}${v.roi.toFixed(1)}%</td>
        <td>${v.brier.toFixed(4)}</td>
        <td style="font-size:11px;color:var(--text3)">${v.first_bet} – ${v.last_bet}</td>
      </tr>`;
  }).join('');

  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Modellversionen</div>
      <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left">
              <th style="padding:8px 6px">Version</th>
              <th style="padding:8px 6px">Wetten</th>
              <th style="padding:8px 6px">Bilanz</th>
              <th style="padding:8px 6px">Win%</th>
              <th style="padding:8px 6px">Profit</th>
              <th style="padding:8px 6px">ROI</th>
              <th style="padding:8px 6px">Brier</th>
              <th style="padding:8px 6px">Zeitraum</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}


// ── Perioden-Tabelle ─────────────────────────────────

function renderPeriodsTable(periods) {
  const rows = periods.map(p => {
    const profitColor = p.profit >= 0 ? 'var(--green)' : 'var(--red)';
    return `
      <tr>
        <td style="font-weight:700">#${p.period_id}</td>
        <td style="font-family:var(--mono);font-size:11px">${p.label}</td>
        <td style="font-family:var(--mono);font-size:11px">${p.model_version}</td>
        <td>${p.bets}</td>
        <td>${(p.win_rate * 100).toFixed(1)}%</td>
        <td style="color:${profitColor};font-weight:700">${p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)}</td>
        <td>${p.roi >= 0 ? '+' : ''}${p.roi.toFixed(1)}%</td>
        <td style="font-size:11px;color:var(--text3)">${p.closed_at?.slice(0, 10) || '–'}</td>
        <td style="font-size:11px;color:var(--text3)">${p.notes || '–'}</td>
      </tr>`;
  }).join('');

  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Abgeschlossene Perioden</div>
      <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left">
              <th style="padding:8px 6px">ID</th>
              <th style="padding:8px 6px">Label</th>
              <th style="padding:8px 6px">Version</th>
              <th style="padding:8px 6px">Wetten</th>
              <th style="padding:8px 6px">Win%</th>
              <th style="padding:8px 6px">Profit</th>
              <th style="padding:8px 6px">ROI</th>
              <th style="padding:8px 6px">Geschlossen</th>
              <th style="padding:8px 6px">Notizen</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}


// ── Vergleichs-Selector ──────────────────────────────

function renderCompareSelector(versions) {
  const opts = versions.map(v =>
    `<option value="${v.version}">${v.version} (${v.bets} Wetten)</option>`
  ).join('');

  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Direktvergleich</div>
      <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
        <div style="flex:1;min-width:160px">
          <label style="font-size:12px;color:var(--text3)">Version A</label>
          <select id="compare-v1" style="width:100%">${opts}</select>
        </div>
        <div style="font-size:18px;color:var(--text3);padding-bottom:6px">vs</div>
        <div style="flex:1;min-width:160px">
          <label style="font-size:12px;color:var(--text3)">Version B</label>
          <select id="compare-v2" style="width:100%">${opts}</select>
        </div>
        <button onclick="runVersionCompare()">Vergleichen</button>
      </div>
    </div>`;
}


// ── Vergleich ausführen ──────────────────────────────

async function runVersionCompare() {
  const v1 = document.getElementById('compare-v1')?.value;
  const v2 = document.getElementById('compare-v2')?.value;
  const el = document.getElementById('version-compare-result');
  if (!v1 || !v2 || !el) return;
  if (v1 === v2) { alert('Bitte zwei verschiedene Versionen wählen.'); return; }

  el.innerHTML = loadingHtml('Vergleiche...');
  try {
    const data = await apiFetch(`/api/bets/version-compare?v1=${encodeURIComponent(v1)}&v2=${encodeURIComponent(v2)}`);
    el.innerHTML = renderVersionCompare(data);
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
}


function renderVersionCompare(data) {
  const { v1, v2, deltas, better } = data;

  function deltaCell(key, suffix = '', invert = false) {
    const d = deltas[key] || 0;
    const positive = invert ? d < 0 : d > 0;
    const color = d === 0 ? 'var(--text3)' : positive ? 'var(--green)' : 'var(--red)';
    const sign = d > 0 ? '+' : '';
    return `<span style="color:${color};font-weight:700">${sign}${typeof d === 'number' ? d.toFixed(4) : d}${suffix}</span>`;
  }

  function row(label, k1, k2, key, fmt, suffix = '', invert = false) {
    return `
      <tr>
        <td style="font-weight:500;padding:6px 8px">${label}</td>
        <td style="padding:6px 8px;font-family:var(--mono)">${fmt(k1)}</td>
        <td style="padding:6px 8px;font-family:var(--mono)">${fmt(k2)}</td>
        <td style="padding:6px 8px;text-align:center">${deltaCell(key, suffix, invert)}</td>
      </tr>`;
  }

  const pct = v => (v * 100).toFixed(1) + '%';
  const num = v => typeof v === 'number' ? v.toFixed(2) : v;
  const num4 = v => typeof v === 'number' ? v.toFixed(4) : v;

  const betterLabel = better === v1.version ? v1.version : v2.version;

  return `
    <div class="card">
      <div class="card-title">${v1.version} vs ${v2.version}</div>
      <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left">
              <th style="padding:8px">Metrik</th>
              <th style="padding:8px">${v1.version}</th>
              <th style="padding:8px">${v2.version}</th>
              <th style="padding:8px;text-align:center">Delta</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="padding:6px 8px">Wetten</td>
              <td style="padding:6px 8px">${v1.bets}</td>
              <td style="padding:6px 8px">${v2.bets}</td>
              <td></td>
            </tr>
            ${row('Win-Rate', v1.win_rate, v2.win_rate, 'win_rate', pct)}
            ${row('Profit', v1.profit, v2.profit, 'profit', num)}
            ${row('ROI', v1.roi, v2.roi, 'roi', num, '%')}
            ${row('Brier Score', v1.brier, v2.brier, 'brier', num4, '', true)}
            ${row('Avg Edge', v1.avg_edge, v2.avg_edge, 'avg_edge', num4)}
          </tbody>
        </table>
      </div>
      <div style="margin-top:12px;padding:10px 14px;background:var(--bg2);border-radius:8px;display:flex;align-items:center;gap:10px">
        <span style="font-size:18px">🏆</span>
        <div>
          <div style="font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:1px">Profitabler</div>
          <div style="font-weight:700;font-family:var(--mono)">${betterLabel}</div>
        </div>
      </div>
    </div>`;
}
