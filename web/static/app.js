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
    predict: loadPipelineStatus,
  };
  if (loaders[id]) loaders[id]();
}

// ══════════════════════════════════════════════════════
//  FETCH HELPER
// ══════════════════════════════════════════════════════
let _apiOffline = false;

function _setOfflineBanner(offline) {
  if (_apiOffline === offline) return;
  _apiOffline = offline;
  document.getElementById('offline-banner').style.display = offline ? 'block' : 'none';
  document.querySelector('main.main').style.marginTop = offline ? '42px' : '';
}

async function checkApiStatus() {
  try {
    const s = await fetch(API + '/api/status').then(r => r.json());
    _setOfflineBanner(!s.online);
  } catch {
    _setOfflineBanner(true);
  }
}

async function apiFetch(url) {
  const res = await fetch(API + url);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.error) msg = body.error;
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function errorHtml(msg) {
  const isOffline = msg.includes('nicht erreichbar') || msg.includes('Verbindungsfehler') || msg.includes('pausiere');
  const text = isOffline ? 'NBA API nicht erreichbar – Daten können aktuell nicht geladen werden.' : msg;
  return `<div class="error-msg">⚠ ${text}</div>`;
}
function loadingHtml(text = 'Lade Daten...') {
  return `<div class="loading"><div class="spinner"></div>${text}</div>`;
}

// ══════════════════════════════════════════════════════
//  AUTO-REFRESH SYSTEM
// ══════════════════════════════════════════════════════

const GAME_HOURS = { start: 1, end: 7 };
const SCORES_REFRESH_MS = 5 * 60 * 1000;

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
//  ML PIPELINE STATUS
// ══════════════════════════════════════════════════════
let _pipelineRefreshTimer = null;

async function loadPipelineStatus() {
  const widget = document.getElementById('pipeline-status-widget');
  if (!widget) return;

  try {
    const s = await apiFetch('/api/pipeline/status');
    renderPipelineStatus(s, widget);

    // Immer pollen – 3 s bei laufender Pipeline, 30 s im Ruhezustand.
    // So sehen auch andere Browser-Tabs / Nutzer Änderungen zeitnah.
    clearInterval(_pipelineRefreshTimer);
    _pipelineRefreshTimer = setInterval(loadPipelineStatus, s.running ? 3000 : 30000);
  } catch (e) {
    widget.innerHTML = '';
    clearInterval(_pipelineRefreshTimer);
    _pipelineRefreshTimer = setInterval(loadPipelineStatus, 30000);
  }
}

function renderPipelineStatus(s, widget) {
  // Banner wenn Pipeline gerade läuft – kein Trigger-Button sichtbar
  if (s.running) {
    widget.innerHTML = `
      <div class="pipeline-running-banner">
        <div class="spinner" style="flex-shrink:0"></div>
        <div style="flex:1;min-width:0">
          <div style="font-family:var(--head);font-weight:700;font-size:13px;color:var(--orange)">ML-Pipeline läuft …</div>
          <div style="font-family:var(--mono);font-size:11px;color:var(--text2);margin-top:2px;
                      overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.step || '&nbsp;'}</div>
        </div>
        <div style="font-size:11px;color:var(--text3);font-family:var(--mono);white-space:nowrap;flex-shrink:0">
          Altes Modell aktiv bis Abschluss
        </div>
      </div>`;
    return;
  }

  const active = s.active_model;
  const models = s.models || [];

  // Kein Modell vorhanden
  if (!active && !models.length) {
    widget.innerHTML = `
      <div class="pipeline-info-bar">
        <span style="color:var(--text3)">Kein ML-Modell vorhanden.</span>
        <button class="btn btn-secondary pipeline-trigger-btn"
                onclick="triggerPipeline()"
                style="margin-left:auto;font-size:11px;padding:6px 12px">
          ▶ Pipeline starten
        </button>
      </div>`;
    return;
  }

  // Aktives Modell + Modell-Vergleich
  const trainedAt = active?.trained_at
    ? new Date(active.trained_at).toLocaleDateString('de-DE', {day:'2-digit', month:'2-digit', year:'numeric'})
    : '—';
  const lastMonth = s.last_trained_month ? ` · Training: ${s.last_trained_month}` : '';

  const modelRows = models.length ? models.map(m => {
    const isWinner = m.model_id === s.winner;
    const badge = isWinner ? ' <span style="color:var(--green);font-size:10px">✓ Aktiv</span>' : '';
    const accPct = (m.accuracy * 100).toFixed(1);
    const auc = m.roc_auc?.toFixed(3) ?? '—';
    const brier = m.brier_score?.toFixed(3) ?? '—';
    const barW = Math.round(m.accuracy * 100);
    return `
      <div class="pipeline-model-row ${isWinner ? 'pipeline-model-winner' : ''}">
        <div class="pipeline-model-name">${m.model_name}${badge}</div>
        <div class="pipeline-model-bar-wrap">
          <div class="pipeline-model-bar" style="width:${barW}%"></div>
        </div>
        <div class="pipeline-model-stats">
          <span title="Accuracy">${accPct}%</span>
          <span title="ROC-AUC" style="color:var(--text3)">AUC ${auc}</span>
          <span title="Brier Score" style="color:var(--text3)">B ${brier}</span>
        </div>
      </div>`;
  }).join('') : '';

  const errorBanner = s.error
    ? `<div style="background:rgba(220,38,38,0.1);border:1px solid rgba(220,38,38,0.3);border-radius:8px;
                   padding:8px 12px;margin-bottom:12px;font-family:var(--mono);font-size:11px;color:#f87171">
         Fehler: ${s.error}
       </div>`
    : '';

  widget.innerHTML = `
    ${errorBanner}
    <div class="pipeline-info-bar">
      <div style="min-width:0;overflow:hidden">
        <span style="font-family:var(--head);font-weight:700;font-size:12px;color:var(--text1)">${active?.model_name ?? '—'}</span>
        <span style="font-family:var(--mono);font-size:11px;color:var(--text3);margin-left:8px">
          Accuracy ${active ? (active.accuracy*100).toFixed(1)+'%' : '—'} · ROC-AUC ${active?.roc_auc?.toFixed(3) ?? '—'}
        </span>
        <span style="font-family:var(--mono);font-size:10px;color:var(--text3);margin-left:8px">${trainedAt}${lastMonth}</span>
      </div>
      <button class="btn btn-secondary pipeline-trigger-btn"
              onclick="triggerPipeline()"
              style="margin-left:auto;flex-shrink:0;font-size:11px;padding:6px 12px"
              title="Pipeline manuell neu starten">
        ↺ Neu trainieren
      </button>
    </div>
    ${modelRows ? `<div class="pipeline-models">${modelRows}</div>` : ''}`;
}

