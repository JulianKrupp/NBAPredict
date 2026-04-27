"""
Unit-Tests für den NBAApiClient und OddsApiClient (mit Mock-Objekten).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.api.base_client import ApiError
from src.api.nba_api_client import TEAM_NAME_ALIASES, NBAApiClient
from src.api.odds_api_client import GameOdds, OddsApiClient
from src.models.game import Game
from src.utils.config import Config


@pytest.fixture
def mock_config() -> Config:
    """Erstellt eine Mock-Konfiguration."""
    config = MagicMock(spec=Config)
    config.balldontlie_api_key = "test_key_123"
    config.odds_api_key = "odds_key_456"
    config.balldontlie_base_url = "https://api.balldontlie.io/v1"
    config.odds_api_base_url = "https://api.the-odds-api.com/v4"
    config.request_timeout = 10
    config.max_retries = 3
    config.retry_delay = 1.0
    config.cache_ttl = 300
    return config


def _make_game(game_id, home, away, home_score, away_score, status="Final"):
    return Game(
        game_id=game_id, home_team=home, away_team=away,
        home_score=home_score, away_score=away_score,
        status=status, date="2025-01-15", season=2024,
    )


class TestNBAApiClient:
    """Tests für den NBAApiClient."""

    @patch.object(NBAApiClient, "get")
    def test_get_live_games_returns_game_list(self, mock_get, mock_config):
        """get_live_games gibt eine Liste von Game-Objekten zurück."""
        mock_get.return_value = {
            "data": [{
                "id": 1,
                "home_team": {"id": 1, "full_name": "Lakers", "name": "LAL"},
                "visitor_team": {"id": 2, "full_name": "Celtics", "name": "BOS"},
                "home_team_score": 55, "visitor_team_score": 48,
                "status": "live", "date": "2025-03-08T00:00:00.000Z", "season": 2024,
            }]
        }
        client = NBAApiClient(mock_config)
        games = client.get_live_games()
        assert len(games) == 1
        assert games[0].home_team == "Lakers"
        assert games[0].is_live is True

    @patch.object(NBAApiClient, "get")
    def test_get_live_games_returns_empty_list_on_api_error(self, mock_get, mock_config):
        """get_live_games gibt leere Liste zurück bei API-Fehler."""
        mock_get.side_effect = ApiError("Verbindungsfehler")
        client = NBAApiClient(mock_config)
        assert client.get_live_games() == []

    @patch.object(NBAApiClient, "get")
    def test_get_games_by_date_uses_provided_date(self, mock_get, mock_config):
        """get_games_by_date übergibt das Datum korrekt als Parameter."""
        mock_get.return_value = {"data": []}
        client = NBAApiClient(mock_config)
        client.get_games_by_date("2025-01-15")
        assert "2025-01-15" in str(mock_get.call_args)

    @patch.object(NBAApiClient, "get")
    def test_get_games_by_date_returns_empty_on_error(self, mock_get, mock_config):
        """get_games_by_date gibt leere Liste zurück bei API-Fehler."""
        mock_get.side_effect = ApiError("Fehler")
        client = NBAApiClient(mock_config)
        assert client.get_games_by_date("2025-01-01") == []

    # ── Standings (werden jetzt aus Games berechnet) ──────────────────────

    @patch.object(NBAApiClient, "_fetch_season_games_paginated")
    def test_get_standings_returns_team_list(self, mock_fetch, mock_config):
        """
        get_standings berechnet Tabellenstände aus Spielergebnissen.
        Der /standings-Endpunkt ist im Free-Tier gesperrt; stattdessen
        werden abgeschlossene Spiele ausgewertet.
        """
        mock_fetch.return_value = [
            _make_game(1, "Los Angeles Lakers", "Boston Celtics", 112, 108),
            _make_game(2, "Boston Celtics", "Los Angeles Lakers", 105, 115),
        ]
        client = NBAApiClient(mock_config)
        standings = client.get_standings()

        assert len(standings) == 2
        lakers = next((t for t in standings if "Lakers" in t.name), None)
        assert lakers is not None
        assert lakers.wins == 2
        assert lakers.losses == 0

    @patch.object(NBAApiClient, "_fetch_season_games_paginated")
    def test_get_standings_returns_empty_list_when_no_games(self, mock_fetch, mock_config):
        """get_standings gibt leere Liste zurück, wenn keine Spielergebnisse vorhanden."""
        mock_fetch.return_value = []
        client = NBAApiClient(mock_config)
        assert client.get_standings() == []

    @patch.object(NBAApiClient, "_fetch_season_games_paginated")
    def test_standings_calculates_win_rate_correctly(self, mock_fetch, mock_config):
        """Standings-Berechnung ermittelt Win-Rate korrekt."""
        mock_fetch.return_value = [
            _make_game(1, "Lakers", "Celtics", 110, 100),
            _make_game(2, "Lakers", "Warriors", 95,  105),
            _make_game(3, "Lakers", "Suns",    115, 100),
        ]
        client = NBAApiClient(mock_config)
        standings = client.get_standings()
        lakers = next(t for t in standings if "Lakers" in t.name)
        assert lakers.wins == 2
        assert lakers.losses == 1
        assert abs(lakers.win_rate - 2/3) < 0.01

    @patch.object(NBAApiClient, "_fetch_season_games_paginated")
    def test_standings_calculates_avg_points(self, mock_fetch, mock_config):
        """Standings-Berechnung berechnet Punktdurchschnitt korrekt."""
        mock_fetch.return_value = [
            _make_game(1, "Lakers", "Celtics", 100, 90),
            _make_game(2, "Lakers", "Warriors", 120, 110),
        ]
        client = NBAApiClient(mock_config)
        standings = client.get_standings()
        lakers = next(t for t in standings if "Lakers" in t.name)
        assert lakers.avg_points_scored == pytest.approx(110.0)

    # ── Sonstige Methoden ─────────────────────────────────────────────────

    def test_resolve_team_name_handles_alias(self, mock_config):
        """_resolve_team_name löst bekannte Aliase korrekt auf."""
        client = NBAApiClient(mock_config)
        assert client._resolve_team_name("lakers") == "Los Angeles Lakers"
        assert client._resolve_team_name("celtics") == "Boston Celtics"

    def test_resolve_team_name_returns_original_for_unknown(self, mock_config):
        """_resolve_team_name gibt Original zurück, wenn kein Alias bekannt."""
        client = NBAApiClient(mock_config)
        assert client._resolve_team_name("Mavericks") == "Mavericks"

    def test_all_aliases_map_to_valid_strings(self, mock_config):
        """Alle Aliase in TEAM_NAME_ALIASES sind nicht-leere Strings."""
        for alias, full_name in TEAM_NAME_ALIASES.items():
            assert isinstance(alias, str) and len(alias) > 0
            assert isinstance(full_name, str) and len(full_name) > 0

    def test_calculate_standings_home_away_split(self, mock_config):
        """Standings unterscheiden Heim- und Auswärtsspiele korrekt."""
        client = NBAApiClient(mock_config)
        games = [
            _make_game(1, "Lakers", "Celtics", 110, 100),   # Lakers Heimsieg
            _make_game(2, "Celtics", "Lakers",  95, 105),   # Lakers Auswärtssieg
        ]
        teams = client._calculate_standings_from_games(games, 2024)
        lakers = teams.get("Lakers")
        assert lakers is not None
        assert lakers.home_wins == 1
        assert lakers.away_wins == 1


class TestOddsApiClient:
    """Tests für den OddsApiClient."""

    @patch.object(OddsApiClient, "get")
    def test_get_odds_returns_game_odds(self, mock_get, mock_config):
        """get_odds gibt GameOdds zurück, wenn ein passendes Spiel gefunden wird."""
        mock_get.return_value = [{
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics",
            "bookmakers": [{
                "key": "bet365",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Los Angeles Lakers", "price": 1.85},
                    {"name": "Boston Celtics",     "price": 2.00},
                ]}],
            }],
        }]
        client = OddsApiClient(mock_config)
        odds = client.get_odds("Lakers", "Celtics")
        assert odds is not None
        assert isinstance(odds, GameOdds)
        assert odds.odds_home == pytest.approx(1.85)
        assert odds.odds_away == pytest.approx(2.00)

    def test_get_odds_returns_none_when_no_api_key(self, mock_config):
        """get_odds gibt None zurück wenn kein API-Key konfiguriert."""
        mock_config.odds_api_key = ""
        client = OddsApiClient(mock_config)
        assert client.get_odds("Lakers", "Celtics") is None

    @patch.object(OddsApiClient, "get")
    def test_get_odds_returns_none_when_no_match(self, mock_get, mock_config):
        """get_odds gibt None zurück wenn das Spiel nicht gefunden wird."""
        mock_get.return_value = [{
            "home_team": "Golden State Warriors",
            "away_team": "Phoenix Suns",
            "bookmakers": [],
        }]
        client = OddsApiClient(mock_config)
        assert client.get_odds("Lakers", "Celtics") is None

    @patch.object(OddsApiClient, "get")
    def test_get_odds_returns_none_on_api_error(self, mock_get, mock_config):
        """get_odds gibt None zurück bei API-Fehler."""
        mock_get.side_effect = ApiError("Fehler")
        client = OddsApiClient(mock_config)
        assert client.get_odds("Lakers", "Celtics") is None

    def test_game_odds_implied_probability_equal_odds(self):
        """Bei gleichen Quoten sind beide Wahrscheinlichkeiten 50%."""
        odds = GameOdds(home_team="A", away_team="B", odds_home=2.0, odds_away=2.0)
        assert odds.implied_home_probability == pytest.approx(0.5)
        assert odds.implied_away_probability == pytest.approx(0.5)

    def test_game_odds_implied_probability_for_favorite(self):
        """Niedrigere Quote = höhere implizite Gewinnwahrscheinlichkeit."""
        odds = GameOdds(home_team="Strong", away_team="Weak",
                        odds_home=1.50, odds_away=2.80)
        assert odds.implied_home_probability > odds.implied_away_probability

    def test_normalize_odds_removes_vig(self):
        """Normierte Quoten ergeben Summe von 1.0 (Vig-bereinigt)."""
        from src.ml.comparison import OddsVsMLComparison
        home_p, away_p = OddsVsMLComparison._normalize_odds(1.80, 2.10)
        assert abs(home_p + away_p - 1.0) < 0.001
        assert home_p > away_p  # Heimfavorit bei 1.80
