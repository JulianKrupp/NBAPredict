"""
ML-basierter Spielvorhersager.

Lädt das aktuell aktive Modell (siehe active_model.json) und liefert
Wahrscheinlichkeitsvorhersagen. Das aktive Modell wird von MLPipeline
nach jedem Training auf das mit höchstem ROC-AUC gesetzt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from src.api.nba_stats_client import AdvancedTeamStats, NBAStatsApiClient
from src.api.odds_api_client import GameOdds
from src.ml.data_collector import TrainingSample
from src.ml.elo import calculate_elo_ratings
from src.ml.model_trainer import ACTIVE_MODEL_PATH, MODEL_DIR, MODEL_PATH, NBAModelTrainer
from src.models.team import Team
from src.utils.config import Config


@dataclass
class MLPredictionResult:
    """Vorhersageergebnis des ML-Modells."""
    ml_home_win_probability: float
    ml_predicted_winner: str
    ml_confidence: str

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


class MLPredictor:
    """
    Vorhersagen über das aktuell aktive ML-Modell.

    Das Modell wird beim ersten Aufruf geladen und gecacht.
    Wird active_model.json zwischenzeitlich geändert (z.B. nach einem
    Pipeline-Lauf), invalidiert _load_model() den Cache automatisch.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.stats_client = NBAStatsApiClient(config)
        self.trainer = NBAModelTrainer()
        self._model: Any | None = None
        self._loaded_model_path: Path | None = None   # für Cache-Invalidierung
        self._elo_cache: dict[str, float] | None = None
        self._adv_stats_cache: dict[str, AdvancedTeamStats] | None = None
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def predict(
        self,
        home_team: Team,
        away_team: Team,
        odds: GameOdds | None = None,
    ) -> MLPredictionResult:
        """Erstellt eine ML-gestützte Vorhersage."""
        home_adv = self._get_advanced_stats(home_team)
        away_adv = self._get_advanced_stats(away_team)

        ml_home_prob = self._ml_predict(home_team, away_team, home_adv, away_adv)
        ml_winner = "home" if ml_home_prob >= 0.5 else "away"
        ml_confidence = self._confidence_label(
            ml_home_prob if ml_winner == "home" else 1.0 - ml_home_prob
        )

        # Wettquoten-Wahrscheinlichkeit
        odds_home_prob: float | None = None
        odds_winner: str | None = None
        if odds is not None:
            total = odds.implied_home_probability + odds.implied_away_probability
            if total > 0:
                odds_home_prob = odds.implied_home_probability / total
                odds_winner = "home" if odds_home_prob >= 0.5 else "away"

        # Konsens ML vs Odds
        winners = [ml_winner]
        if odds_winner:
            winners.append(odds_winner)
        consensus = max(set(winners), key=winners.count)
        agreement_count = winners.count(consensus)

        # Geschätzte Scores aus Team-Durchschnitt
        predicted_home_score = (home_team.avg_points_scored + away_team.avg_points_allowed) / 2
        predicted_away_score = (away_team.avg_points_scored + home_team.avg_points_allowed) / 2

        return MLPredictionResult(
            ml_home_win_probability=ml_home_prob,
            ml_predicted_winner=ml_winner,
            ml_confidence=ml_confidence,
            odds_home_win_probability=odds_home_prob,
            odds_predicted_winner=odds_winner,
            home_team=home_team.name,
            away_team=away_team.name,
            predicted_home_score=round(predicted_home_score, 1),
            predicted_away_score=round(predicted_away_score, 1),
            feature_contributions=self._get_feature_contributions(),
            consensus_winner=consensus,
            consensus_agreement_count=agreement_count,
        )

    def is_model_available(self) -> bool:
        return self._get_active_model_path() is not None

    def get_model_metrics(self) -> dict | None:
        return self.trainer.load_metrics()

    def get_active_model_info(self) -> dict | None:
        return self.trainer.get_active_model_info()

    # ── Private Methoden ─────────────────────────────────────────────────

    def _get_active_model_path(self) -> Path | None:
        """Gibt den Pfad des aktiv konfigurierten Modells zurück."""
        if ACTIVE_MODEL_PATH.exists():
            with open(ACTIVE_MODEL_PATH, encoding="utf-8") as f:
                model_id = json.load(f).get("model_id", "logistic_regression")
            path = MODEL_DIR / f"{model_id}.joblib"
            if path.exists():
                return path
        # Legacy-Fallback
        return MODEL_PATH if MODEL_PATH.exists() else None

    def _load_model(self) -> Any | None:
        """
        Lädt das aktive Modell. Invalidiert den Cache wenn active_model.json
        auf ein anderes Modell zeigt (z.B. nach einem Pipeline-Lauf).
        """
        current_path = self._get_active_model_path()
        if current_path is None:
            return None

        # Cache-Invalidierung: Pfad geändert → neu laden
        if current_path != self._loaded_model_path:
            self._model = None
            self._loaded_model_path = current_path

        if self._model is None:
            try:
                self._model = joblib.load(current_path)
                self.logger.info("ML-Modell geladen: %s", current_path)
            except Exception as exc:
                self.logger.warning("ML-Modell konnte nicht geladen werden: %s", exc)

        return self._model

    def _ml_predict(
        self,
        home_team: Team, away_team: Team,
        home_adv: AdvancedTeamStats, away_adv: AdvancedTeamStats,
    ) -> float:
        """ML-Vorhersage. Wirft RuntimeError wenn kein Modell geladen werden kann."""
        model = self._load_model()

        if model is None:
            raise RuntimeError(
                "Kein ML-Modell vorhanden.\n"
                "Erst 'python main.py train all' ausführen."
            )

        feature_vector = self._build_feature_vector(
            home_team, away_team, home_adv, away_adv,
        )

        X = np.array([feature_vector], dtype=float)
        prob = model.predict_proba(X)[0][1]
        return float(np.clip(prob, 0.05, 0.95))

    def _build_feature_vector(
        self,
        home: Team, away: Team,
        home_adv: AdvancedTeamStats, away_adv: AdvancedTeamStats,
    ) -> list[float]:
        """
        Erstellt den Feature-Vektor für das ML-Modell (45 Features).
        Reihenfolge MUSS exakt mit TrainingSample.get_feature_columns() übereinstimmen!
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
            home.last_5_win_rate,
            home.last_10_win_rate,
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
            away.last_5_win_rate,
            away.last_10_win_rate,
            away_adv.days_since_last_game,
            away.current_streak,
            away.fatigue_score,
            away.form_rating,
            away.games_last_7_days,

            # ── Differenz-Features (6 Features) ──────────────────────
            home.win_rate - away.win_rate,
            home.point_differential - away.point_differential,
            home_adv.net_rating - away_adv.net_rating,
            home.last_5_win_rate - away.last_5_win_rate,
            home.current_streak - away.current_streak,
            home.fatigue_score - away.fatigue_score,

            # ── Elo-Features (3 Features) ────────────────────────────
            home_elo,
            away_elo,
            home_elo - away_elo,
        ]

    def _get_team_elo(self, team_name: str) -> float:
        if self._elo_cache is None:
            self._elo_cache = self._compute_current_elo()
        return self._elo_cache.get(team_name, 1500.0)

    def _compute_current_elo(self) -> dict[str, float]:
        try:
            from datetime import date

            from src.api.nba_api_client import NBAApiClient
            nba = NBAApiClient(self.config)
            today = date.today()
            season = today.year - 1 if today.month < 10 else today.year
            games = nba._fetch_season_games_paginated(season, max_games=1300)
            return calculate_elo_ratings(games)
        except Exception as exc:
            self.logger.warning("Elo-Berechnung fehlgeschlagen: %s", exc)
            return {}

    def _get_advanced_stats(self, team: Team) -> AdvancedTeamStats:
        if self._adv_stats_cache is None:
            self._adv_stats_cache = self._load_advanced_stats()
        adv = self._adv_stats_cache.get(team.name)
        if adv is None:
            # Fuzzy-Match: Substring-Suche
            name_lower = team.name.lower()
            for key, val in self._adv_stats_cache.items():
                if name_lower in key.lower() or key.lower() in name_lower:
                    adv = val
                    break
        if adv is None:
            raise RuntimeError(
                f"Advanced Stats für Team '{team.name}' nicht verfügbar.\n"
                "Stelle sicher dass nba_api installiert ist: pip install nba_api\n"
                "und stats.nba.com erreichbar ist."
            )
        adv.days_since_last_game = team.days_rest
        return adv

    def _load_advanced_stats(self) -> dict[str, AdvancedTeamStats]:
        from datetime import date
        today = date.today()
        season = today.year - 1 if today.month < 10 else today.year
        stats = self.stats_client.get_all_team_advanced_stats(season)
        if not stats:
            raise RuntimeError(
                "Echte Advanced Stats nicht verfügbar.\n"
                "Stelle sicher dass nba_api installiert ist: pip install nba_api\n"
                "und stats.nba.com erreichbar ist."
            )
        return stats

    def _get_feature_contributions(self) -> dict[str, float]:
        """Extrahiert Top-Feature-Importances aus dem Modell."""
        model = self._load_model()
        if model is None:
            return {}
        try:
            features = TrainingSample.get_feature_columns()
            clf = model.named_steps.get("clf") if hasattr(model, "named_steps") else model
            if hasattr(clf, "coef_"):
                imp = np.abs(clf.coef_[0])
            elif hasattr(clf, "feature_importances_"):
                imp = clf.feature_importances_
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
