# NBA Predict

**Ein datengetriebenes Prognose- und Analysetool für die National Basketball Association (NBA).**

Dieses Projekt wurde im Rahmen des Moduls *Fortgeschrittene Programmierung* im 2. Semester Wirtschaftsinformatik (Data Science) entwickelt. Es verbindet Datenbeschaffung über externe Schnittstellen (APIs), Feature Engineering, den Vergleich mehrerer Machine-Learning-Modelle und eine modulare, getestete Codebasis.

---

## 1. ZIEL & ERGEBNISSE

### Ziel
**NBA Predict** sagt auf Basis historischer NBA-Spieldaten die Siegwahrscheinlichkeit des Heimteams voraus. Das Projekt deckt den kompletten Ablauf ab: Daten über APIs abrufen, Merkmale berechnen, mehrere Modelle trainieren und vergleichen, Ergebnisse in CLI und Web-Dashboard anzeigen. Als externer Vergleichsmaßstab lassen sich die Modellwahrscheinlichkeiten zusätzlich den aus Buchmacherquoten abgeleiteten Wahrscheinlichkeiten gegenüberstellen.

### Ergebnisse (Training vom 03.06.2026)
Datengrundlage: 4.377 abgeschlossene Spiele der Saisons 2022–2025, 45 Merkmale, Aufteilung 3.501 Trainings- / 876 Testspiele. Zum Vergleich: Wer immer auf das Heimteam tippt, liegt in diesem Datensatz bei 55,1 %.

| Modell | Accuracy (Test) | ROC-AUC | Brier Score | CV-Accuracy |
| :--- | ---: | ---: | ---: | ---: |
| **Logistic Regression** (aktiv) | **66,7 %** | **0,722** | **0,212** | 65,5 % |
| MLP | 64,2 % | 0,715 | 0,214 | 63,9 % |
| XGBoost | 64,0 % | 0,694 | 0,222 | 64,1 % |
| Random Forest | 63,0 % | 0,700 | 0,218 | 65,4 % |

Die wichtigsten Merkmale des aktiven Modells sind die Siegquoten beider Teams, die Elo-Differenz und die Ermüdungswerte. Die Zahlen lassen sich mit `python main.py train all` und `python main.py train metrics` reproduzieren; sie verändern sich mit jedem neuen Trainingslauf leicht.

---

## 2. FEATURES

| Kategorie | Kernfunktionen |
| :--- | :--- |
| **Datenbeschaffung & ETL** | Anbindung der *BallDontLie API*, *NBA Stats API* und *The Odds API* zum Abrufen historischer Spiele, Advanced Stats und aktueller Quoten. |
| **Feature Engineering** | Berechnung komplexer Features zur Laufzeit (z.B. kumulatives Elo-Rating, Fatigue-Metriken, Offensive/Defensive Ratings) zur Vermeidung von Data Leakage. |
| **ML-Prediction-Logik** | Training und Evaluierung mehrerer Algorithmen (Logistic Regression, XGBoost, Random Forest, MLP). Dynamische Selektion des kalibriertesten Modells (Brier Score / ROC-AUC) zur Vorhersage. |
| **CLI & Web-Dashboard** | Hybrides Bedienkonzept: Eine leichtgewichtige Kommandozeile (CLI) für Entwickler und ein interaktives Flask-Web-Dashboard für Endanwender. |

---

## 3. PROJEKTSTRUKTUR

Das System folgt strikt den Prinzipien des **Clean Code** und des **Single Responsibility Principles (SRP)**. Im Zuge von Refactorings wurden veraltete, ungenutzte Module (`src/betting`, `src/prediction-rules`) restlos entfernt. Die verbleibende Architektur trennt Infrastruktur, Geschäftslogik und Datenstrukturen sauber voneinander:

```text
NBAPredict/
│
├── main.py                 # Zentraler CLI-Einstiegspunkt
├── Dockerfile              # Multi-Stage-Build für ein schlankes Image
├── docker-compose.yml      # Orchestrierung des Web-Containers
├── requirements.txt        # Abhängigkeitsmanagement (Laufzeit)
├── pyproject.toml          # Dev-Abhängigkeiten, Ruff-Linting & Pytest-Konfiguration
├── .env.example            # Vorlage für Umgebungsvariablen
│
├── src/                    # Geschäftslogik & Core-Module
│   ├── api/                # API-Clients für externe Daten (Adapter-Pattern)
│   ├── ml/                 # Data Collection, Pipeline, Training & Inferenz
│   ├── models/             # Domänenmodelle (Game, Team) als Dataclasses
│   └── utils/              # Hilfsmodule (Config, Logging, Formatting)
│
├── data/                   # Persistenz (wird automatisch befüllt)
│   ├── models/             # Trainierte Modelle (.joblib) & Metriken (.json)
│   └── training/           # Gesammelte Trainingsdaten & Metadaten
│
├── tests/                  # Testumgebung (Unittests, Mocking, Coverage)
├── logs/                   # Laufzeit-Logs (nba_predict.log)
└── web/                    # Präsentationsschicht (Flask REST-API & Frontend)
```

