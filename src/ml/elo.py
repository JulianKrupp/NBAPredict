"""
Elo-Rating-Berechnung für NBA-Teams.

Berechnet Elo-Ratings aus historischen Spielergebnissen.
Zwei Modi:
  - Endgültige Ratings (für Vorhersagen mit aktuellem Stand)
  - Ratings pro Spiel (für Trainingsdaten – Elo VOR dem Spiel)
"""

from __future__ import annotations

from collections import defaultdict
from src.models.game import Game


def calculate_elo_ratings(
    games: list[Game],
    k: float = 20.0,
    home_advantage: float = 100.0,
) -> dict[str, float]:
    """
    Berechnet finale Elo-Ratings aus einer Spielliste.

    Args:
        games:          Liste abgeschlossener Spiele.
        k:              K-Faktor (Lernrate). 20 ist NBA-Standard.
        home_advantage: Elo-Bonus für das Heimteam (~100 für NBA).

    Returns:
        Dictionary: Teamname → aktuelles Elo-Rating.
    """
    elo: dict[str, float] = defaultdict(lambda: 1500.0)

    for game in sorted(games, key=lambda g: g.date):
        if not game.is_final or game.home_score == 0:
            continue
        _update_elo(elo, game, k, home_advantage)

    return dict(elo)


def calculate_elo_per_game(
    games: list[Game],
    k: float = 20.0,
    home_advantage: float = 100.0,
) -> dict[int, tuple[float, float]]:
    """
    Berechnet Elo-Ratings ZUM ZEITPUNKT jedes Spiels (vor dem Update).

    Für Trainingsdaten: Das Elo-Rating das jedes Team hatte BEVOR
    das Spiel gespielt wurde.

    Args:
        games:          Liste abgeschlossener Spiele.
        k:              K-Faktor.
        home_advantage: Elo-Bonus Heimteam.

    Returns:
        Dictionary: game_id → (home_elo_before, away_elo_before)
    """
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    elo_per_game: dict[int, tuple[float, float]] = {}

    for game in sorted(games, key=lambda g: g.date):
        if not game.is_final or game.home_score == 0:
            continue

        # Elo VOR dem Spiel speichern
        elo_per_game[game.game_id] = (
            elo[game.home_team],
            elo[game.away_team],
        )

        # Elo aktualisieren
        _update_elo(elo, game, k, home_advantage)

    return elo_per_game


def _update_elo(
    elo: dict[str, float],
    game: Game,
    k: float,
    home_advantage: float,
) -> None:
    """Aktualisiert die Elo-Ratings basierend auf einem Spielergebnis."""
    eh = elo[game.home_team]
    ea = elo[game.away_team]

    # Erwartungswert mit Heimvorteil
    expected_home = 1.0 / (1.0 + 10 ** ((ea - eh - home_advantage) / 400))
    result = 1.0 if game.home_score > game.away_score else 0.0

    # Margin-of-Victory-Multiplikator (deutliche Siege zählen stärker)
    mov = abs(game.home_score - game.away_score)
    mov_mult = ((mov + 3) ** 0.8) / (7.5 + 0.006 * abs(eh - ea))

    update = k * mov_mult * (result - expected_home)
    elo[game.home_team] += update
    elo[game.away_team] -= update
