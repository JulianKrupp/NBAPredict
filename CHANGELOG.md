# Changelog

Alle relevanten Änderungen am NBA Tracker werden in dieser Datei dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

---

## [1.2.0] – Regelmodell im Quoten-Tab & Circuit-Breaker-Fix

### Hinzugefügt

#### Regelbasiertes Modell im Quoten-Vergleich
- **`ComparisonEntry`** um `rule_home_prob`, `rule_away_prob`, `rule_winner` erweitert.
- **`OddsVsMLComparison`**: Neue Hilfsmethode `_rule_home_prob()` ruft `GamePredictor`
  auf und normiert das Ergebnis auf eine Heimsieg-Wahrscheinlichkeit.
  Wird in `_compare_single_game()` und `run_comparison_for_teams()` aufgerufen.
- **`/api/compare`**: Response enthält jetzt `rule_home`, `rule_away`, `rule_winner`.
- **Quoten-Tab (Frontend)**: Dritter Balken „Regel" (blau) zwischen ML und Odds.
  Alle drei Modelle — ML, Regelmodell, Buchmacher — auf einen Blick vergleichbar.

### Behoben

- **Circuit Breaker global geteilt** (`src/api/base_client.py`): `_global_offline_until`
  als Modul-Variable eingeführt. Ein DNS-Fehler in einem Client setzt alle Clients
  auf Cooldown — verhindert dass z.B. der Odds-Client nach NBA-API-Ausfall trotzdem
  30s wartet und einen Browser-seitigen `NetworkError` verursacht.
- **`connect=0` in Retry-Konfiguration**: Kein Retry bei DNS/ConnectionError –
  der Circuit Breaker übernimmt die Cooldown-Logik. HTTP-5xx-Retries (`total=3`)
  bleiben unverändert.

---

## [1.1.0] – Docker-Netzwerk-Fixes, Circuit Breaker & Offline-Banner

Verbesserung der Docker-Betriebsstabilität: Der Container ist jetzt von außen
erreichbar, API-Ausfälle werden sauber abgefangen und dem Nutzer kommuniziert,
und die Logs bleiben ruhig wenn die externe API nicht erreichbar ist.

### Hinzugefügt

- **Circuit Breaker** (`src/api/base_client.py`): Nach einem `ConnectionError`
  pausiert der Client 60 Sekunden lang alle weiteren API-Versuche. Verhindert
  Retry-Spam bei dauerhaft unerreichbarer API.
  - Neues Property `is_offline` – prüft ob der Cooldown noch aktiv ist.
- **`/api/status`-Endpunkt** (`web/server.py`): Gibt `{"online": true/false}`
  zurück basierend auf dem Circuit-Breaker-Zustand von `nba_client` und
  `odds_client`. Kein externer API-Call.
- **Offline-Banner** (`web/static/index.html`, `app.js`): Roter Banner oben,
  sobald `/api/status` meldet dass die NBA API nicht erreichbar ist.
  Verschwindet automatisch bei Wiederherstellung der Verbindung. Polling alle 30s.

### Geändert

- **`app.run(host="0.0.0.0")`** (`web/server.py`): Flask lauschte bisher nur
  auf `127.0.0.1` (Loopback) – Container war von außen nicht erreichbar.
  Fix: explizites `host="0.0.0.0"`.
- **DNS in Docker** (`docker-compose.yml`): `dns: [8.8.8.8, 1.1.1.1]` ergänzt
  um DNS-Auflösung im Container zu gewährleisten.
- **Healthcheck** (`docker-compose.yml`): Von `/api/standings` auf `/api/status`
  umgestellt – verhindert dass der Healthcheck alle 30s einen externen API-Call
  auslöst und den Circuit Breaker zurücksetzt.
- **Log-Bereinigung** (`src/utils/logger.py`, `base_client.py`, `nba_api_client.py`):
  - `urllib3.connectionpool` auf ERROR-Level gesetzt – Retry-Warnings unterdrückt
    (der eigentliche Fehler wird bereits auf ERROR in den API-Clients geloggt).
  - `RotatingFileHandler` in Docker (`FLASK_ENV=production`) deaktiviert –
    verhindert `OSError: [Errno 5]` auf Windows-NTFS-Volumes via WSL2.
  - Fehlertext bei `ConnectionError` auf einzeilige Zusammenfassung gekürzt.
  - `Seitenladefehler` im paginierten Abruf: auf `DEBUG` reduziert wenn
    Circuit Breaker bereits aktiv ist (kein doppelter ERROR-Eintrag).

---

## [1.0.0] – Stabilitäts-Refactoring, CLI-Erweiterung & Website/CLI-Trennung

Erste stabile Release-Version. Schwerpunkt auf Code-Qualität, klarer
Aufgabentrennung zwischen Web-Interface und CLI sowie Reduzierung von
Coderedundanz in den zentralen Modulen.

### Hinzugefügt

#### CLI – `bets`-Subkommando
- **`main.py`**: Neues Subkommando `bets` mit fünf Unterkommandos:
  - `bets list [--status open|won|lost|all]` – tabellarische Übersicht aller Wetten
  - `bets stats` – vollständige Statistiken inkl. Rating-Aufschlüsselung
  - `bets resolve` – automatisches Auflösen offener Wetten via `BetResolver`
  - `bets reset` – Löschen aller Wetten mit doppelter Bestätigung
  - `bets close-period [--label TEXT] [--notes TEXT]` – Periode abschließen

### Geändert

#### Code-Qualität: Fehlerbehandlung in `server.py`
- **`handle_errors`-Decorator** ersetzt 12 identische `try/except`-Blöcke in allen
  API-Routen. Jede Route wird jetzt mit `@handle_errors` dekoriert; Logging erfolgt
  automatisch mit dem Funktionsnamen als Kontext.
- Alle Route-Handler vereinfacht: kein verschachteltes `try/except` mehr nötig.

#### Code-Qualität: Gruppen-Statistiken in `tracker.py`
- **`_group_stats(group)`** extrahiert die gemeinsame Berechnung von won/lost/profit/
  roi/avg_odds/avg_edge, die zuvor in `_by_rating`, `_by_team`, `_by_side` und
  `_group_by_range` dupliziert war.
- `_by_rating`: 19 → 5 Zeilen
- `_by_team`: 16 → 5 Zeilen
- `_by_side`: 12 → 3 Zeilen
- `_group_by_range`: 13 → 4 Zeilen

#### Website/CLI-Trennung
- **Website** zeigt ausschließlich Nutzer-Funktionen: Standings, Spiele, KI-Vorhersage,
  Quoten-Vergleich, Wetten platzieren/einsehen/löschen, Analytik, Versionsvergleich.
- **Train-Tab entfernt**: KI-Training (`page-train`, Nav-Button, `loadMetrics()`,
  `startTraining()`) vollständig aus Website entfernt. Training erfolgt ausschließlich
  über `python main.py train`.
