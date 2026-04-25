# 🏀 NBA Predict

NBA-Vorhersagesystem mit ML-Pipeline, Quoten-Vergleich und EV-Analyse. Läuft als Web-App (Docker) oder CLI.

---

## APIs

| # | API | Zweck | Key |
|---|-----|-------|-----|
| 1 | [BallDontLie](https://www.balldontlie.io) | Spielergebnisse, Scores, Trainingsdaten | ✅ Free Tier |
| 2 | [The Odds API](https://the-odds-api.com) | Buchmacher-Quoten (500 Req/Monat) | ✅ Free Tier |
| 3 | [nba_api](https://github.com/swar/nba_api) | Advanced Stats von stats.nba.com (nur Vorhersage) | ❌ Kein Key |

> **Hinweis:** `nba_api` ist ein inoffizielles Community-Package das stats.nba.com abfragt. Wird nur bei der Live-Vorhersage genutzt, nicht mehr beim Training.

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
| **KI-Vorhersage** | ML-Modell + Wettquoten im Vergleich, Pipeline-Status, manuelles Retraining |
| **KI vs Quoten** | Wahrscheinlichkeitsvergleich, Vig-bereinigt, EV- und Edge-Analyse |

---

## CLI

```bash
# Spieldaten
python main.py live
python main.py scores --date 2025-03-01
python main.py standings
python main.py team lakers

# Vorhersage
python main.py ml-predict lakers celtics

# Quoten-Vergleich
python main.py compare
python main.py compare --home lakers --away celtics

# Training
python main.py train collect                          # Daten sammeln (Standard: letzte 4 Saisons)
python main.py train collect --seasons 2022 2023 2024 --max-games 5000
python main.py train model                            # Nur Modell trainieren
python main.py train all                              # Alles in einem Schritt
python main.py train metrics                          # Gespeicherte Metriken anzeigen
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

> Advanced Stats (Off-/Def-Rating, Pace, TS%) werden im Training **ausschließlich aus kumulativen Spielergebnissen geschätzt** – kein externer API-Abruf, kein Data Leakage.

### Modell-Pipeline

Jeden Monat werden alle vier Modelle auf denselben Daten trainiert. Das Modell mit dem höchsten **ROC-AUC** wird automatisch als aktives Modell gesetzt.

| Modell | Warum dabei |
|--------|-------------|
| **Logistic Regression** | Inherent gut kalibriert, liefert zuverlässige Wahrscheinlichkeiten |
| **Random Forest** | Robustes Ensemble, fängt nicht-lineare Zusammenhänge |
| **XGBoost** | Gradient Boosting, stark bei tabellarischen Daten |
| **MLP** | Neuronales Netz, lernt komplexe Feature-Interaktionen |

> **Warum ROC-AUC als Auswahlkriterium?** ROC-AUC misst, wie gut das Modell zwischen Sieg und Niederlage unterscheiden kann – unabhängig vom Schwellenwert. Robust bei leicht unbalancierten Klassen (~55% Heimsiege).

### Trainingsdaten

- **Quelle:** BallDontLie API (abgeschlossene Spiele)
- **Umfang:** ~5000 Spiele aus den letzten 4 NBA-Saisons (dynamisch berechnet)
- **Saisons:** werden automatisch ermittelt – April 2026 → [2022, 2023, 2024, 2025]
- **Kein Leakage:** Statistiken werden für jedes Spiel nur aus vorherigen Spielen berechnet

### Aktuelle Metriken

Nach dem letzten Training einsehbar über:
```bash
python main.py train metrics
# oder im Web unter KI-Vorhersage → Modell-Übersicht
```

> **Einordnung:** Heimsieg-Baseline ~55%, reines Elo-Modell ~60%, Buchmacher ~67%. Realistische Erwartung für ein faires Modell: 64–68%.

---

## Tests

```bash
pytest                              # Alle Tests + Coverage
pytest tests/test_ml_system.py -v  # ML-Pipeline-Tests
pytest tests/test_elo.py -v         # Elo + Data-Leakage-Tests
ruff check src/                     # Linting
```

| Datei | Schwerpunkt |
|-------|-------------|
| `test_ml_system.py` | ML-Pipeline, CumulativeTeamTracker, compute_advanced_stats |
| `test_elo.py` | Elo-Berechnung, Nullsumme, Heimvorteil |
| `test_comparison.py` | KI vs. Quoten, EV-Formel, Edge-Stufen |
| `test_api_clients.py` | API-Client-Logik |
| `test_game.py` / `test_team.py` | Datenmodelle |

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
│   │   ├── nba_stats_client.py     # nba_api → stats.nba.com (nur Vorhersage)
│   │   └── odds_api_client.py      # The Odds API
│   │
│   ├── ml/
│   │   ├── data_collector.py       # Trainingsdaten (45 Features, kumulativ, leak-frei)
│   │   ├── elo.py                  # Elo-Rating-Berechnung
│   │   ├── pipeline.py             # ML-Pipeline (Status, monatliches Retraining)
│   │   ├── model_trainer.py        # 4 Modelle trainieren, bestes auswählen
│   │   ├── ml_predictor.py         # ML-Vorhersage (lädt aktives Modell dynamisch)
│   │   └── comparison.py           # ML vs. Wettquoten, EV-Berechnung
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
    ├── training/                   # CSV + Metadaten (lokal generiert, nicht in Git)
    └── models/                     # *.joblib + Metriken-JSON + Pipeline-Status
```

---

## Commit-Konventionen

`feat:` · `fix:` · `refactor:` · `test:` · `docs:` · `chore:`
