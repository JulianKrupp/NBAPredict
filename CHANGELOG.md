# Changelog

Alle relevanten Änderungen am NBA Tracker werden in dieser Datei dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

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

**69.8% Accuracy** liegt im erwarteten Bereich für NBA-Vorhersagemodelle
(Buchmacher: ~67%, beste öffentliche Modelle: ~68–72%). Das Modell schlägt
die Buchmacher-Baseline um ~2.8%, was theoretisch für profitable
Value-Bets ausreicht.

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
