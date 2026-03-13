"""Wettquoten-Client für die Odds API (https://the-odds-api.com)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.api.base_client import BaseApiClient, ApiError
from src.utils.config import Config


@dataclass
class GameOdds:
    home_team: str
    away_team: str
    odds_home: float
    odds_away: float
    bookmaker: str = "Durchschnitt"

    @property
    def implied_home_probability(self) -> float:
        if self.odds_home <= 0:
            return 0.5
        return 1.0 / self.odds_home

    @property
    def implied_away_probability(self) -> float:
        if self.odds_away <= 0:
            return 0.5
        return 1.0 / self.odds_away


class OddsApiClient(BaseApiClient):

    SPORT_KEY = "basketball_nba"
    REGION    = "eu"
    MARKET    = "h2h"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.base_url = config.odds_api_base_url
        self.api_key  = config.odds_api_key
        self.logger   = logging.getLogger(__name__)

    def get_odds(self, home_team: str, away_team: str) -> GameOdds | None:
        """Quoten für ein konkretes Matchup. None wenn kein Key oder kein Spiel gefunden."""
        if not self.api_key:
            self.logger.info("ODDS_API_KEY nicht gesetzt, überspringe Quoten.")
            return None
        all_odds = self._fetch_all_odds()
        if not all_odds:
            return None
        return self._find_matching_odds(all_odds, home_team, away_team)

    def get_all_upcoming_odds(self) -> list[GameOdds]:
        if not self.api_key:
            return []
        return [o for event in self._fetch_all_odds() if (o := self._parse_odds_event(event))]

    def _fetch_all_odds(self) -> list[dict]:
        url = f"{self.base_url}/sports/{self.SPORT_KEY}/odds"
        params = {
            "apiKey":     self.api_key,
            "regions":    self.REGION,
            "markets":    self.MARKET,
            "oddsFormat": "decimal",
        }
        try:
            resp = self.get(url, params=params)
            return resp if isinstance(resp, list) else []
        except ApiError as exc:
            self.logger.error("Fehler beim Laden der Wettquoten: %s", exc)
            return []

    def _find_matching_odds(
        self, events: list[dict], home_team: str, away_team: str
    ) -> GameOdds | None:
        home_lower = home_team.lower()
        away_lower = away_team.lower()
        for event in events:
            eh = event.get("home_team", "").lower()
            ea = event.get("away_team", "").lower()
            if any(w in eh for w in home_lower.split()) and \
               any(w in ea for w in away_lower.split()):
                return self._parse_odds_event(event)
        self.logger.info("Keine Quoten für %s vs %s", home_team, away_team)
        return None

    def _parse_odds_event(self, event: dict) -> GameOdds | None:
        """Mittelt die Quoten aller verfügbaren Buchmacher."""
        try:
            home = event["home_team"]
            away = event["away_team"]
            home_odds_list, away_odds_list = [], []

            for bm in event.get("bookmakers", []):
                for market in bm.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == home:
                            home_odds_list.append(float(outcome["price"]))
                        elif outcome["name"] == away:
                            away_odds_list.append(float(outcome["price"]))

            if not home_odds_list or not away_odds_list:
                return None

            return GameOdds(
                home_team=home,
                away_team=away,
                odds_home=round(sum(home_odds_list) / len(home_odds_list), 3),
                odds_away=round(sum(away_odds_list) / len(away_odds_list), 3),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.logger.debug("Quote konnte nicht geparst werden: %s", exc)
            return None