---

## 4. KONFIGURATION & UMGEBUNGSVARIABLEN

Alle API-Keys und Laufzeitparameter werden über eine `.env`-Datei gesetzt. Die Vorlage `.env.example` enthält alle verfügbaren Variablen:

```dotenv
# ─── Pflichtfelder (API-Keys) ─────────────────────────────────────────────────
BALLDONTLIE_API_KEY=    # https://www.balldontlie.io – kostenloses Tier verfügbar
ODDS_API_KEY=           # https://the-odds-api.com – 500 kostenlose Anfragen/Monat

# Hinweis: stats.nba.com (via nba_api) benötigt keinen API-Key.

# ─── Optionale Request-Konfiguration ─────────────────────────────────────────
REQUEST_TIMEOUT=10      # HTTP-Timeout in Sekunden
MAX_RETRIES=3           # Maximale Retry-Versuche bei Netzwerkfehlern
RETRY_DELAY=1.0         # Wartezeit zwischen Retries (Sekunden)
CACHE_TTL=300           # Client-seitiger Cache in Sekunden

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_FILE=logs/nba_tracker.log
```

> Ohne einen gültigen `BALLDONTLIE_API_KEY` sind Scores und Standings nicht abrufbar. Ohne `ODDS_API_KEY` werden Quoten-Vergleiche übersprungen – die ML-Vorhersage funktioniert weiterhin.

---

## 5. INSTALLATION & SETUP

Das Projekt lässt sich per Docker oder in einer lokalen virtuellen Umgebung starten. Docker ist der schnellste Weg zu einer isolierten, reproduzierbaren Umgebung.

