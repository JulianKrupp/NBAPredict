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
    season: int = field(default_factory=lambda: (
        datetime.now().year if datetime.now().month >= 10 else datetime.now().year - 1
    ))
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
        if self.home_score > self.away_score:
            return self.home_team
        if self.away_score > self.home_score:
            return self.away_team
        return None

    def __str__(self) -> str:
        return (
            f"{self.home_team} {self.home_score} – {self.away_score} {self.away_team}"
            f" ({self.status})"
        )

    @staticmethod
    def _season_from_date(date_str: str) -> int:
        """Oktober–Dezember -> aktuelles Jahr, Januar–Juni -> Vorjahr, analog zu den Seasons der NBA"""
        if not date_str:
            return datetime.now().year if datetime.now().month >= 10 else datetime.now().year - 1
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.year if dt.month >= 10 else dt.year - 1

    @classmethod
    def from_api_response(cls, data: dict) -> Game:
        """
        Erstellt ein Game-Objekt aus einem BallDontLie-API-Response-Dict.
        Je nach Endpoint sind Feldernamen unterschiedlich. zB. "name" und "full_name"

        Args:
            data: Rohdaten aus der API-Antwort

        Returns:
            Instanz von Game

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
            season=int(data.get("season") or Game._season_from_date(str(data.get("date", "")))),
            period=int(data.get("period", 0) or 0),
            time_remaining=str(data.get("time", "") or ""),
        )
