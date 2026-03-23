# Changelog

Alle relevanten Änderungen am NBA Tracker werden in dieser Datei dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

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
