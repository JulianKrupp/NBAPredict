"""
ML-basierter Spielvorhersager.

Nutzt das trainierte Random-Forest-Modell für Wahrscheinlichkeitsvorhersagen
und kombiniert dessen Ergebnis mit dem klassischen regelbasierten Predictor.
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
from src.ml.model_trainer import NBAModelTrainer, MODEL_PATH
from src.prediction.predictor import GamePredictor, PredictionResult
from src.utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class MLPredictionResult:
    """
    Erweitertes Vorhersageergebnis mit KI- und regelbasiertem Vergleich.
    """
    # KI-Vorhersage
    ml_home_win_probability: float
    ml_predicted_winner: str        # 'home' oder 'away'
    ml_confidence: str

    # Regelbasierte Vorhersage (zum Vergleich)
    rule_home_win_probability: float
    rule_predicted_winner: str

    # Wettquoten-Wahrscheinlichkeit (aus The Odds API)
    odds_home_win_probability: float | None
    odds_predicted_winner: str | None

    # Details
    home_team: str
    away_team: str
    predicted_home_score: float
    predicted_away_score: float
    feature_contributions: dict[str, float]

    # Konsens der drei Methoden
    consensus_winner: str
    consensus_agreement_count: int  # Wie viele Methoden einig sind (1-3)

    @property
    def all_agree(self) -> bool:
        """True, wenn KI und Wettquoten (wenn verfügbar) übereinstimmen."""
        return self.consensus_agreement_count >= 2

    def probability_for_team(self, team_type: str) -> float:
        """Gibt die KI-Wahrscheinlichkeit für 'home' oder 'away' zurück."""
        if team_type == "home":
            return self.ml_home_win_probability
        return 1.0 - self.ml_home_win_probability


class MLPredictor:
    """
    Kombiniert ML-Modell, regelbasiertem Predictor und Wettquoten
    zu einer umfassenden Spielvorhersage.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.stats_client = NBAStatsApiClient(config)
        self.rule_predictor = GamePredictor()
        self.trainer = NBAModelTrainer()
        self._model: Any | None = None
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def predict(
        self,
        home_team: Team,
        away_team: Team,
        odds: GameOdds | None = None,
    ) -> MLPredictionResult:
        """
        Erstellt eine vollständige ML-gestützte Vorhersage.

        Args:
            home_team: Heimteam mit Statistiken.
            away_team: Auswärtsteam mit Statistiken.
            odds:      Optionale Wettquoten.

        Returns:
            MLPredictionResult mit KI-, Regel- und Wettquoten-Vergleich.
        """
        # Advanced Stats für beide Teams berechnen
        home_adv = self._get_advanced_stats(home_team)
        away_adv = self._get_advanced_stats(away_team)

        # KI-Vorhersage
        ml_home_prob = self._ml_predict(home_team, away_team, home_adv, away_adv, odds)

        # Regelbasierte Vorhersage
        rule_result: PredictionResult = self.rule_predictor.predict(home_team, away_team, odds)

        # Wettquoten-Wahrscheinlichkeit
        odds_prob: float | None = None
        if odds is not None:
            total = odds.implied_home_probability + odds.implied_away_probability
            odds_prob = odds.implied_home_probability / total if total > 0 else 0.5

        # Konsens berechnen
        ml_winner = "home" if ml_home_prob >= 0.5 else "away"
        rule_winner = rule_result.predicted_winner
        odds_winner = ("home" if odds_prob >= 0.5 else "away") if odds_prob is not None else None

        winners = [ml_winner, rule_winner]
        if odds_winner:
            winners.append(odds_winner)
        consensus = max(set(winners), key=winners.count)
        agreement_count = winners.count(consensus)

        # Score-Schätzung
        predicted_home_score = rule_result.predicted_home_score
        predicted_away_score = rule_result.predicted_away_score

        return MLPredictionResult(
            ml_home_win_probability=ml_home_prob,
            ml_predicted_winner=ml_winner,
            ml_confidence=self._confidence_label(ml_home_prob if ml_winner == "home"
                                                  else 1.0 - ml_home_prob),
            rule_home_win_probability=rule_result.win_probability if rule_winner == "home"
                                       else 1.0 - rule_result.win_probability,
            rule_predicted_winner=rule_winner,
            odds_home_win_probability=odds_prob,
            odds_predicted_winner=odds_winner,
            home_team=home_team.name,
            away_team=away_team.name,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            feature_contributions=rule_result.factors,
            consensus_winner=consensus,
            consensus_agreement_count=agreement_count,
        )

    def is_model_available(self) -> bool:
        """Gibt True zurück, wenn ein trainiertes Modell vorhanden ist."""
        return MODEL_PATH.exists()

    def get_model_metrics(self) -> dict | None:
        """Gibt die gespeicherten Modell-Metriken zurück."""
        return self.trainer.load_metrics()

    # ── Private Methoden ─────────────────────────────────────────────────

    def _load_model(self) -> Any | None:
        """Lädt das ML-Modell (lazy loading)."""
        if self._model is None and MODEL_PATH.exists():
            try:
                self._model = self.trainer.load_model()
                self.logger.info("ML-Modell geladen: %s", MODEL_PATH)
            except Exception as exc:
                self.logger.warning("ML-Modell konnte nicht geladen werden: %s", exc)
        return self._model

    def _ml_predict(
        self,
        home_team: Team,
        away_team: Team,
        home_adv: AdvancedTeamStats,
        away_adv: AdvancedTeamStats,
        odds: GameOdds | None,
    ) -> float:
        """
        Führt die ML-Vorhersage durch.

        Fällt auf regelbasierte Vorhersage zurück, wenn kein Modell vorhanden.

        Returns:
            Siegwahrscheinlichkeit des Heimteams (0.0–1.0).
        """
        model = self._load_model()

        if model is None:
            self.logger.info("Kein ML-Modell – nutze regelbasierte Fallback-Vorhersage.")
            rule_result = self.rule_predictor.predict(home_team, away_team, odds)
            if rule_result.predicted_winner == "home":
                return rule_result.win_probability
            return 1.0 - rule_result.win_probability

        # Feature-Vektor aufbauen
        feature_vector = self._build_feature_vector(
            home_team, away_team, home_adv, away_adv, odds
        )

        try:
            X = np.array([feature_vector], dtype=float)
            prob = model.predict_proba(X)[0][1]  # Wahrscheinlichkeit für Klasse 1 (Heimsieg)
            return float(np.clip(prob, 0.05, 0.95))
        except Exception as exc:
            self.logger.error("ML-Vorhersagefehler: %s", exc)
            rule_result = self.rule_predictor.predict(home_team, away_team, odds)
            if rule_result.predicted_winner == "home":
                return rule_result.win_probability
            return 1.0 - rule_result.win_probability

    def _build_feature_vector(
        self,
        home: Team,
        away: Team,
        home_adv: AdvancedTeamStats,
        away_adv: AdvancedTeamStats,
        odds: GameOdds | None,
    ) -> list[float]:
        """Erstellt den Feature-Vektor für das ML-Modell."""
        odds_prob = 0.5
        if odds is not None:
            total = odds.implied_home_probability + odds.implied_away_probability
            odds_prob = odds.implied_home_probability / total if total > 0 else 0.5

        return [
            # Heimteam
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
            # Auswärtsteam
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
            # Differenz-Features
            home.win_rate - away.win_rate,
            home.point_differential - away.point_differential,
            home_adv.net_rating - away_adv.net_rating,
            home_adv.last_5_win_rate - away_adv.last_5_win_rate,
            # Wettquoten
            odds_prob,
        ]

    def _get_advanced_stats(self, team: Team) -> AdvancedTeamStats:
        """
        Berechnet Advanced Stats für ein Team.

        Versucht zuerst, echte Form-Daten (letzte 10 Spiele) über die
        BallDontLie-API zu laden, damit last_5_win_rate und last_10_win_rate
        die aktuelle Form widerspiegeln – nicht den Saisondurchschnitt.

        Falls der API-Abruf fehlschlägt (Rate-Limit, kein Netz, o.ä.),
        fällt die Form-Berechnung auf die Saison-Win-Rate zurück.
        """
        recent_results: list[bool] = []
        try:
            from src.api.nba_api_client import NBAApiClient
            nba_client = NBAApiClient(self.config)
            recent_games = nba_client.get_recent_games(team.name, num_games=10)
            # True = Sieg des abgefragten Teams
            for game in recent_games:
                if game.home_team == team.name:
                    recent_results.append(game.home_score > game.away_score)
                else:
                    recent_results.append(game.away_score > game.home_score)
        except Exception as exc:
            self.logger.debug(
                "Form-Daten für '%s' nicht verfügbar, nutze Saison-WR: %s",
                team.name, exc,
            )

        return self.stats_client.build_advanced_stats_from_basic(
            team_id=team.team_id,
            team_name=team.name,
            wins=team.wins,
            losses=team.losses,
            avg_pts_scored=team.avg_points_scored,
            avg_pts_allowed=team.avg_points_allowed,
            recent_game_results=recent_results if recent_results else None,
        )

    @staticmethod
    def _confidence_label(probability: float) -> str:
        """Gibt eine lesbare Konfidenzbezeichnung zurück."""
        if probability >= 0.75:
            return "Sehr sicher 🟢"
        if probability >= 0.62:
            return "Sicher 🟡"
        if probability >= 0.54:
            return "Leicht bevorzugt 🟠"
        return "Knapp / Unentschieden 🔴"
