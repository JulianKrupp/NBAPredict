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

    # Tage seit dem letzten Spiel (0 = Back-to-Back).
    days_rest: int = 2

    # Anzahl Spiele in den letzten 7 Tagen (Belastungsindikator).
    # Der Faktor density_fatigue ist bei 2 Spielen/7 Tagen bei 0.0
    games_last_7_days: int = 2

    # ── Properties: Basis ─────────────────────────────────────────────────

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

    # ── Properties: Form & Streaks ────────────────────────────────────────

    @property
    def last_3_win_rate(self) -> float:
        """Siegquote der letzten 3 Spiele – kurzfristigster Formindikator."""
        results = self.recent_game_results[-3:]
        if not results:
            return self.win_rate
        return sum(results) / len(results)

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
    def current_streak(self) -> int:
        """Aktuelle Serie: positiv = Siegesserie, negativ = Niederlagenserie.
        last_result True bei Sieg, False bei Niederlage

        Beispiel: [W, W, L, W, W, W] → +3  (drei Siege in Folge)
                  [W, L, L, L]       → -3  (drei Niederlagen in Folge)
                  []                 →  0
        """
        if not self.recent_game_results:
            return 0
        streak = 0
        last_result = self.recent_game_results[-1]
        for result in reversed(self.recent_game_results):
            if result == last_result:
                streak += 1
            else:
                break
        return streak if last_result else -streak

    @property
    def form_rating(self) -> float:
        """Gewichtete Formkurve: L3 (30 %) + L5 (40 %) + L10 (30 %).

        Drei Fenster geben ein ausgewogeneres Bild als nur L5/L10:
        - L3 fängt *ganz aktuelle* Dynamik ein (z. B. Spieler-Rückkehr).
        - L5 ist der Kern-Formindikator.
        - L10 glättet Ausreißer und verhindert Überreaktion.
        """
        if not self.recent_game_results:
            return self.win_rate
        return (
            0.30 * self.last_3_win_rate
            + 0.40 * self.last_5_win_rate
            + 0.30 * self.last_10_win_rate
        )

    @property
    def has_recent_form_data(self) -> bool:
        """Mindestens 3 Spielergebnisse vorhanden."""
        return len(self.recent_game_results) >= 3

    # ── Properties: Belastung ─────────────────────────────────────────────

    @property
    def fatigue_score(self) -> float:
        """Ermüdungswert zwischen 0.0 (ausgeruht) und 1.0 (stark belastet).

        Kombiniert Ruhetage und Spieldichte der letzten Woche.
        """
        # Ruhetage: 0 → 1.0 (B2B), 1 → 0.45, 2 → 0.15, 3+ → 0.0
        if self.days_rest >= 3:
            rest_fatigue = 0.0
        elif self.days_rest == 2:
            rest_fatigue = 0.15
        elif self.days_rest == 1:
            rest_fatigue = 0.45
        else:
            rest_fatigue = 1.0

        # Spieldichte: 4+ Spiele in 7 Tagen = maximale Belastung
        density_fatigue = min(1.0, max(0.0, (self.games_last_7_days - 2) / 2.0))

        return 0.65 * rest_fatigue + 0.35 * density_fatigue

    # ── Dunder & Factory ──────────────────────────────────────────────────

    def __str__(self) -> str:
        return f"{self.name} ({self.wins}-{self.losses})"

    @classmethod
    def from_standings_response(cls, raw: dict) -> "Team":
        """Erstellt ein Team aus einer API-Antwort (Standings-Endpoint)."""
        team_data = raw.get("team", raw)
        return cls(
            team_id=team_data.get("id", 0),
            name=team_data.get("full_name", team_data.get("name", "Unknown")),
            abbreviation=team_data.get("abbreviation", "???"),
            conference=team_data.get("conference", ""),
            division=team_data.get("division", ""),
            wins=raw.get("wins", 0),
            losses=raw.get("losses", 0),
            home_wins=raw.get("home_wins", 0),
            home_losses=raw.get("home_losses", 0),
            away_wins=raw.get("away_wins", 0),
            away_losses=raw.get("away_losses", 0),
            avg_points_scored=raw.get("pts", 0.0),
            avg_points_allowed=raw.get("opp_pts", 0.0),
        )