- Admin-Aktionen (`resolveAllBets`, `confirmResetBets`, `closePeriod`) bleiben auf der
  Website verfügbar und sind zusätzlich über das neue CLI-Kommando `bets` erreichbar.

### Behoben
- **`ResourceWarning` (unclosed SQLite connections)**: `_connect()` in `tracker.py`
  von direkter Connection-Rückgabe auf `@contextlib.contextmanager` umgestellt.
  `finally: conn.close()` garantiert sauberes Schließen auch bei Exceptions.
- **Docker WAL-Fehler**: `PRAGMA journal_mode=WAL` entfernt. WAL erfordert
  Shared-Memory-Dateien (`bets.db-shm`), die auf Windows-NTFS-Volumes über WSL2
  nicht unterstützt werden. Standard-Journaling ist für diesen Anwendungsfall
  ausreichend.
- **Blank-Page in Docker**: `send_from_directory` und `static_folder` auf absoluten
  Pfad (`Path(__file__).parent / "static"`) umgestellt, damit die Pfadauflösung
  unabhängig vom Arbeitsverzeichnis beim Containerstart korrekt funktioniert.
- **Modellversion**: Neue Wetten wurden fälschlicherweise dem alten Format
  `Logist_f45_a65` zugeordnet. Version liest jetzt `trained_at` aus
  `model_metrics.json` und gibt `Logist_f45_2026-04-02` zurück.
  `model_trainer.py` schreibt `trained_at` als ISO-Timestamp bei jedem Training.

### Metriken
- Gesamt-Codezeilen reduziert: −46 Zeilen (server.py −38, tracker.py −8)
- Alle bestehenden Tests weiterhin grün (29/29 tracker, 23/23 comparison, 15/15 elo)

---

## [0.9.0] – Containerisierung, erweitertes Test-Suite & Projekt-Professionalisierung

Professionalisierung der Projekt-Infrastruktur: Docker-Container für reproduzierbare
Deployments, 197 automatisierte Tests mit Coverage-Enforcement, `pyproject.toml`
als moderner Python-Standard, sowie Ruff-Konfiguration für statische Code-Analyse.

### Hinzugefügt

#### Docker & Containerisierung
- **`Dockerfile`** (Multi-Stage-Build): Builder-Stage installiert Abhängigkeiten,
  Runtime-Stage ist schlank (python:3.12-slim). Inkl. Healthcheck auf `/api/standings`.
- **`docker-compose.yml`**: `web`-Service startet den Flask-Server mit persistenten Volumes
  (`./data`, `./logs`). Optionaler `resolver`-Service für automatisches Bet-Resolving
  (auskommentiert, dokumentiert).
- **`.dockerignore`**: Schließt `.venv/`, `.env`, `.git/`, Cache- und Testdateien aus dem
  Image aus.
- **`.env.example`**: Vorlage für Umgebungsvariablen mit Dokumentation aller Keys.
  Start: `cp .env.example .env && nano .env`

#### Projekt-Konfiguration
- **`pyproject.toml`**: Moderner Python-Projektstandard mit `[project]`-Metadaten,
  CLI-Einstiegspunkt (`nba = "main:main"`), `[tool.ruff]`-Konfiguration (100-Zeichen-Limit,
  Regelsätze E/W/F/I/N/UP/B/SIM), `[tool.coverage]` und gespiegelte pytest-Konfiguration.

#### Tests (neu: 197 gesamt, vorher ~120)
- **`tests/test_comparison.py`** (neu): 23 Tests für `ComparisonEntry` und `OddsVsMLComparison`:
  - Guardrail 1: Quote > 6.0 & ML-Prob < 70% → "none"
  - Guardrail 2: Quote > 3.5 & Methoden uneinig → "none"
  - Alle vier Edge-Stufen (strong/good/slight/none)
  - EV-Formel, `bet_side`-Logik, `methods_agree`
  - Vig-Normierung inkl. Randfall (Quote = 0)
- **`tests/test_elo.py`** (neu): 15 Tests für das Elo-Rating-System:
  - Nullsummen-Eigenschaft, Startwert 1500
  - Heimvorteil (Auswärtssieg > Heimsieg für gleiche Teams)
  - Margin-of-Victory-Multiplikator (Blowout > knapper Sieg)
  - Saisonale Regression-to-Mean (Faktor 0.75)
  - Daten-Leakage-Prävention in `calculate_elo_per_game` (Elo vor Spiel, nicht nach)
  - Ausschluss nicht-abgeschlossener Spiele
- **`tests/test_tracker.py`** (neu): 29 Tests für `BettingTracker` mit isolierter
  In-Memory-Datenbank (`tmp_path`):
  - `place_bet`: ID-Eindeutigkeit, Status, Persistenz, Modellversion
  - `resolve_bet`: Auszahlungsformel, Endpunktstand, Doppelauflösung, Teil-Namens-Match
  - `get_open_bets`: Filterung aufgelöster Wetten
  - `get_stats`: Win-Rate, ROI, Won/Lost-Zähler
- **`tests/test_predictor.py`** (ergänzt): Neue Klasse `TestPredictorInternals`:
  - `FACTOR_WEIGHTS`-Summe = 1.0
  - `_compare_stats` (Randwerte, Skala-Parameter)
  - `_normalize_to_probability` (Klammerung auf [0.10, 0.90])
  - Fatigue-Effekt auf Punkt-Schätzung (`days_rest=0` vs `days_rest=3`)

### Nicht umgesetzt (erfordert Server/CI-Infrastruktur)

| Feature | Begründung |
|---------|-----------|
| **GitHub Actions CI/CD** | Erfordert remote Repository mit Actions-Zugang. Workflow-Template: `.github/workflows/ci.yml` mit `pytest` + `docker build`. |
| **Alembic Datenbankmigrationen** | Overkill für SQLite-Projektgröße; aktuelle manuelle `ALTER TABLE`-Checks in `tracker.py` sind ausreichend. |
| **Produktions-Deployment** | Erfordert Server (VPS/Cloud). Docker-Image ist deployment-ready; fehlt nur Zielinfrastruktur. |

### Verwendung

```bash
# Docker (empfohlen für Deployment)
cp .env.example .env   # API-Keys eintragen
docker compose up -d

# Lokal (Entwicklung)
pip install -r requirements.txt
python web/server.py

# Tests ausführen
pytest                 # alle 197 Tests + Coverage
pytest tests/test_comparison.py -v   # nur Guardrail-Tests

# Code-Qualität prüfen
ruff check src/        # Linting
ruff format src/       # Formatierung
```

---

## [0.8.0] – Betting-Scores, Bet-Guardrails, Season-Fix & Modell-Neutraining

Vier Bereiche verbessert: Abgeschlossene Wetten zeigen jetzt den Endpunktstand,
die Wettempfehlung filtert unglaubwürdige Tipps auf Außenseiter heraus,
Season-Parameter werden überall dynamisch berechnet statt hardcodiert,
und das Modell wurde mit den v0.7.0-Fixes neu trainiert.

