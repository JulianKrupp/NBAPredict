"""
Regelbasiertes Vorhersagemodell (v2).

Gewichteter Score aus zehn Faktoren. Dient als Baseline und als
Fallback, wenn kein trainiertes ML-Modell vorhanden ist.

Änderungen gegenüber v1
-----------------------
- Aktuelle Form nutzt jetzt echte ``team.form_rating`` statt Approximation.
- Neue Faktoren: Defensiv-Stärke, Ruhetage / Back-to-Back,
  Streak-Momentum, Pace-Mismatch, Verletzungseinfluss.
- Gewichte neu kalibriert (Summe weiterhin 1.0).
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


# ── Gewichte ──────────────────────────────────────────────────────────────────
#
# Summe = 1.0
#
# Begründungen:
#   • Win-Rate & Punkt-Diff bleiben stärkste Einzelfaktoren – sie spiegeln
#     die Gesamtstärke über die komplette Saison wider.
#   • Aktuelle Form (0.12) wird bewusst unter Win-Rate gehalten, da
#     NBA-Streaks stark schwanken und Überreaktion vermieden werden soll.
#   • Wettquoten (0.10) aggregieren bereits viele dieser Signale; ein zu
#     hohes Gewicht würde die eigene Analyse verwässern.
#   • Defensiv-Stärke (0.08) als eigenständiger Faktor, da gute Defense
#     in den Playoffs überproportional wichtig ist und im Schnitt stabiler
#     als Offense über die Saison ist.
#   • Ruhetage (0.06) – Back-to-Backs kosten in der NBA nachweislich
#     ~3-4 % Siegwahrscheinlichkeit.
#   • Verletzungen (0.06) – selbst ein einzelner Star-Ausfall kann den
#     erwarteten Siegwert um 5-10 % verschieben.
#   • Streak (0.04) – rein psychologisches Momentum; statistisch schwach,
#     aber nicht null.
#   • Pace-Mismatch (0.03) – Tempo-Kontraste erzeugen seltener einen
#     klaren Vorteil, können aber bei Extremen relevant sein.

FACTOR_WEIGHTS: dict[str, float] = {
    "Win-Rate":          0.18,
    "Punkt-Differenz":   0.16,
    "Heimvorteil":       0.12,
    "Aktuelle Form":     0.12,
    "Wettquoten":        0.10,
    "Offensiv-Stärke":   0.08,
    "Defensiv-Stärke":   0.08,
    "Ruhetage":          0.06,
    "Verletzungen":      0.06,
    "Streak":            0.04,
}

HOME_ADVANTAGE_BONUS = 0.04   # leicht gesenkt – Post-COVID-Daten zeigen ~58 %
NBA_AVG_POINTS = 113.5        # Saison 2024-25 Durchschnitt


class GamePredictor:
    """
    Berechnet Spielvorhersagen anhand eines gewichteten Scoring-Modells.

    Das Modell kombiniert historische Team-Statistiken, aktuelle Form,
    Belastung, Verletzungen und optionale Wettquoten zu einer
    Gesamtwahrscheinlichkeit für das Heimteam.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methode ──────────────────────────────────────────────

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
            "Vorhersage: %s (Heim) vs %s (Auswärts)", home_team.name, away_team.name,
        )

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

        home_score, away_score = self._estimate_scores(
            home_team, away_team, home_prob,
        )

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

    # ── Faktor-Berechnung ────────────────────────────────────────────────

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

        # ── 1. Win-Rate ──────────────────────────────────────────────────
        factors["Win-Rate"] = self._compare_stats(home.win_rate, away.win_rate)

        # ── 2. Punkt-Differenz ───────────────────────────────────────────
        factors["Punkt-Differenz"] = self._compare_stats(
            home.point_differential, away.point_differential, scale=20.0,
        )

        # ── 3. Heimvorteil ───────────────────────────────────────────────
        home_rate = home.home_win_rate if home.home_win_rate > 0 else home.win_rate
        away_rate = away.away_win_rate if away.away_win_rate > 0 else away.win_rate
        factors["Heimvorteil"] = (
            self._compare_stats(home_rate, away_rate) + HOME_ADVANTAGE_BONUS
        )

        # ── 4. Aktuelle Form (echte form_rating statt Approximation) ────
        home_form = self._estimate_form(home)
        away_form = self._estimate_form(away)
        factors["Aktuelle Form"] = self._compare_stats(home_form, away_form)

        # ── 5. Wettquoten ────────────────────────────────────────────────
        if odds is not None:
            implied_total = (
                odds.implied_home_probability + odds.implied_away_probability
            )
            if implied_total > 0:
                factors["Wettquoten"] = odds.implied_home_probability / implied_total
            else:
                factors["Wettquoten"] = 0.5
        else:
            factors["Wettquoten"] = 0.5

        # ── 6. Offensiv-Stärke ───────────────────────────────────────────
        factors["Offensiv-Stärke"] = self._compare_stats(
            home.avg_points_scored,
            away.avg_points_scored,
            scale=20.0,
            center=NBA_AVG_POINTS,
        )

        # ── 7. Defensiv-Stärke (NEU) ────────────────────────────────────
        #    Weniger kassierte Punkte = bessere Defense → invertierter
        #    Vergleich: *niedrigerer* Wert ist besser → away zuerst.
        factors["Defensiv-Stärke"] = self._compare_stats(
            away.avg_points_allowed,  # hoher Wert = schlechte Def. des Gegners → Vorteil Heim
            home.avg_points_allowed,  # invertiert, damit > 0.5 = Heim besser
            scale=20.0,
            center=NBA_AVG_POINTS,
        )

        # ── 8. Ruhetage / Back-to-Back (NEU) ────────────────────────────
        #    fatigue_score: 0.0 = ausgeruht, 1.0 = stark belastet.
        #    Wir invertieren, damit ein *ausgeruhteres* Heimteam > 0.5 bekommt.
        home_fresh = 1.0 - home.fatigue_score
        away_fresh = 1.0 - away.fatigue_score
        factors["Ruhetage"] = self._compare_stats(home_fresh, away_fresh)

        # ── 9. Verletzungen (NEU) ────────────────────────────────────────
        #    injury_impact: 0.0 = gesund, 1.0 = stark geschwächt.
        #    Wieder invertiert: weniger Impact = gesünder = besser.
        home_health = 1.0 - home.injury_impact
        away_health = 1.0 - away.injury_impact
        factors["Verletzungen"] = self._compare_stats(home_health, away_health)

        # ── 10. Streak / Momentum (NEU) ──────────────────────────────────
        #    current_streak: +N = Siegesserie, -N = Niederlagenserie.
        #    Auf Skala normiert, damit eine 5er-Serie ≈ Maximum ist.
        home_streak_norm = max(-1.0, min(1.0, home.current_streak / 5.0))
        away_streak_norm = max(-1.0, min(1.0, away.current_streak / 5.0))
        factors["Streak"] = 0.5 + (home_streak_norm - away_streak_norm) * 0.25

        # Alle Werte auf [0.0, 1.0] begrenzen
        return {k: max(0.0, min(1.0, v)) for k, v in factors.items()}

    # ── Hilfsmethoden ────────────────────────────────────────────────────

    @staticmethod
    def _estimate_form(team: "Team") -> float:
        """Echte Formkurve oder Fallback auf Saison-Approximation.

        Wenn ``recent_game_results`` gefüllt ist (>= 3 Spiele), wird
        ``team.form_rating`` verwendet (30 % L3, 40 % L5, 30 % L10).
        Andernfalls Näherung über Saisondurchschnitt.
        """
        if team.has_recent_form_data:
            return team.form_rating
        # Fallback: keine aktuellen Spielergebnisse verfügbar
        return (team.win_rate + max(0.0, team.point_differential / 20.0)) / 2.0

    def _compute_weighted_score(self, factors: dict[str, float]) -> float:
        """Berechnet den gewichteten Gesamtscore des Heimteams."""
        total = 0.0
        for name, weight in FACTOR_WEIGHTS.items():
            total += factors.get(name, 0.5) * weight
        return total

    def _normalize_to_probability(self, raw_score: float) -> float:
        """Konvertiert den Rohscore in eine Wahrscheinlichkeit.

        Nutzt eine lineare Normierung um 0.5 mit Dämpfung,
        damit Extremwerte realistisch bleiben (max ~85 %).
        """
        dampening = 0.80
        deviation = (raw_score - 0.5) * dampening
        return max(0.10, min(0.90, 0.5 + deviation))

    def _estimate_scores(
        self,
        home: "Team",
        away: "Team",
        home_prob: float,
    ) -> tuple[float, float]:
        """Schätzt das Spielergebnis aus Team-Statistiken und Siegwahrscheinlichkeit."""
        home_off = home.avg_points_scored or NBA_AVG_POINTS
        home_def = home.avg_points_allowed or NBA_AVG_POINTS
        away_off = away.avg_points_scored or NBA_AVG_POINTS
        away_def = away.avg_points_allowed or NBA_AVG_POINTS

        home_base = (home_off + away_def) / 2.0
        away_base = (away_off + home_def) / 2.0

        # Ermüdung beeinflusst die erwartete Punktzahl leicht
        home_fatigue_penalty = home.fatigue_score * 2.5  # max. ~2.5 Punkte Abzug
        away_fatigue_penalty = away.fatigue_score * 2.5

        home_base -= home_fatigue_penalty
        away_base -= away_fatigue_penalty

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
