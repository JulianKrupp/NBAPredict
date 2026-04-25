"""
Unit-Tests für das Game-Datenmodell.
"""

import pytest
from src.models.game import Game


class TestGame:
    """Tests für die Game-Klasse."""

    def test_game_creation_with_defaults(self):
        """Erstellt ein Game-Objekt mit Standardwerten."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics")
        assert game.game_id == 1
        assert game.home_team == "Lakers"
        assert game.away_team == "Celtics"
        assert game.home_score == 0
        assert game.away_score == 0
        assert game.status == "scheduled"

    def test_is_final_returns_true_for_finished_game(self):
        """is_final gibt True zurück, wenn der Status 'Final' ist."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics", status="Final")
        assert game.is_final is True

    def test_is_final_returns_false_for_live_game(self):
        """is_final gibt False zurück, wenn das Spiel live läuft."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics", status="live")
        assert game.is_final is False

    def test_is_live_returns_true_for_live_status(self):
        """is_live gibt True zurück, wenn Status 'live' oder 'InProgress' ist."""
        game = Game(game_id=1, home_team="A", away_team="B", status="InProgress")
        assert game.is_live is True

    def test_winner_is_none_for_ongoing_game(self):
        """winner gibt None zurück, wenn das Spiel noch nicht beendet ist."""
        game = Game(game_id=1, home_team="A", away_team="B", status="live",
                    home_score=50, away_score=48)
        assert game.winner is None

    def test_winner_is_home_team_when_home_wins(self):
        """winner gibt den Heimteamnamen zurück, wenn Heimteam gewinnt."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics",
                    status="Final", home_score=110, away_score=105)
        assert game.winner == "Lakers"

    def test_winner_is_away_team_when_away_wins(self):
        """winner gibt den Auswärtsteamnamen zurück, wenn Auswärtsteam gewinnt."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics",
                    status="Final", home_score=100, away_score=115)
        assert game.winner == "Celtics"

    def test_str_representation(self):
        """__str__ gibt eine lesbare Darstellung des Spiels zurück."""
        game = Game(game_id=1, home_team="Lakers", away_team="Celtics",
                    status="Final", home_score=110, away_score=105)
        result = str(game)
        assert "Lakers" in result
        assert "Celtics" in result
        assert "110" in result
        assert "105" in result

    def test_from_api_response_valid_data(self):
        """from_api_response erstellt korrekt ein Game-Objekt aus API-Daten."""
        raw = {
            "id": 42,
            "home_team": {"id": 1, "full_name": "Los Angeles Lakers", "name": "Lakers"},
            "visitor_team": {"id": 2, "full_name": "Boston Celtics", "name": "Celtics"},
            "home_team_score": 112,
            "visitor_team_score": 108,
            "status": "Final",
            "date": "2025-01-15T00:00:00.000Z",
            "season": 2024,
            "period": 4,
            "time": "",
        }
        game = Game.from_api_response(raw)
        assert game.game_id == 42
        assert game.home_team == "Los Angeles Lakers"
        assert game.away_team == "Boston Celtics"
        assert game.home_score == 112
        assert game.away_score == 108
        assert game.status == "Final"
        assert game.date == "2025-01-15"

    def test_from_api_response_missing_scores(self):
        """from_api_response behandelt fehlende Score-Werte als 0."""
        raw = {
            "id": 1,
            "home_team": {"id": 1, "full_name": "Team A", "name": "A"},
            "visitor_team": {"id": 2, "full_name": "Team B", "name": "B"},
            "home_team_score": None,
            "visitor_team_score": None,
            "status": "scheduled",
            "date": "2025-03-01T00:00:00.000Z",
            "season": 2024,
        }
        game = Game.from_api_response(raw)
        assert game.home_score == 0
        assert game.away_score == 0

    def test_from_api_response_raises_on_missing_id(self):
        """from_api_response wirft KeyError, wenn die ID fehlt."""
        raw = {
            "home_team": {"id": 1, "full_name": "A", "name": "A"},
            "visitor_team": {"id": 2, "full_name": "B", "name": "B"},
        }
        with pytest.raises(KeyError):
            Game.from_api_response(raw)
