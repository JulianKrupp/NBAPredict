"""
NBA Tracker – Flask Web-Server

Starten mit:  python web/server.py
Aufruf im Browser: http://localhost:5000
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import date
from functools import wraps
from pathlib import Path

# Projektstamm zum Python-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from src.api.nba_api_client import NBAApiClient
from src.api.odds_api_client import OddsApiClient
from src.ml.comparison import OddsVsMLComparison
from src.ml.ml_predictor import MLPredictor
from src.ml.model_trainer import NBAModelTrainer
from src.ml.data_collector import default_training_seasons, DEFAULT_MAX_GAMES
from src.ml.pipeline import MLPipeline
from src.utils.config import Config
from src.utils.logger import setup_logger


# ── App-Setup ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR))
CORS(app)

config = Config()
for warning in config.validate():
    print(f"[WARNUNG] {warning}")
setup_logger(config.log_level, config.log_file)
logger = logging.getLogger(__name__)

nba_client   = NBAApiClient(config)
odds_client  = OddsApiClient(config)
ml_predictor = MLPredictor(config)
comparison   = OddsVsMLComparison(config)
pipeline     = MLPipeline()

# Training-Status (für den Fortschrittsbalken im Frontend)
_training_status: dict = {"running": False, "step": "", "done": False, "error": ""}

# Beim Server-Start: hängenden "running"-Status aus einem abgebrochenen
# Lauf bereinigen. Kein Thread läuft mehr → running muss False sein.
pipeline._update_status(running=False, step="", error="")


def _run_pipeline_background(
    seasons: list[int] | None = None,
    max_games: int = DEFAULT_MAX_GAMES,
) -> None:
    """Startet die ML-Pipeline in einem Hintergrund-Thread."""
    global _training_status
    if _training_status.get("running"):
        return
    seasons = seasons or default_training_seasons()

    def _run() -> None:
        global _training_status
        _training_status = {"running": True, "step": "Starte Pipeline...", "done": False, "error": ""}
        try:
            all_metrics = pipeline.run(
                seasons=seasons,
                max_games=max_games,
                config=config,
                progress_callback=lambda s: _training_status.update({"step": s}),
            )
            # Cache des Predictors ungültig machen → nächste Vorhersage lädt neues Modell
            ml_predictor._model = None
            ml_predictor._loaded_model_path = None

            status = pipeline.get_status()
            _training_status = {
                "running": False,
                "done":    True,
                "step":    "Fertig",
                "error":   "",
                "models":  status.get("models", []),
                "winner":  status.get("winner", ""),
            }
            logger.info("Pipeline abgeschlossen. Gewinner: %s", status.get("winner"))
        except Exception as exc:
            _training_status = {
                "running": False, "done": False,
                "step": "", "error": str(exc),
            }
            logger.error("Pipeline-Fehler: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


def _monthly_scheduler() -> None:
    """
    Hintergrund-Thread: prüft stündlich ob ein neues Monats-Retraining fällig ist.
    Startet die Pipeline automatisch wenn should_retrain() True zurückgibt.
    """
    import time
    time.sleep(15)  # Server zuerst hochfahren lassen
    while True:
        try:
            if not _training_status.get("running") and pipeline.should_retrain():
                logger.info("Monatliches ML-Retraining wird automatisch gestartet.")
                _run_pipeline_background()
        except Exception as exc:
            logger.error("Monatlicher Scheduler-Fehler: %s", exc)
        time.sleep(3600)  # Stündlich prüfen


def handle_errors(f):
    """Decorator: fängt Exceptions in API-Routen ab und gibt JSON 500 zurück."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as exc:
            logger.error("%s: %s", f.__name__, exc)
            return jsonify({"error": str(exc)}), 500
    return wrapper


# ── Frontend ausliefern ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/status")
def api_status():
    offline = nba_client.is_offline or odds_client.is_offline
    return jsonify({"online": not offline})


# ── API: Standings ─────────────────────────────────────────────────────────────

