"""
Wettquoten-Client basierend auf der Odds API (https://the-odds-api.com).
Ruft aktuelle Buchmacher-Quoten für NBA-Spiele ab.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.api.base_client import BaseApiClient, ApiError
from src.utils.config import Config


@dataclass
class GameOdds:
    """Repräsentiert die Wettquoten eines NBA-Spiels."""
    home_team: str
    away_team: str
    odds_home: float
    odds_away: float
    bookmaker: str = "Durchschnitt"

    @property
    def implied_home_probability(self) -> float:
        """Berechnet die implizite Siegwahrscheinlichkeit des Heimteams."""
        if self.odds_home <= 0:
            return 0.5
        return 1.0 / self.odds_home

    @property
    def implied_away_probability(self) -> float:
        """Berechnet die implizite Siegwahrscheinlichkeit des Auswärtsteams."""
        if self.odds_away <= 0:
            return 0.5
        return 1.0 / self.odds_away


class OddsApiClient(BaseApiClient):
    """Client für die Odds API – liefert Wettquoten für NBA-Spiele."""

    SPORT_KEY = "basketball_nba"
    REGION    = "eu"
    MARKET    = "h2h"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.base_url  = config.odds_api_base_url
        self.api_key   = config.odds_api_key
        self.logger    = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def get_odds(self, home_team: str, away_team: str) -> GameOdds | None:
        """
        Gibt die aktuellen Wettquoten für ein bestimmtes Spiel zurück.

        Args:
            home_team: Name des Heimteams.
            away_team: Name des Auswärtsteams.

        Returns:
            GameOdds-Objekt oder None, wenn keine Quoten verfügbar.
        """
        if not self.api_key:
            self.logger.info("Odds-API-Key nicht gesetzt – Quoten werden übersprungen.")
            return None

        all_odds = self._fetch_all_odds()
        if not all_odds:
            return None

        return self._find_matching_odds(all_odds, home_team, away_team)

    def get_all_upcoming_odds(self) -> list[GameOdds]:
        """
        Gibt Quoten für alle bevorstehenden NBA-Spiele zurück.

        Returns:
            Liste von GameOdds-Objekten.
        """
        if not self.api_key:
            return []

        all_odds = self._fetch_all_odds()
        return [self._parse_odds_event(event) for event in all_odds if event]

    # ── Private Hilfsmethoden ─────────────────────────────────────────────

    def _fetch_all_odds(self) -> list[dict]:
        """Ruft alle aktuellen NBA-Quoten von der API ab."""
        url = f"{self.base_url}/sports/{self.SPORT_KEY}/odds"
        params = {
            "apiKey":  self.api_key,
            "regions": self.REGION,
            "markets": self.MARKET,
            "oddsFormat": "decimal",
        }
        try:
            response = self.get(url, params=params)
            return response if isinstance(response, list) else []
        except ApiError as exc:
            self.logger.error("Fehler beim Laden der Wettquoten: %s", exc)
            return []

    def _find_matching_odds(
        self, events: list[dict], home_team: str, away_team: str
    ) -> GameOdds | None:
        """
        Sucht ein passendes Spiel in der Ereignisliste.

        Args:
            events:    Liste aller Spielereignisse mit Quoten.
            home_team: Gesuchtes Heimteam.
            away_team: Gesuchtes Auswärtsteam.

        Returns:
            Passendes GameOdds-Objekt oder None.
        """
        home_lower = home_team.lower()
        away_lower = away_team.lower()

        for event in events:
            event_home = event.get("home_team", "").lower()
            event_away = event.get("away_team", "").lower()

            home_match = any(word in event_home for word in home_lower.split())
            away_match = any(word in event_away for word in away_lower.split())

            if home_match and away_match:
                return self._parse_odds_event(event)

        self.logger.info(
            "Keine Quoten gefunden für %s vs %s", home_team, away_team
        )
        return None

    def _parse_odds_event(self, event: dict) -> GameOdds | None:
        """
        Extrahiert Quoten aus einem API-Ereignisobjekt.

        Berechnet den Durchschnitt über alle verfügbaren Buchmacher.

        Args:
            event: Rohdaten eines Spielereignisses.

        Returns:
            GameOdds-Objekt oder None bei fehlerhaften Daten.
        """
        try:
            home_team = event["home_team"]
            away_team = event["away_team"]
            bookmakers = event.get("bookmakers", [])

            if not bookmakers:
                return None

            home_odds_list: list[float] = []
            away_odds_list: list[float] = []

            for bookmaker in bookmakers:
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        price = float(outcome.get("price", 0))
                        if outcome["name"].lower() in home_team.lower():
                            home_odds_list.append(price)
                        elif outcome["name"].lower() in away_team.lower():
                            away_odds_list.append(price)

            if not home_odds_list or not away_odds_list:
                return None

            return GameOdds(
                home_team=home_team,
                away_team=away_team,
                odds_home=sum(home_odds_list) / len(home_odds_list),
                odds_away=sum(away_odds_list) / len(away_odds_list),
            )

        except (KeyError, ValueError, ZeroDivisionError) as exc:
            self.logger.warning("Fehler beim Parsen der Quoten: %s", exc)
            return None
