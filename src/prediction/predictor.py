"""
Regelbasiertes Vorhersagemodell.

Gewichteter Score aus sechs Faktoren. Dient als Baseline und als
Fallback, wenn kein trainiertes ML-Modell vorhanden ist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.team import Team
    from src.api.odds_api_client import GameOdds


@dataclass
class PredictionResult:
    predicted_winner: str       # 'home' oder 'away'
    win_probability: float      # Wahrscheinlichkeit für den vorhergesagten Sieger
    predicted_home_score: float
    predicted_away_score: float
    factors: dict[str, float] = field(default_factory=dict)
    odds_home: float | None = None
    odds_away: float | None = None

    @property
    def confidence_label(self) -> str:
        if self.win_probability >= 0.75:
            return "Sehr sicher"
        if self.win_probability >= 0.60:
            return "Sicher"
        if self.win_probability >= 0.52:
            return "Leicht bevorzugt"
        return "Unentschieden / Knapp"


# Gewichte summieren sich auf 1.0.
# Aktuelle Form hat dasselbe Gewicht wie Heimvorteil und Quoten – bewusst
# nicht höher angesetzt, da der NBA-Saisonschnitt träger reagiert als z.B.
# Fußball und kurzfristige Streaks stark schwanken können.
FACTOR_WEIGHTS: dict[str, float] = {
    "Win-Rate":         0.25,
    "Punkt-Differenz":  0.20,
    "Heimvorteil":      0.15,
    "Aktuelle Form":    0.15,
    "Wettquoten":       0.15,
    "Offensiv-Stärke":  0.10,
}

HOME_ADVANTAGE_BONUS = 0.05   # NBA-Heimteams gewinnen ~60 % ihrer Spiele
NBA_AVG_POINTS = 113.0


class GamePredictor:

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def predict(
        self,
        home_team: "Team",
        away_team: "Team",
        odds: "GameOdds | None" = None,
    ) -> PredictionResult:
        self.logger.info("Vorhersage: %s vs %s", home_team.name, away_team.name)

        home_src = "echt" if home_team.has_recent_form_data else "geschätzt"
        away_src = "echt" if away_team.has_recent_form_data else "geschätzt"
        self.logger.debug(
            "Formdaten – Heim: %d Spiele (%s), Auswärts: %d Spiele (%s)",
            len(home_team.recent_game_results), home_src,
            len(away_team.recent_game_results), away_src,
        )

        factor_scores = self._calculate_factor_scores(home_team, away_team, odds)
        home_raw = self._compute_weighted_score(factor_scores)
        home_prob = self._normalize_to_probability(home_raw)

        home_score, away_score = self._estimate_scores(home_team, away_team, home_prob)
        winner = "home" if home_prob >= 0.5 else "away"
        win_prob = home_prob if winner == "home" else 1.0 - home_prob

        return PredictionResult(
            predicted_winner=winner,
            win_probability=win_prob,
            predicted_home_score=home_score,
            predicted_away_score=away_score,
            factors=factor_scores,
            odds_home=odds.odds_home if odds else None,
            odds_away=odds.odds_away if odds else None,
        )

    def _calculate_factor_scores(
        self,
        home: "Team",
        away: "Team",
        odds: "GameOdds | None",
    ) -> dict[str, float]:
        """
        Normiert alle Faktoren auf [0.0, 1.0].
        Werte > 0.5 bedeuten Vorteil für das Heimteam.
        """
        factors: dict[str, float] = {}

        factors["Win-Rate"] = self._compare_stats(home.win_rate, away.win_rate)

        factors["Punkt-Differenz"] = self._compare_stats(
            home.point_differential, away.point_differential, scale=20.0
        )

        home_rate = home.home_win_rate if home.home_win_rate > 0 else home.win_rate
        away_rate = away.away_win_rate if away.away_win_rate > 0 else away.win_rate
        factors["Heimvorteil"] = self._compare_stats(home_rate, away_rate) + HOME_ADVANTAGE_BONUS

        factors["Aktuelle Form"] = self._compare_stats(
            self._compute_form(home),
            self._compute_form(away),
        )

        if odds is not None:
            total = odds.implied_home_probability + odds.implied_away_probability
            factors["Wettquoten"] = odds.implied_home_probability / total
        else:
            factors["Wettquoten"] = 0.5

        factors["Offensiv-Stärke"] = self._compare_stats(
            home.avg_points_scored, away.avg_points_scored,
            scale=20.0, center=NBA_AVG_POINTS,
        )

        return {k: max(0.0, min(1.0, v)) for k, v in factors.items()}

    @staticmethod
    def _compute_form(team: "Team") -> float:
        """
        Gibt die aktuelle Form als Wert zwischen 0 und 1 zurück.

        Wenn recent_game_results gefüllt ist (>= 3 Spiele), wird
        team.form_rating verwendet (60 % last-5, 40 % last-10).
        Andernfalls Näherung über Saisondurchschnitt.
        """
        if team.has_recent_form_data:
            return team.form_rating
        # Fallback: keine aktuellen Spielergebnisse verfügbar
        return (team.win_rate + max(0.0, team.point_differential / 20.0)) / 2.0

    def _compute_weighted_score(self, factors: dict[str, float]) -> float:
        total = 0.0
        for name, weight in FACTOR_WEIGHTS.items():
            total += factors.get(name, 0.5) * weight
        return total

    def _normalize_to_probability(self, raw_score: float) -> float:
        # Dämpfung auf max ~85 %, damit Extremwerte realistisch bleiben
        deviation = (raw_score - 0.5) * 0.80
        return max(0.10, min(0.90, 0.5 + deviation))

    def _estimate_scores(
        self,
        home: "Team",
        away: "Team",
        home_prob: float,
    ) -> tuple[float, float]:
        home_off = home.avg_points_scored  or NBA_AVG_POINTS
        home_def = home.avg_points_allowed or NBA_AVG_POINTS
        away_off = away.avg_points_scored  or NBA_AVG_POINTS
        away_def = away.avg_points_allowed or NBA_AVG_POINTS

        home_base = (home_off + away_def) / 2.0
        away_base = (away_off + home_def) / 2.0

        edge = (home_prob - 0.5) * 25.0
        pred_home = home_base + edge / 2.0
        pred_away = away_base - edge / 2.0

        # Sieger soll immer mehr Punkte haben
        if home_prob >= 0.5 and pred_home <= pred_away:
            pred_home = pred_away + 1.0
        elif home_prob < 0.5 and pred_away <= pred_home:
            pred_away = pred_home + 1.0

        return round(max(85.0, pred_home), 1), round(max(85.0, pred_away), 1)

    @staticmethod
    def _compare_stats(
        home_value: float,
        away_value: float,
        scale: float = 1.0,
        center: float = 0.0,
    ) -> float:
        """Normiert zwei Werte zu einem Heim-Vorteil-Score [0, 1], Mitte = 0.5."""
        if scale == 1.0 and center == 0.0:
            total = home_value + away_value
            return home_value / total if total != 0 else 0.5
        norm_home = (home_value - center) / scale
        norm_away = (away_value - center) / scale
        return max(0.0, min(1.0, 0.5 + (norm_home - norm_away) * 0.5))
