# NBA Predict

**Ein datengetriebenes Prognose- und Analysetool für die National Basketball Association (NBA).**

Dieses Projekt wurde im Rahmen des Moduls *Fortgeschrittene Programmierung* im 2. Semester Wirtschaftsinformatik (Data Science) entwickelt. Es demonstriert die Integration von Machine Learning, Datenbeschaffung über externe Schnittstellen (APIs) und modularem Software-Engineering auf Produktionsniveau.

---

## 1. TITEL & VISION

### Vision und Business Case
Die präzise Vorhersage von Sportergebnissen bietet enormes Potenzial für die moderne Sportanalytik. **NBA Predict** verfolgt das Ziel, rohe, historische NBA-Spieldaten in verwertbares Wissen (Insights) zu transformieren. 

Für Sport-Analysten und Wettanbieter entsteht ein direkter Business Case: Durch das automatisierte Scraping aktueller Buchmacherquoten und deren Abgleich mit unseren ML-basierten Siegwahrscheinlichkeiten identifiziert das System profitable Wettchancen (Expected Value / Value Bets). Die Anwendung dient somit als fundiertes Decision-Support-System, das emotionale Bauchentscheidungen durch statistische Wahrscheinlichkeiten ersetzt.

---

## 2. FEATURES

| Kategorie | Kernfunktionen |
| :--- | :--- |
| **Daten-Scraping & ETL** | Vollautomatische Anbindung der *BallDontLie API*, *NBA Stats API* und *The Odds API* zum Abrufen historischer Spiele, Advanced Stats und Live-Buchmacherquoten. |
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
├── Dockerfile              # Multi-Stage-Build-Anweisung für Produktion
├── docker-compose.yml      # Orchestrierung des Web-Containers
├── requirements.txt        # Abhängigkeitsmanagement
│
├── src/                    # Geschäftslogik & Core-Module
│   ├── api/                # API-Clients für externe Daten (Adapter-Pattern)
│   ├── ml/                 # Data Collection, Pipeline, Training & Inferenz
│   ├── models/             # Domänenmodelle (Game, Team) als Dataclasses
│   └── utils/              # Hilfsmodule (Config, Logging, Formatting)
│
├── tests/                  # Testumgebung (Unittests, Mocking, Coverage)
└── web/                    # Präsentationsschicht (Flask REST-API & Frontend)
```

---

## 4. INSTALLATION & SETUP

Das Projekt unterstützt ein hybrides Setup. Für den produktiven Einsatz wird Docker empfohlen, um eine isolierte, reproduzierbare Umgebung zu garantieren.

### Option A: Docker-Environment (Produktion)
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

---

## 5. CODE-QUALITÄT & STABILITÄT

Um Laufzeitfehler während des laufenden Betriebs (insbesondere bei inkonsistenten API-Antworten) zu verhindern, setzt NBA Predict auf:
*   **Integriertes Exception Handling:** Fehler bei Netzwerkanfragen werden durch spezifische Exceptions (`ApiError`) abgefangen. Es existiert eine automatisierte Retry-Logik mit Backoff für vorübergehende API-Ausfälle.
*   **Zentrales Logging:** Alle relevanten Ereignisse, Warnungen und Fehler werden zentral erfasst und in die Datei `logs/nba_predict.log` geschrieben. Dies erlaubt eine präzise Überwachung des Docker-Containers (`nba-predict-web`) in Produktion.

---

## 6. TESTING

Eine umfassende Test-Coverage ist essentiell für die funktionale Korrektheit komplexer ML-Pipelines. Wir nutzen `pytest` für unsere Tests und stellen sicher, dass alle kritischen Berechnungen (z.B. Elo-Rating) korrekt und frei von Data-Leakage sind.

**Tests ausführen:**
```bash
# Gesamte Testsuite durchlaufen
pytest

# Testsuite mit Coverage-Report ausführen (Sollwert: >75%)
pytest --cov=src
```

---

## 7. TECH-STACK

Die gewählten Technologien entsprechen modernen Data-Science-Standards:

*   **Backend & CLI:** Python 3.12
*   **Machine Learning:** Scikit-learn, XGBoost, Numpy, Pandas (via nba_api)
*   **Web-API & Frontend:** Flask, Flask-CORS, Vanilla HTML/CSS/JS
*   **Infrastruktur & DevOps:** Docker, Docker-Compose, python-dotenv
*   **Testing & Linting:** Pytest, pytest-cov, Ruff
*   **Persistenz:** JSON und Joblib (lokale Speicherung von Modellen und Logs – keine externe Datenbank wie MongoDB erforderlich, um das Setup leichtgewichtig zu halten).
