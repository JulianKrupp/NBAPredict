"""
Datenmodell für ein NBA-Team mit Statistiken.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Team:
    """Repräsentiert ein NBA-Team mit aggregierten Saisonstatistiken."""

    team_id: int
    name: str
    abbreviation: str
    conference: str = ""
    division: str = ""

    # Saisonstatistiken
    wins: int = 0
    losses: int = 0
    avg_points_scored: float = 0.0
    avg_points_allowed: float = 0.0
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0

    # Erweiterte Statistiken
    avg_rebounds: float = 0.0
    avg_assists: float = 0.0
    avg_steals: float = 0.0
    avg_blocks: float = 0.0
    avg_turnovers: float = 0.0
    field_goal_percentage: float = 0.0
    three_point_percentage: float = 0.0
    free_throw_percentage: float = 0.0

    @property
    def total_games(self) -> int:
        """Gesamtanzahl gespielter Spiele."""
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        """Siegquote (0.0–1.0)."""
        if self.total_games == 0:
            return 0.0
        return self.wins / self.total_games

    @property
    def home_win_rate(self) -> float:
        """Heimsiegquote (0.0–1.0)."""
        home_games = self.home_wins + self.home_losses
        if home_games == 0:
            return 0.0
        return self.home_wins / home_games

    @property
    def away_win_rate(self) -> float:
        """Auswärtssiegquote (0.0–1.0)."""
        away_games = self.away_wins + self.away_losses
        if away_games == 0:
            return 0.0
        return self.away_wins / away_games

    @property
    def point_differential(self) -> float:
        """Durchschnittliche Punktedifferenz pro Spiel."""
        return self.avg_points_scored - self.avg_points_allowed

    def __str__(self) -> str:
        return f"{self.name} ({self.wins}W/{self.losses}L, {self.win_rate:.1%})"

    @classmethod
    def from_standings_response(cls, data: dict) -> "Team":
        """
        Erstellt ein Team-Objekt aus einem Tabellenstands-API-Response.

        Args:
            data: Rohdaten aus der API-Antwort.

        Returns:
            Instanz von Team.
        """
        team_data = data.get("team", data)
        return cls(
            team_id=team_data.get("id", 0),
            name=team_data.get("full_name", team_data.get("name", "Unbekannt")),
            abbreviation=team_data.get("abbreviation", ""),
            conference=team_data.get("conference", ""),
            division=team_data.get("division", ""),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            home_wins=int(data.get("home_wins", 0)),
            home_losses=int(data.get("home_losses", 0)),
            away_wins=int(data.get("away_wins", 0)),
            away_losses=int(data.get("away_losses", 0)),
            avg_points_scored=float(data.get("pts", 0) or 0),
            avg_points_allowed=float(data.get("opp_pts", 0) or 0),
        )
