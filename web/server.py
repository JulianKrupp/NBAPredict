"""
NBA Tracker – Flask Web-Server

Starten mit:  python web/server.py
Aufruf im Browser: http://localhost:5000

Exponiert alle CLI-Funktionen als REST-API und liefert das Frontend aus.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict
from datetime import date
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
from src.prediction.predictor import GamePredictor
from src.utils.config import Config
from src.utils.logger import setup_logger

# ── App-Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
CORS(app)

config = Config()
setup_logger(config.log_level, config.log_file)
logger = logging.getLogger(__name__)

nba_client   = NBAApiClient(config)
odds_client  = OddsApiClient(config)
ml_predictor = MLPredictor(config)
comparison   = OddsVsMLComparison(config)

# Training-Status (für den Fortschrittsbalken im Frontend)
_training_status: dict = {"running": False, "step": "", "done": False, "error": ""}


# ── Frontend ausliefern ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── API: Standings ─────────────────────────────────────────────────────────────

@app.route("/api/standings")
def get_standings():
    season = request.args.get("season", 2024, type=int)
    try:
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
    except Exception as exc:
        logger.error("Standings-Fehler: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── API: Scores ───────────────────────────────────────────────────────────────

@app.route("/api/scores")
def get_scores():
    game_date = request.args.get("date", str(date.today()))
    try:
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
    except Exception as exc:
        logger.error("Scores-Fehler: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── API: Team ─────────────────────────────────────────────────────────────────

@app.route("/api/team/<team_name>")
def get_team(team_name: str):
    try:
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
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── API: Vorhersage ───────────────────────────────────────────────────────────

@app.route("/api/predict", methods=["POST"])
def predict():
    data = request.get_json() or {}
    home_name = data.get("home", "")
    away_name = data.get("away", "")
    use_ml    = data.get("ml", True)

    if not home_name or not away_name:
        return jsonify({"error": "home und away sind erforderlich"}), 400

    try:
        home_stats = nba_client.get_team_stats(home_name)
        away_stats = nba_client.get_team_stats(away_name)
        if not home_stats:
            return jsonify({"error": f"Team '{home_name}' nicht gefunden"}), 404
        if not away_stats:
            return jsonify({"error": f"Team '{away_name}' nicht gefunden"}), 404

        odds = odds_client.get_odds(home_name, away_name)

        if use_ml and ml_predictor.is_model_available():
            result = ml_predictor.predict(home_stats, away_stats, odds)
            return jsonify({
                "type":             "ml",
                "home":             home_stats.name,
                "away":             away_stats.name,
                "ml_home_prob":     round(result.ml_home_win_probability, 3),
                "ml_away_prob":     round(1 - result.ml_home_win_probability, 3),
                "ml_winner":        result.ml_predicted_winner,
                "ml_confidence":    result.ml_confidence,
                "rule_home_prob":   round(result.rule_home_win_probability, 3),
                "rule_away_prob":   round(1 - result.rule_home_win_probability, 3),
                "rule_winner":      result.rule_predicted_winner,
                "odds_home_prob":   round(result.odds_home_win_probability, 3) if result.odds_home_win_probability else None,
                "odds_away_prob":   round(1 - result.odds_home_win_probability, 3) if result.odds_home_win_probability else None,
                "odds_home_raw":    odds.odds_home if odds else None,
                "odds_away_raw":    odds.odds_away if odds else None,
                "home_score":       result.predicted_home_score,
                "away_score":       result.predicted_away_score,
                "consensus":        result.consensus_winner,
                "agreement":        result.consensus_agreement_count,
                "factors":          result.feature_contributions,
            })
        else:
            predictor = GamePredictor()
            result = predictor.predict(home_stats, away_stats, odds)
            home_prob = result.win_probability if result.predicted_winner == "home" else 1 - result.win_probability
            return jsonify({
                "type":           "rule",
                "home":           home_stats.name,
                "away":           away_stats.name,
                "rule_home_prob": round(home_prob, 3),
                "rule_away_prob": round(1 - home_prob, 3),
                "rule_winner":    result.predicted_winner,
                "ml_home_prob":   None,
                "odds_home_prob": odds.implied_home_probability / (odds.implied_home_probability + odds.implied_away_probability) if odds else None,
                "home_score":     result.predicted_home_score,
                "away_score":     result.predicted_away_score,
                "factors":        result.factors,
            })
    except Exception as exc:
        logger.error("Predict-Fehler: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── API: Vergleich KI vs. Odds ────────────────────────────────────────────────

@app.route("/api/compare")
def compare():
    home = request.args.get("home")
    away = request.args.get("away")
    try:
        if home and away:
            entry = comparison.run_comparison_for_teams(home, away)
            entries = [entry] if entry else []
        else:
            entries = comparison.run_comparison()

        return jsonify([{
            "home":        e.home_team,
            "away":        e.away_team,
            "ml_home":     round(e.ml_home_prob, 3),
            "ml_away":     round(e.ml_away_prob, 3),
            "ml_winner":   e.ml_winner,
            "odds_home":   round(e.odds_home_prob, 3),
            "odds_away":   round(e.odds_away_prob, 3),
            "odds_winner": e.odds_winner,
            "odds_home_raw": e.odds_home_raw,
            "odds_away_raw": e.odds_away_raw,
            "diff":        round(e.prob_difference, 3),
            "agree":       e.methods_agree,
            "indicator":   e.value_bet_indicator,
        } for e in entries])
    except Exception as exc:
        logger.error("Compare-Fehler: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── API: Modell-Metriken ──────────────────────────────────────────────────────

@app.route("/api/metrics")
def get_metrics():
    trainer = NBAModelTrainer()
    metrics = trainer.load_metrics()
    if not metrics:
        return jsonify({"available": False})
    return jsonify({"available": True, **metrics})


# ── API: Training auslösen (asynchron) ───────────────────────────────────────

@app.route("/api/train", methods=["POST"])
def train():
    global _training_status
    if _training_status["running"]:
        return jsonify({"error": "Training läuft bereits"}), 409

    data    = request.get_json() or {}
    command = data.get("command", "all")
    seasons = data.get("seasons", [2023, 2024])
    max_g   = data.get("max_games", 300)

    def run():
        global _training_status
        _training_status = {"running": True, "step": "Starte...", "done": False, "error": ""}
        try:
            from src.ml.data_collector import TrainingDataCollector
            _training_status["step"] = "Trainingsdaten sammeln..."
            collector = TrainingDataCollector(config)
            samples = collector.collect_with_progress(seasons=seasons, max_games=max_g)

            if not samples:
                _training_status = {"running": False, "step": "", "done": False,
                                    "error": "Keine Trainingsdaten gesammelt"}
                return

            _training_status["step"] = f"Modell trainieren ({len(samples)} Samples)..."
            trainer = NBAModelTrainer()
            metrics = trainer.train(samples=samples)
            _training_status = {
                "running": False, "done": True, "step": "Fertig",
                "error": "",
                "accuracy": metrics.accuracy,
                "model":    metrics.model_name,
            }
        except Exception as exc:
            _training_status = {"running": False, "step": "", "done": False, "error": str(exc)}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/train/status")
def train_status():
    return jsonify(_training_status)


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🏀 NBA Tracker Web-Server")
    print("  http://localhost:5000")
    print("="*55 + "\n")
    app.run(debug=False, port=5000, threaded=True)
