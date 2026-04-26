# Projekt-Infrastruktur – Erklärung & Anpassungsanleitung

Dieses Dokument erklärt alle Infrastruktur-Dateien des Projekts:
was sie tun, warum sie existieren, was sie ersetzen und wie man sie anpasst.
Es richtet sich an Leser ohne Vorkenntnisse in Docker oder Python-Packaging.

---

## Inhaltsverzeichnis

1. [Überblick: Was ist was?](#1-überblick-was-ist-was)
2. [Docker – Containerisierung](#2-docker--containerisierung)
   - [Was ist Docker?](#was-ist-docker)
   - [Dockerfile](#dockerfile)
   - [docker-compose.yml](#docker-composeyml)
   - [.dockerignore](#dockerignore)
3. [Konfiguration](#3-konfiguration)
   - [.env / .env.example](#env--envexample)
4. [pyproject.toml – Projekt-Standard](#4-pyprojecttoml--projekt-standard)
   - [Was ersetzt es?](#was-ersetzt-es)
   - [[project] – Metadaten](#project--metadaten)
   - [[project.scripts] – CLI-Befehl](#projectscripts--cli-befehl)
   - [[tool.ruff] – Code-Qualität](#toolruff--code-qualität)
   - [[tool.pytest] – Tests](#toolpytest--tests)
   - [[tool.coverage] – Testabdeckung](#toolcoverage--testabdeckung)
5. [Schnellreferenz: Häufige Anpassungen](#5-schnellreferenz-häufige-anpassungen)

---

## 1. Überblick: Was ist was?

```
NBAPredict/
├── Dockerfile           ← Bauanleitung für das Docker-Image
├── docker-compose.yml   ← Startkonfiguration für Container
├── .dockerignore        ← Ausschlussliste beim Image-Bau
├── .env.example         ← Vorlage für API-Keys und Einstellungen
├── .env                 ← Echte Konfiguration (nicht in Git!)
└── pyproject.toml       ← Moderner Python-Projektstandard
```

| Datei | Ohne diese Datei... |
|-------|---------------------|
| `Dockerfile` | ...müsste jeder Python selbst installieren und konfigurieren |
| `docker-compose.yml` | ...müsste man `docker run` mit vielen Parametern aufrufen |
| `.dockerignore` | ...würde das Image unnötig groß und `.env` wäre darin enthalten |
| `.env.example` | ...wüsste niemand, welche Keys konfiguriert werden müssen |
| `pyproject.toml` | ...gibt es keine zentralisierte Tool-Konfiguration |

---

## 2. Docker – Containerisierung

### Was ist Docker?

Docker verpackt eine Anwendung mit allem, was sie braucht (Python, Bibliotheken,
Konfiguration), in einen sogenannten **Container**. Dieser Container läuft
identisch auf jedem Rechner – egal ob Windows, macOS oder Linux.

**Analogie:** Ein Container ist wie ein USB-Stick mit einem kompletten,
vorinstallierten Betriebssystem. Man steckt ihn ein (startet den Container)
und alles läuft sofort – ohne Installation.

**Was Docker ersetzt:**
- Die manuelle Anleitung "installiere Python 3.12, erstelle eine venv,
  installiere requirements.txt, setze Umgebungsvariablen..."
- Probleme wie "bei mir funktioniert es, bei dir nicht" durch unterschiedliche
  Python-Versionen oder Betriebssysteme

**Voraussetzung:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
muss installiert sein.

---

### Dockerfile

**Pfad:** `Dockerfile` (im Projektstamm)

Das Dockerfile ist die **Bauanleitung** für das Docker-Image. Ein Image ist
der "Bauplan" – der Container ist die laufende Instanz davon.

```dockerfile
# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder
```
Startet mit einem offiziellen Python-3.12-Basis-Image (klein = "slim").
Das `AS builder` benennt diese Phase.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*
```
Installiert C-Compiler, die numpy/scipy beim Installieren benötigen.
`--no-install-recommends` und `rm -rf /var/lib/apt/lists/*` halten das
Image klein.

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
```
Kopiert die Abhängigkeitsliste in den Container und installiert sie.
`--no-cache-dir` spart Speicher. `--user` legt die Pakete unter
`/root/.local` ab, damit sie in Stage 2 übernommen werden können.

```dockerfile
# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
```
Startet ein **neues, sauberes** Image. Das ist der **Multi-Stage-Build**:
Stage 1 (mit gcc etc.) wird verworfen – in das finale Image kommt nur, was
in Stage 2 steht.

```dockerfile
COPY --from=builder /root/.local /root/.local
```
Übernimmt ausschließlich die installierten Python-Pakete aus Stage 1.
Der Compiler und alle Build-Tools bleiben zurück.

```dockerfile
COPY src/      ./src/
COPY web/      ./web/
COPY main.py   .
```
Kopiert den Quellcode. Nur die nötigen Ordner – keine Tests, keine Docs.

```dockerfile
RUN mkdir -p logs data/models data/training_data data/cache
```
Legt Verzeichnisse an, die das Programm erwartet. Ohne `mkdir` würde
der Server beim Starten abstürzen, weil er `logs/` nicht schreiben kann.

```dockerfile
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
```
Setzt Umgebungsvariablen im Container:
- `FLASK_ENV=production`: Flask läuft im Produktionsmodus (kein Debug)
- `PYTHONUNBUFFERED=1`: Log-Ausgaben erscheinen sofort (kein Puffer)
- `PYTHONDONTWRITEBYTECODE=1`: Keine `.pyc`-Cache-Dateien anlegen

```dockerfile
EXPOSE 5000
```
Dokumentiert, dass der Container auf Port 5000 lauscht. **Öffnet den Port
nicht selbst** – das macht erst `docker-compose.yml` mit der Zeile
`ports: - "5000:5000"`.

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/standings')" \
    || exit 1
```
Docker prüft alle 30 Sekunden, ob der Server antwortet. Wenn er es nach
3 Versuchen nicht tut, gilt der Container als "unhealthy". Das ermöglicht
automatischen Neustart und Monitoring.

```dockerfile
CMD ["python", "web/server.py"]
```
Der Standardbefehl beim Start des Containers. Kann in
`docker-compose.yml` mit `command:` überschrieben werden.

#### Wie anpassen?

| Änderung | Was bearbeiten |
|----------|---------------|
| Python-Version ändern | `FROM python:3.12-slim` → z.B. `python:3.13-slim` |
| Anderen Port | `EXPOSE 5000` → `EXPOSE 8080` (+ Compose anpassen) |
| Anderen Startbefehl | `CMD [...]` anpassen |
| Mehr Systemtools | In `apt-get install` ergänzen |

Nach jeder Änderung am Dockerfile muss das Image neu gebaut werden:
```bash
docker compose build
```

---

### docker-compose.yml

**Pfad:** `docker-compose.yml` (im Projektstamm)

Compose ist der **Dirigent**: Er baut das Image (wenn nötig), startet den
Container mit allen Einstellungen und verwaltet Volumes, Ports und
Umgebungsvariablen. Ohne Compose müsste man `docker run` mit vielen
Parametern von Hand aufrufen.

**Was Compose ersetzt:**
```bash
# Ohne Compose:
docker run -p 5000:5000 \
  -v ./data:/app/data \
  -v ./logs:/app/logs \
  --env-file .env \
  --restart unless-stopped \
  nba-predict

# Mit Compose:
docker compose up
```

#### Aufbau im Detail:

```yaml
services:
  web:
```
Definiert einen Service namens `web`. Es können mehrere Services
(z.B. Datenbank, Worker) nebeneinander stehen.

```yaml
    build: .
```
Baut das Image aus dem `Dockerfile` im aktuellen Verzeichnis (`.`).

```yaml
    container_name: nba-predict-web
```
Gibt dem laufenden Container einen festen Namen. Ohne diesen Eintrag
würde Docker einen zufälligen Namen generieren (z.B. `nbapredict_web_1`).

```yaml
    ports:
      - "5000:5000"
```
Verbindet Port 5000 des Hosts mit Port 5000 des Containers.
Format: `"HOST:CONTAINER"`.

Beispiel: `"8080:5000"` würde bedeuten: Der Container lauscht intern
auf 5000, ist von außen aber unter `localhost:8080` erreichbar.

```yaml
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
```
**Das Wichtigste überhaupt.** Verbindet Verzeichnisse auf dem Host mit
Verzeichnissen im Container.

Format: `HOST_PFAD:CONTAINER_PFAD`

Ohne Volumes wären die trainierten Modelle (`data/models/`) und der
Pipeline-Status nach jedem `docker compose down` verloren,
weil das Container-Dateisystem flüchtig ist. Mit Volumes liegen die Daten
auf dem Host und überleben jeden Neustart.

```yaml
    env_file:
      - .env
```
Liest alle Zeilen aus `.env` und setzt sie als Umgebungsvariablen im
Container. So gelangen API-Keys ins Programm, ohne dass sie im
Dockerfile oder im Code stehen.

```yaml
    environment:
      - FLASK_ENV=production
      - PYTHONUNBUFFERED=1
```
Direkt gesetzte Umgebungsvariablen (Ergänzung zu `env_file`).

```yaml
    restart: unless-stopped
```
Startet den Container automatisch neu, wenn er abstürzt oder der
Rechner neu gestartet wird. Hört erst auf, wenn man ihn explizit
mit `docker compose stop` stoppt.

Mögliche Werte:
- `no` – nie automatisch neustarten
- `always` – immer neustarten (auch bei `docker compose stop`)
- `unless-stopped` – neustarten, außer wenn manuell gestoppt *(empfohlen)*
- `on-failure` – nur bei Absturz (Exit-Code ≠ 0)

```yaml
  # worker:
  #   build: .
  #   command: python -c "..."
```
Auskommentierter optionaler Service für zukünftige Hintergrund-Jobs.
Zum Aktivieren die `#`-Zeichen entfernen.

#### Wichtigste Befehle:

```bash
docker compose up           # Startet alle Services im Vordergrund
docker compose up -d        # Startet im Hintergrund (detached)
docker compose down         # Stoppt und entfernt Container
docker compose restart      # Neustart aller Services
docker compose logs -f      # Live-Logs anzeigen
docker compose build        # Image neu bauen (nach Code-Änderungen)
docker compose ps           # Zeigt laufende Container
```

#### Wie anpassen?

| Änderung | Was bearbeiten |
|----------|---------------|
| Port ändern | `"5000:5000"` → `"8080:5000"` |
| Weiteres Verzeichnis mounten | Neues `- ./pfad:/app/pfad` unter `volumes:` |
| Resolver aktivieren | `# resolver:` Block auskommentieren |
| Zweite Instanz hinzufügen | Neuen Service unter `services:` anlegen |

---

### .dockerignore

**Pfad:** `.dockerignore` (im Projektstamm)

Beim `docker build` liest Docker alle Dateien des Projekts ein und schickt
sie an den Docker-Daemon. Ohne `.dockerignore` würde dabei folgendes
im Image landen:

- `.venv/` (~500 MB Python-Pakete, die im Container sowieso neu installiert werden)
- `.env` (API-Keys im Image = Sicherheitsrisiko)
- `.git/` (komplette Git-Historie, nutzlos im Container)
- `htmlcov/` (Test-Coverage-Berichte)
- `*.log` (alte Logs)

```
.venv/          ← riesig, unnötig
.env            ← Sicherheitsrisiko!
.git/
htmlcov/
*.log
*.docx
```

**Faustregel:** Alles, was auch in `.gitignore` steht, gehört auch in
`.dockerignore`. Zusätzlich: alles, was im Container nicht benötigt wird
(Dokumentation, Test-Artefakte, Logs).

#### Wie anpassen?

Einfach neue Zeilen hinzufügen. Syntax ist identisch mit `.gitignore`:

```
datei.txt           ← genau diese Datei
*.log               ← alle .log-Dateien
ordner/             ← ganzen Ordner ausschließen
!wichtig.log        ← Ausnahme: diese Datei doch einschließen
```

---

## 3. Konfiguration

### .env / .env.example

**Pfad:** `.env` (nicht in Git), `.env.example` (in Git)

`.env` ist eine einfache Textdatei mit Schlüssel-Wert-Paaren:

```
BALLDONTLIE_API_KEY=abc123
ODDS_API_KEY=xyz789
REQUEST_TIMEOUT=10
LOG_LEVEL=INFO
```

Das Programm liest diese Werte beim Start über `python-dotenv` (`load_dotenv()`)
und macht sie als Umgebungsvariablen verfügbar.

**Warum nicht direkt im Code?**
API-Keys dürfen nie im Quellcode stehen – sie würden sonst im Git-Repository
sichtbar sein. Die `.env`-Datei steht in `.gitignore` und bleibt lokal.

**`.env.example`** ist die öffentliche Vorlage ohne echte Werte. Sie zeigt,
welche Keys existieren und was sie bedeuten, ohne Secrets preiszugeben.

#### Ersteinrichtung:

```bash
cp .env.example .env
# Dann .env öffnen und API-Keys eintragen
```

#### Alle verfügbaren Einstellungen:

| Variable | Bedeutung | Standard |
|----------|-----------|---------|
| `BALLDONTLIE_API_KEY` | API-Key für Spielergebnisse (balldontlie.io) | – |
| `ODDS_API_KEY` | API-Key für Wettquoten (the-odds-api.com) | – |
| `REQUEST_TIMEOUT` | Sekunden bis API-Anfrage abbricht | `10` |
| `MAX_RETRIES` | Wiederholungsversuche bei API-Fehler | `3` |
| `RETRY_DELAY` | Sekunden zwischen Wiederholungen | `1.0` |
| `CACHE_TTL` | Cache-Lebensdauer in Sekunden | `300` |
| `LOG_LEVEL` | Detailtiefe der Logs (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `LOG_FILE` | Pfad zur Log-Datei | `logs/nba_predict.log` |

---

## 4. pyproject.toml – Projekt-Standard

**Pfad:** `pyproject.toml` (im Projektstamm)

### Was ersetzt es?

`pyproject.toml` ist der moderne Python-Projektstandard (PEP 517/518/621).
Er **zentralisiert** Konfigurationen, die früher auf mehrere Dateien verteilt waren:

| Früher | Jetzt in `pyproject.toml` |
|--------|--------------------------|
| `requirements.txt` | `[project] dependencies` |
| `setup.py` / `setup.cfg` | `[project]` |
| `pytest.ini` | `[tool.pytest.ini_options]` |
| `.flake8` / `tox.ini` (Linting) | `[tool.ruff]` |
| `.coveragerc` | `[tool.coverage]` |

**Wichtig:** `requirements.txt` und `pytest.ini` existieren noch und werden
weiterhin unterstützt. `pyproject.toml` ist eine Ergänzung, keine erzwungene
Migration.

---

### [project] – Metadaten

```toml
[project]
name = "nba-predict"
version = "0.9.0"
description = "KI-gestütztes NBA Vorhersagesystem mit Multi-Modell-Pipeline"
requires-python = ">=3.12"
readme = "README.md"

dependencies = [
    "requests>=2.32.0",
    "scikit-learn>=1.3.0",
    "flask>=3.0.0",
    ...
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.5.0",
]
```

**`dependencies`** sind die Pakete, die zum Ausführen des Programms nötig sind.

**`[project.optional-dependencies]`** trennt Dev-Tools (pytest, ruff) von
Runtime-Paketen. Das verhindert, dass beim Deployment auf einem Server unnötig
Test-Tools installiert werden.

Installation:
```bash
pip install -e .          # nur Runtime-Pakete
pip install -e ".[dev]"   # Runtime + Dev-Tools (für Entwicklung)
```

Das `-e` steht für "editable install": Änderungen am Code sind sofort wirksam,
ohne neu installieren zu müssen.

**Versionsspezifikationen:**

| Ausdruck | Bedeutung |
|----------|-----------|
| `flask>=3.0.0` | Flask Version 3.0.0 oder neuer |
| `numpy>=1.24.0,<2.0.0` | numpy zwischen 1.24 und 2.0 |
| `requests==2.32.0` | exakt diese Version (nicht empfohlen) |

---

### [project.scripts] – CLI-Befehl

```toml
[project.scripts]
nba = "main:main"
```

Registriert einen Kommandozeilen-Befehl `nba`, der auf die Funktion `main()`
in `main.py` zeigt.

Nach `pip install -e .` kann statt:
```bash
python main.py train collect --seasons 2024 2025
```
geschrieben werden:
```bash
nba train collect --seasons 2024 2025
```

Format: `befehlsname = "modul:funktion"`

Weitere Befehle hinzufügen:
```toml
[project.scripts]
nba        = "main:main"
nba-server = "web.server:main"   # z.B. separater Server-Befehl
```

---

### [tool.ruff] – Code-Qualität

Ruff ist ein Linter und Formatter – er prüft den Code auf Fehler und
Stilprobleme, **ohne ihn auszuführen** (statische Analyse).

```toml
[tool.ruff]
target-version = "py312"   # Welche Python-Version als Ziel
line-length = 100           # Maximale Zeilenlänge (Zeilen länger als 100 Zeichen → Fehler)
exclude = [".venv", ".git", "__pycache__", ...]  # Diese Ordner überspringen
```

```toml
[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "SIM"]
```

**Aktivierte Regelgruppen:**

| Kürzel | Name | Prüft auf |
|--------|------|-----------|
| `E` | pycodestyle errors | Syntaxfehler, falsche Einrückung |
| `W` | pycodestyle warnings | Überflüssige Leerzeichen, leere Zeilen |
| `F` | Pyflakes | Unbenutzte Imports, undefinierte Variablen |
| `I` | isort | Falsch sortierte Import-Reihenfolge |
| `N` | pep8-naming | Namenskonventionen (snake_case, PascalCase) |
| `UP` | pyupgrade | Veraltete Syntax (z.B. `Union[X, Y]` → `X \| Y`) |
| `B` | flake8-bugbear | Häufige logische Fehler und Anti-Patterns |
| `SIM` | flake8-simplify | Vereinfachbare Ausdrücke |

```toml
ignore = [
    "E501",  # Zeilenlänge – durch line-length geregelt, kein Doppel-Check
    "N803",  # Argument-Namen (ML: X, y sind Konvention, aber nicht snake_case)
    "N806",  # Variablen in Funktionen (ML: X_train, y_test)
]
```

**Ignore-Regeln** schalten einzelne Prüfungen aus. Hier werden ML-Konventionen
(Großbuchstaben für Matrizen: `X_train`, `y_test`) von der Namensregel
ausgenommen.

```toml
[tool.ruff.lint.isort]
known-first-party = ["src"]
```

Teilt Ruff mit, dass `src` ein internes Paket ist. Dadurch werden Imports
korrekt sortiert: Standardbibliothek → externe Pakete → interne (`src`).

**Verwendung:**
```bash
ruff check src/          # Zeigt alle Verstöße
ruff check src/ --fix    # Behebt automatisch behebbare Probleme
ruff format src/         # Formatiert Code (wie Black)
ruff format src/ --check # Prüft nur, ohne zu ändern
```

**Neue Regelgruppe hinzufügen:**
```toml
select = ["E", "W", "F", "I", "N", "UP", "B", "SIM", "C90"]
#                                                        ^^^
#                                                 McCabe-Komplexität
```

Alle verfügbaren Regelgruppen: https://docs.astral.sh/ruff/rules/

---

### [tool.pytest] – Tests

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "--verbose",
    "--tb=short",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=75",
]
```

Diese Konfiguration spiegelt `pytest.ini` – beide Dateien werden unterstützt.

**`addopts`** – Parameter die immer zu `pytest` hinzugefügt werden:

| Option | Bedeutung |
|--------|-----------|
| `--verbose` | Jeden einzelnen Test namentlich ausgeben |
| `--tb=short` | Bei Fehlern: kurze Fehlermeldung (nicht den vollen Stacktrace) |
| `--cov=src` | Coverage für den `src/`-Ordner messen |
| `--cov-report=term-missing` | Zeigt in der Konsole welche Zeilen nicht getestet wurden |
| `--cov-report=html:htmlcov` | Erstellt HTML-Bericht unter `htmlcov/index.html` |
| `--cov-fail-under=75` | Test-Lauf schlägt fehl, wenn weniger als 75% abgedeckt sind |

**`--cov-fail-under=75` anpassen:**
```toml
"--cov-fail-under=80",   # Strengeres Minimum auf 80% erhöhen
```

---

### [tool.coverage] – Testabdeckung

```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "src/utils/display.py",
    "src/utils/ml_display.py",
    "**/__init__.py",
]
```

**`omit`** schließt Dateien von der Coverage-Messung aus.
`display.py` und `ml_display.py` enthalten nur `print()`-Aufrufe – es wäre
aufwendig und wenig sinnvoll, diese zu testen.

```toml
[tool.coverage.report]
show_missing = true   # Zeigt Zeilennummern nicht getesteter Zeilen
skip_covered = false  # Zeigt auch zu 100% abgedeckte Dateien
```

**HTML-Bericht öffnen** (nach `pytest`):
```bash
# Windows
start htmlcov/index.html

# macOS
open htmlcov/index.html
```

---

## 5. Schnellreferenz: Häufige Anpassungen

### Projekt auf Docker starten

```bash
# 1. Konfiguration einrichten (einmalig)
cp .env.example .env
# .env öffnen und BALLDONTLIE_API_KEY + ODDS_API_KEY eintragen

# 2. Image bauen und starten
docker compose up -d

# 3. Im Browser öffnen
# http://localhost:5000

# 4. Logs anzeigen
docker compose logs -f

# 5. Stoppen
docker compose down
```

### Port ändern (z.B. auf 8080)

In `docker-compose.yml`:
```yaml
ports:
  - "8080:5000"   # War: "5000:5000"
```

### Python-Version aktualisieren

In `Dockerfile` (beide Stellen):
```dockerfile
FROM python:3.13-slim AS builder   # War: 3.12-slim
FROM python:3.13-slim AS runtime   # War: 3.12-slim
```

In `pyproject.toml`:
```toml
requires-python = ">=3.13"         # War: >=3.12

[tool.ruff]
target-version = "py313"           # War: py312
```

### Neue Abhängigkeit hinzufügen

In `requirements.txt` (für direktes `pip install`) **und** in `pyproject.toml`:
```toml
dependencies = [
    ...
    "neue-bibliothek>=1.0.0",   # hinzufügen
]
```

Dann Image neu bauen:
```bash
docker compose build
```

### Ruff-Regel deaktivieren

```toml
[tool.ruff.lint]
ignore = [
    "E501",
    "N803",
    "N806",
    "B006",   # neu: konkrete Regel durch ihren Code deaktivieren
]
```

Regelcodes findet man in der Ruff-Dokumentation oder indem man die
Fehlermeldung von `ruff check` liest (z.B. `B006 Do not use mutable...`).

### Coverage-Minimum anpassen

```toml
addopts = [
    ...
    "--cov-fail-under=80",   # War: 75
]
```

### Datei von Coverage ausschließen

```toml
[tool.coverage.run]
omit = [
    "src/utils/display.py",
    "src/utils/ml_display.py",
    "**/__init__.py",
    "src/neue_datei.py",     # hinzufügen
]
```
