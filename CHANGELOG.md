# Changelog

Alle relevanten Änderungen am NBA Tracker werden in dieser Datei dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

---

## [0.4.0] – Wettempfehlung, Wett-Tracker & Analyse-Dashboard

Drei neue Features: Value-Bet-Empfehlungen auf der Compare-Seite,
ein virtueller Wett-Tracker mit SQLite-Speicherung und ein
umfassendes Analyse-Dashboard zur Bewertung der Modell-Effektivität.

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/ml/comparison.py` | Wettempfehlungs-Properties auf `ComparisonEntry` |
| `src/betting/tracker.py` | Virtueller Wett-Tracker mit SQLite (NEU) |
| `src/betting/resolver.py` | Auto-Auflösung offener Wetten (NEU) |
| `src/betting/__init__.py` | Modul-Exporte (NEU) |
| `scripts/resolve_bets.py` | Cron-Job-Skript für Raspberry Pi (NEU) |
| `web/server.py` | Neue API-Routen für Wetten + Analytics, erweiterte Compare-API |
| `web/static/index.html` | Aufgeteilt in HTML/CSS/JS, neue Bets-Seite |
| `web/static/style.css` | Ausgelagert aus index.html, inkl. Bet-Styles (NEU) |
| `web/static/app.js` | Ausgelagert aus index.html, inkl. Bet-Logik (NEU) |
| `src/api/nba_api_client.py` | Clippers-Alias-Fix, robusteres Team-Matching |

---

### Hinzugefügt

#### Wettempfehlung auf der Compare-Seite

Neue Properties auf `ComparisonEntry` in `src/ml/comparison.py`:

| Property | Typ | Beschreibung |
|----------|-----|--------------|
| `ev_home` / `ev_away` | `float` | Expected Value: `(KI-Prob × Quote) - 1` |
| `best_ev` | `float` | Höchster EV der beiden Seiten |
| `bet_team` | `str` | Name des Teams mit bestem EV |
| `bet_side` | `str` | `"home"` oder `"away"` |
| `bet_odds_raw` | `float` | Dezimalquote der empfohlenen Seite |
| `bet_ml_prob` | `float` | KI-Wahrscheinlichkeit der empfohlenen Seite |
| `bet_odds_prob` | `float` | Quoten-Wahrscheinlichkeit der empfohlenen Seite |
| `edge` | `float` | `bet_ml_prob - bet_odds_prob` |
| `bet_rating` | `str` | `"strong"` / `"good"` / `"slight"` / `"none"` |
| `bet_rating_label` | `str` | Menschenlesbares Label (z.B. "🔥 Stark empfohlen") |
| `bet_confidence` | `int` | Score 0–100 basierend auf Edge + Methodenübereinstimmung |

Bewertungsstufen:

| Rating | Edge | Label |
|--------|------|-------|
| `strong` | ≥ 15% | 🔥 Stark empfohlen |
| `good` | ≥ 8% | ✅ Empfohlen |
| `slight` | ≥ 4% | 💡 Leicht positiv |
| `none` | < 4% | ⏸️ Kein Value |

#### Virtueller Wett-Tracker

Neues Modul `src/betting/` mit SQLite-Datenbank (`data/betting/bets.db`).

**`src/betting/tracker.py` – BettingTracker:**

| Methode | Beschreibung |
|---------|--------------|
| `place_bet()` | Virtuelle Wette platzieren (10 Einheiten Standard) |
| `resolve_bet()` | Wette als gewonnen/verloren auflösen |
| `get_stats()` | Aggregierte Statistiken (W/L, ROI, Serien, Rating-Aufschlüsselung) |
| `get_profit_history()` | Kumulativer Profitverlauf für Charts |
| `get_analytics()` | Umfassende Effektivitäts-Analyse (siehe unten) |
| `get_all_bets()` | Alle Wetten mit optionalem Status-Filter |
| `delete_bet()` / `reset()` | Einzelne/alle Wetten löschen |

**`src/betting/resolver.py` – BetResolver:**

| Methode | Beschreibung |
|---------|--------------|
| `resolve_all_open()` | Prüft Spiele der letzten 3 Tage via BallDontLie-API und löst offene Wetten auf |

**`scripts/resolve_bets.py` – Cron-Job:**

Standalone-Skript für den Raspberry Pi. Einrichten per `crontab -e`:

```cron
0 9 * * * cd /home/pi/nba-tracker && .venv/bin/python scripts/resolve_bets.py >> logs/resolve.log 2>&1
```

SQLite-Tabelle `bets`:

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | INTEGER PK | Auto-Increment |
| `home_team` / `away_team` | TEXT | Teamnamen |
| `bet_on` | TEXT | Gewettetes Team |
| `bet_side` | TEXT | `"home"` / `"away"` |
| `odds` | REAL | Dezimalquote zum Wettzeitpunkt |
| `stake` | REAL | Virtueller Einsatz (Default: 10.0) |
| `ml_prob` / `odds_prob` | REAL | KI- und Quoten-Wahrscheinlichkeit |
| `edge` / `ev` | REAL | Edge und Expected Value |
| `bet_rating` | TEXT | Rating-Stufe |
| `status` | TEXT | `"open"` / `"won"` / `"lost"` |
| `actual_winner` | TEXT | Tatsächlicher Gewinner (nach Auflösung) |
| `payout` / `profit` | REAL | Auszahlung und Gewinn/Verlust |
| `placed_at` / `resolved_at` | TEXT | ISO-Zeitstempel |

WAL-Modus aktiviert für bessere Performance auf dem Raspberry Pi.

#### Analyse-Dashboard (`get_analytics()`)

Umfassende Effektivitäts-Analyse über alle aufgelösten Wetten:

| Dimension | Beschreibung |
|-----------|--------------|
| `profit_history` | Kumulativer Profitverlauf (Chartdaten) |
| `by_rating` | Bilanz pro Empfehlungsstufe (strong/good/slight/none) mit Win%, ROI, Ø Quote, Ø Edge |
| `by_team` | Profitabelste Teams (Top 15, sortiert nach Profit) |
| `by_side` | Heim- vs Auswärts-Wetten |
| `by_odds_range` | Gruppiert nach Quotenbereich (1.0–1.5, 1.5–2.0, 2.0–2.5, 2.5–3.5, 3.5+) |
| `by_edge_range` | Gruppiert nach Edge-Bereich (0–5%, 5–10%, 10–15%, 15–20%, 20%+) |
| `calibration` | KI-Wahrscheinlichkeit vs tatsächliche Win-Rate in 10%-Buckets |
| `expected_vs_actual` | Erwarteter Profit (Summe EV) vs tatsächlicher Profit |
| `weekly` | Wöchentlicher Verlauf mit kumulativem Stand |
| `kelly_analysis` | Kelly-Criterion-Simulation: optimaler Einsatz vs Flat-Stake |
| `avg_profit_won` / `avg_profit_lost` | Ø Gewinn bzw. Verlust pro Wette |

**Kalibrierungs-Analyse:** Zeigt ob das KI-Modell gut kalibriert ist.
Beispiel: Wenn die KI "70% Chance" sagt, sollten ~70% der Wetten gewonnen werden.
Positiver Diff-Wert = Modell unterschätzt, Negativer = Modell überschätzt.

**Kelly-Criterion-Simulation:** Simuliert was passiert wäre, wenn statt
eines festen Einsatzes (10 Einheiten) der mathematisch optimale
Kelly-Einsatz verwendet worden wäre. Start-Bankroll: 1000 Einheiten.
Kelly-Fraction gecappt bei 25% pro Wette.

#### Neue API-Endpunkte in `web/server.py`

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| GET | `/api/bets` | Alle Wetten (optional `?status=open`) |
| POST | `/api/bets` | Neue Wette platzieren |
| DELETE | `/api/bets/<id>` | Wette löschen |
| GET | `/api/bets/stats` | Aggregierte Statistiken |
| GET | `/api/bets/history` | Kumulativer Profitverlauf |
| GET | `/api/bets/analytics` | Umfassende Effektivitäts-Analyse |
| POST | `/api/bets/resolve` | Offene Wetten automatisch auflösen |
| POST | `/api/bets/reset` | ALLE Wetten löschen |

Erweiterte Compare-API (`/api/compare`) mit 10 neuen Feldern:
`bet_team`, `bet_side`, `bet_rating`, `bet_rating_label`, `bet_ev`,
`bet_edge`, `bet_confidence`, `bet_odds_raw`, `bet_ml_prob`, `bet_odds_prob`.

#### Frontend-Aufspaltung

`web/static/index.html` wurde in drei Dateien aufgeteilt:

| Datei | Zeilen | Inhalt |
|-------|--------|--------|
| `index.html` | ~195 | Reines HTML-Markup, lädt `style.css` + `app.js` |
| `style.css` | ~410 | Alle CSS-Regeln inkl. Bet-Recommendation + Bet-Tracker |
| `app.js` | ~980 | Gesamte JS-Logik inkl. Compare mit Wette-Button + Analyse-Tab |

Referenzen in index.html nutzen `/static/`-Prefix für Flask:
```html
<link rel="stylesheet" href="/static/style.css">
<script src="/static/app.js"></script>
```

Neue Seite **💰 Wetten** mit 4 Tabs:

| Tab | Beschreibung |
|-----|--------------|
| Dashboard | Bilanz, ROI, Serien, Profit nach Rating-Stufe |
| Offen | Alle offenen Wetten mit Lösch-Button |
| Historie | Alle Wetten chronologisch |
| Analyse | Vollständiges Effektivitäts-Dashboard (11 Sektionen) |

"Wette platzieren"-Button in jeder Compare-Karte (nur bei Rating ≠ "none").

#### Raspberry-Pi-Deployment

Systemd-Service-Konfiguration für dauerhaften Betrieb:

```ini
[Unit]
Description=NBA Tracker Web-Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/nba-tracker
ExecStart=/home/pi/nba-tracker/.venv/bin/python web/server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

