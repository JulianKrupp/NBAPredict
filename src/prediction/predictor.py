"""
Spielvorhersage-Modul für den NBA Tracker.
Nutzt ein gewichtetes Scoring-Modell auf Basis von Team-Statistiken und Wettquoten.
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
    """Enthält das vollständige Ergebnis einer Spielvorhersage."""

    predicted_winner: str          # 'home' oder 'away'
    win_probability: float         # 0.0–1.0 für den vorhergesagten Sieger
    predicted_home_score: float
    predicted_away_score: float
    factors: dict[str, float] = field(default_factory=dict)
    odds_home: float | None = None
    odds_away: float | None = None

    @property
    def confidence_label(self) -> str:
        """Gibt eine lesbare Einschätzung der Vorhersagesicherheit zurück."""
        if self.win_probability >= 0.75:
            return "Sehr sicher"
        if self.win_probability >= 0.60:
            return "Sicher"
        if self.win_probability >= 0.52:
            return "Leicht bevorzugt"
        return "Unentschieden / Knapp"


# Gewichtung der einzelnen Vorhersagefaktoren (Summe = 1.0)
FACTOR_WEIGHTS: dict[str, float] = {
    "Win-Rate":            0.25,
    "Punkt-Differenz":     0.20,
    "Heimvorteil":         0.15,
    "Aktuelle Form":       0.15,
    "Wettquoten":          0.15,
    "Offensiv-Stärke":     0.10,
}

# Heimvorteil-Bonus (NBA-Durchschnitt ~60 % Heimsiege)
HOME_ADVANTAGE_BONUS = 0.05

# Durchschnittliche NBA-Punktzahl pro Team
NBA_AVG_POINTS = 113.0


class GamePredictor:
    """
    Berechnet Spielvorhersagen anhand eines gewichteten Scoring-Modells.

    Das Modell kombiniert historische Team-Statistiken mit
    optionalen Wettquoten zu einer Gesamtwahrscheinlichkeit.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def predict(
        self,
        home_team: "Team",
        away_team: "Team",
        odds: "GameOdds | None" = None,
    ) -> PredictionResult:
        """
        Berechnet die Vorhersage für ein Spiel.

        Args:
            home_team: Statistiken des Heimteams.
            away_team: Statistiken des Auswärtsteams.
            odds:      Optionale Wettquoten.

        Returns:
            PredictionResult mit Sieger, Wahrscheinlichkeit und Faktoren.
        """
        self.logger.info(
            "Berechne Vorhersage: %s (Heim) vs %s (Auswärts)",
            home_team.name,
            away_team.name,
        )

        factor_scores = self._calculate_factor_scores(home_team, away_team, odds)
        home_raw_score = self._compute_weighted_score(factor_scores)
        home_probability = self._normalize_to_probability(home_raw_score)

        predicted_home_score, predicted_away_score = self._estimate_scores(
            home_team, away_team, home_probability
        )

        winner = "home" if home_probability >= 0.5 else "away"
        win_probability = home_probability if winner == "home" else 1.0 - home_probability

        return PredictionResult(
            predicted_winner=winner,
            win_probability=win_probability,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            factors=factor_scores,
            odds_home=odds.odds_home if odds else None,
            odds_away=odds.odds_away if odds else None,
        )

    # ── Private Berechnungsmethoden ───────────────────────────────────────

    def _calculate_factor_scores(
        self,
        home: "Team",
        away: "Team",
        odds: "GameOdds | None",
    ) -> dict[str, float]:
        """
        Berechnet die normierten Faktorwerte (0.0–1.0) für das Heimteam.

        Ein Wert > 0.5 bedeutet Vorteil für das Heimteam.

        Args:
            home: Heimteam-Statistiken.
            away: Auswärtsteam-Statistiken.
            odds: Optionale Wettquoten.

        Returns:
            Dictionary der Faktornamen → Faktorwerte.
        """
        factors: dict[str, float] = {}

        # 1. Win-Rate-Vergleich
        factors["Win-Rate"] = self._compare_stats(home.win_rate, away.win_rate)

        # 2. Punkt-Differenz-Vergleich
        factors["Punkt-Differenz"] = self._compare_stats(
            home.point_differential, away.point_differential, scale=20.0
        )

        # 3. Heimvorteil
        home_rate = home.home_win_rate if home.home_win_rate > 0 else home.win_rate
        away_rate = away.away_win_rate if away.away_win_rate > 0 else away.win_rate
        factors["Heimvorteil"] = self._compare_stats(home_rate, away_rate) + HOME_ADVANTAGE_BONUS

        # 4. Aktuelle Form (approximiert durch Win-Rate + Punkt-Differenz)
        home_form = (home.win_rate + max(0.0, home.point_differential / 20.0)) / 2.0
        away_form = (away.win_rate + max(0.0, away.point_differential / 20.0)) / 2.0
        factors["Aktuelle Form"] = self._compare_stats(home_form, away_form)

        # 5. Wettquoten (invertiert: niedrigere Quote = Favorit)
        if odds is not None:
            factors["Wettquoten"] = odds.implied_home_probability / (
                odds.implied_home_probability + odds.implied_away_probability
            )
        else:
            # Neutraler Wert, wenn keine Quoten vorhanden
            factors["Wettquoten"] = 0.5

        # 6. Offensiv-Stärke
        factors["Offensiv-Stärke"] = self._compare_stats(
            home.avg_points_scored,
            away.avg_points_scored,
            scale=20.0,
            center=NBA_AVG_POINTS,
        )

        # Alle Werte auf [0.0, 1.0] begrenzen
        return {k: max(0.0, min(1.0, v)) for k, v in factors.items()}

    def _compute_weighted_score(self, factors: dict[str, float]) -> float:
        """
        Berechnet den gewichteten Gesamtscore des Heimteams.

        Args:
            factors: Faktorwerte als Dictionary.

        Returns:
            Gewichteter Score (0.0–1.0+).
        """
        total = 0.0
        for factor_name, weight in FACTOR_WEIGHTS.items():
            factor_value = factors.get(factor_name, 0.5)
            total += factor_value * weight
        return total

    def _normalize_to_probability(self, raw_score: float) -> float:
        """
        Konvertiert den Rohscore in eine Wahrscheinlichkeit (0.0–1.0).

        Nutzt eine lineare Normierung um 0.5 mit einer Dämpfung
        (Extreme Werte werden etwas abgeschwächt).

        Args:
            raw_score: Gewichteter Score des Heimteams.

        Returns:
            Wahrscheinlichkeit für einen Heimsieg.
        """
        # Dämpfungsfaktor, damit Vorhersagen realistisch bleiben (max ~85 %)
        dampening = 0.80
        deviation = (raw_score - 0.5) * dampening
        return max(0.10, min(0.90, 0.5 + deviation))

    def _estimate_scores(
        self,
        home: "Team",
        away: "Team",
        home_win_probability: float,
    ) -> tuple[float, float]:
        """
        Schätzt das Spielergebnis aus Team-Statistiken und Siegwahrscheinlichkeit.

        Formel (basketballanalytisch korrekt):
          Basis-Erwartungswert = Mittelwert aus eigener Offense und gegnerischer Defense.

            home_base = (home.avg_pts_scored + away.avg_pts_allowed) / 2
            away_base = (away.avg_pts_scored + home.avg_pts_allowed) / 2

          Beispiel OKC (114 Off, 106 Def) vs Denver (119 Off, 118 Def):
            home_base = (114 + 118) / 2 = 116.0
            away_base = (119 + 106) / 2 = 112.5

          Dann Wahrscheinlichkeits-Aufschlag: edge = prob - 0.5 × Faktor 14
          Bei 88% Wahrscheinlichkeit: edge = 0.38 × 14 = +5.3 Pkt Aufschlag
            home = 116.0 + 2.65 = 118.7  →  OKC mehr Punkte ✓
            away = 112.5 - 2.65 = 109.8  →  Denver weniger   ✓

          Der Aufschlag ist absichtlich klein gehalten (Faktor 14), weil
          basketball-statistisch auch klare Favoriten selten mehr als 15 Pkt
          Vorsprung haben. Realwerte NBA 2024/25: Ø Siegmarge ~10 Pkt.

        Args:
            home:                  Heimteam-Statistiken.
            away:                  Auswärtsteam-Statistiken.
            home_win_probability:  Siegwahrscheinlichkeit des Heimteams (0.0–1.0).

        Returns:
            Tupel (home_score, away_score), Sieger hat garantiert mehr Punkte.
        """
        home_off = home.avg_points_scored  if home.avg_points_scored  > 0 else NBA_AVG_POINTS
        home_def = home.avg_points_allowed if home.avg_points_allowed > 0 else NBA_AVG_POINTS
        away_off = away.avg_points_scored  if away.avg_points_scored  > 0 else NBA_AVG_POINTS
        away_def = away.avg_points_allowed if away.avg_points_allowed > 0 else NBA_AVG_POINTS

        # Basis: eigene Offense trifft auf gegnerische Defense
        home_base = (home_off + away_def) / 2.0
        away_base = (away_off + home_def) / 2.0

        # Wahrscheinlichkeits-Aufschlag: bei 50/50 → 0 Pkt, bei 65% → ±1.9 Pkt
        # Faktor 25: Basis-Differenz trägt den Großteil, Prob feintunet
        edge = (home_win_probability - 0.5) * 25.0
        predicted_home = home_base + (edge / 2.0)
        predicted_away = away_base - (edge / 2.0)

        # Sicherheitsnetz: Sieger hat immer mehr Punkte
        # (greift nur wenn Basis-Werte extrem ungleich und Prob knapp bei 50%)
        if home_win_probability >= 0.5 and predicted_home <= predicted_away:
            predicted_home = predicted_away + 1.0
        elif home_win_probability < 0.5 and predicted_away <= predicted_home:
            predicted_away = predicted_home + 1.0

        return round(max(85.0, predicted_home), 1), round(max(85.0, predicted_away), 1)

    @staticmethod
    def _compare_stats(
        home_value: float,
        away_value: float,
        scale: float = 1.0,
        center: float = 0.0,
    ) -> float:
        """
        Normiert zwei Statistiken zu einem Wert zwischen 0.0 und 1.0.

        Ein Ergebnis von 0.5 bedeutet Gleichstand.

        Args:
            home_value: Wert des Heimteams.
            away_value: Wert des Auswärtsteams.
            scale:      Skalierungsfaktor für die Differenz.
            center:     Mittelpunkt für absolute Werte (z.B. NBA-Durchschnitt).

        Returns:
            Normierter Vergleichswert (0.0–1.0).
        """
        if scale == 1.0 and center == 0.0:
            # Direkte Wahrscheinlichkeiten (z.B. Win-Rate)
            total = home_value + away_value
            if total == 0:
                return 0.5
            return home_value / total

        # Skalierte Differenz
        normalized_home = (home_value - center) / scale
        normalized_away = (away_value - center) / scale
        diff = normalized_home - normalized_away
        return max(0.0, min(1.0, 0.5 + diff * 0.5))
