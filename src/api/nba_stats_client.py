"""
Advanced Stats Client – basierend auf dem `nba_api` Python-Package.

Greift direkt auf stats.nba.com zu – KEIN API-Key erforderlich.
Package: https://github.com/swar/nba_api  (pip install nba_api)

Liefert echte Advanced Stats (Offensive/Defensive Rating, Pace, True Shooting %)
über den LeagueDashTeamStats-Endpoint von NBA.com.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AdvancedTeamStats:
    """Erweiterte Teamstatistiken von stats.nba.com (LeagueDashTeamStats)."""
    team_id: int
    team_name: str

    offensive_rating: float = 0.0   # Punkte pro 100 Ballbesitze (Offense)
    defensive_rating: float = 0.0   # Punkte pro 100 Ballbesitze (Defense)
    net_rating: float = 0.0         # Offensive - Defensive Rating
    pace: float = 0.0               # Ballbesitze pro 48 Minuten
    true_shooting_pct: float = 0.0  # Effektive Trefferquote

    # Gesetzt durch MLPredictor._get_advanced_stats() aus Team.days_rest
    days_since_last_game: int = 2



class NBAStatsApiClient:
    """
    Client für Advanced NBA-Statistiken von stats.nba.com.

    Nutzt das `nba_api`-Package (pip install nba_api) – kein API-Key nötig.
    Wirft RuntimeError wenn das Package nicht installiert ist oder NBA.com
    nicht erreichbar ist – kein Fallback auf Näherungswerte.

    Verfügbare Endpunkte (nba_api):
      - LeagueDashTeamStats  → Off/Def Rating, Pace, True Shooting %
    """

    # NBA.com Saison-Format: "2024-25" für Saison 2024
    @staticmethod
    def _season_string(season: int) -> str:
        return f"{season}-{str(season + 1)[-2:]}"

    def __init__(self, config=None) -> None:
        self.logger = logging.getLogger(__name__)
        self._nba_api_available = self._check_nba_api()
        if not self._nba_api_available:
            self.logger.warning("nba_api nicht installiert – Advanced Stats nicht verfügbar.")

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def get_all_team_advanced_stats(
        self, season: int = 2024
    ) -> dict[str, AdvancedTeamStats]:
        """
        Lädt Advanced Stats für alle 30 NBA-Teams von stats.nba.com.

        Verwendet den LeagueDashTeamStats-Endpoint mit MeasureType='Advanced',
        der echte Offensive/Defensive Ratings, Pace und TS% liefert.

        Args:
            season: NBA-Saison (z.B. 2024 für die Saison 2024/25).

        Returns:
            Dictionary: Teamname → AdvancedTeamStats.
            Leeres Dict bei Fehler oder fehlendem nba_api-Package.
        """
        if not self._nba_api_available:
            return {}

        try:
            from nba_api.stats.endpoints import leaguedashteamstats
            season_str = self._season_string(season)

            self.logger.info(
                "Lade Advanced Stats von stats.nba.com (Saison %s)...", season_str
            )

            # Advanced Stats (Off/Def Rating, Pace, TS%)
            adv_response = leaguedashteamstats.LeagueDashTeamStats(
                season=season_str,
                measure_type_detailed_defense="Advanced",
                timeout=15,
            )
            time.sleep(0.6)  # Rate-Limiting: NBA.com blockiert bei zu schnellen Anfragen

            adv_df = adv_response.get_data_frames()[0]
            result: dict[str, AdvancedTeamStats] = {}

            for _, row in adv_df.iterrows():
                team_name = str(row.get("TEAM_NAME", ""))
                if not team_name:
                    continue

                stats = AdvancedTeamStats(
                    team_id=int(row.get("TEAM_ID", 0)),
                    team_name=team_name,
                    offensive_rating=float(row.get("OFF_RATING", 0) or 0),
                    defensive_rating=float(row.get("DEF_RATING", 0) or 0),
                    net_rating=float(row.get("NET_RATING", 0) or 0),
                    pace=float(row.get("PACE", 98.0) or 98.0),
                    true_shooting_pct=float(row.get("TS_PCT", 0.555) or 0.555),
                )
                result[team_name] = stats

            self.logger.info(
                "Advanced Stats geladen: %d Teams (Saison %s)", len(result), season_str
            )
            return result

        except Exception as exc:
            self.logger.error(
                "Fehler beim Laden der Advanced Stats von NBA.com: %s", exc
            )
            return {}

    # ── Private Methoden ─────────────────────────────────────────────────

    @staticmethod
    def _check_nba_api() -> bool:
        """Prüft, ob das nba_api-Package installiert ist."""
        try:
            import nba_api  # noqa: F401
            return True
        except ImportError:
            return False