### Behoben

#### LA Clippers Team-Name-Mismatch

**Problem:** BallDontLie-API führt das Team seit Saison 2024/25 als
"LA Clippers", die Odds API sendet weiterhin "Los Angeles Clippers".
Der Namensvergleich in `get_team_stats()` findet keinen Match.

**Lösung in `src/api/nba_api_client.py`:**

1. Neue Aliase in `TEAM_NAME_ALIASES`:
```python
"clippers":              "LA Clippers",
"los angeles clippers":  "LA Clippers",
"la clippers":           "LA Clippers",
```

2. Bidirektionaler Vergleich in `get_team_stats()`:
```python
# ALT (nur einseitig):
if resolved_name.lower() in team.name.lower():

# NEU (bidirektional):
if resolved_lower in name_lower or name_lower in resolved_lower:
```

---

### Neue Projektstruktur (ergänzt)

```
src/betting/                    # NEU
├── __init__.py
├── tracker.py                  # SQLite-Wett-Tracker + Analyse
└── resolver.py                 # Auto-Auflösung via API

scripts/                        # NEU
└── resolve_bets.py             # Cron-Job für Raspberry Pi

data/betting/                   # NEU (wird automatisch erstellt)
└── bets.db                     # SQLite-Datenbank

web/static/
├── index.html                  # GEÄNDERT: Nur noch HTML-Markup
├── style.css                   # NEU: Ausgelagerte CSS-Regeln
└── app.js                      # NEU: Ausgelagerte JS-Logik
```

