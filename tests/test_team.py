"""
Unit-Tests für das Team-Datenmodell.
"""

import pytest

from src.models.team import Team


class TestTeam:
    """Tests für die Team-Klasse."""

    def _make_team(self, wins: int = 40, losses: int = 20, **kwargs) -> Team:
        """Hilfsmethode: Erstellt ein Team mit vordefinierten Werten."""
        return Team(
            team_id=1,
            name="Los Angeles Lakers",
            abbreviation="LAL",
            wins=wins,
            losses=losses,
            **kwargs,
        )

    def test_total_games_is_sum_of_wins_and_losses(self):
        """total_games ist die Summe aus Siegen und Niederlagen."""
        team = self._make_team(wins=35, losses=25)
        assert team.total_games == 60

    def test_win_rate_calculates_correctly(self):
        """win_rate berechnet die Siegquote korrekt."""
        team = self._make_team(wins=60, losses=20)
        assert team.win_rate == pytest.approx(0.75)

    def test_win_rate_returns_zero_when_no_games(self):
        """win_rate gibt 0.0 zurück, wenn noch keine Spiele gespielt wurden."""
        team = self._make_team(wins=0, losses=0)
        assert team.win_rate == 0.0

    def test_home_win_rate_calculates_correctly(self):
        """home_win_rate berechnet die Heimsiegquote korrekt."""
        team = self._make_team(home_wins=20, home_losses=10)
        assert team.home_win_rate == pytest.approx(2 / 3)

    def test_away_win_rate_returns_zero_when_no_away_games(self):
        """away_win_rate gibt 0.0 zurück, wenn keine Auswärtsspiele gespielt wurden."""
        team = self._make_team(away_wins=0, away_losses=0)
        assert team.away_win_rate == 0.0

    def test_point_differential_is_positive_for_strong_offense(self):
        """point_differential ist positiv, wenn mehr Punkte erzielt als kassiert wurden."""
        team = self._make_team(avg_points_scored=115.0, avg_points_allowed=108.0)
        assert team.point_differential == pytest.approx(7.0)

    def test_point_differential_is_negative_for_weak_team(self):
        """point_differential ist negativ, wenn mehr Punkte kassiert als erzielt wurden."""
        team = self._make_team(avg_points_scored=105.0, avg_points_allowed=112.0)
        assert team.point_differential == pytest.approx(-7.0)

    def test_str_representation_contains_name_and_record(self):
        """__str__ gibt den Namen und das Sieg/Niederlage-Verhältnis zurück."""
        team = self._make_team(wins=40, losses=20)
        result = str(team)
        assert "Los Angeles Lakers" in result
        assert "40" in result
        assert "20" in result

    def test_from_standings_response_valid_data(self):
        """from_standings_response erstellt korrekt ein Team aus API-Daten."""
        raw = {
            "team": {
                "id": 14,
                "full_name": "Los Angeles Lakers",
                "abbreviation": "LAL",
                "conference": "West",
                "division": "Pacific",
            },
            "wins": 45,
            "losses": 20,
            "home_wins": 25,
            "home_losses": 8,
            "away_wins": 20,
            "away_losses": 12,
            "pts": 116.5,
            "opp_pts": 110.2,
        }
        team = Team.from_standings_response(raw)
        assert team.team_id == 14
        assert team.name == "Los Angeles Lakers"
        assert team.abbreviation == "LAL"
        assert team.wins == 45
        assert team.losses == 20
        assert team.avg_points_scored == pytest.approx(116.5)
        assert team.avg_points_allowed == pytest.approx(110.2)

    def test_from_standings_response_handles_missing_fields(self):
        """from_standings_response behandelt fehlende Felder mit Standardwerten."""
        raw = {
            "team": {"id": 1, "full_name": "Unknown Team", "abbreviation": "UNK"},
        }
        team = Team.from_standings_response(raw)
        assert team.wins == 0
        assert team.losses == 0
        assert team.total_games == 0
