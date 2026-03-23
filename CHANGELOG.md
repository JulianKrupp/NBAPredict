# Changelog

Alle relevanten Änderungen am NBA Tracker werden in dieser Datei dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

---

## [Unreleased] – Teambewertung v2

Komplette Überarbeitung des Vorhersagemodells. Ziel: aktuelle Spieltagsrealität
(Form, Verletzungen, Belastung) stärker in die Bewertung einfließen lassen,
statt sich ausschließlich auf Saison-Aggregate zu stützen.

### Geänderte Dateien

- `src/models/team.py` – Erweitertes Team-Datenmodell
- `src/prediction/predictor.py` – Predictor v2 (10 statt 6 Faktoren)
- `tests/test_team_evaluation_v2.py` – Neue Testsuite (NEU)

---

### Hinzugefügt

#### Team-Model: 4 neue Felder

| Feld | Typ | Default | Beschreibung |
|------|-----|---------|--------------|
| `days_rest` | `int` | `2` | Ruhetage seit dem letzten Spiel. `0` = Back-to-Back. |
| `games_last_7_days` | `int` | `2` | Anzahl Spiele in den letzten 7 Tagen (Belastungsdichte). |
| `injured_players_count` | `int` | `0` | Verletzte Spieler (Starter / Top-Rotation). |
| `injured_salary_ratio` | `float` | `0.0` | Anteil am Teamgehalt, der ausfällt (0.0–1.0). |

**Begründung:** Bisher standen dem Predictor keinerlei Informationen zu
Spielergesundheit und Belastungssteuerung zur Verfügung. Back-to-Back-Spiele
kosten in der NBA statistisch nachweisbar ~3–4 % Siegwahrscheinlichkeit.
Verletzungen von Schlüsselspielern (z.B. Star-Ausfall) können den erwarteten
Siegwert um 5–10 % verschieben. Der `injured_salary_ratio` dient dabei als Proxy
für die *Wichtigkeit* der Ausfälle – ein verletzter Max-Vertragsspieler wiegt
schwerer als drei ausfallende Bankdrücker.

#### Team-Model: 6 neue Properties

| Property | Rückgabe | Beschreibung |
|----------|----------|--------------|
| `last_3_win_rate` | `float` | Kürzestes Formfenster – fängt ganz aktuelle Dynamik ein. |
| `current_streak` | `int` | +N = Siegesserie, -N = Niederlagenserie, 0 = keine Daten. |
| `is_back_to_back` | `bool` | `True` wenn `days_rest == 0`. |
| `is_well_rested` | `bool` | `True` wenn `days_rest >= 3`. |
| `fatigue_score` | `float` | Ermüdungswert 0.0 (ausgeruht) bis 1.0 (stark belastet). Kombiniert Ruhetage (65 %) und Spieldichte (35 %). |
| `injury_impact` | `float` | Verletzungseinfluss 0.0 (gesund) bis 1.0. Kombiniert Spieleranzahl (35 %) und Gehaltsanteil (65 %). |

**Begründung:** Die bisherige `form_rating` hatte nur zwei Fenster (L5/L10).
`last_3_win_rate` schließt eine Lücke – drei Spiele sind das kürzeste
sinnvolle Fenster und fangen z.B. die Rückkehr eines Stars oder einen
plötzlichen Einbruch schneller ein. `current_streak` ist ein psychologischer
Faktor (Momentum), der in Sportanalysen konsistent als kleiner, aber realer
Effekt gemessen wird. Die Fatigue- und Injury-Properties kapseln die
Berechnungslogik sauber im Model statt im Predictor.

#### Predictor v2: 4 neue Faktoren