---

---

## [Unreleased] – Teambewertung & ML-Pipeline v2

Komplette Überarbeitung beider Vorhersagepfade (regelbasiert + ML-Modell).
Ziel: aktuelle Spieltagsrealität (Form, Verletzungen, Belastung, Streaks)
stärker in die Bewertung einfließen lassen.

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/models/team.py` | 4 neue Felder, 6 neue Properties |
| `src/prediction/predictor.py` | 10 statt 6 Faktoren, echte Formdaten |
| `src/ml/data_collector.py` | TrainingSample: 43 statt 33 Features |
| `src/ml/ml_predictor.py` | Feature-Vektor auf 43 Features erweitert |
| `src/ml/comparison.py` | `_normalize_odds` als statische Methode wiedereingeführt |
| `tests/test_team_evaluation_v2.py` | Neue Testsuite für Team + Predictor (NEU) |
| `tests/test_ml_system.py` | Angepasst an 43-Feature-Format |

---

### Hinzugefügt

#### Team-Model: 4 neue Felder

| Feld | Typ | Default | Beschreibung |
|------|-----|---------|--------------|
| `days_rest` | `int` | `2` | Ruhetage seit dem letzten Spiel. `0` = Back-to-Back. |
| `games_last_7_days` | `int` | `2` | Anzahl Spiele in den letzten 7 Tagen. |
| `injured_players_count` | `int` | `0` | Verletzte Spieler (Starter / Top-Rotation). |
| `injured_salary_ratio` | `float` | `0.0` | Anteil am Teamgehalt, der ausfällt (0.0–1.0). |

**Begründung:** Back-to-Back-Spiele kosten ~3–4 % Siegwahrscheinlichkeit.
Verletzungen von Schlüsselspielern verschieben den Siegwert um 5–10 %.
Der `injured_salary_ratio` dient als Proxy für die Wichtigkeit der Ausfälle.

#### Team-Model: 6 neue Properties

| Property | Rückgabe | Beschreibung |
|----------|----------|--------------|
| `last_3_win_rate` | `float` | Kürzestes Formfenster. |
| `current_streak` | `int` | +N Siegesserie, -N Niederlagenserie. |
| `is_back_to_back` | `bool` | `True` wenn `days_rest == 0`. |
| `is_well_rested` | `bool` | `True` wenn `days_rest >= 3`. |
| `fatigue_score` | `float` | 0.0 (ausgeruht) bis 1.0 (belastet). |
| `injury_impact` | `float` | 0.0 (gesund) bis 1.0 (stark geschwächt). |

#### Predictor v2: 4 neue Faktoren

| Faktor | Gewicht | Beschreibung |
|--------|---------|--------------|
| Defensiv-Stärke | 0.08 | Vergleich kassierter Punkte. |
| Ruhetage | 0.06 | Vergleich `fatigue_score`. |
| Verletzungen | 0.06 | Vergleich `injury_impact`. |
| Streak | 0.04 | Vergleich Sieges-/Niederlagenserien. |

#### ML-Pipeline: 10 neue Features in TrainingSample

| Feature | Typ | Beschreibung |
|---------|-----|--------------|
| `home_current_streak` | `int` | Aktuelle Serie des Heimteams. |
| `home_fatigue_score` | `float` | Ermüdungswert des Heimteams. |
| `home_form_rating` | `float` | Gewichtete Formkurve (L3/L5/L10). |
| `home_games_last_7_days` | `int` | Spieldichte Heimteam. |
| `away_current_streak` | `int` | Aktuelle Serie des Auswärtsteams. |
| `away_fatigue_score` | `float` | Ermüdungswert des Auswärtsteams. |
| `away_form_rating` | `float` | Gewichtete Formkurve (L3/L5/L10). |
| `away_games_last_7_days` | `int` | Spieldichte Auswärtsteam. |
| `diff_streak` | `int` | Differenz der Serien (Heim − Auswärts). |
| `diff_fatigue` | `float` | Differenz der Ermüdungswerte. |

**Begründung:** Das ML-Modell hatte bisher keinen Zugang zu Belastungs-,
Streak- und echten Formdaten. Die `form_rating` als eigenes Feature
(unabhängig von `last_5`/`last_10`) erlaubt dem Modell, die gewichtete
Kombination direkt zu nutzen. Die Differenz-Features (`diff_streak`,
`diff_fatigue`) geben dem Modell einen direkten Vergleichswert, der
erfahrungsgemäß stärker als die Einzelwerte korreliert.

Feature-Anzahl gesamt: **33 → 43**.

#### `_normalize_odds` in OddsVsMLComparison

Statische Methode wiedereingeführt, die beim Refactoring versehentlich entfernt
wurde. Die Inline-Normierung in `_compare_game()` nutzt jetzt diese Methode.

**Begründung:** Reine Funktion (zwei Floats rein, zwei raus) ist eigenständig
testbar. Behebt `AttributeError` in `test_normalize_odds_removes_vig`.

---

### Geändert

#### Predictor: Gewichte neu kalibriert (Summe = 1.0)

| Faktor | Alt (v1) | Neu (v2) |
|--------|----------|----------|
| Win-Rate | 0.25 | 0.18 |
| Punkt-Differenz | 0.20 | 0.16 |
| Heimvorteil | 0.15 | 0.12 |
| Aktuelle Form | 0.15 | 0.12 |
| Wettquoten | 0.15 | 0.10 |
| Offensiv-Stärke | 0.10 | 0.08 |
| Defensiv-Stärke | — | 0.08 |
| Ruhetage | — | 0.06 |
| Verletzungen | — | 0.06 |
| Streak | — | 0.04 |

#### Predictor: Aktuelle Form nutzt echte Formdaten

**Vorher:** `(win_rate + point_diff/20) / 2` – faktisch redundant zur Win-Rate.
**Nachher:** `team.form_rating` (30 % L3 + 40 % L5 + 30 % L10) mit Fallback.

#### Team: `form_rating` auf 3 Fenster erweitert

**Vorher:** `0.6 * L5 + 0.4 * L10`
**Nachher:** `0.3 * L3 + 0.4 * L5 + 0.3 * L10`

#### ML-Pipeline: `_build_feature_vector` erweitert

**Vorher:** 33 Features → **Nachher:** 43 Features.
Reihenfolge exakt synchron mit `TrainingSample.get_feature_columns()`.

#### Sonstige Anpassungen

- `HOME_ADVANTAGE_BONUS`: 0.05 → 0.04 (Post-COVID ~57–58 % statt 60 %).
- `NBA_AVG_POINTS`: 113.0 → 113.5 (Saison 2024-25).
- Ermüdung beeinflusst vorhergesagte Punktzahl (max. ~2.5 Punkte Abzug).

---

### Behoben

- `AttributeError: OddsVsMLComparison._normalize_odds` – Methode war beim
  Refactoring zu Inline-Code geworden, aber der Test referenzierte sie noch.
  Jetzt als `@staticmethod` wiederhergestellt und in `_compare_game` genutzt.

---

### Inkompatibilitäten / Migration

**Das alte ML-Modell ist inkompatibel und muss neu trainiert werden.**

Das gespeicherte Modell unter `data/models/nba_predictor.joblib` erwartet
33 Features. Nach diesem Update liefert `_build_feature_vector` 43 Features
→ `predict_proba()` wirft einen Fehler. Ebenso ist die alte CSV unter
`data/training/training_data.csv` inkompatibel (33 statt 43 Spalten).

Migrations-Schritte:

```bash
# 1. Alte Trainingsdaten und Modell löschen
rm data/training/training_data.csv
rm data/training/metadata.json
rm data/models/nba_predictor.joblib
rm data/models/model_metrics.json

