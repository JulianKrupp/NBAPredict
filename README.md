# 🏀 NBA Predict

NBA-Wettempfehlungssystem mit ML-Vorhersage, regelbasiertem Modell, Quoten-Vergleich und virtuellem Wett-Tracker. Läuft als Web-App (Docker) oder CLI.

---

## APIs

| # | API | Zweck | Key |
|---|-----|-------|-----|
| 1 | [BallDontLie](https://www.balldontlie.io) | Spielergebnisse, Scores, Trainingsdaten | ✅ Free Tier |
| 2 | [The Odds API](https://the-odds-api.com) | Buchmacher-Quoten (500 Req/Monat) | ✅ Free Tier |
| 3 | [nba_api](https://github.com/swar/nba_api) | Advanced Stats von stats.nba.com | ❌ Kein Key |

> **Hinweis:** `nba_api` ist ein inoffizielles Community-Package das stats.nba.com abfragt. Kein Account nötig, aber künstliche Delays vermeiden Rate-Limiting.

---

## Schnellstart

### Docker (empfohlen)

```bash
cp .env.example .env      # API-Keys eintragen
docker compose up -d
# → http://localhost:5000
```

### Lokal

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate # Linux/macOS
pip install -r requirements.txt
cp .env.example .env
python web/server.py
```

---

## Konfiguration (.env)

```env
BALLDONTLIE_API_KEY=...   # Pflicht  → balldontlie.io
ODDS_API_KEY=...          # Optional → the-odds-api.com (für Quoten-Vergleich)
```

---

## Web-Interface

| Tab | Funktion |
|-----|----------|
| **Stand** | Tabelle berechnet aus Spielergebnissen (kein /standings-Endpunkt im Free Tier) |
| **Spiele** | Scores nach Datum, Auto-Refresh 1–7 Uhr MEZ |
| **KI** | Vorhersage: ML-Modell + Regelmodell + Wettquoten im Vergleich |
| **Quoten** | KI vs. Buchmacher – Edge, EV, Wettempfehlung mit Guardrails |
| **Wetten** | Virtueller Wett-Tracker mit Analytik (ROI, Win-Rate, Rating-Aufschlüsselung) |

---

## CLI

```bash
# Spieldaten
python main.py live
python main.py scores --date 2025-03-01
python main.py standings
python main.py team lakers

# Vorhersage
python main.py predict lakers celtics          # Regelbasiert
python main.py ml-predict lakers celtics       # ML + Regelmodell + Quoten

# Quoten-Vergleich
python main.py compare
python main.py compare --home lakers --away celtics

# Training
python main.py train collect --seasons 2022 2023 2024 --max-games 5000
python main.py train model
python main.py train all --seasons 2023 2024
python main.py train metrics

# Wett-Verwaltung
python main.py bets list [--status open|won|lost|all]
python main.py bets stats
python main.py bets resolve
python main.py bets reset
python main.py bets close-period [--label TEXT] [--notes TEXT]
```

---

## ML-System

### Features (45 gesamt)

| Kategorie | Features |
|-----------|----------|
| Heimteam Basis | Win-Rate, Punkt-Diff, Ø Pts scored/allowed, Heim/Auswärts-WR |
| Heimteam Advanced | Off-Rating, Def-Rating, Net-Rating, Pace, True Shooting % |
| Heimteam Form | letzte 5/10 Spiele, Streak, Fatigue-Score, Form-Rating, Ruhetage |
| Auswärtsteam | identisch (18 Features) |
| Differenz-Features | Δ Win-Rate, Δ Punkt-Diff, Δ Net-Rating, Δ Form, Δ Streak, Δ Fatigue |
| Elo | home_elo, away_elo, diff_elo |

### Modellauswahl

Vier Kandidaten werden per 5-Fold Stratified CV auf `neg_brier_score` verglichen:

| Modell | Aufbau | Ergebnis |
|--------|--------|---------|
| **Logistic Regression** | StandardScaler + LogReg, C ∈ {0.1, 1, 10} | ✅ Gewinner – beste Kalibrierung |
| Gradient Boosting | 150–300 Bäume, lr 0.03–0.08, max_depth 3–5 | ~gleiche Accuracy, schlechter kalibriert |
| XGBoost | 200–400 Bäume, L1/L2-Regularisierung | ~gleiche Accuracy, overconfident |
| Random Forest | 200–400 Bäume, max_depth 6–10, balanced | Schlechteste Kalibrierung |

> **Warum Logistic Regression?** Scoring-Metrik ist `neg_brier_score` — misst nicht nur ob die Vorhersage stimmt, sondern ob die *Wahrscheinlichkeit* stimmt. Kalibrierte Wahrscheinlichkeiten sind entscheidend für die EV-Berechnung der Wettempfehlungen. LogReg ist inherent gut kalibriert, XGBoost/RF sind es nicht.

### Aktuelle Metriken (v1.2.0, trainiert 2026-04-02)

| Metrik | Wert |
|--------|------|
| Accuracy (Test) | 64.95% |
| ROC-AUC | 0.6989 |
| Brier Score | 0.2183 |
| CV-Accuracy | 66.0% ± 1.7% |
| Trainingssamples | 4504 (Saisons 2021–2025) |

> **Einordnung:** Heimsieg-Baseline ~55%, reines Elo-Modell ~60%, Buchmacher ~67%.

### Regelbasiertes Modell (`src/prediction/predictor.py`)

Gewichteter Score aus 10 Faktoren (kein Training, immer verfügbar):

```
Win-Rate 18% · Punkt-Differenz 16% · Heimvorteil 12% · Form 12%
Wettquoten 10% · Offense 8% · Defense 8% · Ruhetage 6%
Verletzungen 6% · Streak 4%
```

Dient als Baseline, Fallback und Kreuzcheck gegenüber dem ML-Modell.

### Wettempfehlung & Guardrails

```
Edge = KI-Prob − Buchmacher-Prob

strong  → Edge > 15%
good    → Edge > 8%
slight  → Edge > 3%
none    → darunter ODER Guardrail aktiv
```

**Guardrails:**
```
Quote > 6.0  UND  KI-Prob < 70%   →  "none"  (KI zu unsicher bei Außenseiter)
Quote > 3.5  UND  Methoden uneinig →  "none"  (Markt und KI widersprechen sich)
```

---

## Tests

```bash
pytest                              # 197 Tests + Coverage
pytest tests/test_comparison.py -v  # Guardrail-Tests
pytest tests/test_elo.py -v         # Elo + Data-Leakage-Tests
ruff check src/                     # Linting
```

| Datei | Tests | Schwerpunkt |
|-------|-------|-------------|
| `test_elo.py` | 15 | Nullsumme, Heimvorteil, MoV, Data Leakage |
| `test_tracker.py` | 29 | place/resolve/stats, In-Memory-SQLite |
| `test_comparison.py` | 23 | Guardrails, Edge-Stufen, EV-Formel, Vig |
| `test_predictor.py` | ~15 | FACTOR_WEIGHTS, normalize, Fatigue |

---

## Projektstruktur

```
├── main.py                         # CLI-Einstiegspunkt
├── pyproject.toml                  # Projekt-Konfiguration, Ruff, pytest
├── Dockerfile                      # Multi-Stage-Build
├── docker-compose.yml
├── .env.example
│
├── src/
│   ├── api/
│   │   ├── base_client.py          # HTTP-Basis (Retry, Cache, Circuit Breaker)
│   │   ├── nba_api_client.py       # BallDontLie API
│   │   ├── nba_stats_client.py     # nba_api → stats.nba.com
│   │   └── odds_api_client.py      # The Odds API
│   │
│   ├── betting/
│   │   ├── tracker.py              # SQLite Wett-Tracker
│   │   └── resolver.py             # Auto-Auflösung offener Wetten
│   │
│   ├── ml/
│   │   ├── data_collector.py       # Trainingsdaten-Pipeline (45 Features)
│   │   ├── elo.py                  # Elo-Rating-Berechnung
│   │   ├── model_trainer.py        # LogReg / RF / GB / XGBoost + Grid Search
│   │   ├── ml_predictor.py         # ML-Vorhersage
│   │   └── comparison.py           # ML + Regelmodell vs. Wettquoten
│   │
│   ├── prediction/
│   │   └── predictor.py            # Regelbasiertes Modell (10 Faktoren)
│   │
│   └── utils/
│       ├── config.py
│       ├── logger.py
│       └── display.py
│
├── web/
│   ├── server.py                   # Flask REST-API
│   └── static/                     # index.html, app.js, style.css
│
├── tests/
└── data/
    ├── training/                   # CSV + Metadaten
    ├── models/                     # model.joblib + model_metrics.json
    └── betting/                    # bets.db (SQLite)
```

---

## Commit-Konventionen

`feat:` · `fix:` · `refactor:` · `test:` · `docs:` · `chore:`