@app.route("/api/standings")
@handle_errors
def get_standings():
    season = request.args.get("season", 2024, type=int)
    teams = nba_client.get_standings(season)
    return jsonify([{
        "name":        t.name,
        "wins":        t.wins,
        "losses":      t.losses,
        "win_rate":    round(t.win_rate, 3),
        "pts":         round(t.avg_points_scored, 1),
        "pts_allowed": round(t.avg_points_allowed, 1),
        "pt_diff":     round(t.point_differential, 1),
        "home_wr":     round(t.home_win_rate, 3),
        "away_wr":     round(t.away_win_rate, 3),
    } for t in teams])


# ── API: Scores ───────────────────────────────────────────────────────────────

@app.route("/api/scores")
@handle_errors
def get_scores():
    game_date = request.args.get("date", str(date.today()))
    games = nba_client.get_games_by_date(game_date)
    return jsonify([{
        "id":         g.game_id,
        "home":       g.home_team,
        "away":       g.away_team,
        "home_score": g.home_score,
        "away_score": g.away_score,
        "status":     g.status,
        "date":       g.date,
        "is_final":   g.is_final,
        "is_live":    g.is_live,
        "winner":     g.winner,
    } for g in games])


# ── API: Team ─────────────────────────────────────────────────────────────────

@app.route("/api/team/<team_name>")
@handle_errors
def get_team(team_name: str):
    team = nba_client.get_team_stats(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' nicht gefunden"}), 404
    return jsonify({
        "name":        team.name,
        "wins":        team.wins,
        "losses":      team.losses,
        "win_rate":    round(team.win_rate, 3),
        "pts":         round(team.avg_points_scored, 1),
        "pts_allowed": round(team.avg_points_allowed, 1),
        "pt_diff":     round(team.point_differential, 1),
        "home_wr":     round(team.home_win_rate, 3),
        "away_wr":     round(team.away_win_rate, 3),
    })


# ── API: Vorhersage ───────────────────────────────────────────────────────────

@app.route("/api/predict", methods=["POST"])
@handle_errors
def predict():
    data = request.get_json() or {}
    home_name = data.get("home", "")
    away_name = data.get("away", "")

    if not home_name or not away_name:
        return jsonify({"error": "home und away sind erforderlich"}), 400

    home_stats = nba_client.get_team_stats(home_name)
    away_stats = nba_client.get_team_stats(away_name)
    if not home_stats:
        return jsonify({"error": f"Team '{home_name}' nicht gefunden"}), 404
    if not away_stats:
        return jsonify({"error": f"Team '{away_name}' nicht gefunden"}), 404

    if not ml_predictor.is_model_available():
        return jsonify({"error": "Kein ML-Modell vorhanden. Erst 'train all' ausführen."}), 503

    odds = odds_client.get_odds(home_name, away_name)
    result = ml_predictor.predict(home_stats, away_stats, odds)
    return jsonify({
        "type":           "ml",
        "home":           home_stats.name,
        "away":           away_stats.name,
        "ml_home_prob":   round(result.ml_home_win_probability, 3),
        "ml_away_prob":   round(1 - result.ml_home_win_probability, 3),
        "ml_winner":      result.ml_predicted_winner,
        "ml_confidence":  result.ml_confidence,
        "odds_home_prob": round(result.odds_home_win_probability, 3) if result.odds_home_win_probability else None,
        "odds_away_prob": round(1 - result.odds_home_win_probability, 3) if result.odds_home_win_probability else None,
        "odds_home_raw":  odds.odds_home if odds else None,
        "odds_away_raw":  odds.odds_away if odds else None,
        "home_score":     result.predicted_home_score,
        "away_score":     result.predicted_away_score,
        "factors":        result.feature_contributions,
    })


# ── API: Vergleich KI vs. Odds ────────────────────────────────────────────────

@app.route("/api/compare")
@handle_errors
def compare():
    home = request.args.get("home")
    away = request.args.get("away")
    if home and away:
        entry = comparison.run_comparison_for_teams(home, away)
        entries = [entry] if entry else []
    else:
        entries = comparison.run_comparison()

    return jsonify([{
        "home":          e.home_team,
        "away":          e.away_team,
        "ml_home":       round(e.ml_home_prob, 3),
        "ml_away":       round(e.ml_away_prob, 3),
        "ml_winner":     e.ml_winner,
        "odds_home":     round(e.odds_home_prob, 3),
        "odds_away":     round(e.odds_away_prob, 3),
        "odds_winner":   e.odds_winner,
        "odds_home_raw": e.odds_home_raw,
        "odds_away_raw": e.odds_away_raw,
        "diff":          round(e.prob_difference, 3),
        "ev_home":       round(e.ev_home, 4),
        "ev_away":       round(e.ev_away, 4),
        "edge_home":     round(e.edge_home, 4),
        "edge_away":     round(e.edge_away, 4),
    } for e in entries])


# ── API: Modell-Metriken ──────────────────────────────────────────────────────

@app.route("/api/metrics")
def get_metrics():
    trainer = NBAModelTrainer()
    metrics = trainer.load_metrics()
    if not metrics:
        return jsonify({"available": False})
    return jsonify({"available": True, **metrics})


# ── API: Training auslösen (asynchron, über Pipeline) ────────────────────────

@app.route("/api/train", methods=["POST"])
def train():
    if _training_status.get("running"):
        return jsonify({"error": "Training läuft bereits"}), 409

    data    = request.get_json() or {}
    seasons = data.get("seasons") or default_training_seasons()
    max_g   = data.get("max_games", DEFAULT_MAX_GAMES)

    _run_pipeline_background(seasons=seasons, max_games=max_g)
    return jsonify({"started": True})


@app.route("/api/train/status")
def train_status():
    return jsonify(_training_status)


# ── API: ML-Pipeline ──────────────────────────────────────────────────────────

@app.route("/api/pipeline/status")
def pipeline_status():
    """
    Gibt den vollständigen Pipeline-Status zurück:
    - running: bool
    - step: aktueller Schritt
    - models: Liste aller Modell-Metriken aus dem letzten Lauf
    - winner: model_id des besten Modells
    - last_trained_month: "YYYY-MM" des letzten Trainings
    - active_model: Info zum aktuell geladenen Modell
    - error: Fehlermeldung falls vorhanden
    """
    status = pipeline.get_status()
    active = ml_predictor.get_active_model_info()
    return jsonify({**status, "active_model": active})


@app.route("/api/pipeline/trigger", methods=["POST"])
def pipeline_trigger():
    """Löst manuell ein Pipeline-Retraining aus."""
    if _training_status.get("running"):
        return jsonify({"error": "Pipeline läuft bereits"}), 409

    data    = request.get_json() or {}
    seasons = data.get("seasons") or default_training_seasons()
    max_g   = data.get("max_games", DEFAULT_MAX_GAMES)

    _run_pipeline_background(seasons=seasons, max_games=max_g)
    return jsonify({"started": True})


@app.route("/api/pipeline/models")
def pipeline_models():
    """Gibt die Metriken aller trainierten Modelle zurück."""
    trainer = NBAModelTrainer()
    return jsonify(trainer.load_all_metrics())


@app.route("/api/pipeline/reset", methods=["POST"])
def pipeline_reset():
    """
    Setzt einen hängenden 'running'-Status zurück.
    Nur erlaubt wenn kein aktiver Thread läuft (_training_status.running == False).
    """
    if _training_status.get("running"):
        return jsonify({"error": "Pipeline läuft gerade – kein Reset möglich."}), 409
    pipeline._update_status(running=False, step="", error="")
    return jsonify({"reset": True})


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Monatlichen Retrain-Scheduler starten
    threading.Thread(target=_monthly_scheduler, daemon=True).start()

    print("\n" + "="*55)
    print("  🏀 NBA Tracker Web-Server")
    print("  http://localhost:5000")
    print("  ML-Pipeline: automatisches Monats-Retraining aktiv")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", debug=False, port=5000, threaded=True)