| Faktor | Gewicht | Beschreibung |
|--------|---------|--------------|
| Defensiv-Stärke | 0.08 | Vergleich der kassierten Punkte beider Teams. Invertiert: weniger kassierte Punkte = besser. |
| Ruhetage | 0.06 | Vergleich der `fatigue_score`-Werte. Ausgeruhteres Team bekommt Vorteil. |
| Verletzungen | 0.06 | Vergleich der `injury_impact`-Werte. Gesünderes Team bekommt Vorteil. |
| Streak | 0.04 | Vergleich der Sieges-/Niederlagenserien. Auf ±5 Spiele normiert. |

**Begründung je Faktor:**

- **Defensiv-Stärke:** War bisher kein eigenständiger Faktor, obwohl Defense in
  der NBA (besonders in den Playoffs) überproportional wichtig ist und über die
  Saison stabiler als Offense bleibt. Die Offensiv-Stärke allein bildet nur die
  halbe Wahrheit ab.

- **Ruhetage:** NBA-Teams mit Back-to-Back-Spielen verlieren nachweislich
  häufiger. Der Effekt verstärkt sich bei hoher Spieldichte (4+ Spiele in 7
  Tagen, z.B. Ende der Regular Season). Das Gewicht von 0.06 reflektiert, dass
  der Effekt real, aber nicht dominierend ist.

- **Verletzungen:** Selbst ein einzelner All-Star-Ausfall kann die Teamdynamik
  fundamental verändern. Der bisherige Predictor war komplett blind dafür. Das
  moderate Gewicht von 0.06 ist bewusst gewählt, da Verletzungsdaten oft
  unvollständig sind und der Einfluss schwer exakt zu quantifizieren ist.

- **Streak:** Rein statistisch ist der Momentum-Effekt in der NBA schwach
  (heiße/kalte Serien erklären sich größtenteils durch Spielplanstärke). Das
  niedrige Gewicht von 0.04 respektiert das, nimmt den Faktor aber nicht völlig
  heraus, da die psychologische Komponente (Selbstvertrauen, Teamchemie) nicht
  null ist.

---

### Geändert

#### Predictor: Gewichte neu kalibriert

Alle Gewichte summieren sich weiterhin auf 1.0.

| Faktor | Alt (v1) | Neu (v2) | Änderung |
|--------|----------|----------|----------|
| Win-Rate | 0.25 | 0.18 | ↓ 0.07 |
| Punkt-Differenz | 0.20 | 0.16 | ↓ 0.04 |
| Heimvorteil | 0.15 | 0.12 | ↓ 0.03 |
| Aktuelle Form | 0.15 | 0.12 | ↓ 0.03 |
| Wettquoten | 0.15 | 0.10 | ↓ 0.05 |
| Offensiv-Stärke | 0.10 | 0.08 | ↓ 0.02 |
| Defensiv-Stärke | — | 0.08 | NEU |
| Ruhetage | — | 0.06 | NEU |
| Verletzungen | — | 0.06 | NEU |
| Streak | — | 0.04 | NEU |

**Begründung:** Die Gewichtsreduktion der bestehenden Faktoren ist proportional.
Win-Rate und Punkt-Differenz bleiben die stärksten Einzelfaktoren, da sie die
Gesamtstärke über die komplette Saison widerspiegeln. Die Wettquoten wurden am
stärksten reduziert (0.15 → 0.10), da sie bereits viele Signale (inkl.
Verletzungen und Formkurve) aggregieren – ein zu hohes Gewicht würde die eigene
Analyse verwässern.

#### Predictor: `_estimate_form()` nutzt echte Formdaten

**Vorher (v1):**
```python
home_form = (home.win_rate + max(0.0, home.point_differential / 20.0)) / 2.0
```
Die "Aktuelle Form" war eigentlich nur eine Umrechnung der Saisondurchschnitte –
sie reagierte nicht auf aktuelle Spielergebnisse.

**Nachher (v2):**
```python
if team.has_recent_form_data:
    return team.form_rating  # 30 % L3 + 40 % L5 + 30 % L10
```
Jetzt wird `team.form_rating` verwendet, das drei Zeitfenster gewichtet. Der alte
Fallback bleibt als Rückfalloption, wenn noch keine Spielergebnisse vorliegen.

