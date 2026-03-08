"""
Gemeinsame pytest-Fixtures für alle Tests.
"""

import pytest
from unittest.mock import MagicMock
from src.utils.config import Config
from src.models.team import Team
from src.models.game import Game


@pytest.fixture
def sample_config() -> Config:
    """Gibt eine Minimal-Konfiguration für Tests zurück."""
    config = MagicMock(spec=Config)
    config.balldontlie_api_key = "test_api_key"
    config.odds_api_key = "test_odds_key"
    config.balldontlie_base_url = "https://api.balldontlie.io/v1"
    config.odds_api_base_url = "https://api.the-odds-api.com/v4"
    config.request_timeout = 5
    config.max_retries = 1
    config.retry_delay = 0.1
    config.cache_ttl = 60
    return config


@pytest.fixture
def sample_home_team() -> Team:
    """Gibt ein Beispiel-Heimteam zurück."""
    return Team(
        team_id=14,
        name="Los Angeles Lakers",
        abbreviation="LAL",
        conference="West",
        wins=45,
        losses=20,
        avg_points_scored=116.5,
        avg_points_allowed=110.0,
        home_wins=26,
        home_losses=8,
        away_wins=19,
        away_losses=12,
    )


@pytest.fixture
def sample_away_team() -> Team:
    """Gibt ein Beispiel-Auswärtsteam zurück."""
    return Team(
        team_id=2,
        name="Boston Celtics",
        abbreviation="BOS",
        conference="East",
        wins=50,
        losses=15,
        avg_points_scored=118.0,
        avg_points_allowed=107.5,
        home_wins=28,
        home_losses=5,
        away_wins=22,
        away_losses=10,
    )


@pytest.fixture
def sample_finished_game() -> Game:
    """Gibt ein beendetes Beispielspiel zurück."""
    return Game(
        game_id=1001,
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        home_score=112,
        away_score=108,
        status="Final",
        date="2025-03-01",
        season=2024,
    )


@pytest.fixture
def sample_live_game() -> Game:
    """Gibt ein laufendes Beispielspiel zurück."""
    return Game(
        game_id=1002,
        home_team="Golden State Warriors",
        away_team="Phoenix Suns",
        home_score=55,
        away_score=52,
        status="live",
        date="2025-03-08",
        season=2024,
        period=3,
        time_remaining="4:30",
    )