### Problemanalyse

| # | Problem | Schwere | Status |
|---|---------|---------|--------|
| 1 | Abgeschlossene Wetten zeigten keinen Endpunktstand | Mittel | ✅ Behoben |
| 2 | `bet_rating` rein edge-basiert – empfahl Außenseiter bei starker Marktmeinung | Hoch | ✅ Behoben |
| 3 | Season-Parameter `2024` hardcodiert – falsche Daten ab Saison 2025/26 | Kritisch | ✅ Behoben |
| 4 | Modell mit veralteten Feature-Formeln trainiert (v0.6.x) | Kritisch | ✅ Behoben |

---

### Technische Änderungen

#### Endpunktstand bei aufgelösten Wetten (`tracker.py`, `resolver.py`, `server.py`, `app.js`)

Abgeschlossene Wetten speichern und zeigen jetzt `home_score : away_score`.

**`tracker.py`** – `Bet`-Dataclass um zwei Felder erweitert:
```python
home_score: int | None = None
away_score: int | None = None
```

Datenbank-Schema und Migration (`_migrate_v2`) um beide Spalten ergänzt.
`resolve_bet()` nimmt optionale Score-Parameter entgegen:
```python
def resolve_bet(
    self, bet_id: int, actual_winner: str,
    home_score: int | None = None,
    away_score: int | None = None,
) -> Bet | None:
```

**`resolver.py`** – `_find_game_winner()` umbenannt zu `_find_game_result()`
und gibt jetzt ein Dict zurück statt nur den Sieger-String:
```python
return {"winner": ..., "home_score": ..., "away_score": ...}
```
`_fetch_recent_finished_games()` fügt `home_score`/`away_score` aus
`g.home_score`/`g.away_score` dem Game-Dict hinzu.

**`server.py`** – `/api/bets` GET-Response enthält `home_score`, `away_score`.

**`app.js`** – `renderBetCard()` zeigt bei aufgelösten Wetten:
```
Gewinner: Charlotte Hornets   Charlotte Hornets 108:112 Brooklyn Nets
```

---

#### Bet-Guardrails gegen Außenseiter-Empfehlungen (`comparison.py`)

`bet_rating` prüft jetzt zwei Schutzregeln, bevor die Edge-Schwellen greifen:

| Bedingung | Wirkung |
|---|---|
| `bet_odds_raw > 6.0` und `bet_ml_prob < 0.70` | `→ "none"` – KI zu unsicher bei starkem Außenseiter |
| `bet_odds_raw > 3.5` und `not methods_agree` | `→ "none"` – KI und Buchmacher uneinig beim Underdog |

**Beispiel (Auslöser dieser Änderung):** Brooklyn Nets (1-9) als Heimteam gegen
Charlotte Hornets (7-3). KI: 54.8 % für Nets, Quoten: 9.12 (impliziert 10.5 %).
Edge = 44.3 % → bisherige Logik: `"strong"`. Neue Logik: Quote 9.12 > 6.0,
KI-Prob 54.8 % < 70 % → `"none"`. Kein Wetttipp.

Die Grundursache (KI-Modell gibt 54.8 % für ein 1-9-Team) wird durch das
Modell-Neutraining und den Season-Fix (unten) adressiert.

---

#### Season-Parameter dynamisch (`nba_api_client.py`, `ml_predictor.py`)

`season = 2024` war an mehreren Stellen hardcodiert. Da die NBA-Saison
im Oktober beginnt, gilt: `season = Jahr - 1` wenn Monat < Oktober.

Neue Hilfsmethode in `NBAApiClient`:
```python
def _current_season(self) -> int:
    today = date.today()
    return today.year if today.month >= 10 else today.year - 1
```

Betroffen: `get_standings()`, `get_team_stats()`, `get_recent_games()`,
`_compute_current_elo()` (ml_predictor.py).

| Vorher | Nachher |
|--------|---------|
| `season: int = 2024` (hardcodiert) | `season: int \| None = None` → `_current_season()` |
| Saison 2024-25 auch in 2025-26 geladen | Immer korrekte aktuelle Saison |

---

#### Modell-Neutraining (v0.7.0-Fixes aktiv)

Erstes Training mit den korrekten Feature-Formeln aus v0.7.0.

**Trainingsdaten:** Saisons 2021 (partial), 2023, 2024, 2025
(Saison 2022 und Teile von 2021 wegen API-Verbindungsabbruch nicht verfügbar)

| Metrik | v0.6.x | v0.8.0 | Δ |
|--------|--------|--------|---|
| Modell | LogisticRegression | LogisticRegression | – |
| Accuracy (Test) | 65.1 % | 65.0 % | −0.1 pp |
| ROC-AUC | 0.7056 | 0.6989 | −0.007 |
| Brier Score | 0.2154 | 0.2183 | +0.003 |
| CV-Accuracy | 64.1 % ± 0.5 % | **66.0 % ± 1.7 %** | +1.9 pp |
| Train-Samples | 5 935 | 4 504 | −1 431 |
| Feature-Anzahl | 45 | 45 | ✓ |

**Wichtigste Beobachtung – Feature-Shift:**

| Rang | v0.6.x | v0.8.0 |
|------|--------|--------|
| 1 | `home_defensive_rating` (2.193) | `home_elo` (0.272) |
| 2 | `home_avg_pts_allowed` (1.868) | `diff_elo` (0.264) |
| 3 | `home_point_diff` (1.512) | `home_fatigue_score` (0.146) |
| 4 | `home_net_rating` (1.279) | `home_games_last_7_days` (0.142) |
| 5 | `away_point_diff` (1.152) | `diff_fatigue` (0.134) |

Das alte Modell stützte sich auf drei Variationen derselben Metrik
(`avg_pts_allowed`, `defensive_rating`, `point_diff` – alle abgeleitet von
Punkten pro Spiel). Das neue Modell gewichtet **Elo** (dynamische Saisonform)
und **Fatigue** (Belastungssteuerung) – konzeptuell unabhängige Signale.

Die erhöhte CV-Varianz (±1.7 % statt ±0.5 %) und der minimal schlechtere
Brier Score sind auf die kleinere Datenbasis (API-Abbruch) zurückzuführen.
Ein vollständiges Neutraining mit allen Saisons wird bessere Kalibrierung
erwarten lassen.

---

## [0.7.0] – Train/Predict-Mismatches, Elo-Regression & Logikfixes

Kritische Korrekturen an der ML-Pipeline: Zwei Feature-Formeln, die beim
Training und bei der Vorhersage unterschiedliche Werte lieferten, wurden
vereinheitlicht. Außerdem saisonale Elo-Regression, Pace-Clamping und
kleinere Logikfehler behoben. Das Modell muss neu trainiert werden.

