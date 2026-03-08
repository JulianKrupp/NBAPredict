"""
NBA-API-Client basierend auf der BallDontLie API (https://www.balldontlie.io).

Free-Tier-kompatibel: Standings und Team-Stats werden aus den /games- und
/teams-Endpunkten berechnet, da /standings im Free-Tier nicht verfügbar ist.

Verfügbare Free-Tier-Endpunkte (relevant für dieses Projekt):
  GET /v1/teams          → alle 30 NBA-Teams
  GET /v1/games          → Spiele nach Datum, Saison, Team
  GET /v1/games/live     → aktuell laufende Spiele
  GET /v1/stats          → Spielerstatistiken
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from src.api.base_client import BaseApiClient, ApiError
from src.models.game import Game
from src.models.team import Team
from src.utils.config import Config

# Bekannte NBA-Teamnamen-Aliase für die Suche
TEAM_NAME_ALIASES: dict[str, str] = {
    "lakers":    "Los Angeles Lakers",
    "celtics":   "Boston Celtics",
    "warriors":  "Golden State Warriors",
    "bulls":     "Chicago Bulls",
    "heat":      "Miami Heat",
    "nets":      "Brooklyn Nets",
    "knicks":    "New York Knicks",
    "bucks":     "Milwaukee Bucks",
    "suns":      "Phoenix Suns",
    "nuggets":   "Denver Nuggets",
    "sixers":    "Philadelphia 76ers",
    "raptors":   "Toronto Raptors",
    "mavs":      "Dallas Mavericks",
    "clippers":  "Los Angeles Clippers",
    "spurs":     "San Antonio Spurs",
    "thunder":   "Oklahoma City Thunder",
    "jazz":      "Utah Jazz",
    "hawks":     "Atlanta Hawks",
    "cavaliers": "Cleveland Cavaliers",
    "pistons":   "Detroit Pistons",
    "wolves":    "Minnesota Timberwolves",
    "timberwolves": "Minnesota Timberwolves",
    "pacers":    "Indiana Pacers",
    "hornets":   "Charlotte Hornets",
    "wizards":   "Washington Wizards",
    "magic":     "Orlando Magic",
    "blazers":   "Portland Trail Blazers",
    "grizzlies": "Memphis Grizzlies",
    "pelicans":  "New Orleans Pelicans",
    "kings":     "Sacramento Kings",
    "rockets":   "Houston Rockets",
}

# NBA.com Team-IDs (stabil, werden für Team-Lookups verwendet)
# BallDontLie IDs – aus /v1/teams abrufbar
_KNOWN_TEAM_IDS: dict[str, int] = {
    "Atlanta Hawks": 1, "Boston Celtics": 2, "Brooklyn Nets": 3,
    "Charlotte Hornets": 4, "Chicago Bulls": 5, "Cleveland Cavaliers": 6,
    "Dallas Mavericks": 7, "Denver Nuggets": 8, "Detroit Pistons": 9,
    "Golden State Warriors": 10, "Houston Rockets": 11, "Indiana Pacers": 12,
    "Los Angeles Clippers": 13, "Los Angeles Lakers": 14, "Memphis Grizzlies": 15,
    "Miami Heat": 16, "Milwaukee Bucks": 17, "Minnesota Timberwolves": 18,
    "New Orleans Pelicans": 19, "New York Knicks": 20, "Oklahoma City Thunder": 21,
    "Orlando Magic": 22, "Philadelphia 76ers": 23, "Phoenix Suns": 24,
    "Portland Trail Blazers": 25, "Sacramento Kings": 26, "San Antonio Spurs": 27,
    "Toronto Raptors": 28, "Utah Jazz": 29, "Washington Wizards": 30,
}


class NBAApiClient(BaseApiClient):
    """
    Client für die BallDontLie NBA-API (Free-Tier-kompatibel).

    Da /standings im Free-Tier gesperrt ist, werden Tabellenstände und
    Team-Statistiken direkt aus den Spielergebnissen (/games) berechnet.
    """

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.base_url = config.balldontlie_base_url
        self._default_headers = {"Authorization": config.balldontlie_api_key}
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def get_live_games(self) -> list[Game]:
        """Gibt alle aktuell laufenden Spiele zurück."""
        try:
            response = self.get(
                f"{self.base_url}/games/live",
                headers=self._default_headers,
            )
            return self._parse_games(response.get("data", []))
        except ApiError as exc:
            self.logger.error("Fehler beim Laden der Live-Spiele: %s", exc)
            return []

    def get_games_by_date(self, target_date: str | None = None) -> list[Game]:
        """Gibt alle Spiele eines bestimmten Datums zurück."""
        game_date = target_date or str(date.today())
        try:
            response = self.get(
                f"{self.base_url}/games",
                params={"dates[]": game_date, "per_page": 100},
                headers=self._default_headers,
            )
            return self._parse_games(response.get("data", []))
        except ApiError as exc:
            self.logger.error("Fehler beim Laden der Spiele für %s: %s", game_date, exc)
            return []

    def get_standings(self, season: int = 2024) -> list[Team]:
        """
        Berechnet Tabellenstände aus Spielergebnissen (Free-Tier-kompatibel).

        Der /standings-Endpunkt ist im Free-Tier gesperrt. Diese Methode
        lädt stattdessen alle abgeschlossenen Spiele der Saison und berechnet
        Siege, Niederlagen und Punktdurchschnitte selbst.

        Args:
            season: NBA-Saison (z.B. 2024 für 2024/25).

        Returns:
            Liste von Team-Objekten, sortiert nach Win-Rate.
        """
        self.logger.info(
            "Berechne Standings aus Spielergebnissen (Free-Tier, Saison %d)...", season
        )
        games = self._fetch_season_games_paginated(season, max_games=400)
        if not games:
            self.logger.warning("Keine Spieldaten für Saison %d gefunden.", season)
            return []

        teams = self._calculate_standings_from_games(games, season)
        return sorted(teams.values(), key=lambda t: t.win_rate, reverse=True)

    def get_team_stats(self, team_name: str, season: int = 2024) -> Team | None:
        """
        Gibt aggregierte Statistiken für ein Team zurück.

        Args:
            team_name: Teamname oder Alias (z.B. 'lakers').
            season:    NBA-Saison.

        Returns:
            Team-Objekt oder None wenn nicht gefunden.
        """
        resolved_name = self._resolve_team_name(team_name)
        standings = self.get_standings(season)
        for team in standings:
            if resolved_name.lower() in team.name.lower():
                return team
        self.logger.warning("Team '%s' nicht gefunden.", team_name)
        return None

    def get_recent_games(self, team_name: str, num_games: int = 10) -> list[Game]:
        """Gibt die letzten N abgeschlossenen Spiele eines Teams zurück."""
        resolved_name = self._resolve_team_name(team_name)
        team_id = self._find_team_id(resolved_name)
        if team_id is None:
            self.logger.warning("Team-ID für '%s' nicht gefunden.", team_name)
            return []
        try:
            response = self.get(
                f"{self.base_url}/games",
                params={
                    "team_ids[]": team_id,
                    "per_page": min(num_games * 2, 100),
                    "seasons[]": 2024,
                },
                headers=self._default_headers,
            )
            games = self._parse_games(response.get("data", []))
            return [g for g in games if g.is_final][:num_games]
        except ApiError as exc:
            self.logger.error("Fehler beim Laden der letzten Spiele: %s", exc)
            return []

    # ── Private: Spieledaten laden ────────────────────────────────────────

    def _fetch_season_games_paginated(
        self, season: int, max_games: int = 400
    ) -> list[Game]:
        """
        Lädt abgeschlossene Spiele einer Saison seitenweise über /v1/games.

        Args:
            season:    NBA-Saison.
            max_games: Maximale Anzahl zu ladender Spiele.

        Returns:
            Liste abgeschlossener Game-Objekte.
        """
        collected: list[Game] = []
        cursor: int | None = None

        while len(collected) < max_games:
            params: dict = {
                "seasons[]": season,
                "per_page": 100,
            }
            if cursor is not None:
                params["cursor"] = cursor

            try:
                response = self.get(
                    f"{self.base_url}/games",
                    params=params,
                    headers=self._default_headers,
                )
            except ApiError as exc:
                self.logger.error("Fehler beim Laden der Spiele (cursor=%s): %s", cursor, exc)
                break

            raw_games = response.get("data", [])
            if not raw_games:
                break

            for raw in raw_games:
                try:
                    game = Game.from_api_response(raw)
                    if game.is_final and game.home_score > 0:
                        collected.append(game)
                except (KeyError, ValueError, TypeError):
                    continue

            # Cursor-basierte Pagination (neues BallDontLie v1 Format)
            meta = response.get("meta", {})
            next_cursor = meta.get("next_cursor")
            if not next_cursor:
                break
            cursor = next_cursor

        self.logger.debug(
            "Saison %d: %d abgeschlossene Spiele geladen", season, len(collected)
        )
        return collected

    # ── Private: Standings berechnen ──────────────────────────────────────

    def _calculate_standings_from_games(
        self, games: list[Game], season: int
    ) -> dict[str, Team]:
        """
        Berechnet Teamstatistiken aus einer Liste abgeschlossener Spiele.

        Args:
            games:  Liste abgeschlossener Spiele.
            season: NBA-Saison (für Team-ID-Lookup).

        Returns:
            Dictionary: Teamname → Team-Objekt mit berechneten Statistiken.
        """
        # Akkumulatoren pro Team
        stats: dict[str, dict] = defaultdict(lambda: {
            "wins": 0, "losses": 0,
            "home_wins": 0, "home_losses": 0,
            "away_wins": 0, "away_losses": 0,
            "pts_scored": 0, "pts_allowed": 0,
            "games": 0,
        })

        for game in games:
            home = game.home_team
            away = game.away_team
            home_won = game.home_score > game.away_score

            # Heimteam
            stats[home]["games"] += 1
            stats[home]["pts_scored"] += game.home_score
            stats[home]["pts_allowed"] += game.away_score
            if home_won:
                stats[home]["wins"] += 1
                stats[home]["home_wins"] += 1
            else:
                stats[home]["losses"] += 1
                stats[home]["home_losses"] += 1

            # Auswärtsteam
            stats[away]["games"] += 1
            stats[away]["pts_scored"] += game.away_score
            stats[away]["pts_allowed"] += game.home_score
            if not home_won:
                stats[away]["wins"] += 1
                stats[away]["away_wins"] += 1
            else:
                stats[away]["losses"] += 1
                stats[away]["away_losses"] += 1

        # Team-Objekte erstellen
        teams: dict[str, Team] = {}
        all_team_ids = self._load_team_ids()

        for team_name, s in stats.items():
            if s["games"] == 0:
                continue
            team_id = all_team_ids.get(team_name, _KNOWN_TEAM_IDS.get(team_name, 0))
            team = Team(
                team_id=team_id,
                name=team_name,
                abbreviation=team_name[:3].upper(),
                wins=s["wins"],
                losses=s["losses"],
                home_wins=s["home_wins"],
                home_losses=s["home_losses"],
                away_wins=s["away_wins"],
                away_losses=s["away_losses"],
                avg_points_scored=round(s["pts_scored"] / s["games"], 1),
                avg_points_allowed=round(s["pts_allowed"] / s["games"], 1),
            )
            teams[team_name] = team

        return teams

    def _load_team_ids(self) -> dict[str, int]:
        """Lädt Team-IDs aus /v1/teams (gecacht)."""
        try:
            response = self.get(
                f"{self.base_url}/teams",
                params={"per_page": 100},
                headers=self._default_headers,
            )
            return {
                t.get("full_name", ""): int(t["id"])
                for t in response.get("data", [])
                if t.get("full_name")
            }
        except ApiError as exc:
            self.logger.debug("Team-IDs konnten nicht geladen werden: %s", exc)
            return {}

    def _find_team_id(self, team_name: str) -> int | None:
        """Sucht die Team-ID anhand des Namens."""
        # Erst lokales Mapping prüfen (kein API-Call nötig)
        for known_name, known_id in _KNOWN_TEAM_IDS.items():
            if team_name.lower() in known_name.lower():
                return known_id
        # Dann API-Lookup
        ids = self._load_team_ids()
        for name, tid in ids.items():
            if team_name.lower() in name.lower():
                return tid
        return None

    def _parse_games(self, raw_games: list[dict]) -> list[Game]:
        """Konvertiert Rohdaten in Game-Objekte."""
        games = []
        for raw in raw_games:
            try:
                games.append(Game.from_api_response(raw))
            except (KeyError, ValueError, TypeError) as exc:
                self.logger.warning("Spiel übersprungen: %s", exc)
        return games

    def _parse_standings(self, raw_standings: list[dict]) -> list[Team]:
        """Konvertiert Rohdaten in Team-Objekte (für direkten /standings-Aufruf)."""
        teams = []
        for raw in raw_standings:
            try:
                teams.append(Team.from_standings_response(raw))
            except (KeyError, ValueError, TypeError) as exc:
                self.logger.warning("Team übersprungen: %s", exc)
        return teams

    @staticmethod
    def _resolve_team_name(name: str) -> str:
        """Löst Teamnamen-Aliase auf."""
        return TEAM_NAME_ALIASES.get(name.lower(), name)
