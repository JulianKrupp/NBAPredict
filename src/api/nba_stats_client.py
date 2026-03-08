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
    """
    Erweiterte Teamstatistiken für das ML-Modell.
    Enthält sowohl direkte NBA.com-Werte als auch berechnete Metriken.
    """
    team_id: int
    team_name: str

    # Echte Advanced Stats von stats.nba.com
    offensive_rating: float = 0.0   # Punkte pro 100 Ballbesitze (Offense)
    defensive_rating: float = 0.0   # Punkte pro 100 Ballbesitze (Defense)
    net_rating: float = 0.0         # Offensive - Defensive Rating
    pace: float = 0.0               # Ballbesitze pro 48 Minuten
    true_shooting_pct: float = 0.0  # Effektive Trefferquote

    # Aktuelle Form (letzte N Spiele)
    last_5_win_rate: float = 0.0
    last_10_win_rate: float = 0.0
    last_5_point_diff: float = 0.0

    # Ruhetage
    days_since_last_game: int = 2

    @property
    def efficiency_margin(self) -> float:
        """Net Rating als kombiniertes Stärkemaß."""
        return self.net_rating

    @classmethod
    def from_basic_stats(
        cls,
        team_id: int,
        team_name: str,
        wins: int,
        losses: int,
        avg_pts_scored: float,
        avg_pts_allowed: float,
        recent_results: list[bool] | None = None,
    ) -> "AdvancedTeamStats":
        """
        Berechnet Advanced Stats aus Basis-Statistiken (Fallback ohne nba_api).

        Args:
            team_id:         Team-ID.
            team_name:       Teamname.
            wins:            Saisonsiege.
            losses:          Saisonnierederlagen.
            avg_pts_scored:  Ø erzielte Punkte.
            avg_pts_allowed: Ø kassierte Punkte.
            recent_results:  Letzte Spielergebnisse (True=Sieg).

        Returns:
            AdvancedTeamStats mit berechneten Näherungswerten.
        """
        results = recent_results or []
        pts = avg_pts_scored if avg_pts_scored > 0 else 113.0
        allowed = avg_pts_allowed if avg_pts_allowed > 0 else 113.0

        # Pace-Näherung (NBA-Durchschnitt ~98–100 Possessions)
        estimated_pace = 98.0 + (pts - 110.0) * 0.3

        # Offensive/Defensive Rating näherungsweise (benötigt echte Possession-Daten)
        off_rating = (pts / estimated_pace) * 100.0
        def_rating = (allowed / estimated_pace) * 100.0

        # Letzte-N-Spiele Form
        last_5 = results[-5:] if len(results) >= 5 else results
        last_10 = results[-10:] if len(results) >= 10 else results
        last_5_wr = sum(last_5) / len(last_5) if last_5 else (wins / (wins + losses) if wins + losses > 0 else 0.5)
        last_10_wr = sum(last_10) / len(last_10) if last_10 else last_5_wr

        # True Shooting % schätzen
        pts_factor = pts / 113.0
        estimated_ts = max(0.45, min(0.65, 0.555 + (pts_factor - 1.0) * 0.05))

        return cls(
            team_id=team_id,
            team_name=team_name,
            offensive_rating=off_rating,
            defensive_rating=def_rating,
            net_rating=off_rating - def_rating,
            pace=estimated_pace,
            true_shooting_pct=estimated_ts,
            last_5_win_rate=last_5_wr,
            last_10_win_rate=last_10_wr,
            last_5_point_diff=pts - allowed,
        )


class NBAStatsApiClient:
    """
    Client für Advanced NBA-Statistiken von stats.nba.com.

    Nutzt das `nba_api`-Package (pip install nba_api) – kein API-Key nötig.
    Fällt automatisch auf berechnete Näherungswerte zurück, wenn das
    Package nicht installiert ist oder NBA.com nicht erreichbar ist.

    Verfügbare Endpunkte (nba_api):
      - LeagueDashTeamStats  → Off/Def Rating, Pace, True Shooting %
      - TeamGameLog          → Letzte Spiele für Form-Berechnung
      - LeagueStandings      → Standings direkt von NBA.com
    """

    # NBA.com Saison-Format: "2024-25" für Saison 2024
    @staticmethod
    def _season_string(season: int) -> str:
        return f"{season}-{str(season + 1)[-2:]}"

    def __init__(self, config=None) -> None:
        self.logger = logging.getLogger(__name__)
        self._nba_api_available = self._check_nba_api()
        if self._nba_api_available:
            self.logger.info("nba_api verfügbar – nutze stats.nba.com für Advanced Stats")
        else:
            self.logger.warning(
                "nba_api nicht installiert. "
                "Installieren mit: pip install nba_api\n"
                "Nutze Fallback-Berechnung."
            )

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
                per_mode_simple="PerGame",
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

    def get_team_last_n_games(
        self, team_id: int, season: int = 2024, last_n: int = 10
    ) -> list[bool]:
        """
        Gibt die letzten N Spielergebnisse eines Teams zurück (True = Sieg).

        Verwendet TeamGameLog von stats.nba.com.

        Args:
            team_id: NBA.com Team-ID.
            season:  NBA-Saison.
            last_n:  Anzahl der letzten Spiele.

        Returns:
            Liste von Booleans (True = Sieg), neueste zuerst.
        """
        if not self._nba_api_available:
            return []

        try:
            from nba_api.stats.endpoints import teamgamelog
            season_str = self._season_string(season)

            game_log = teamgamelog.TeamGameLog(
                team_id=team_id,
                season=season_str,
                timeout=15,
            )
            time.sleep(0.4)

            df = game_log.get_data_frames()[0]
            if df.empty:
                return []

            results = [str(wl).upper() == "W" for wl in df["WL"].head(last_n)]
            return results

        except Exception as exc:
            self.logger.debug("Spielprotokoll nicht verfügbar für Team %d: %s", team_id, exc)
            return []

    def build_advanced_stats_from_basic(
        self,
        team_id: int,
        team_name: str,
        wins: int,
        losses: int,
        avg_pts_scored: float,
        avg_pts_allowed: float,
        recent_game_results: list[bool] | None = None,
    ) -> AdvancedTeamStats:
        """
        Erstellt AdvancedTeamStats – primär aus Basis-Statistiken (Fallback).

        Wird verwendet, wenn nba_api nicht verfügbar ist oder ein Team
        nicht in den NBA.com-Daten gefunden wird.

        Args:
            team_id:             Team-ID.
            team_name:           Teamname.
            wins:                Anzahl Siege.
            losses:              Anzahl Niederlagen.
            avg_pts_scored:      Ø erzielte Punkte.
            avg_pts_allowed:     Ø kassierte Punkte.
            recent_game_results: Letzte Spielergebnisse (optional).

        Returns:
            AdvancedTeamStats-Instanz.
        """
        return AdvancedTeamStats.from_basic_stats(
            team_id=team_id,
            team_name=team_name,
            wins=wins,
            losses=losses,
            avg_pts_scored=avg_pts_scored if avg_pts_scored > 0 else 113.0,
            avg_pts_allowed=avg_pts_allowed if avg_pts_allowed > 0 else 113.0,
            recent_results=recent_game_results or [],
        )

    # ── Private Methoden ─────────────────────────────────────────────────

    @staticmethod
    def _check_nba_api() -> bool:
        """Prüft, ob das nba_api-Package installiert ist."""
        try:
            import nba_api  # noqa: F401
            return True
        except ImportError:
            return False
