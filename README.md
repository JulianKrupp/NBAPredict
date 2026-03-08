# 🏀 NBA Tracker mit KI-Vorhersagesystem

Ein modulares Python-Programm zum Abrufen von NBA-Spielergebnissen, Teamstatistiken, KI-gestützten Spielvorhersagen und einem direkten Vergleich zwischen ML-Modell und Buchmacher-Wettquoten.

---

## APIs

| # | API | Zweck | Key erforderlich? |
|---|-----|-------|-------------------|
| 1 | [BallDontLie](https://www.balldontlie.io) | Spielergebnisse, Standings, Trainingsdaten | ✅ Kostenlos registrieren |
| 2 | [The Odds API](https://the-odds-api.com) | Wettquoten, KI-vs-Quoten-Vergleich | ✅ 500/Monat gratis |
| 3 | [nba_api](https://github.com/swar/nba_api) | Advanced Stats direkt von stats.nba.com | ❌ Kein Key nötig! |

**API 3 (`nba_api`)** ist ein Open-Source Python-Package das direkt stats.nba.com abfragt – komplett kostenlos, kein Account, kein Key. Einfach `pip install nba_api`.

---

## Projektstruktur

```
nba_tracker/
├── main.py
├── requirements.txt
├── pytest.ini
├── .env.example
│
├── src/
│   ├── api/
│   │   ├── base_client.py          # HTTP-Basis (Retry, Cache, Fehlerbehandlung)
│   │   ├── nba_api_client.py       # API 1: BallDontLie
│   │   ├── nba_stats_client.py     # API 3: nba_api → stats.nba.com (kein Key!)
│   │   └── odds_api_client.py      # API 2: The Odds API
│   │
│   ├── models/
│   │   ├── game.py
│   │   └── team.py
│   │
│   ├── ml/
│   │   ├── data_collector.py       # Trainingsdaten-Pipeline
│   │   ├── model_trainer.py        # RF / GB / LogReg, Cross-Validation
│   │   ├── ml_predictor.py         # KI-Vorhersage + Methodenvergleich
│   │   └── comparison.py           # KI vs. Wettquoten
│   │
│   ├── prediction/
│   │   └── predictor.py            # Regelbasiertes Modell
│   │
│   └── utils/
│       ├── config.py
│       ├── display.py
│       ├── ml_display.py
│       └── logger.py
│
├── tests/
│   ├── conftest.py
│   ├── test_game.py
│   ├── test_team.py
│   ├── test_predictor.py
│   ├── test_api_clients.py
│   └── test_ml_system.py
│
└── data/
    ├── training/                   # CSV + Metadaten
    └── models/                     # Gespeichertes Modell + Metriken
```

---

## Installation

```bash
git clone https://github.com/dein-user/nba-tracker.git
cd nba-tracker
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows
pip install -r requirements.txt
cp .env.example .env           # Nur API 1 + 2 Keys eintragen
```

---

## Konfiguration (.env)

```env
BALLDONTLIE_API_KEY=...   # Pflicht  → balldontlie.io
ODDS_API_KEY=...          # Optional → the-odds-api.com (für Wettquoten-Vergleich)
# nba_api (stats.nba.com) braucht keinen Key!
```

---

## Verwendung

```bash
# Klassische Befehle
python main.py live
python main.py scores --date 2025-03-01
python main.py standings
python main.py team lakers

# Regelbasierte Vorhersage
python main.py predict lakers celtics

# ── KI-System ────────────────────────────────────────────────────────────────
# Trainingsdaten sammeln (BallDontLie + nba_api)
python main.py train collect --seasons 2022 2023 2024 --max-games 500

# Modell trainieren (Random Forest / Gradient Boosting / LogReg)
python main.py train model

# Oder beides auf einmal:
python main.py train all --seasons 2023 2024

# Modell-Metriken anzeigen
python main.py train metrics

# KI-Vorhersage (ML-Modell + Regelmodell + Wettquoten im Vergleich)
python main.py ml-predict lakers celtics

# ── Vergleich KI vs. Wettquoten ───────────────────────────────────────────────
python main.py compare                          # alle Spiele
python main.py compare --home lakers --away celtics  # spezifisches Spiel
```

---

## ML-System: Features (33 gesamt)

| Kategorie | Features |
|-----------|----------|
| Heimteam Basis | Win-Rate, Punkt-Diff, Ø Punkte scored/allowed, Heim/Auswärts-WR |
| Heimteam Advanced (nba_api) | Off-Rating, Def-Rating, Net-Rating, Pace, True Shooting %, Form letzte 5/10 |
| Auswärtsteam | identisch wie Heimteam |
| Differenz-Features | Δ Win-Rate, Δ Punkt-Diff, Δ Net-Rating, Δ Form letzte 5 |
| Wettquoten | implizite Heimsieg-Wahrscheinlichkeit (Vig-bereinigt) |

### Modellauswahl per Cross-Validation
Drei Kandidaten werden per 5-Fold Stratified CV verglichen:
- **Random Forest** (200 Bäume, max_depth=8)
- **Gradient Boosting** (150 Bäume, lr=0.05)
- **Logistische Regression** (mit StandardScaler)

### Ausgabe: KI vs. Wettquoten
```
══════════════════════════════════════════════════════════════════════════════
  🤖 KI vs. 📊 Wettquoten – Vergleich der Siegwahrscheinlichkeiten
══════════════════════════════════════════════════════════════════════════════
  Spiel                           KI Heim   KI Ausw  Odds Heim Odds Ausw  Δ
  ─────────────────────────────────────────────────────────────────────────
  Lakers vs Celtics                 58.3%    41.7%     55.0%    45.0%   3.3%  ✅ ≈ Einig
```

---

## Tests

```bash
pytest                        # Alle Tests mit Coverage-Report
pytest tests/test_ml_system.py -v
pytest --no-cov               # Ohne Coverage
```

---

## Git-Workflow

```bash
git init
git add .
git commit -m "Initial commit: NBA Tracker mit KI"

# Feature-Branch
git checkout -b feature/player-stats
git commit -m "feat: Spieler-Statistiken hinzugefügt"
git checkout main && git merge feature/player-stats
```

### Commit-Konventionen
`feat:` | `fix:` | `test:` | `refactor:` | `docs:` | `chore:`
