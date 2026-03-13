"""KI-Vorhersage vs. Wettquoten – tabellarischer Vergleich."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.api.nba_api_client import NBAApiClient
from src.api.odds_api_client import OddsApiClient, GameOdds
from src.ml.ml_predictor import MLPredictor
from src.utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class ComparisonEntry:
    home_team: str
    away_team: str

    ml_home_prob: float
    ml_away_prob: float
    ml_winner: str

    odds_home_prob: float
    odds_away_prob: float
    odds_winner: str
    odds_home_raw: float
    odds_away_raw: float

    prob_difference: float  # |ML_home - Odds_home|

    @property
    def methods_agree(self) -> bool:
        return self.ml_winner == self.odds_winner

    @property
    def value_bet_indicator(self) -> str:
        """
        Zeigt, ob KI und Buchmacher nennenswert voneinander abweichen.
        Kein Wetthinweis – rein analytisch.
        """
        diff = self.ml_home_prob - self.odds_home_prob
        if abs(diff) < 0.05:
            return "≈ Einig"
        if diff > 0.10:
            return "📈 KI favorisiert Heim stärker"
        if diff < -0.10:
            return "📈 KI favorisiert Auswärts stärker"
        return "~ Leichte Abweichung"


class OddsVsMLComparison:

    def __init__(self, config: Config) -> None:
        self.config       = config
        self.nba_client   = NBAApiClient(config)
        self.odds_client  = OddsApiClient(config)
        self.ml_predictor = MLPredictor(config)
        self.logger       = logging.getLogger(__name__)

    def run_comparison(self) -> list[ComparisonEntry]:
        """Vergleich für alle Spiele mit verfügbaren Wettquoten."""
        self.logger.info("Starte KI-vs-Odds-Vergleich...")
        all_odds = self.odds_client.get_all_upcoming_odds()
        if not all_odds:
            self.logger.warning("Keine Wettquoten – ODDS_API_KEY prüfen.")
            return []

        entries = []
        for odds in all_odds:
            entry = self._compare_game(odds)
            if entry:
                entries.append(entry)
        return entries

    def run_comparison_for_teams(self, home: str, away: str) -> ComparisonEntry | None:
        odds = self.odds_client.get_odds(home, away)
        if not odds:
            self.logger.warning("Keine Quoten für %s vs %s.", home, away)
            return None
        return self._compare_game(odds)

    def display_comparison_table(self, entries: list[ComparisonEntry]) -> None:
        if not entries:
            print("Keine Daten für den Vergleich vorhanden.")
            return

        print(f"\n{'='*80}")
        print("  KI vs. Wettquoten")
        print(f"{'='*80}")
        header = f"  {'Spiel':<30} {'KI Heim':>8} {'KI Ausw':>8} {'Q Heim':>8} {'Q Ausw':>8}  Status"
        print(header)
        print(f"  {'-'*72}")

        for e in entries:
            matchup  = f"{e.home_team} vs {e.away_team}"[:28]
            agree    = "✅" if e.methods_agree else "⚠️"
            print(
                f"  {matchup:<30} {e.ml_home_prob:.1%}  {e.ml_away_prob:.1%}"
                f"   {e.odds_home_prob:.1%}  {e.odds_away_prob:.1%}  {agree} {e.value_bet_indicator}"
            )

        print(f"{'='*80}\n")

    def _compare_game(self, odds: GameOdds) -> ComparisonEntry | None:
        home_team = self.nba_client.get_team_stats(odds.home_team)
        away_team = self.nba_client.get_team_stats(odds.away_team)
        if not home_team or not away_team:
            return None

        result = self.ml_predictor.predict(home_team, away_team, odds)

        total = odds.implied_home_probability + odds.implied_away_probability
        odds_home_norm = odds.implied_home_probability / total if total > 0 else 0.5
        odds_away_norm = 1.0 - odds_home_norm
        odds_winner    = "home" if odds_home_norm >= 0.5 else "away"

        return ComparisonEntry(
            home_team=odds.home_team,
            away_team=odds.away_team,
            ml_home_prob=result.ml_home_win_probability,
            ml_away_prob=1.0 - result.ml_home_win_probability,
            ml_winner=result.ml_predicted_winner,
            odds_home_prob=odds_home_norm,
            odds_away_prob=odds_away_norm,
            odds_winner=odds_winner,
            odds_home_raw=odds.odds_home,
            odds_away_raw=odds.odds_away,
            prob_difference=abs(result.ml_home_win_probability - odds_home_norm),
        )