async function triggerPipeline() {
  // Alle Trigger-Buttons sofort deaktivieren und Spinner zeigen –
  // unabhängig davon, wie viele Tabs die Seite geöffnet haben.
  const btns = document.querySelectorAll('.pipeline-trigger-btn');
  btns.forEach(b => {
    b.disabled = true;
    b._origHtml = b.innerHTML;
    b.innerHTML = '<span class="btn-spinner"></span> Startet …';
  });

  try {
    const r = await fetch(API + '/api/pipeline/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const d = await r.json();

    if (!r.ok && r.status !== 409) {
      // Echter Fehler (nicht "läuft bereits") → Button wiederherstellen
      btns.forEach(b => { b.disabled = false; b.innerHTML = b._origHtml; });
      alert(d.error || 'Pipeline konnte nicht gestartet werden.');
      return;
    }

    // 200 (gestartet) oder 409 (läuft bereits von anderem Nutzer) →
    // Sofort Running-Banner zeigen (optimistisch), bevor der Server-Thread
    // pipeline_status.json aktualisiert hat.
    const widget = document.getElementById('pipeline-status-widget');
    if (widget) renderPipelineStatus({ running: true, step: 'Starte Pipeline …' }, widget);
    clearInterval(_pipelineRefreshTimer);
    _pipelineRefreshTimer = setInterval(loadPipelineStatus, 3000);
  } catch (e) {
    btns.forEach(b => { b.disabled = false; b.innerHTML = b._origHtml; });
    alert('Verbindungsfehler: ' + e.message);
  }
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
  if (!home || !away) return;

  const resultEl = document.getElementById('predict-result');
  resultEl.className = 'predict-result show';
  resultEl.innerHTML = `<div class="card">${loadingHtml('Berechne Vorhersage...')}</div>`;

  try {
    const r = await fetch(API + '/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ home, away })
    });
    const d = await r.json();
    if (d.error) { resultEl.innerHTML = `<div class="card">${errorHtml(d.error)}</div>`; return; }
    renderPrediction(d, resultEl);
  } catch (e) {
    resultEl.innerHTML = `<div class="card">${errorHtml(e.message)}</div>`;
  }
}