### Problemanalyse

| # | Problem | Schwere | Status |
|---|---------|---------|--------|
| 1 | Fatigue-Feature: linearer Ausdruck beim Training, stufenbasierte Formel bei Prediction | Kritisch | ✅ Behoben |
| 2 | Form-Rating: unterschiedliche Formeln in `_CumulativeTeamTracker` und `Team` | Kritisch | ✅ Behoben |
| 3 | Pace-Formel ohne Clamping – unrealistische Werte bei Ausreißer-Teams | Mittel | ✅ Behoben |
| 4 | Elo ohne saisonale Regression – frühere Saisons beeinflussen aktuelle Ratings unverhältnismäßig | Mittel | ✅ Behoben |
| 5 | Elo-Cache-Reset bei jeder `predict()`-Aufruf – unnötiger API-Abruf bei Multi-Game-Sessions | Niedrig | ✅ Behoben |
| 6 | `Game.winner` gibt bei Gleichstand `away_team` statt `None` zurück | Niedrig | ✅ Behoben |

**Fatigue-Mismatch im Detail:** Beim Training berechnete `build_samples_cumulative()`
den Ermüdungswert mit `h_fat = h_g7 * 0.15 - h_rest * 0.05` – einer einfachen
linearen Formel. Bei der Vorhersage nutzte das Modell `team.fatigue_score`, das
eine stufenbasierte Nicht-Linearität hat (0 Ruhetage → 1.0, 1 → 0.45, 2 → 0.15,
3+ → 0.0) kombiniert mit Spieldichte. Beispiel: Bei 0 Ruhetagen und 3 Spielen
in 7 Tagen: Training lieferte `0.45 - 0.0 = 0.45`, Prediction `0.65 * 1.0 + 0.35 * 0.5 = 0.825`.
Das Modell lernte eine Feature-Skala, die es bei der Vorhersage nie zu sehen bekam.

**Form-Rating-Mismatch im Detail:** `_CumulativeTeamTracker.form_rating` nutzte
eine positionsgewichtete Formel über die letzten 5 Spiele mit Gewichten
`[0.1, 0.15, 0.2, 0.25, 0.3]`. `Team.form_rating` nutzt dagegen
`0.30×L3 + 0.40×L5 + 0.30×L10`. Beide Formeln liefern für dasselbe Team
deutlich unterschiedliche Werte, was einen klassischen Train/Predict-Mismatch
verursacht.

### Technische Änderungen

#### `_compute_fatigue()` – neue Hilfsfunktion (`data_collector.py`)

Neue Modulfunktion, die exakt die Logik von `Team.fatigue_score` abbildet:

```python
def _compute_fatigue(days_rest: int, games_last_7: int) -> float:
    if days_rest >= 3:   rest_fatigue = 0.0
    elif days_rest == 2: rest_fatigue = 0.15
    elif days_rest == 1: rest_fatigue = 0.45
    else:                rest_fatigue = 1.0
    density_fatigue = min(1.0, max(0.0, (games_last_7 - 2) / 2.0))
    return round(0.65 * rest_fatigue + 0.35 * density_fatigue, 4)
```

Ersetzt die bisherige lineare Inline-Berechnung in `build_samples_cumulative()`.

#### `_CumulativeTeamTracker.form_rating` vereinheitlicht (`data_collector.py`)

`form_rating` und das neue Property `last_3_win_rate` wurden auf
`0.30×L3 + 0.40×L5 + 0.30×L10` umgestellt – identisch zu `Team.form_rating`.

| Vorher | Nachher |
|--------|---------|
| Positionsgewichtete letzte 5 Spiele | `0.30×last_3 + 0.40×last_5 + 0.30×last_10` |
| Eigene Gewichte `[0.1, 0.15, 0.2, 0.25, 0.3]` | Konsistent mit `Team.form_rating` |

#### Pace-Clamping (`data_collector.py`, `nba_stats_client.py`)

Die Näherungsformel `98.0 + (pts - 110.0) * 0.3` wird jetzt auf den
realistischen NBA-Bereich geclampt:

```python
pace = max(85.0, min(115.0, 98.0 + (pts - 110.0) * 0.3))
```

Gilt für `_CumulativeTeamTracker.compute_advanced_stats()` und
`AdvancedTeamStats.from_basic_stats()`. Verhindert Division durch unrealistische
Werte bei der Off/Def-Rating-Berechnung.

#### Saisonale Elo-Regression (`elo.py`)

Bei jedem Saisonwechsel werden alle Elo-Ratings um 25% zur Mitte (1500)
zurückgezogen, bevor das erste Spiel der neuen Saison verarbeitet wird:

```python
ELO_SEASON_REGRESSION = 0.75  # 25% Regression zur Mitte
elo[team] = 1500.0 + (elo[team] - 1500.0) * ELO_SEASON_REGRESSION
```

Gilt für `calculate_elo_ratings()` und `calculate_elo_per_game()`.
Verhindert, dass ein Team aus einer schlechten Saison 2021 mit unverhältnismäßig
niedrigem Elo in die Saison 2024 startet.

#### Elo-Cache-Fix (`ml_predictor.py`)

`self._elo_cache = None` wurde aus `predict()` entfernt. Der Cache ist
instanz-weit gültig und wird automatisch beim Erstellen eines neuen
`MLPredictor`-Objekts zurückgesetzt. Bei Vorhersagen für mehrere Spiele
in einer Session werden 1300 Spielergebnisse jetzt nur noch einmal geladen.

#### `Game.winner` bei Gleichstand (`game.py`)

Bei `home_score == away_score` wurde fälschlicherweise `away_team` zurückgegeben.
Jetzt explizite Drei-Wege-Logik: `home > away → home`, `away > home → away`,
sonst `None`. Im NBA-Betrieb durch Verlängerungen nicht relevant, aber
korrekt für Bet-Resolver-Logik.

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/ml/data_collector.py` | `_compute_fatigue()` (NEU), `last_3_win_rate` (NEU), `form_rating` L3+L5+L10, Pace geclampt |
| `src/ml/elo.py` | `_regress_to_mean()` (NEU), Saisonwechsel-Tracking in beiden Elo-Funktionen |
| `src/ml/ml_predictor.py` | Elo-Cache-Reset aus `predict()` entfernt |
| `src/api/nba_stats_client.py` | Pace-Clamping in `from_basic_stats()` |
| `src/models/game.py` | `winner`-Property: `None` statt `away_team` bei Gleichstand |

### Inkompatibilitäten / Migration

Das v4-Modell (45 Features) bleibt kompatibel – die Feature-Anzahl ändert sich
nicht. Allerdings liefern `fatigue_score` und `form_rating` jetzt andere Werte
als beim Training des v4-Modells. **Neutraining empfohlen**, um von den
korrekten Feature-Werten zu profitieren.

```bash
# Daten NEU sammeln (korrigierte Fatigue- und Form-Formeln):
python main.py train collect --seasons 2021 2022 2023 2024 --max-games 5000

