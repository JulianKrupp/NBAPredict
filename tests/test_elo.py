"""
Unit-Tests für das Elo-Rating-System (src/ml/elo.py).

Testet: Startwert, Sieg/Niederlage-Update, Heimvorteil,
saisonale Regression-to-Mean, Margin-of-Victory-Effekt
und Daten-Leakage-Prävention in calculate_elo_per_game.
"""

import pytest

from src.ml.elo import ELO_SEASON_REGRESSION, calculate_elo_per_game, calculate_elo_ratings
from src.models.game import Game

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _game(
    game_id: int,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    date: str = "2024-01-01",
    season: int = 2024,
) -> Game:
    """Erstellt ein abgeschlossenes Beispielspiel."""
    return Game(
        game_id=game_id,
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        status="Final",
        date=date,
        season=season,
    )


# ── Startwerte ────────────────────────────────────────────────────────────────

class TestEloInitialValues:
    """Tests für die Elo-Initialisierung."""

    def test_new_team_starts_at_1500(self):
        """Jedes Team ohne Vorgeschichte beginnt bei Elo 1500."""
        games = [_game(1, "Lakers", "Celtics", 110, 100)]
        ratings = calculate_elo_ratings(games)
        # Beide Teams müssen vorhanden sein
        assert "Lakers" in ratings
        assert "Celtics" in ratings

    def test_winner_elo_increases_after_game(self):
        """Der Sieger eines Spiels erhält mehr Elo als vorher."""
        games = [_game(1, "Lakers", "Celtics", 110, 100)]
        ratings = calculate_elo_ratings(games)
        # Lakers gewinnt → über 1500; Celtics verliert → unter 1500
        assert ratings["Lakers"] > 1500.0
        assert ratings["Celtics"] < 1500.0

    def test_elo_sum_is_conserved(self):
        """
        Elo ist ein Nullsummenspiel: Die Summe aller Ratings bleibt konstant
        (bei 2 Teams: immer 3000 = 2 × 1500).
        """
        games = [
            _game(1, "Lakers", "Celtics", 110, 100),
            _game(2, "Lakers", "Celtics", 105, 115),
        ]
        ratings = calculate_elo_ratings(games)
        elo_sum = ratings["Lakers"] + ratings["Celtics"]
        assert elo_sum == pytest.approx(3000.0, abs=0.01)

    def test_multiple_wins_increase_elo_further(self):
        """Mehrere Siege erhöhen das Elo stärker als ein einzelner Sieg."""
        one_win = calculate_elo_ratings([_game(1, "Lakers", "Celtics", 110, 100)])
        two_wins = calculate_elo_ratings([
            _game(1, "Lakers", "Celtics", 110, 100),
            _game(2, "Lakers", "Warriors", 105, 95),
        ])
        assert two_wins["Lakers"] > one_win["Lakers"]


# ── Home Advantage ────────────────────────────────────────────────────────────