### Option A: Docker
Voraussetzung: [Docker Desktop](https://www.docker.com/products/docker-desktop/) ist installiert.

1. `.env`-Datei anlegen: `cp .env.example .env` (API-Keys eintragen)
2. Container bauen und im Hintergrund starten:
   ```bash
   docker-compose up --build -d
   ```
3. Das Web-Dashboard ist unter **http://localhost:5000** erreichbar.

### Option B: Lokales venv (Entwicklung)
Voraussetzung: Python 3.12+

1. Virtuelle Umgebung erstellen und aktivieren:
   ```bash
   python -m venv .venv
   source .venv/bin/activate       # macOS/Linux
   .venv\Scripts\activate          # Windows
   ```
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. `.env`-Datei anlegen und konfigurieren (`cp .env.example .env`).
4. Web-Server starten:
   ```bash
   python web/server.py
   ```
*(Alternativ kann die CLI genutzt werden: `python main.py --help`)*

> **Wichtig:** ML-Vorhersagen erfordern ein trainiertes Modell. Vor dem ersten `ml-predict`-Aufruf muss einmalig `python main.py train all` ausgeführt werden (siehe Abschnitt 6).

---

## 6. CLI-REFERENZ

Die Kommandozeile ist der primäre Einstiegspunkt für Entwickler. Alle Befehle werden über `python main.py <befehl>` aufgerufen.

| Befehl | Argumente | Beschreibung |
| :--- | :--- | :--- |
| `live` | – | Zeigt alle aktuell laufenden NBA-Spiele an. |
| `scores` | `[--date YYYY-MM-DD]` | Spielergebnisse für ein Datum (Standard: heute). |
| `standings` | – | Aktuelle NBA-Tabelle mit Team-Statistiken. |
| `team <name>` | Teamname (z. B. `Lakers`) | Detaillierte Statistiken eines Teams. |
| `ml-predict <home> <away>` | Heim- und Auswärtsteam | Modellvorhersage inkl. Vergleich mit den Quoten. |
| `train collect` | `[--seasons …] [--max-games N]` | Rohdaten von der NBA-API abrufen und speichern. |
| `train model` | – | Modell auf den gespeicherten Trainingsdaten trainieren. |
| `train all` | `[--seasons …] [--max-games N]` | Datensammlung **und** Training in einem Schritt (empfohlen). |
| `train metrics` | – | Metriken des zuletzt trainierten Modells anzeigen. |
| `compare` | `[--home …] [--away …]` | Modellwahrscheinlichkeit vs. aus Quoten abgeleitete Wahrscheinlichkeit (alle anstehenden Spiele oder ein konkretes Duell). |

**Beispiele:**

```bash
# Erstes Training (Pflicht vor ml-predict)
python main.py train all

# Vorhersage für ein Spiel
python main.py ml-predict "Lakers" "Celtics"

# Modell und Quoten für alle anstehenden Spiele vergleichen
python main.py compare

# Ergebnisse von gestern
python main.py scores --date 2025-05-05
```

---

## 7. WEB-DASHBOARD

Das Flask-Dashboard unter **http://localhost:5000** bietet dieselben Funktionen wie die CLI, jedoch mit einer grafischen Oberfläche.

| Route / Endpunkt | Methode | Funktion |
| :--- | :--- | :--- |
| `/` | GET | Startseite (Vanilla HTML/CSS/JS) |
| `/api/status` | GET | Online-Status der externen APIs |
| `/api/standings` | GET | Tabelle (`?season=2024`) |
| `/api/scores` | GET | Spielergebnisse (`?date=YYYY-MM-DD`) |
| `/api/team/<name>` | GET | Team-Statistiken |
| `/api/predict` | POST | KI-Vorhersage (`{"home": "…", "away": "…"}`) |
| `/api/compare` | GET | Quoten-Vergleich (`?home=…&away=…` optional) |
| `/api/metrics` | GET | Metriken des aktiven Modells |
| `/api/pipeline/status` | GET | Status des laufenden/letzten Trainings |
| `/api/pipeline/trigger` | POST | Manuelles Retraining anstoßen |
| `/api/pipeline/models` | GET | Metriken aller trainierten Modelle |

Das Dashboard enthält außerdem einen **automatischen Monats-Scheduler**: Erkennt der Server, dass das letzte Training mehr als 30 Tage zurückliegt, startet er die ML-Pipeline im Hintergrund automatisch neu.

---

## 8. CODE-QUALITÄT & STABILITÄT

Um Laufzeitfehler während des laufenden Betriebs (insbesondere bei inkonsistenten API-Antworten) zu verhindern, setzt NBA Predict auf:
*   **Integriertes Exception Handling:** Fehler bei Netzwerkanfragen werden durch spezifische Exceptions (`ApiError`) abgefangen. Es existiert eine automatisierte Retry-Logik mit Backoff für vorübergehende API-Ausfälle.
*   **Zentrales Logging:** Alle relevanten Ereignisse, Warnungen und Fehler werden zentral erfasst und in die Datei `logs/nba_predict.log` geschrieben. Darüber lässt sich auch der Docker-Container (`nba-predict-web`) im laufenden Betrieb überwachen.

---

## 9. TESTING

Eine umfassende Test-Coverage ist essentiell für die funktionale Korrektheit komplexer ML-Pipelines. Wir nutzen `pytest` für unsere Tests und stellen sicher, dass alle kritischen Berechnungen (z.B. Elo-Rating) korrekt und frei von Data-Leakage sind.

**Tests ausführen:**
```bash
# Gesamte Testsuite durchlaufen
pytest

# Testsuite mit Coverage-Report ausführen (Sollwert: >75%)
pytest --cov=src
```

---

## 10. TECH-STACK

Die gewählten Technologien entsprechen modernen Data-Science-Standards:

*   **Backend & CLI:** Python 3.12
*   **Machine Learning:** Scikit-learn, XGBoost, Numpy, Pandas (via nba_api)
*   **Web-API & Frontend:** Flask, Flask-CORS, Vanilla HTML/CSS/JS
*   **Infrastruktur & DevOps:** Docker, Docker-Compose, python-dotenv
*   **Testing & Linting:** Pytest, pytest-cov, Ruff
*   **Persistenz:** JSON und Joblib (lokale Speicherung von Modellen und Logs – keine externe Datenbank wie MongoDB erforderlich, um das Setup leichtgewichtig zu halten).

---

## 11. BEKANNTE EINSCHRÄNKUNGEN

*   **Modellgenauigkeit:** Das aktive Modell erreicht 66,7 % Accuracy auf dem Testset (Heimteam-Baseline: 55,1 %, siehe Abschnitt 1). Verletzungen, Kaderwechsel und Play-off-Motivation sind in den Merkmalen nicht enthalten und begrenzen die erreichbare Genauigkeit.
*   **API Rate Limits:** The Odds API erlaubt im kostenlosen Tier nur 500 Anfragen pro Monat. Bei intensiver Nutzung des `compare`-Befehls kann dieses Kontingent schnell aufgebraucht sein.
*   **Keine Echtzeit-Daten:** Während laufender Spiele werden keine Live-Play-by-Play-Daten aktualisiert. Scores und Spielstatus werden erst nach Spielende zuverlässig angezeigt.
*   **Trainingszeit:** `train all` kann je nach Datenmenge und Hardware zwischen 2 und 10 Minuten dauern. Der erste Lauf lädt mehrere Saisons Daten von der NBA-API und ist entsprechend langsamer.

---

## 12. AUTOREN

Entwickelt im Rahmen des Moduls *Fortgeschrittene Programmierung* (2. Semester, Wirtschaftsinformatik – Data Science):

*   **Julian Krupp**
*   **Max Hähnel**
*   **Teodor Gjorgjeski**