# Modell neu trainieren:
python main.py train model
```

---

## [0.6.0] – Data Leakage Fix, kumulative Stats & Odds-Bereinigung

Kritischer Fix der ML-Pipeline: Data Leakage durch Saison-Endstand-Stats
behoben, nutzloses Odds-Feature entfernt, neuer kumulativer Stats-Tracker
für faire Trainingsdaten. Die gemessene Accuracy sinkt erwartungsgemäß –
die echte Vorhersagequalität steigt.

### Problemanalyse

Ausgangspunkt war eine grob falsche Vorhersage: Das Modell gab den
Brooklyn Nets ~80% Siegwahrscheinlichkeit gegen die Portland Trail Blazers,
das Spiel endete jedoch 133:99 für Portland. Die Analyse deckte sechs
Ursachen auf, von denen zwei kritisch waren:

| # | Problem | Schwere | Status |
|---|---------|---------|--------|
| 1 | `odds_implied_home_prob` im Training immer 0.5, bei Predict echte Werte | Kritisch | ✅ Behoben |
| 2 | Saison-Endstand-Stats als Features (Data Leakage) | Kritisch | ✅ Behoben |
| 3 | Advanced Stats: geschätzt bei Predict, echt bei Train | Mittel | ⚠️ Teilweise (konsistent geschätzt) |
| 4 | Keine Verletzungs-Features | Mittel | 📋 Backlog |
| 5 | Zu wenig Trainingsdaten | Niedrig | ✅ Bereits in v0.5.0 behoben |
| 6 | Clip auf 5%–95% verstärkt Fehler | Niedrig | 📋 Backlog |

**Data Leakage im Detail:** Beim Training sah das Modell für jedes Spiel
die Saison-Endstand-Statistiken beider Teams – auch für Spiele am
Saisonbeginn. Beispiel: Toronto Raptors hatten im allerersten Saisonspiel
2019 bereits eine Win-Rate von 0.72 (ihr Endstand nach 82 Spielen).
Das Modell lernte effektiv aus der Zukunft, was die gemessene Accuracy
um ~4.7 Prozentpunkte künstlich aufblähte.

**Odds-Feature im Detail:** `odds_implied_home_prob` wurde beim Sammeln
der Trainingsdaten auf 0.5 hardcoded (keine historischen Quoten verfügbar).
Das Modell trainierte mit einem Feature, das nie variiert. Bei echten
Vorhersagen kamen dann reale Wettquoten (z.B. 0.35 oder 0.72) in den
Feature-Vektor – ein klassischer Train/Predict-Mismatch.

### Gemessene Ergebnisse

| Metrik | v3 (mit Leakage) | v4 (bereinigt) | Veränderung | Bewertung |
|--------|-------------------|-----------------|-------------|-----------|
| Accuracy | **69.8%** | **65.1%** | -4.7pp | Erwartet – Leakage entfernt |
| ROC-AUC | **0.7427** | **0.706** | -0.037 | Erwartet |
| Brier Score | **0.2034** | **0.215** | +0.012 | Erwartet |
| CV Accuracy | **68.9% ± 2.2%** | **64.1% ± 0.5%** | -4.8pp | Deutlich stabiler |
| Features | 46 | **45** | -1 | odds entfernt |
| Modell | LogisticRegression | **LogisticRegression** | – | Konsistent |

**Warum der Rückgang positiv ist:** Die v3-Accuracy von 69.8% war
geschmeichelt – das Modell schaute beim Training in die Zukunft. Die
v4-Accuracy von 65.1% ist die *echte* Vorhersageleistung, die in der
Praxis reproduzierbar ist. Die CV-Varianz sank von ±2.2% auf ±0.5%,
was zeigt, dass das Modell deutlich stabiler generalisiert.

### Einordnung: Wo steht das Modell?

```
NBA-Vorhersage-Benchmark (Accuracy)
─────────────────────────────────────────────────────────────────
50%         55%         60%         65%      67%      70%    73%
 │           │           │           │        │        │      │
 │  Zufall   │  Elo nur  │           │ Buch-  │  Beste │      │
 │  (Münze)  │  (~63%)   │           │ macher │  ML-   │      │
 │           │           │           │(67-68%)│ Modelle│      │
 │           │           │           │        │(69-72%)│      │
 │           │           │      ★ v4 │        │        │      │
 │           │           │     65.1% │        │        │      │