# 2. Neue Trainingsdaten sammeln (43 Features)
python main.py train collect --seasons 2023 2024 --max-games 500

# 3. Neues Modell trainieren
python main.py train model

# 4. Tests ausführen
pytest
```

Ohne Schritt 1–3 wird `ml-predict` auf den regelbasierten Fallback
zurückgreifen (funktioniert, nutzt aber nicht das ML-Modell).

---

### Noch nicht implementiert (TODO)

- **`days_rest` befüllen:** Bereits als `AdvancedTeamStats.days_since_last_game`
  berechnet. Muss beim Erstellen des Team-Objekts übertragen werden.

- **`games_last_7_days` befüllen:** Berechnung aus Spieldaten ergänzen
  (Differenz der Spieltage in `_calculate_standings_from_games`).

- **Verletzungsdaten (`injured_players_count` / `injured_salary_ratio`):**
  Externe Datenquelle erforderlich (ESPN Injury Reports, Rotowire, o. Ä.).
  Bis dahin bleiben die Werte auf 0 – der Verletzungsfaktor im Predictor
  hat dann keinen Einfluss.

---

### Tests

| Datei | Tests | Beschreibung |
|-------|-------|--------------|
| `tests/test_team_evaluation_v2.py` | 22 | Team-Properties + Predictor-Faktoren (NEU) |
| `tests/test_ml_system.py` | ~15 | Angepasst an 43-Feature-Format |

Neue Tests prüfen unter anderem:
- `test_feature_count_is_43` – Feature-Anzahl korrekt
- `test_new_v2_features_present` – alle 10 neuen Features vorhanden
- `test_build_feature_vector_has_correct_length` – Vektor-Länge == 43
