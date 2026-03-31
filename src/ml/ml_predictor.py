"""
ML-basierter Spielvorhersager (v4).

Nutzt das trainierte Modell für Wahrscheinlichkeitsvorhersagen
und kombiniert dessen Ergebnis mit dem regelbasierten Predictor.

v4: odds_implied_home_prob aus Feature-Vektor entfernt (45 statt 46 Features).
    Elo-Rating weiterhin als Feature.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.models.team import Team
from src.api.odds_api_client import GameOdds
from src.api.nba_stats_client import NBAStatsApiClient, AdvancedTeamStats
from src.ml.data_collector import TrainingSample
from src.ml.elo import calculate_elo_ratings
from src.ml.model_trainer import NBAModelTrainer, MODEL_PATH
from src.prediction.predictor import GamePredictor, PredictionResult
from src.utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class MLPredictionResult:
    """Erweitertes Vorhersageergebnis mit KI- und regelbasiertem Vergleich."""
    ml_home_win_probability: float
    ml_predicted_winner: str
    ml_confidence: str

    rule_home_win_probability: float
    rule_predicted_winner: str

    odds_home_win_probability: float | None
    odds_predicted_winner: str | None

    home_team: str
    away_team: str
    predicted_home_score: float
    predicted_away_score: float
    feature_contributions: dict[str, float]

    consensus_winner: str
    consensus_agreement_count: int

    @property
    def all_agree(self) -> bool:
        return self.consensus_agreement_count >= 2

    def probability_for_team(self, team_type: str) -> float:
        if team_type == "home":
            return self.ml_home_win_probability
        return 1.0 - self.ml_home_win_probability


class MLPredictor:
    """Kombiniert ML-Modell, Regelmodell und Wettquoten."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.stats_client = NBAStatsApiClient(config)
        self.rule_predictor = GamePredictor()
        self.trainer = NBAModelTrainer()
        self._model: Any | None = None
        self._elo_cache: dict[str, float] | None = None
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def predict(
        self,
        home_team: Team,
        away_team: Team,
        odds: GameOdds | None = None,
    ) -> MLPredictionResult:
        """Erstellt eine vollständige ML-gestützte Vorhersage."""
        # Advanced Stats laden
        home_adv = self._get_advanced_stats(home_team)
        away_adv = self._get_advanced_stats(away_team)

        # KI-Vorhersage
        ml_home_prob = self._ml_predict(home_team, away_team, home_adv, away_adv, odds)
        ml_winner = "home" if ml_home_prob >= 0.5 else "away"
        ml_confidence = self._confidence_label(
            ml_home_prob if ml_winner == "home" else 1.0 - ml_home_prob
        )

        # Regelbasierte Vorhersage
        rule_result: PredictionResult = self.rule_predictor.predict(home_team, away_team, odds)
        rule_winner = rule_result.predicted_winner
        rule_home_prob = (
            rule_result.win_probability
            if rule_winner == "home"
            else 1.0 - rule_result.win_probability
        )

        # Wettquoten-Wahrscheinlichkeit
        odds_home_prob: float | None = None
        odds_winner: str | None = None
        if odds is not None:
            total = odds.implied_home_probability + odds.implied_away_probability
            if total > 0:
                odds_home_prob = odds.implied_home_probability / total
                odds_winner = "home" if odds_home_prob >= 0.5 else "away"

        # Konsens berechnen
        winners = [ml_winner, rule_winner]
        if odds_winner:
            winners.append(odds_winner)
        consensus = max(set(winners), key=winners.count)
        agreement_count = winners.count(consensus)

        return MLPredictionResult(
            ml_home_win_probability=ml_home_prob,
            ml_predicted_winner=ml_winner,
            ml_confidence=ml_confidence,
            rule_home_win_probability=rule_home_prob,
            rule_predicted_winner=rule_winner,
            odds_home_win_probability=odds_home_prob,
            odds_predicted_winner=odds_winner,
            home_team=home_team.name,
            away_team=away_team.name,
            predicted_home_score=rule_result.predicted_home_score,
            predicted_away_score=rule_result.predicted_away_score,
            feature_contributions=rule_result.factors,
            consensus_winner=consensus,
            consensus_agreement_count=agreement_count,
        )

    def is_model_available(self) -> bool:
        return MODEL_PATH.exists()

    def get_model_metrics(self) -> dict | None:
        return self.trainer.load_metrics()

    # ── Private Methoden ─────────────────────────────────────────────────

    def _load_model(self) -> Any | None:
        if self._model is None and MODEL_PATH.exists():
            try:
                self._model = self.trainer.load_model()
                self.logger.info("ML-Modell geladen: %s", MODEL_PATH)
            except Exception as exc:
                self.logger.warning("ML-Modell konnte nicht geladen werden: %s", exc)
        return self._model

    def _ml_predict(
        self,
        home_team: Team, away_team: Team,
        home_adv: AdvancedTeamStats, away_adv: AdvancedTeamStats,
        odds: GameOdds | None,
    ) -> float:
        """ML-Vorhersage. Fällt auf Regelmodell zurück wenn kein Modell da."""
        model = self._load_model()

        if model is None:
            self.logger.info("Kein ML-Modell – nutze regelbasierte Vorhersage.")
            rule = self.rule_predictor.predict(home_team, away_team, odds)
            return (
                rule.win_probability
                if rule.predicted_winner == "home"
                else 1.0 - rule.win_probability
            )

        feature_vector = self._build_feature_vector(
            home_team, away_team, home_adv, away_adv, odds,
        )

        try:
            X = np.array([feature_vector], dtype=float)
            prob = model.predict_proba(X)[0][1]
            return float(np.clip(prob, 0.05, 0.95))
        except Exception as exc:
            self.logger.error("ML-Vorhersagefehler: %s", exc)
            rule = self.rule_predictor.predict(home_team, away_team, odds)
            return (
                rule.win_probability
                if rule.predicted_winner == "home"
                else 1.0 - rule.win_probability
            )

    def _build_feature_vector(
        self,
        home: Team, away: Team,
        home_adv: AdvancedTeamStats, away_adv: AdvancedTeamStats,
        odds: GameOdds | None,
    ) -> list[float]:
        """
        Erstellt den Feature-Vektor für das ML-Modell (45 Features).

        v4: odds_implied_home_prob ENTFERNT – war im Training immer 0.5,
        daher lernte das Modell nichts daraus. Bei Predict-Time kamen dann
        echte Quoten rein → Train/Predict-Mismatch.

        WICHTIG: Die Reihenfolge MUSS exakt mit
        TrainingSample.get_feature_columns() übereinstimmen!
        """
        home_elo = self._get_team_elo(home.name)
        away_elo = self._get_team_elo(away.name)

        return [
            # ── Heimteam (18 Features) ───────────────────────────────
            home.win_rate,
            home.point_differential,
            home.avg_points_scored,
            home.avg_points_allowed,
            home.home_win_rate,
            home.away_win_rate,
            home_adv.offensive_rating,
            home_adv.defensive_rating,
            home_adv.net_rating,
            home_adv.pace,
            home_adv.true_shooting_pct,
            home_adv.last_5_win_rate,
            home_adv.last_10_win_rate,
            home_adv.days_since_last_game,
            home.current_streak,
            home.fatigue_score,
            home.form_rating,
            home.games_last_7_days,

            # ── Auswärtsteam (18 Features) ───────────────────────────
            away.win_rate,
            away.point_differential,
            away.avg_points_scored,
            away.avg_points_allowed,
            away.home_win_rate,
            away.away_win_rate,
            away_adv.offensive_rating,
            away_adv.defensive_rating,
            away_adv.net_rating,
            away_adv.pace,
            away_adv.true_shooting_pct,
            away_adv.last_5_win_rate,
            away_adv.last_10_win_rate,
            away_adv.days_since_last_game,
            away.current_streak,
            away.fatigue_score,
            away.form_rating,
            away.games_last_7_days,

            # ── Differenz-Features (6 Features) ──────────────────────
            home.win_rate - away.win_rate,
            home.point_differential - away.point_differential,
            home_adv.net_rating - away_adv.net_rating,
            home_adv.last_5_win_rate - away_adv.last_5_win_rate,
            home.current_streak - away.current_streak,
            home.fatigue_score - away.fatigue_score,

            # ── Elo-Features (3 Features) ────────────────────────────
            home_elo,
            away_elo,
            home_elo - away_elo,

            # v4: KEIN odds_implied_home_prob mehr!
        ]

    def _get_team_elo(self, team_name: str) -> float:
        """Gibt das aktuelle Elo-Rating eines Teams zurück."""
        if self._elo_cache is None:
            self._elo_cache = self._compute_current_elo()
        return self._elo_cache.get(team_name, 1500.0)

    def _compute_current_elo(self) -> dict[str, float]:
        """Berechnet Elo-Ratings aus den aktuellen Saisonspielen."""
        try:
            from src.api.nba_api_client import NBAApiClient
            from datetime import date
            nba = NBAApiClient(self.config)
            today = date.today()
            season = today.year - 1 if today.month < 10 else today.year
            games = nba._fetch_season_games_paginated(season, max_games=1300)
            return calculate_elo_ratings(games)
        except Exception as exc:
            self.logger.warning("Elo-Berechnung fehlgeschlagen: %s", exc)
            return {}

    def _get_advanced_stats(self, team: Team) -> AdvancedTeamStats:
        """Baut AdvancedTeamStats aus Team-Basisdaten."""
        return self.stats_client.build_advanced_stats_from_basic(
            team_id=team.team_id,
            team_name=team.name,
            wins=team.wins,
            losses=team.losses,
            avg_pts_scored=team.avg_points_scored,
            avg_pts_allowed=team.avg_points_allowed,
            recent_game_results=team.recent_game_results if team.has_recent_form_data else None,
        )

    def _get_feature_contributions(self) -> dict[str, float]:
        """Extrahiert Feature-Importances aus dem geladenen Modell."""
        model = self._load_model()
        if model is None:
            return {}
        try:
            features = TrainingSample.get_feature_columns()
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
            elif hasattr(model, "named_steps"):
                clf = model.named_steps.get("clf")
                if hasattr(clf, "coef_"):
                    imp = np.abs(clf.coef_[0])
                else:
                    return {}
            else:
                return {}
            indices = np.argsort(imp)[::-1][:5]
            return {features[i]: round(float(imp[i]), 4) for i in indices}
        except Exception:
            return {}

    @staticmethod
    def _confidence_label(prob: float) -> str:
        if prob >= 0.75:
            return "Sehr sicher"
        if prob >= 0.60:
            return "Sicher"
        if prob >= 0.52:
            return "Leicht bevorzugt"
        return "Knapp"

    @staticmethod
    def _compute_consensus(
        ml_winner: str, rule_winner: str, odds_winner: str | None,
    ) -> tuple[str, int]:
        winners = [ml_winner, rule_winner]
        if odds_winner:
            winners.append(odds_winner)
        consensus = max(set(winners), key=winners.count)
        return consensus, winners.count(consensus)