─────────────────────────────────────────────────────────────────
```

**65.1%** liegt über simplen Elo-Modellen (~63%) aber noch unter den
Buchmachern (~67-68%). Die Lücke erklärt sich durch fehlende Features,
die Buchmacher haben: Verletzungsdaten, Lineup-Informationen,
Spieler-Level-Statistiken und Reisedaten. Das Modell arbeitet ausschließlich
mit team-aggregierten Features und geschätzten Advanced Stats.

**Referenzwerte für NBA-Vorhersagemodelle:**

| Modell / System | Accuracy | Datenquellen |
|-----------------|----------|--------------|
| Münzwurf + Heimvorteil | ~55% | Keine |
| Einfaches Elo | ~63% | Spielergebnisse |
| **NBAPredict v4** | **65.1%** | **Team-Stats, Elo, Form** |
| Buchmacher (Closing Lines) | ~67-68% | Umfassend, proprietär |
| FiveThirtyEight RAPTOR | ~69% | Spieler-Level, proprietär |
| Beste akademische Modelle | ~70-72% | Spieler-Tracking, Lineup |

### Feature-Analyse: Shift nach Data-Leakage-Fix

**v3 Top-Features (mit Leakage):**
```
away_away_win_rate    0.459   ← Kontextuelle Win-Rates dominierten
home_home_win_rate    0.422
home_away_win_rate    0.257
away_home_win_rate    0.242
diff_win_rate         0.145
```

**v4 Top-Features (ohne Leakage):**
```
home_defensive_rating 2.193   ← Defensive Metriken dominieren jetzt
home_avg_pts_allowed  1.868
home_point_diff       1.512
home_net_rating       1.279
away_point_diff       1.152
```

Der Shift ist sportlich plausibel: Ohne Leakage-verzerrte Win-Rates
lernt das Modell, dass defensive Stärke des Heimteams und
Punkt-Differenz die besten Einzelprädiktoren für NBA-Siege sind.
Das entspricht dem allgemeinen Konsens in der NBA-Analytik
("Defense wins championships").

**Hinweis:** Die v4-Werte sind LogReg-Koeffizienten (abs. Betrag),
nicht Feature-Importances. Sie zeigen, wie stark ein Feature die
Log-Odds verschiebt. Hohe Werte bei `home_defensive_rating` bedeuten:
"Ein Heimteam mit guter Defense hat die stärkste Vorhersagekraft."

### Technische Änderungen

#### Neuer `_CumulativeTeamTracker`

Neue Klasse in `data_collector.py`, die Team-Statistiken chronologisch
über die Saison akkumuliert. Für jedes Spiel liefern die Properties
den Zustand *vor* dem Spiel; nach der Feature-Erstellung wird `update()`
aufgerufen.

| Property | Beschreibung |
|----------|--------------|
| `win_rate` | Kumulative Win-Rate (0.5 bei Saisonstart) |
| `home_win_rate` / `away_win_rate` | Getrennt nach Spielort |
| `last_5_win_rate` / `last_10_win_rate` | Rollierende Form |
| `current_streak` | Positiv = Siege, negativ = Niederlagen |
| `days_rest_before(date)` | Ruhetage vor einem bestimmten Spiel |
| `games_last_7_days_before(date)` | Belastung in der Vorwoche |
| `form_rating` | Gewichtete Form (neuere Spiele stärker) |
| `compute_advanced_stats()` | Off/Def Rating, Pace, TS% aus Basisdaten |

#### `build_samples_cumulative()`

Ersetzt `_build_samples()` + `_game_to_sample()`. Sortiert alle Spiele
chronologisch, iteriert durch und erstellt Features ausschließlich aus
bisherigen Daten. `MIN_GAMES_THRESHOLD = 10`: Die ersten 10 Spiele pro
Team pro Saison werden übersprungen (zu wenig Datenbasis für stabile Stats).

#### Vereinfachte `collect()`-Methode

| Schritt | v3 (vorher) | v4 (jetzt) |
|---------|-------------|------------|
| 1 | Spiele laden | Spiele laden |
| 2 | Team-Standings pro Saison | *(entfallen)* |
| 3 | Advanced Stats (NBA.com) | *(entfallen)* |
| 4 | Elo-Ratings | Elo-Ratings |
| 5 | Samples aus Endstand-Stats | Kumulative Samples |

#### `odds_implied_home_prob` aus Features entfernt

- `get_feature_columns()`: Feld zu `excluded_fields` hinzugefügt
- `_build_feature_vector()`: `odds_prob`-Berechnung und letzte Zeile entfernt
- Feature-Anzahl: 46 → 45
- Das Feld bleibt im `TrainingSample`-Dataclass für CSV-Kompatibilität

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/ml/data_collector.py` | `_CumulativeTeamTracker`, `build_samples_cumulative()`, vereinfachte `collect()`, `get_feature_columns()` ohne odds |
| `src/ml/ml_predictor.py` | `_build_feature_vector()` ohne odds (45 statt 46 Features) |
| `tests/test_ml_system.py` | 45-Feature-Asserts, `TestCumulativeTeamTracker` (9 Tests), odds-Ausschluss-Test |

### Behoben

- **Data Leakage:** Saison-Endstand-Stats → kumulative Stats bis Spieltag
- **Train/Predict-Mismatch (Odds):** Feature entfernt, das im Training 0.5 war
- **Train/Predict-Konsistenz (Advanced Stats):** Beide Pfade nutzen jetzt die gleiche `from_basic_stats`-Berechnung

### Inkompatibilitäten / Migration

Das v3-Modell ist **inkompatibel** (46 Features ≠ 45 Features).
Daten müssen neu gesammelt und das Modell neu trainiert werden.

```bash
# Altes Modell löschen
rm data/models/nba_predictor.joblib data/models/model_metrics.json

# Daten NEU sammeln (kumulative Stats):
python main.py train collect --seasons 2019 2020 2021 2022 2023 2024 --max-games 7800

# Modell neu trainieren:
python main.py train model

# Tests:
pytest tests/test_ml_system.py -v
```

### Verbesserungspotenzial (priorisiert nach erwartetem Hebel)

#### 1. Echte Advanced Stats bei Prediction (~1-2% Accuracy)

Aktuell werden Off/Def Rating, Pace und TS% sowohl beim Training als
auch bei der Prediction über `build_advanced_stats_from_basic()` geschätzt.
Die Pace-Schätzung `98.0 + (pts - 110) * 0.3` kann 5-10 Punkte von der
Realität abweichen. Wenn `nba_api` zuverlässig auf dem Raspberry Pi läuft,
sollte `_get_advanced_stats()` in `ml_predictor.py` echte Daten von
stats.nba.com holen statt zu schätzen. Konsistenz mit dem Training muss
dann ebenfalls über echte Stats hergestellt werden.

#### 2. Verletzungs-Features (~1-3% Accuracy)

Ein einzelner Star-Ausfall verschiebt die Siegwahrscheinlichkeit um
5-10%. Das Team-Model hat bereits `injured_players_count` und
`injured_salary_ratio` als Felder – sie werden nur nie befüllt.
Mögliche Datenquellen: ESPN Injury API, RotoWire, oder Web Scraping.
Die Integration als Feature in den `_CumulativeTeamTracker` wäre
straightforward, sobald eine Datenquelle angebunden ist.

#### 3. CalibratedClassifierCV für baumbasierte Modelle (~0.5-1% Brier)

LogReg gewinnt aktuell, weil es von Natur aus kalibrierte
Wahrscheinlichkeiten liefert. XGBoost und GradientBoosting hatten
bessere Roh-Accuracy (-0.2228 vs -0.2227 Brier), sind aber
overconfident. Ein `CalibratedClassifierCV`-Wrapper mit isotonischer
Regression könnte die Stärke beider Ansätze kombinieren:

```python
from sklearn.calibration import CalibratedClassifierCV
calibrated_xgb = CalibratedClassifierCV(xgb_model, method="isotonic", cv=5)
```

#### 4. Historische Wettquoten als echtes Feature (~0.5-1% Accuracy)

The Odds API bietet historische Quoten. Wenn diese beim Datensammeln
mitgespeichert werden (statt 0.5 zu hardcoden), wäre
`odds_implied_home_prob` ein wertvolles Feature – Buchmacher-Quoten
enthalten Informationen, die das Modell nicht hat (Insider-Wissen,
Verletzungen, etc.). Erfordert API-Calls beim Collect.

#### 5. Head-to-Head-Feature und Reisedaten (marginal)

Historische Duelle zwischen Teams und Reisedistanz/Zeitzonen-Effekte
könnten geringe Verbesserungen bringen, sind aber aufwändig zu
implementieren und haben in der Literatur nur marginalen Effekt
(~0.2-0.5% Accuracy).

---

## [0.5.0] – ML-Optimierung: Elo, XGBoost, Grid Search & Kalibrierung

Umfassende Optimierung der ML-Pipeline in 5 Phasen. Feature-Anzahl
von 43 auf 46 erhöht (Elo-Ratings), Scoring von Accuracy auf Brier Score
umgestellt, XGBoost als vierter Modellkandidat, Grid Search für
Hyperparameter-Tuning und Pagination-Fix für deutlich mehr Trainingsdaten.

