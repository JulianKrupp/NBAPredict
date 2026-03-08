"""
Gegenüberstellung: KI-Vorhersage vs. Wettquoten (Odds API).

Vergleicht die Siegwahrscheinlichkeiten des ML-Modells mit den
impliziten Wahrscheinlichkeiten der Buchmacher für aktuelle NBA-Spiele.
Zeigt Diskrepanzen auf und bewertet die Übereinstimmung.
"""

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
    """Vergleichseintrag für ein einzelnes Spiel."""
    home_team: str
    away_team: str

    # KI-Wahrscheinlichkeiten
    ml_home_prob: float
    ml_away_prob: float
    ml_winner: str

    # Wettquoten-Wahrscheinlichkeiten (normiert, Vig-bereinigt)
    odds_home_prob: float
    odds_away_prob: float
    odds_winner: str
    odds_home_raw: float    # Dezimalquote
    odds_away_raw: float

    # Differenz
    prob_difference: float  # |ML - Odds| für Home

    @property
    def methods_agree(self) -> bool:
        """True, wenn KI und Buchmacher denselben Sieger sehen."""
        return self.ml_winner == self.odds_winner

    @property
    def value_bet_indicator(self) -> str:
        """
        Hinweis auf mögliche Diskrepanz zwischen KI und Buchmacher.
        Keine Wettempfehlung – nur analytischer Vergleichswert.
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
    """
    Erstellt eine Gegenüberstellung der KI-Vorhersagen
    und der Wettquoten für aktuelle NBA-Spiele.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.nba_client = NBAApiClient(config)
        self.odds_client = OddsApiClient(config)
        self.ml_predictor = MLPredictor(config)
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def run_comparison(self) -> list[ComparisonEntry]:
        """
        Führt den vollständigen Vergleich für alle Spiele mit verfügbaren
        Wettquoten durch.

        Returns:
            Liste von ComparisonEntry-Objekten.
        """
        self.logger.info("Starte KI vs. Odds-Vergleich...")

        # Wettquoten laden
        all_odds = self.odds_client.get_all_upcoming_odds()
        if not all_odds:
            self.logger.warning("Keine Wettquoten verfügbar – prüfe ODDS_API_KEY.")
            return []

        self.logger.info("%d Spiele mit Wettquoten gefunden", len(all_odds))

        entries: list[ComparisonEntry] = []
        for odds in all_odds:
            entry = self._compare_single_game(odds)
            if entry is not None:
                entries.append(entry)

        return entries

    def run_comparison_for_teams(
        self, home_team_name: str, away_team_name: str
    ) -> ComparisonEntry | None:
        """
        Vergleich für ein spezifisches Spiel.

        Args:
            home_team_name: Name des Heimteams.
            away_team_name: Name des Auswärtsteams.

        Returns:
            ComparisonEntry oder None wenn Teams/Quoten nicht gefunden.
        """
        home_stats = self.nba_client.get_team_stats(home_team_name)
        away_stats = self.nba_client.get_team_stats(away_team_name)
        odds = self.odds_client.get_odds(home_team_name, away_team_name)

        if not home_stats or not away_stats:
            return None

        # KI-Vorhersage
        ml_result = self.ml_predictor.predict(home_stats, away_stats, odds)

        # Wettquoten normiert
        if odds:
            odds_home_prob, odds_away_prob = self._normalize_odds(
                odds.odds_home, odds.odds_away
            )
        else:
            odds_home_prob, odds_away_prob = 0.5, 0.5

        ml_home_prob = ml_result.ml_home_win_probability

        return ComparisonEntry(
            home_team=home_stats.name,
            away_team=away_stats.name,
            ml_home_prob=ml_home_prob,
            ml_away_prob=1.0 - ml_home_prob,
            ml_winner="home" if ml_home_prob >= 0.5 else "away",
            odds_home_prob=odds_home_prob,
            odds_away_prob=odds_away_prob,
            odds_winner="home" if odds_home_prob >= 0.5 else "away",
            odds_home_raw=odds.odds_home if odds else 0.0,
            odds_away_raw=odds.odds_away if odds else 0.0,
            prob_difference=abs(ml_home_prob - odds_home_prob),
        )

    def display_comparison_table(self, entries: list[ComparisonEntry]) -> None:
        """
        Gibt die Vergleichstabelle formatiert auf der Konsole aus.

        Args:
            entries: Liste von ComparisonEntry-Objekten.
        """
        if not entries:
            print("\n  ⚠️  Keine Vergleichsdaten verfügbar.")
            print("      Stelle sicher, dass ODDS_API_KEY gesetzt ist.\n")
            return

        print(f"\n{'='*90}")
        print(f"  🤖 KI vs. 📊 Wettquoten – Vergleich der Siegwahrscheinlichkeiten")
        print(f"{'='*90}")
        print(
            f"  {'Spiel':<42} "
            f"{'KI Heim':>8} {'KI Ausw':>8}  "
            f"{'Odds Heim':>9} {'Odds Ausw':>9}  "
            f"{'Δ':>6}  {'Status':<30}"
        )
        print(f"  {'─'*86}")

        for entry in entries:
            game_label = f"{entry.home_team} vs {entry.away_team}"
            if len(game_label) > 40:
                game_label = game_label[:37] + "..."

            agree_icon = "✅" if entry.methods_agree else "⚠️ "
            print(
                f"  {game_label:<42} "
                f"{entry.ml_home_prob:>7.1%} {entry.ml_away_prob:>8.1%}  "
                f"{entry.odds_home_prob:>8.1%} {entry.odds_away_prob:>9.1%}  "
                f"{entry.prob_difference:>5.1%}  "
                f"{agree_icon} {entry.value_bet_indicator}"
            )

        print(f"\n  {'─'*86}")
        agree_count = sum(1 for e in entries if e.methods_agree)
        print(f"  Übereinstimmung KI ↔ Quoten: {agree_count}/{len(entries)} "
              f"({agree_count/len(entries):.0%})")

        avg_diff = sum(e.prob_difference for e in entries) / len(entries)
        print(f"  Ø Abweichung              : {avg_diff:.1%}")
        print(f"{'='*90}\n")

        # Hinweis
        print("  ℹ️  Hinweis: Wahrscheinlichkeitsdifferenzen zeigen analytische")
        print("     Abweichungen. Dies ist keine Wettempfehlung.\n")

    # ── Private Methoden ─────────────────────────────────────────────────

    def _compare_single_game(self, odds: GameOdds) -> ComparisonEntry | None:
        """Vergleich für ein einzelnes Spiel aus den Wettquoten-Daten."""
        home_stats = self.nba_client.get_team_stats(odds.home_team)
        away_stats = self.nba_client.get_team_stats(odds.away_team)

        if not home_stats or not away_stats:
            self.logger.debug(
                "Teams nicht gefunden: %s / %s", odds.home_team, odds.away_team
            )
            return None

        try:
            ml_result = self.ml_predictor.predict(home_stats, away_stats, odds)
            ml_home_prob = ml_result.ml_home_win_probability

            odds_home_prob, odds_away_prob = self._normalize_odds(
                odds.odds_home, odds.odds_away
            )

            return ComparisonEntry(
                home_team=home_stats.name,
                away_team=away_stats.name,
                ml_home_prob=ml_home_prob,
                ml_away_prob=1.0 - ml_home_prob,
                ml_winner="home" if ml_home_prob >= 0.5 else "away",
                odds_home_prob=odds_home_prob,
                odds_away_prob=odds_away_prob,
                odds_winner="home" if odds_home_prob >= 0.5 else "away",
                odds_home_raw=odds.odds_home,
                odds_away_raw=odds.odds_away,
                prob_difference=abs(ml_home_prob - odds_home_prob),
            )
        except Exception as exc:
            self.logger.error("Fehler bei Vergleich %s vs %s: %s",
                              odds.home_team, odds.away_team, exc)
            return None

    @staticmethod
    def _normalize_odds(odds_home: float, odds_away: float) -> tuple[float, float]:
        """
        Normiert Dezimalquoten zu Wahrscheinlichkeiten (Vig-bereinigt).

        Args:
            odds_home: Dezimalquote Heim.
            odds_away: Dezimalquote Auswärts.

        Returns:
            Tupel (home_probability, away_probability) mit Summe = 1.0.
        """
        if odds_home <= 0 or odds_away <= 0:
            return 0.5, 0.5

        raw_home = 1.0 / odds_home
        raw_away = 1.0 / odds_away
        total = raw_home + raw_away  # > 1.0 wegen Vig (Buchmachergewinn)

        return raw_home / total, raw_away / total
