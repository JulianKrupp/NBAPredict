"""
BallDontLie API-Client (Free-Tier).

Der /standings-Endpunkt ist im Free-Tier gesperrt, daher werden
Tabellenstände aus den Spielergebnissen (/games) selbst berechnet.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from src.api.base_client import BaseApiClient, ApiError
from src.models.game import Game
from src.models.team import Team
from src.utils.config import Config

TEAM_NAME_ALIASES: dict[str, str] = {
    "lakers":       "Los Angeles Lakers",
    "celtics":      "Boston Celtics",
    "warriors":     "Golden State Warriors",
    "bulls":        "Chicago Bulls",
    "heat":         "Miami Heat",
    "nets":         "Brooklyn Nets",
    "knicks":       "New York Knicks",
    "bucks":        "Milwaukee Bucks",
    "suns":         "Phoenix Suns",
    "nuggets":      "Denver Nuggets",
    "sixers":       "Philadelphia 76ers",
    "raptors":      "Toronto Raptors",
    "mavs":         "Dallas Mavericks",
    "clippers":              "LA Clippers",
    "los angeles clippers":  "LA Clippers",
    "la clippers":           "LA Clippers",
    "spurs":        "San Antonio Spurs",
    "thunder":      "Oklahoma City Thunder",
    "jazz":         "Utah Jazz",
    "hawks":        "Atlanta Hawks",
    "cavaliers":    "Cleveland Cavaliers",
    "pistons":      "Detroit Pistons",
    "wolves":       "Minnesota Timberwolves",
    "timberwolves": "Minnesota Timberwolves",
    "pacers":       "Indiana Pacers",
    "hornets":      "Charlotte Hornets",
    "wizards":      "Washington Wizards",
    "magic":        "Orlando Magic",
    "blazers":      "Portland Trail Blazers",
    "grizzlies":    "Memphis Grizzlies",
    "pelicans":     "New Orleans Pelicans",
    "kings":        "Sacramento Kings",
    "rockets":      "Houston Rockets",
}

_KNOWN_TEAM_IDS: dict[str, int] = {
    "Atlanta Hawks": 1,         "Boston Celtics": 2,        "Brooklyn Nets": 3,
    "Charlotte Hornets": 4,     "Chicago Bulls": 5,         "Cleveland Cavaliers": 6,
    "Dallas Mavericks": 7,      "Denver Nuggets": 8,        "Detroit Pistons": 9,
    "Golden State Warriors": 10,"Houston Rockets": 11,      "Indiana Pacers": 12,
    "Los Angeles Clippers": 13, "Los Angeles Lakers": 14,   "Memphis Grizzlies": 15,
    "Miami Heat": 16,           "Milwaukee Bucks": 17,      "Minnesota Timberwolves": 18,
    "New Orleans Pelicans": 19, "New York Knicks": 20,      "Oklahoma City Thunder": 21,
    "Orlando Magic": 22,        "Philadelphia 76ers": 23,   "Phoenix Suns": 24,
    "Portland Trail Blazers": 25,"Sacramento Kings": 26,    "San Antonio Spurs": 27,
    "Toronto Raptors": 28,      "Utah Jazz": 29,            "Washington Wizards": 30,
}


class NBAApiClient(BaseApiClient):

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.base_url = config.balldontlie_base_url
        self._default_headers = {"Authorization": config.balldontlie_api_key}
        self.logger = logging.getLogger(__name__)

    def get_live_games(self) -> list[Game]:
        try:
            resp = self.get(f"{self.base_url}/games/live", headers=self._default_headers)
            return self._parse_games(resp.get("data", []))
        except ApiError as exc:
            self.logger.error("Live-Spiele konnten nicht geladen werden: %s", exc)
            return []

    def get_games_by_date(self, target_date: str | None = None) -> list[Game]:
        game_date = target_date or str(date.today())
        try:
            resp = self.get(
                f"{self.base_url}/games",
                params={"dates[]": game_date, "per_page": 100},
                headers=self._default_headers,
            )
            return self._parse_games(resp.get("data", []))
        except ApiError as exc:
            self.logger.error("Spiele für %s konnten nicht geladen werden: %s", game_date, exc)
            return []

    def _current_season(self) -> int:
        """Gibt das aktuelle NBA-Saisonstart-Jahr zurück.
        NBA-Saison beginnt im Oktober: Oct 2025 – Jun 2026 = season 2025.
        """
        today = date.today()
        return today.year if today.month >= 10 else today.year - 1

    def get_standings(self, season: int | None = None) -> list[Team]:
        """Berechnet Standings aus Spielergebnissen (Free-Tier-Workaround)."""
        if season is None:
            season = self._current_season()
        self.logger.info("Lade Standings via /games (Saison %d)...", season)
        games = self._fetch_season_games_paginated(season, max_games=400)
        if not games:
            self.logger.warning("Keine Spieldaten für Saison %d.", season)
            return []
        teams = self._calculate_standings_from_games(games, season)
        return sorted(teams.values(), key=lambda t: t.win_rate, reverse=True)

    def get_team_stats(self, team_name: str, season: int | None = None) -> Team | None:
        resolved = self._resolve_team_name(team_name)
        for team in self.get_standings(season):
            if resolved.lower() in team.name.lower():
                return team
        self.logger.warning("Team '%s' nicht gefunden.", team_name)
        return None

    def get_recent_games(self, team_name: str, num_games: int = 10) -> list[Game]:
        resolved = self._resolve_team_name(team_name)
        team_id = self._find_team_id(resolved)
        if team_id is None:
            self.logger.warning("Team-ID für '%s' nicht gefunden.", team_name)
            return []
        try:
            resp = self.get(
                f"{self.base_url}/games",
                params={"team_ids[]": team_id, "per_page": min(num_games * 2, 100), "seasons[]": self._current_season()},
                headers=self._default_headers,
            )
            games = self._parse_games(resp.get("data", []))
            return [g for g in games if g.is_final][:num_games]
        except ApiError as exc:
            self.logger.error("Letzte Spiele für '%s' nicht ladbar: %s", team_name, exc)
            return []

    def _fetch_season_games_paginated(self, season: int, max_games: int = 400) -> list[Game]:
        collected: list[Game] = []
        cursor: int | None = None

        while len(collected) < max_games:
            params: dict = {"seasons[]": season, "per_page": 100}
            if cursor is not None:
                params["cursor"] = cursor
            try:
                resp = self.get(f"{self.base_url}/games", params=params, headers=self._default_headers)
            except ApiError as exc:
                self.logger.error("Seitenladefehler (cursor=%s): %s", cursor, exc)
                break

            raw_games = resp.get("data", [])
            if not raw_games:
                break

            for raw in raw_games:
                try:
                    game = Game.from_api_response(raw)
                    if game.is_final and game.home_score > 0:
                        collected.append(game)
                except (KeyError, ValueError, TypeError):
                    continue

            next_cursor = resp.get("meta", {}).get("next_cursor")
            if not next_cursor:
                break
            cursor = next_cursor

        self.logger.debug("Saison %d: %d Spiele geladen.", season, len(collected))
        return collected

    def _calculate_standings_from_games(self, games: list[Game], season: int) -> dict[str, Team]:
        """
        Berechnet Win/Loss-Statistiken aus der Spielliste.

        Spiele werden zuerst chronologisch sortiert, damit recent_game_results
        die tatsächliche Reihenfolge widerspiegelt (ältestes Spiel zuerst).
        """
        sorted_games = sorted(games, key=lambda g: g.date)

        stats: dict[str, dict] = defaultdict(lambda: {
            "wins": 0, "losses": 0,
            "home_wins": 0, "home_losses": 0,
            "away_wins": 0, "away_losses": 0,
            "pts_scored": 0, "pts_allowed": 0,
            "games": 0,
            "results": [],  # chronologische Siegfolge (True = Sieg)
        })

        for game in sorted_games:
            home, away = game.home_team, game.away_team
            home_won = game.home_score > game.away_score

            stats[home]["games"] += 1
            stats[home]["pts_scored"]  += game.home_score
            stats[home]["pts_allowed"] += game.away_score
            stats[home]["results"].append(home_won)
            if home_won:
                stats[home]["wins"] += 1
                stats[home]["home_wins"] += 1
            else:
                stats[home]["losses"] += 1
                stats[home]["home_losses"] += 1

            stats[away]["games"] += 1
            stats[away]["pts_scored"]  += game.away_score
            stats[away]["pts_allowed"] += game.home_score
            stats[away]["results"].append(not home_won)
            if not home_won:
                stats[away]["wins"] += 1
                stats[away]["away_wins"] += 1
            else:
                stats[away]["losses"] += 1
                stats[away]["away_losses"] += 1

        all_team_ids = self._load_team_ids()
        teams: dict[str, Team] = {}

        for name, s in stats.items():
            if s["games"] == 0:
                continue
            team_id = all_team_ids.get(name, _KNOWN_TEAM_IDS.get(name, 0))
            teams[name] = Team(
                team_id=team_id,
                name=name,
                abbreviation=name[:3].upper(),
                wins=s["wins"],
                losses=s["losses"],
                home_wins=s["home_wins"],
                home_losses=s["home_losses"],
                away_wins=s["away_wins"],
                away_losses=s["away_losses"],
                avg_points_scored=round(s["pts_scored"] / s["games"], 1),
                avg_points_allowed=round(s["pts_allowed"] / s["games"], 1),
                recent_game_results=s["results"],
            )

        return teams

    def _load_team_ids(self) -> dict[str, int]:
        try:
            resp = self.get(
                f"{self.base_url}/teams",
                params={"per_page": 100},
                headers=self._default_headers,
            )
            return {t.get("full_name", ""): int(t["id"]) for t in resp.get("data", []) if t.get("full_name")}
        except ApiError as exc:
            self.logger.debug("Team-IDs konnten nicht geladen werden: %s", exc)
            return {}

    def _find_team_id(self, team_name: str) -> int | None:
        for known_name, known_id in _KNOWN_TEAM_IDS.items():
            if team_name.lower() in known_name.lower():
                return known_id
        ids = self._load_team_ids()
        for name, tid in ids.items():
            if team_name.lower() in name.lower():
                return tid
        return None

    def _parse_games(self, raw_games: list[dict]) -> list[Game]:
        games = []
        for raw in raw_games:
            try:
                games.append(Game.from_api_response(raw))
            except (KeyError, ValueError, TypeError) as exc:
                self.logger.warning("Spiel übersprungen: %s", exc)
        return games

    @staticmethod
    def _resolve_team_name(name: str) -> str:
        return TEAM_NAME_ALIASES.get(name.lower(), name)