### Gemessene Ergebnisse

| Metrik | Vorher (v2, ~500 Samples) | Nachher (v3, 7514 Samples) | Veränderung |
|--------|---------------------------|----------------------------|-------------|
| Accuracy | ~58–63% (geschätzt) | **69.8%** | +7–12% |
| ROC-AUC | – | **0.7427** | – |
| Brier Score | – | **0.2034** | – |
| CV Accuracy | – | **68.9% ± 2.2%** | – |
| Trainingssamples | ~500 | **7514** (6011 Train / 1503 Test) | ×15 |
| Features | 43 | **46** (+3 Elo) | +3 |
| Modellkandidaten | 3 (RF, GB, LogReg) | **4** (+XGBoost) | +1 |

**Gewähltes Modell: LogisticRegression.** Trotz Verfügbarkeit von XGBoost,
Random Forest und Gradient Boosting hat die Logistische Regression mit
StandardScaler über alle drei Trainingsläufe konsistent den besten
neg_brier_score erzielt. Das zeigt, dass bei gut gewählten Features ein
einfacheres, lineares Modell besser kalibrierte Wahrscheinlichkeiten liefert
als baumbasierte Modelle – entscheidend für profitable Wettempfehlungen.

### Trainingsprotokoll (3 Durchläufe)

**Durchlauf 1 – Baseline (7514 Samples, 43 Features, Accuracy-Scoring):**

```
Modell:     LogisticRegression
Accuracy:   69.2%
ROC-AUC:    0.7422
Brier:      0.2033
CV:         68.8% ± 2.0%
Top-Feature: away_away_win_rate (0.466)
```

**Durchlauf 2 – Brier-Score-Scoring (gleiche Daten):**

```
Modell:     LogisticRegression
Accuracy:   69.2%
ROC-AUC:    0.7422
Brier:      0.2033
CV:         68.8% ± 2.0%
```

Identisches Ergebnis, weil bei diesen Daten das Brier-optimale und
das Accuracy-optimale Modell dasselbe sind. Bestätigt, dass LogReg
von Natur aus gut kalibriert ist (im Gegensatz zu baumbasierten Modellen
die oft overconfident sind).

**Durchlauf 3 – Elo-Features + Grid Search + XGBoost (7514 Samples, 46 Features):**

```
Modell:     LogisticRegression
Accuracy:   69.8% (+0.6%)
ROC-AUC:    0.7427 (+0.0005)
Brier:      0.2034 (+0.0001)
CV:         68.9% ± 2.2%
Top-Features:
  away_away_win_rate   0.459
  home_home_win_rate   0.422
  home_away_win_rate   0.257
  away_home_win_rate   0.242
  diff_win_rate        0.145
```

Elo hat die Accuracy um 0.6% verbessert. Elo-Features tauchen nicht in
den Top-5 der Feature-Importances auf, was bedeutet, dass sie ergänzende
Information liefern die das Modell nutzt, aber nicht die dominanten
Prädiktoren sind. Die dominanten Features sind Heim-/Auswärts-Win-Rates
und die Win-Rate-Differenz – konsistent über alle Durchläufe.

### Interpretation der Ergebnisse

**69.8% Accuracy** war künstlich durch Data Leakage erhöht (siehe v0.6.0).
Die echte Vorhersageleistung liegt bei **65.1%** (v4, bereinigt).

**Brier Score 0.2034** bei einem Erwartungswert von 0.25 für zufälliges
Raten zeigt solide Kalibrierung. Perfekt kalibriert wäre ~0.18–0.19 für
NBA-Daten. Verbesserungspotenzial besteht, aber der Wert ist für
Wettempfehlungen brauchbar.