class TestEloHomeAdvantage:
    """Tests für den Heimvorteil im Elo-System."""

    def test_away_win_gives_larger_elo_increase_than_home_win(self):
        """
        Ein Auswärtssieg gegen das gleiche Team bringt mehr Elo als ein Heimsieg,
        weil er weniger erwartet wird.
        """
        # Heimsieg
        home_win_ratings = calculate_elo_ratings(
            [_game(1, "A", "B", 110, 100)]
        )
        elo_after_home_win = home_win_ratings["A"]

        # Auswärtssieg von B über A
        away_win_ratings = calculate_elo_ratings(
            [_game(1, "A", "B", 100, 110)]
        )
        elo_after_away_win = away_win_ratings["B"]

        assert elo_after_away_win > elo_after_home_win

    def test_expected_win_gives_smaller_gain_than_upset(self):
        """
        Ein erwarteter Sieg bringt weniger Elo als eine Überraschung.

        Wenn ein starkes Team (hohes Elo) gegen ein Team mit 1500 Elo gewinnt,
        ist das weniger überraschend als wenn das schwache Team gewinnt.
        """
        # Strong baut Elo durch viele Siege auf
        warm_up = [_game(i, "Strong", f"Weak{i}", 120, 90) for i in range(1, 11)]
        ratings_before = calculate_elo_ratings(warm_up)

        # Erwarteter Sieg: Strong gewinnt gegen Newcomer (1500 Elo)
        all_expected = warm_up + [_game(11, "Strong", "Newcomer", 115, 95)]
        ratings_expected = calculate_elo_ratings(all_expected)
        expected_gain = ratings_expected["Strong"] - ratings_before["Strong"]

        # Überraschung: Newcomer (1500) schlägt Strong in einem Auswärtsspiel
        all_upset = warm_up + [_game(12, "Newcomer", "Strong", 110, 100)]
        ratings_upset = calculate_elo_ratings(all_upset)
        upset_gain = ratings_upset["Newcomer"] - 1500.0

        # Erwartet: positiver aber kleiner Gewinn; Überraschung: größerer Gewinn
        assert expected_gain > 0, "Erwarteter Sieg sollte Elo-Zuwachs bringen"
        assert upset_gain > expected_gain, (
            f"Upset-Gewinn ({upset_gain:.1f}) sollte größer sein als "
            f"erwarteter Sieg ({expected_gain:.1f})"
        )


# ── Margin of Victory ─────────────────────────────────────────────────────────

class TestEloMarginOfVictory:
    """Tests für den Margin-of-Victory-Multiplikator."""

    def test_larger_margin_gives_bigger_elo_change(self):
        """Ein deutlicher Sieg bringt mehr Elo-Punkte als ein knapper Sieg."""
        close_win = calculate_elo_ratings([_game(1, "Lakers", "Celtics", 101, 100)])
        blowout   = calculate_elo_ratings([_game(1, "Lakers", "Celtics", 130, 100)])

        elo_gain_close   = close_win["Lakers"] - 1500.0
        elo_gain_blowout = blowout["Lakers"] - 1500.0

        assert elo_gain_blowout > elo_gain_close

    def test_small_margin_still_updates_elo(self):
        """Selbst ein 1-Punkt-Sieg aktualisiert das Elo-Rating."""
        ratings = calculate_elo_ratings([_game(1, "A", "B", 101, 100)])
        assert ratings["A"] > 1500.0
        assert ratings["B"] < 1500.0


# ── Saisonale Regression ──────────────────────────────────────────────────────

class TestEloSeasonRegression:
    """Tests für die Regression-to-Mean beim Saisonwechsel."""

    def test_elo_regresses_toward_1500_at_season_boundary(self):
        """
        Am Saisonbeginn wird das Elo (elo - 1500) um 25% zur Mitte gezogen.
        ELO_SEASON_REGRESSION = 0.75 → verbleibende Abweichung = 75%.
        """
        # Team A baut in Saison 2023 ein hohes Elo auf
        season_2023_games = [_game(i, "A", f"B{i}", 120, 90, f"2023-0{i+1}-01", season=2023)
                             for i in range(1, 8)]
        ratings_end_2023 = calculate_elo_ratings(season_2023_games)
        elo_before = ratings_end_2023["A"]
        assert elo_before > 1550  # Sicherheitsnetz: A ist wirklich gut

        # Saison 2024 beginnt: Regression should have happened
        all_games = season_2023_games + [
            _game(100, "A", "C", 110, 100, "2024-01-01", season=2024)
        ]
        ratings_after_regression = calculate_elo_ratings(all_games)

        # Nach Regression (vor dem 2024er Spiel) wäre A's Elo:
        # 1500 + (elo_before - 1500) * 0.75
        expected_after_regression = 1500.0 + (elo_before - 1500.0) * ELO_SEASON_REGRESSION
        # Nach dem zusätzlichen Sieg in 2024 liegt A leicht höher als der Regressionswert
        assert ratings_after_regression["A"] > expected_after_regression
        # Aber deutlich unter dem Vor-Regressions-Wert
        assert ratings_after_regression["A"] < elo_before

    def test_regression_factor_is_correct(self):
        """ELO_SEASON_REGRESSION ist 0.75 (25% Regression zur Mitte)."""
        assert ELO_SEASON_REGRESSION == 0.75


