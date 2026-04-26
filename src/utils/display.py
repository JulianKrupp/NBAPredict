"""
Ausgabe-Hilfsfunktionen für den NBA Predict (Terminal-Formatierung).
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.game import Game
    from src.models.team import Team
    from src.ml.ml_predictor import MLPredictionResult


def display_games(games: list["Game"], title: str = "Spiele") -> None:
    """
    Gibt eine Liste von Spielen formatiert auf der Konsole aus.

    Args:
        games: Liste von Game-Objekten.
        title: Überschrift der Ausgabe.
    """
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    for game in games:
        status_label = _format_status(game)
        print(
            f"  {game.home_team:<25} vs  {game.away_team:<25}"
        )
        print(
            f"  Score: {game.home_score:>3} – {game.away_score:<3}   | {status_label}"
        )
        print(f"  {'-'*56}")

    print()



def display_standings(standings: list["Team"]) -> None:
    """
    Gibt die Tabellenstände sortiert nach Win-Rate aus.

    Args:
        standings: Liste von Team-Objekten.
    """
    sorted_teams = sorted(standings, key=lambda t: t.win_rate, reverse=True)

    print(f"\n{'='*70}")
    print(f"  🏆 NBA Tabelle")
    print(f"{'='*70}")
    print(f"  {'#':>3}  {'Team':<28}  {'S':>4}  {'N':>4}  {'Win%':>6}  {'Ø Punkte':>9}")
    print(f"  {'-'*62}")

    for rank, team in enumerate(sorted_teams, start=1):
        print(
            f"  {rank:>3}. {team.name:<28}  {team.wins:>4}  {team.losses:>4}"
            f"  {team.win_rate:>5.1%}  {team.avg_points_scored:>9.1f}"
        )

    print(f"{'='*70}\n")


# ── Private Hilfsfunktionen ──────────────────────────────────────────────────

def _format_status(game: "Game") -> str:
    """Gibt einen lesbaren Status-String für ein Spiel zurück."""
    status_map = {
        "Final":     "Beendet",
        "live":      "LIVE 🔴",
        "scheduled": "Geplant",
    }
    return status_map.get(game.status, game.status)
