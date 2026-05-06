# ── NBA Predict – Docker Image ────────────────────────────────────────────────
# Multi-Stage-Build: Builder installiert Abhängigkeiten, Runtime bleibt schlank.

# ── Stage 1: Abhängigkeiten installieren ─────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System-Dependencies für numerische Bibliotheken
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten separat kopieren (Docker-Cache-Layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime-Image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="NBA Predict"
LABEL description="KI-gestütztes NBA Vorhersage- und Wettanalyse-System"
LABEL version="0.9.0"

WORKDIR /app

# Python-Pfad: installierten Pakete aus Builder-Stage übernehmen
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Quellcode kopieren
COPY src/      ./src/
COPY web/      ./web/
COPY main.py   .

# Laufzeit-Verzeichnisse anlegen
RUN mkdir -p logs data/models data/training_data data/cache

# Flask-Konfiguration
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Port 5000 freigeben (Flask-Standard)
EXPOSE 5000

# Healthcheck: prüft ob der Server antwortet
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/standings')" \
    || exit 1

# Standard: Web-Server starten
CMD ["python", "web/server.py"]
