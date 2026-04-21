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
from src.utils.config import Config
from src.utils.logger import setup_logger
from src.betting.tracker import BettingTracker
from src.betting.resolver import BetResolver


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
bet_tracker  = BettingTracker()
bet_resolver = BetResolver(config, bet_tracker)

# Training-Status (für den Fortschrittsbalken im Frontend)
_training_status: dict = {"running": False, "step": "", "done": False, "error": ""}


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


# ── API: Training auslösen (asynchron) ───────────────────────────────────────

@app.route("/api/train", methods=["POST"])
def train():
    global _training_status
    if _training_status["running"]:
        return jsonify({"error": "Training läuft bereits"}), 409

    data    = request.get_json() or {}
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


# ── API: Wetten ───────────────────────────────────────────────────────────────

@app.route("/api/bets", methods=["GET"])
@handle_errors
def get_bets():
    status = request.args.get("status")
    limit = request.args.get("limit", 100, type=int)
    bets = bet_tracker.get_all_bets(limit=limit, status=status)
    return jsonify([{
        "id": b.id, "home_team": b.home_team, "away_team": b.away_team,
        "bet_on": b.bet_on, "bet_side": b.bet_side,
        "odds": b.odds, "stake": b.stake,
        "ml_prob": round(b.ml_prob, 3), "odds_prob": round(b.odds_prob, 3),
        "edge": round(b.edge, 4), "ev": round(b.ev, 4),
        "bet_rating": b.bet_rating, "status": b.status,
        "actual_winner": b.actual_winner,
        "home_score": b.home_score, "away_score": b.away_score,
        "payout": round(b.payout, 2), "profit": round(b.profit, 2),
        "placed_at": b.placed_at, "resolved_at": b.resolved_at,
        "model_version": b.model_version,
    } for b in bets])


@app.route("/api/bets", methods=["POST"])
@handle_errors
def place_bet():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON-Body fehlt"}), 400
    required = ["home_team", "away_team", "bet_on", "bet_side", "odds",
                "ml_prob", "odds_prob", "edge", "ev"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Felder fehlen: {', '.join(missing)}"}), 400
    bet = bet_tracker.place_bet(
        home_team=data["home_team"], away_team=data["away_team"],
        bet_on=data["bet_on"], bet_side=data["bet_side"],
        odds=float(data["odds"]), ml_prob=float(data["ml_prob"]),
        odds_prob=float(data["odds_prob"]), edge=float(data["edge"]),
        ev=float(data["ev"]), bet_rating=data.get("bet_rating", "none"),
        stake=float(data.get("stake", 10.0)),
        model_version=data.get("model_version"),
    )
    return jsonify({"success": True, "bet_id": bet.id})


@app.route("/api/bets/<int:bet_id>", methods=["DELETE"])
def delete_bet(bet_id: int):
    if not bet_tracker.delete_bet(bet_id):
        return jsonify({"error": "Nicht gefunden"}), 404
    return jsonify({"success": True})


@app.route("/api/bets/stats")
def bet_stats():
    return jsonify(bet_tracker.get_stats().to_dict())


@app.route("/api/bets/history")
def bet_history():
    return jsonify(bet_tracker.get_profit_history())


@app.route("/api/bets/resolve", methods=["POST"])
def resolve_bets():
    return jsonify(bet_resolver.resolve_all_open())


@app.route("/api/bets/reset", methods=["POST"])
def reset_bets():
    return jsonify({"success": True, "deleted": bet_tracker.reset()})


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  🏀 NBA Tracker Web-Server")
    print("  http://localhost:5000")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", debug=False, port=5000, threaded=True)