**LogReg als Gewinner** ist kein Zufall: Bei 46 Features und 7500 Samples
hat LogReg genug Daten für stabile Koeffizienten, ist inherent gut
kalibriert (Output ist per Definition eine Wahrscheinlichkeit), und
overfittet weniger als baumbasierte Modelle. Für die Zukunft könnte
eine CalibratedClassifierCV um XGBoost/GB herum bessere Ergebnisse liefern.

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/ml/elo.py` | Elo-Rating-Berechnung (NEU) |
| `src/ml/data_collector.py` | 46 Features, Elo-Integration, Pagination-Fix |
| `src/ml/ml_predictor.py` | 46er Feature-Vektor, Elo-Cache für Vorhersagen |
| `src/ml/model_trainer.py` | XGBoost, Grid Search, Brier-Scoring, float-inf-Fix |
| `tests/test_ml_system.py` | Angepasst an 46 Features, Elo-Tests |
| `requirements.txt` | xgboost, flask, flask-cors |

---

### Hinzugefügt

#### Phase 1: Mehr Trainingsdaten (Pagination-Fix)

**Problem:** Der data_collector nutzte seitenbasierte Pagination
(page=1, 2, 3), aber die BallDontLie API v1 verwendet cursor-basierte
Pagination. Ergebnis: exakt 100 Spiele pro Saison (nur erste Seite),
unabhängig vom --max-games-Parameter.

**Lösung:** _fetch_historical_games nutzt jetzt
nba_client._fetch_season_games_paginated() mit cursor-basierter
Pagination. Die alte _fetch_season_games-Methode wurde entfernt.

**Effekt:** Von ~600 auf **7514 Samples** bei 6 Saisons. Das ist der
mit Abstand größte Einzelhebel für die Modellqualität – die Accuracy
stieg allein dadurch von ~60% auf ~69%.

**Wichtig:** --max-games ist das Gesamtlimit über alle Saisons.
Für 6 Saisons à ~1200 Spiele: --max-games 7800 verwenden.

```bash
python main.py train collect --seasons 2019 2020 2021 2022 2023 2024 --max-games 7800
```

#### Phase 2: Brier Score als Optimierungsziel

**Entscheidung:** Scoring von accuracy auf neg_brier_score umgestellt.

**Begründung:** Für Wettempfehlungen sind kalibrierte Wahrscheinlichkeiten
wichtiger als reine Trefferquote. Ein Modell das bei "70% Chance" auch
~70% der Spiele richtig vorhersagt, ermöglicht profitablere EV-Berechnungen
als eins mit höherer Accuracy aber verzerrten Wahrscheinlichkeiten.

**Technisch:** SCORING_METRIC = "neg_brier_score" als Modul-Konstante.
best_score initialisiert mit float("-inf") statt 0.0 (da Brier
Scores negiert und damit negativ sind).

**Ergebnis:** Bei diesen Daten wählt Brier-Scoring dasselbe Modell wie
Accuracy-Scoring (LogReg). Das bestätigt, dass LogReg von Natur aus
gut kalibriert ist.

#### Phase 3: Elo-Rating als Feature

Neues Modul src/ml/elo.py mit zwei Funktionen:

| Funktion | Beschreibung |
|----------|--------------|
| calculate_elo_ratings(games) | Finale Elo-Ratings (für Vorhersagen) |
| calculate_elo_per_game(games) | Elo zum Zeitpunkt jedes Spiels (für Trainingsdaten) |

Elo-System-Parameter:

| Parameter | Wert | Begründung |
|-----------|------|------------|
| K-Faktor | 20 | NBA-Standard, balanciert Reaktivität und Stabilität |
| Heimvorteil | 100 Elo-Punkte | Entspricht ~60% erwarteter Heimsiegquote |
| Start-Elo | 1500 | Konvention |
| MoV-Multiplikator | ((mov+3)^0.8) / (7.5 + 0.006*elo_diff) | Deutliche Siege zählen mehr, gedämpft bei großen Elo-Differenzen |

Drei neue Features: home_elo, away_elo, diff_elo. Feature-Anzahl: **43 → 46**.

**Effekt:** +0.6% Accuracy (69.2% → 69.8%), +0.0005 ROC-AUC.

#### Phase 4: XGBoost als Modellkandidat

XGBoost als vierter Kandidat mit optionalem Import (HAS_XGBOOST-Flag).
Wenn xgboost nicht installiert ist, wird der Kandidat übersprungen.

**Ergebnis:** Bei diesen Daten wurde XGBoost nicht als bestes Modell
gewählt – LogReg hatte den besseren Brier Score. XGBoost neigt dazu,
overconfident zu sein, was den Brier Score verschlechtert.

#### Phase 5: Grid Search mit automatischem Fallback

Grid Search wird bei >1000 Samples aktiviert, sonst feste Parameter.
Reduzierte Grid-Größe: ~115 Fits statt ~1350. Laufzeit ~3–5 Min.

| Modell | Kombinationen × 5 Folds |
|--------|-------------------------|
| GradientBoosting | 40 Fits |
| RandomForest | 20 Fits |
| LogisticRegression | 15 Fits |
| XGBoost | 40 Fits |
| **Gesamt** | **115 Fits** |

---

### Behoben

- **Pagination-Bug:** Immer exakt 100 Spiele/Saison wegen page- statt cursor-Pagination.
- **float("-inf")-Fix:** best_score = 0.0 verhinderte Modellauswahl bei neg_brier_score.
- **Grid-Search-Laufzeit:** Von ~1350 auf ~115 Fits reduziert.

---

### Top-Features (Interpretation)

| Rang | Feature | Importance | Interpretation |
|------|---------|------------|----------------|
| 1 | away_away_win_rate | 0.459 | Wie gut das Auswärtsteam auswärts spielt |
| 2 | home_home_win_rate | 0.422 | Wie gut das Heimteam zu Hause spielt |
| 3 | home_away_win_rate | 0.257 | Allgemeine Stärke des Heimteams |
| 4 | away_home_win_rate | 0.242 | Allgemeine Stärke des Auswärtsteams |
| 5 | diff_win_rate | 0.145 | Direkte Win-Rate-Differenz |

Das Modell gewichtet kontextuelle Win-Rates (Heim/Auswärts) deutlich
stärker als aggregierte Metriken wie Net-Rating oder Elo. "Wo wird
gespielt?" ist der dominante Vorhersagefaktor.

**Hinweis:** Diese Feature-Importances stammen aus dem v3-Training
*mit* Data Leakage. Die v4-Features (ohne Leakage) zeigen einen
deutlichen Shift hin zu defensiven Metriken – siehe v0.6.0.

---

### Inkompatibilitäten / Migration

```bash
rm data/training/training_data.csv data/models/nba_predictor.joblib
pip install -r requirements.txt
python main.py train collect --seasons 2019 2020 2021 2022 2023 2024 --max-games 7800
python main.py train model
pytest
```

---

---

## [0.4.0] – Wettempfehlung, Wett-Tracker & Analyse-Dashboard

Drei neue Features: Value-Bet-Empfehlungen auf der Compare-Seite,
ein virtueller Wett-Tracker mit SQLite-Speicherung und ein
umfassendes Analyse-Dashboard zur Bewertung der Modell-Effektivität.

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| src/ml/comparison.py | Wettempfehlungs-Properties auf ComparisonEntry |
| src/betting/tracker.py | Virtueller Wett-Tracker mit SQLite (NEU) |
| src/betting/resolver.py | Auto-Auflösung offener Wetten (NEU) |
| src/betting/__init__.py | Modul-Exporte (NEU) |
| scripts/resolve_bets.py | Cron-Job-Skript für Raspberry Pi (NEU) |
| web/server.py | Neue API-Routen für Wetten + Analytics |
| web/static/index.html | Aufgeteilt in HTML/CSS/JS |
| web/static/style.css | Ausgelagert inkl. Bet-Styles (NEU) |
| web/static/app.js | Ausgelagert inkl. Bet-Logik (NEU) |
| src/api/nba_api_client.py | Clippers-Alias-Fix |

---

### Hinzugefügt

- Value-Bet-Empfehlungen (EV, Edge, Rating) auf ComparisonEntry
- Virtueller Wett-Tracker mit SQLite (place, resolve, stats, analytics)
- Analyse-Dashboard (Kalibrierung, Kelly, Rating-Breakdown, etc.)
- 8 neue API-Endpunkte für den Wett-Tracker
- Frontend aufgeteilt in HTML/CSS/JS mit neuem Wetten-Tab
- Raspberry-Pi-Deployment (systemd + Cron)

### Behoben

- LA Clippers Name-Mismatch (BallDontLie "LA Clippers" vs Odds API "Los Angeles Clippers")
- Bidirektionaler Teamname-Vergleich in get_team_stats()

---

---

## [Unreleased] – Teambewertung & ML-Pipeline v2

Komplette Überarbeitung beider Vorhersagepfade (regelbasiert + ML-Modell).

### Hinzugefügt

- Team-Model: 4 neue Felder (days_rest, games_last_7_days, injured_players_count, injured_salary_ratio)
- Team-Model: 6 neue Properties (last_3_win_rate, current_streak, is_back_to_back, is_well_rested, fatigue_score, injury_impact)
- Predictor v2: 4 neue Faktoren (Defensiv-Stärke, Ruhetage, Verletzungen, Streak)
- ML-Pipeline: 10 neue Features, Feature-Anzahl 33 → 43

### Geändert

- Predictor-Gewichte neu kalibriert (10 Faktoren, Summe = 1.0)
- form_rating: 0.3×L3 + 0.4×L5 + 0.3×L10
- HOME_ADVANTAGE_BONUS: 0.05 → 0.04
- NBA_AVG_POINTS: 113.0 → 113.5

### Behoben

- _normalize_odds als @staticmethod wiederhergestellt

### Noch nicht implementiert (TODO)

- Verletzungsdaten (externe Quelle nötig)
- CalibratedClassifierCV für baumbasierte Modelle
- Head-to-Head-Feature
- Reisedistanz / Zeitzonen als Feature