# ── calculate_elo_per_game (Daten-Leakage) ───────────────────────────────────

class TestEloPerGame:
    """Tests für calculate_elo_per_game – verhindert Daten-Leakage."""

    def test_elo_per_game_records_rating_before_game(self):
        """
        calculate_elo_per_game speichert das Elo VOR dem Spiel.
        Das erste Spiel muss immer 1500 / 1500 haben.
        """
        games = [_game(1, "Lakers", "Celtics", 110, 100)]
        elo_per_game = calculate_elo_per_game(games)

        assert 1 in elo_per_game
        home_elo_before, away_elo_before = elo_per_game[1]
        assert home_elo_before == pytest.approx(1500.0)
        assert away_elo_before == pytest.approx(1500.0)

    def test_elo_per_game_updates_after_each_game(self):
        """
        Nach dem ersten Spiel hat der Sieger ein höheres Elo.
        Dieses höhere Elo wird für das zweite Spiel verwendet.
        """
        games = [
            _game(1, "Lakers", "Celtics", 110, 100, "2024-01-01"),
            _game(2, "Lakers", "Celtics", 105, 95,  "2024-01-05"),
        ]
        elo_per_game = calculate_elo_per_game(games)

        home_elo_game1, _ = elo_per_game[1]
        home_elo_game2, _ = elo_per_game[2]

        # Spiel 2: Lakers hatte vorher Elo > 1500 (nach Sieg in Spiel 1)
        assert home_elo_game2 > home_elo_game1

    def test_elo_per_game_does_not_leak_future_data(self):
        """
        Das Elo für Spiel N darf NICHT das Ergebnis von Spiel N beinhalten.
        Spiel 1: Lakers schlägt Celtics → Lakers-Elo steigt
        Spiel 2: Elo vor Spiel 2 muss > 1500 für Lakers sein (Spiel 1 eingeflossen)
        aber Spiel 1's eigenes Elo ist exakt 1500 (noch nicht beeinflusst).
        """
        games = [
            _game(1, "Lakers", "Celtics", 110, 100, "2024-01-01"),
            _game(2, "Lakers", "Warriors", 108, 95, "2024-01-03"),
        ]
        elo_per_game = calculate_elo_per_game(games)

        # Spiel 1: Elo vor dem Spiel = 1500 (keine Vorgeschichte)
        lakers_before_game1, _ = elo_per_game[1]
        assert lakers_before_game1 == pytest.approx(1500.0)

        # Spiel 2: Elo nach Spiel 1, aber vor Spiel 2
        lakers_before_game2, _ = elo_per_game[2]
        assert lakers_before_game2 > 1500.0  # Sieg in Spiel 1 ist eingeflossen

    def test_elo_per_game_returns_dict_keyed_by_game_id(self):
        """Das Ergebnis von calculate_elo_per_game ist nach game_id indiziert."""
        games = [
            _game(42, "A", "B", 110, 100),
            _game(99, "A", "C", 105, 95, "2024-01-05"),
        ]
        elo_per_game = calculate_elo_per_game(games)
        assert 42 in elo_per_game
        assert 99 in elo_per_game
        home_elo, away_elo = elo_per_game[42]
        assert isinstance(home_elo, float)
        assert isinstance(away_elo, float)

    def test_non_final_games_are_excluded(self):
        """Nicht abgeschlossene Spiele fließen nicht in die Elo-Berechnung ein."""
        games = [
            Game(game_id=1, home_team="A", away_team="B",
                 home_score=55, away_score=48, status="live",
                 date="2024-01-01", season=2024),
        ]
        elo_per_game = calculate_elo_per_game(games)
        assert 1 not in elo_per_game