**Begründung:** Der größte Einzelfehler in v1. Der Faktor "Aktuelle Form" hieß
so, tat aber nichts Aktuelles – er war redundant zu Win-Rate und Punkt-Differenz.
Die neue Implementierung nutzt die bereits im Team-Model vorhandenen
`recent_game_results`, die in `_calculate_standings_from_games` befüllt werden.

#### Team-Model: `form_rating` auf 3 Fenster erweitert

**Vorher:** `0.6 * L5 + 0.4 * L10`
**Nachher:** `0.3 * L3 + 0.4 * L5 + 0.3 * L10`

**Begründung:** Drei Fenster geben ein ausgewogeneres Bild:
- L3 fängt ganz aktuelle Dynamik ein (Spieler-Rückkehr, Verletzung, Coaching-Wechsel).
- L5 bleibt der Kern-Formindikator.
- L10 glättet Ausreißer und verhindert Überreaktion auf 1–2 schlechte Spiele.

#### Predictor: `HOME_ADVANTAGE_BONUS` leicht gesenkt

**Vorher:** 0.05 → **Nachher:** 0.04

**Begründung:** Post-COVID-Daten zeigen, dass der NBA-Heimvorteil von historisch
~60 % auf ~57–58 % gesunken ist. Die kleine Anpassung reflektiert diesen Trend.

#### Predictor: `NBA_AVG_POINTS` aktualisiert

**Vorher:** 113.0 → **Nachher:** 113.5

**Begründung:** Anpassung an den aktuellen Saisondurchschnitt 2024-25.

#### Predictor: Ermüdung beeinflusst Predicted Score

In `_estimate_scores()` wird jetzt die `fatigue_score` beider Teams als
Punkteabzug berücksichtigt (max. ~2.5 Punkte). Ein B2B-Team bekommt tendenziell
weniger Punkte vorhergesagt.

---

### Noch nicht implementiert (TODO)

Die neuen Team-Felder müssen noch befüllt werden:

- **`days_rest`:** Bereits als `AdvancedTeamStats.days_since_last_game` berechnet.
  Muss beim Erstellen des Team-Objekts übertragen werden (in `NBAApiClient` oder
  im Caller).

- **`games_last_7_days`:** Berechnung aus den `recent_game_results` und
  Spieldaten ergänzen (z.B. in `_calculate_standings_from_games`).

- **`injured_players_count` / `injured_salary_ratio`:** Externe Datenquelle
  erforderlich. Optionen:
  - ESPN Injury Reports (Scraping, kein offizielles API)
  - Rotowire / CBS Sports Injury API
  - `nba_api` Package – `commonallplayers` Endpoint (begrenzt)

  Bis dahin bleiben die Werte auf 0 (= Team gilt als vollständig gesund), und der
  Verletzungsfaktor hat keinen Einfluss auf die Vorhersage.

---

### Tests

Neue Testsuite `tests/test_team_evaluation_v2.py` mit 22 Tests in 6 Klassen:

| Klasse | Tests | Prüft |
|--------|-------|-------|
| `TestTeamStreak` | 5 | `current_streak` bei Siege, Niederlagen, leer, einzeln |
| `TestTeamFormRating` | 3 | Drei-Fenster-Berechnung, Fallback, L3-Berechnung |
| `TestTeamFatigue` | 4 | B2B-Erkennung, Rested-Erkennung, Dichteeinfluss, Wertebereich |
| `TestTeamInjury` | 4 | Gesundes Team, Schweregradvergleich, Star vs. Bench, Cap |
| `TestPredictorFactors` | 9 | Gewichte-Summe, alle Faktoren vorhanden, Wertebereiche, Richtungstests für jeden neuen Faktor |
| `TestPredictorEdgeCases` | 3 | Identische Teams, Extremmismatch, keine Spiele |