function renderPrediction(d, el) {
  const homeProb = d.ml_home_prob;
  const awayProb = d.ml_away_prob;
  const hPct = (homeProb * 100).toFixed(1);
  const aPct = (awayProb * 100).toFixed(1);

  const mlColor   = '#ff5f1f';
  const oddsColor = '#ffc107';

  const mlWinner    = d.ml_winner === 'home' ? d.home : d.away;
  const oddsWinner  = d.odds_home_prob ? (d.odds_home_prob >= 0.5 ? d.home : d.away) : null;

  const methods = [
    { label: 'ML-MODELL',  color: mlColor,   winner: mlWinner,   hp: d.ml_home_prob,   ap: d.ml_away_prob,   available: d.ml_home_prob !== null },
    { label: 'WETTQUOTEN', color: oddsColor, winner: oddsWinner, hp: d.odds_home_prob, ap: d.odds_away_prob, available: d.odds_home_prob !== null,
      raw: d.odds_home_raw ? `${d.odds_home_raw} / ${d.odds_away_raw}` : null },
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
        <div class="card-title">Einflussfaktoren</div>
        <div class="factors-grid">${rows}</div>
      </div>`;
  }

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

    <div class="consensus-box">
      <div class="consensus-icon">🤖</div>
      <div>
        <div class="consensus-label">ML-Vorhersage</div>
        <div class="consensus-winner">${mlWinner}</div>
        <div class="consensus-sub">${d.ml_confidence ?? ''}</div>
      </div>
    </div>

    ${factorsHtml}
  </div>`;
}

// ══════════════════════════════════════════════════════
//  COMPARE (KI vs QUOTEN + EV)
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

    const cards = entries.map((e, idx) => {
      const hp  = (e.ml_home   * 100).toFixed(1);
      const ap  = (e.ml_away   * 100).toFixed(1);
      const ohp = (e.odds_home * 100).toFixed(1);
      const oap = (e.odds_away * 100).toFixed(1);
      const diff = (e.diff * 100).toFixed(1);
      const diffClass = e.diff > 0.10 ? 'diff-big' : 'diff-small';

      const evHomeColor = e.ev_home > 0 ? 'var(--green)' : 'var(--red)';
      const evAwayColor = e.ev_away > 0 ? 'var(--green)' : 'var(--red)';
      const edgeHomeSign = e.edge_home >= 0 ? '+' : '';
      const edgeAwaySign = e.edge_away >= 0 ? '+' : '';

      const evHtml = `
        <div class="bet-details" style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
          <div style="font-size:10px;color:var(--text3);font-family:var(--head);font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;grid-column:1/-1">Expected Value</div>
          <div class="bet-detail">
            <div class="bet-detail-label">${e.home}</div>
            <div class="bet-detail-value" style="color:${evHomeColor}">${e.ev_home >= 0 ? '+' : ''}${(e.ev_home * 100).toFixed(1)}%</div>
            <div style="font-size:10px;color:var(--text3);font-family:var(--mono)">Edge: ${edgeHomeSign}${(e.edge_home * 100).toFixed(1)}%</div>
          </div>
          <div class="bet-detail">
            <div class="bet-detail-label">${e.away}</div>
            <div class="bet-detail-value" style="color:${evAwayColor}">${e.ev_away >= 0 ? '+' : ''}${(e.ev_away * 100).toFixed(1)}%</div>
            <div style="font-size:10px;color:var(--text3);font-family:var(--mono)">Edge: ${edgeAwaySign}${(e.edge_away * 100).toFixed(1)}%</div>
          </div>
        </div>`;

      return `
      <div class="compare-card">
        <div class="compare-teams">${e.home} <span style="color:var(--text3)">vs</span> ${e.away}</div>
        <div class="compare-bars">
          <div class="compare-bar-row">
            <div class="compare-bar-label" style="color:var(--orange)">ML</div>
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
          <div class="compare-diff ${diffClass}">Δ ${diff}%</div>
          <div style="font-size:10px;color:var(--text3);font-family:var(--mono)">${e.odds_home_raw} / ${e.odds_away_raw}</div>
        </div>
        ${evHtml}
      </div>`;
    }).join('');

    const avgDiff = entries.reduce((s, e) => s + e.diff, 0) / entries.length;

    el.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-bottom:20px;">
      <div class="stat-badge"><div class="stat-val">${entries.length}</div><div class="stat-lbl">Spiele</div></div>
      <div class="stat-badge"><div class="stat-val">${(avgDiff * 100).toFixed(1)}%</div><div class="stat-lbl">Ø Abweichung</div></div>
    </div>
    <div style="background:rgba(255,95,31,0.08);border:1px solid rgba(255,95,31,0.2);border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:12px;color:var(--text2);font-family:var(--mono);">
      ⚠️ EV-Werte basieren auf dem KI-Modell und garantieren keine Gewinne. Wette verantwortungsvoll.
    </div>
    <div class="compare-row-grid">${cards}</div>`;
  } catch (e) {
    el.innerHTML = errorHtml(e.message);
  }
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
  checkApiStatus();
  setInterval(checkApiStatus, 30000);
  initScores();
  loadStandings();
  loadScores();
  setInterval(updateRefreshStatus, 30000);
})();
