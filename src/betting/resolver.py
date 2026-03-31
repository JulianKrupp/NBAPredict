"""
Automatische Wettauflösung.

Prüft offene Wetten gegen die tatsächlichen Spielergebnisse
und löst sie als 'won' oder 'lost' auf.

Kann per Cron-Job auf dem Raspberry Pi laufen:
  python scripts/resolve_bets.py
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from src.api.nba_api_client import NBAApiClient
from src.betting.tracker import BettingTracker
from src.utils.config import Config

logger = logging.getLogger(__name__)


class BetResolver:
    """
    Löst offene Wetten automatisch auf, indem die
    tatsächlichen Spielergebnisse abgefragt werden.
    """

    def __init__(self, config: Config, tracker: BettingTracker | None = None) -> None:
        self.config = config
        self.nba_client = NBAApiClient(config)
        self.tracker = tracker or BettingTracker()
        self.logger = logging.getLogger(__name__)

    def resolve_all_open(self) -> dict:
        """
        Versucht alle offenen Wetten aufzulösen.

        Prüft die Spiele der letzten 3 Tage und matcht sie
        gegen offene Wetten anhand der Teamnamen.

        Returns:
            dict mit Zusammenfassung:
              { resolved: int, won: int, lost: int, still_open: int, errors: int }
        """
        open_bets = self.tracker.get_open_bets()
        if not open_bets:
            self.logger.info("Keine offenen Wetten vorhanden.")
            return {"resolved": 0, "won": 0, "lost": 0, "still_open": 0, "errors": 0}

        self.logger.info("%d offene Wetten gefunden, suche Ergebnisse...", len(open_bets))

        # Spiele der letzten 3 Tage laden
        recent_games = self._fetch_recent_finished_games(days_back=3)
        self.logger.info("%d beendete Spiele gefunden.", len(recent_games))

        resolved = 0
        won = 0
        lost = 0
        errors = 0

        for bet in open_bets:
            try:
                game_result = self._find_game_result(bet, recent_games)
                if game_result is None:
                    continue  # Spiel noch nicht beendet

                result = self.tracker.resolve_bet(
                    bet.id, game_result["winner"],
                    home_score=game_result.get("home_score"),
                    away_score=game_result.get("away_score"),
                )
                if result:
                    resolved += 1
                    if result.is_won:
                        won += 1
                    else:
                        lost += 1
            except Exception as exc:
                self.logger.error("Fehler bei Wette #%d: %s", bet.id, exc)
                errors += 1

        still_open = len(open_bets) - resolved
        self.logger.info(
            "Auflösung fertig: %d aufgelöst (%d W / %d L), %d offen, %d Fehler",
            resolved, won, lost, still_open, errors,
        )

        return {
            "resolved": resolved,
            "won": won,
            "lost": lost,
            "still_open": still_open,
            "errors": errors,
        }

    def _fetch_recent_finished_games(self, days_back: int = 3) -> list[dict]:
        """
        Lädt beendete Spiele der letzten N Tage.

        Returns:
            Liste von dicts mit: home, away, winner, date
        """
        games = []
        today = date.today()

        for i in range(days_back + 1):
            check_date = today - timedelta(days=i)
            date_str = check_date.isoformat()

            try:
                day_games = self.nba_client.get_games_by_date(date_str)
                for g in day_games:
                    if g.is_final and g.winner:
                        games.append({
                            "home": g.home_team,
                            "away": g.away_team,
                            "winner": g.winner,
                            "home_score": g.home_score,
                            "away_score": g.away_score,
                            "date": date_str,
                        })
            except Exception as exc:
                self.logger.warning("Spiele für %s nicht ladbar: %s", date_str, exc)

        return games

    @staticmethod
    def _find_game_result(bet, games: list[dict]) -> dict | None:
        """
        Findet das Ergebnis des Spiels, das zur Wette passt.

        Matcht über Teamnamen (case-insensitive, Teilstring-Match).
        Returns dict mit winner, home_score, away_score oder None.
        """
        bet_home = bet.home_team.lower()
        bet_away = bet.away_team.lower()

        for game in games:
            game_home = game["home"].lower()
            game_away = game["away"].lower()

            # Flexibles Matching: mindestens ein Wort muss passen
            home_match = any(w in game_home for w in bet_home.split()) or \
                         any(w in bet_home for w in game_home.split())
            away_match = any(w in game_away for w in bet_away.split()) or \
                         any(w in bet_away for w in game_away.split())

            if home_match and away_match:
                return {
                    "winner": game["winner"],
                    "home_score": game.get("home_score"),
                    "away_score": game.get("away_score"),
                }

        return None  # Spiel noch nicht beendet
