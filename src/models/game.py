"""
Datenmodell für ein NBA-Spiel.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Game:
    """Repräsentiert ein einzelnes NBA-Spiel."""

    game_id: int
    home_team: str
    away_team: str
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"
    date: str = ""
    season: int = 2024
    period: int = 0
    time_remaining: str = ""

    @property
    def is_final(self) -> bool:
        """Gibt True zurück, wenn das Spiel beendet ist."""
        return self.status.lower() in ("final", "ft", "beendet")

    @property
    def is_live(self) -> bool:
        """Gibt True zurück, wenn das Spiel gerade läuft."""
        return self.status.lower() in ("live", "inprogress", "in progress")

    @property
    def winner(self) -> str | None:
        """
        Gibt den Sieger zurück, wenn das Spiel beendet ist.

        Returns:
            Name des Siegerteams oder None, wenn noch nicht entschieden.
        """
        if not self.is_final:
            return None
        return self.home_team if self.home_score > self.away_score else self.away_team

    @property
    def score_difference(self) -> int:
        """Gibt die absolute Punktedifferenz zurück."""
        return abs(self.home_score - self.away_score)

    def __str__(self) -> str:
        return (
            f"{self.home_team} {self.home_score} – {self.away_score} {self.away_team}"
            f" ({self.status})"
        )

    @classmethod
    def from_api_response(cls, data: dict) -> "Game":
        """
        Erstellt ein Game-Objekt aus einem BallDontLie-API-Response-Dict.

        Args:
            data: Rohdaten aus der API-Antwort.

        Returns:
            Instanz von Game.

        Raises:
            KeyError: Wenn ein Pflichtfeld fehlt.
        """
        home_team_data = data.get("home_team", {})
        away_team_data = data.get("visitor_team", {})

        return cls(
            game_id=data["id"],
            home_team=home_team_data.get("full_name", home_team_data.get("name", "Unbekannt")),
            away_team=away_team_data.get("full_name", away_team_data.get("name", "Unbekannt")),
            home_score=int(data.get("home_team_score", 0) or 0),
            away_score=int(data.get("visitor_team_score", 0) or 0),
            status=str(data.get("status", "scheduled")),
            date=str(data.get("date", ""))[:10],
            season=int(data.get("season", 2024)),
            period=int(data.get("period", 0) or 0),
            time_remaining=str(data.get("time", "") or ""),
        )
