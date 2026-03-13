from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Team:
    """NBA-Team mit aggregierten Saisonstatistiken."""

    team_id: int
    name: str
    abbreviation: str
    conference: str = ""
    division: str = ""

    wins: int = 0
    losses: int = 0
    avg_points_scored: float = 0.0
    avg_points_allowed: float = 0.0
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0

    avg_rebounds: float = 0.0
    avg_assists: float = 0.0
    avg_steals: float = 0.0
    avg_blocks: float = 0.0
    avg_turnovers: float = 0.0
    field_goal_percentage: float = 0.0
    three_point_percentage: float = 0.0
    free_throw_percentage: float = 0.0

    # Chronologisch sortierte Ergebnisse der Saisonspiele (True = Sieg).
    # Wird in _calculate_standings_from_games befüllt.
    recent_game_results: list[bool] = field(default_factory=list)

    @property
    def total_games(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total_games == 0:
            return 0.0
        return self.wins / self.total_games

    @property
    def home_win_rate(self) -> float:
        home_games = self.home_wins + self.home_losses
        if home_games == 0:
            return 0.0
        return self.home_wins / home_games

    @property
    def away_win_rate(self) -> float:
        away_games = self.away_wins + self.away_losses
        if away_games == 0:
            return 0.0
        return self.away_wins / away_games

    @property
    def point_differential(self) -> float:
        return self.avg_points_scored - self.avg_points_allowed

    @property
    def last_5_win_rate(self) -> float:
        """Siegquote der letzten 5 Spiele, Fallback auf Saison-Gesamt."""
        results = self.recent_game_results[-5:]
        if not results:
            return self.win_rate
        return sum(results) / len(results)

    @property
    def last_10_win_rate(self) -> float:
        """Siegquote der letzten 10 Spiele, Fallback auf Saison-Gesamt."""
        results = self.recent_game_results[-10:]
        if not results:
            return self.win_rate
        return sum(results) / len(results)

    @property
    def form_rating(self) -> float:
        """Gewichtete Formkurve: letzte 5 Spiele (60 %) + letzte 10 (40 %).
        Neuere Ergebnisse zählen stärker, ohne zu empfindlich auf einzelne
        Ausreißer zu reagieren."""
        if not self.recent_game_results:
            return self.win_rate
        return 0.6 * self.last_5_win_rate + 0.4 * self.last_10_win_rate

    @property
    def has_recent_form_data(self) -> bool:
        """Mindestens 3 Spielergebnisse vorhanden."""
        return len(self.recent_game_results) >= 3

    def __str__(self) -> str:
        form_str = ""
        if self.has_recent_form_data:
            form_str = f", L5: {self.last_5_win_rate:.0%}"
        return f"{self.name} ({self.wins}W/{self.losses}L, {self.win_rate:.1%}{form_str})"

    @classmethod
    def from_standings_response(cls, data: dict) -> "Team":
        return cls(
            team_id=data.get("id", 0),
            name=data.get("full_name", ""),
            abbreviation=data.get("abbreviation", ""),
            conference=data.get("conference", ""),
            division=data.get("division", ""),
        )
