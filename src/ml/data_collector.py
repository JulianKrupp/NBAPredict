"""
Trainingsdaten-Kollektor für das NBA ML-Modell.

Kombiniert Daten aus drei Quellen:
  1. BallDontLie API  – historische Spielergebnisse & Team-Standings
  2. RapidAPI NBA     – erweiterte Team-Statistiken (Advanced Stats)
  3. The Odds API     – historische Wettquoten als zusätzliches Feature

Jede Trainingszeile repräsentiert ein abgeschlossenes Spiel mit
Feature-Vektor (Teamstats zum Spielzeitpunkt) und Label (Heimsieg = 1).
"""

from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from src.api.nba_api_client import NBAApiClient
from src.api.nba_stats_client import NBAStatsApiClient, AdvancedTeamStats
from src.api.odds_api_client import OddsApiClient
from src.api.base_client import ApiError
from src.models.game import Game
from src.models.team import Team
from src.utils.config import Config

logger = logging.getLogger(__name__)

# Pfad für die Trainingsdaten
TRAINING_DATA_PATH = Path("data/training/training_data.csv")
METADATA_PATH = Path("data/training/metadata.json")


@dataclass
class TrainingSample:
    """
    Eine Zeile Trainingsdaten – ein abgeschlossenes NBA-Spiel.

    Features beschreiben den Zustand beider Teams VOR dem Spiel.
    Label = 1 wenn Heimteam gewonnen hat, 0 wenn Auswärtsteam.
    """
    # Metadaten (nicht als Feature verwendet)
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int

    # ── Heimteam-Features ──────────────────────────────────────────────
    home_win_rate: float
    home_point_diff: float
    home_avg_pts_scored: float
    home_avg_pts_allowed: float
    home_home_win_rate: float
    home_away_win_rate: float
    home_offensive_rating: float
    home_defensive_rating: float
    home_net_rating: float
    home_pace: float
    home_true_shooting: float
    home_last_5_win_rate: float
    home_last_10_win_rate: float
    home_days_rest: int

    # ── Auswärtsteam-Features ─────────────────────────────────────────
    away_win_rate: float
    away_point_diff: float
    away_avg_pts_scored: float
    away_avg_pts_allowed: float
    away_home_win_rate: float
    away_away_win_rate: float
    away_offensive_rating: float
    away_defensive_rating: float
    away_net_rating: float
    away_pace: float
    away_true_shooting: float
    away_last_5_win_rate: float
    away_last_10_win_rate: float
    away_days_rest: int

    # ── Differenz-Features (Heimteam minus Auswärtsteam) ─────────────
    diff_win_rate: float
    diff_point_diff: float
    diff_net_rating: float
    diff_last_5: float

    # ── Wettquoten-Feature (optional, 0.5 wenn nicht verfügbar) ──────
    odds_implied_home_prob: float

    # ── Label ─────────────────────────────────────────────────────────
    home_team_won: int  # 1 = Heimteam gewann, 0 = Auswärtsteam gewann

    @classmethod
    def get_feature_columns(cls) -> list[str]:
        """Gibt die Namen aller Feature-Spalten zurück (ohne Metadaten und Label)."""
        all_fields = list(asdict(cls(
            0, "", "", "", 0, 0,
            0,0,0,0,0,0,0,0,0,0,0,0,0,0,
            0,0,0,0,0,0,0,0,0,0,0,0,0,0,
            0,0,0,0,0,0
        )).keys())
        meta_fields = {"game_id", "game_date", "home_team", "away_team",
                       "home_score", "away_score", "home_team_won"}
        return [f for f in all_fields if f not in meta_fields]


class TrainingDataCollector:
    """
    Sammelt historische NBA-Spieldaten aus mehreren APIs
    und erstellt daraus einen strukturierten Trainingsdatensatz.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.nba_client = NBAApiClient(config)
        self.stats_client = NBAStatsApiClient(config)
        self.odds_client = OddsApiClient(config)
        self.logger = logging.getLogger(__name__)

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def collect(
        self,
        seasons: list[int] | None = None,
        max_games: int = 500,
        output_path: Path = TRAINING_DATA_PATH,
    ) -> int:
        """
        Hauptmethode: Sammelt Trainingsdaten für die angegebenen Saisons.

        Args:
            seasons:     Liste von NBA-Saisons (z.B. [2022, 2023, 2024]).
            max_games:   Maximale Anzahl zu sammelnder Spiele.
            output_path: Pfad für die CSV-Ausgabedatei.

        Returns:
            Anzahl der gesammelten Trainingssamples.
        """
        seasons = seasons or [2023, 2024]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "Starte Datensammlung: Saisons=%s, max_games=%d", seasons, max_games
        )
        print(f"\n{'='*60}")
        print(f"  📊 Trainingsdaten-Sammlung gestartet")
        print(f"  Saisons: {seasons} | Max. Spiele: {max_games}")
        print(f"{'='*60}")

        # Schritt 1: Team-Statistiken für alle Saisons laden
        print("\n  [1/4] Lade Team-Statistiken aus BallDontLie API...")
        all_team_stats: dict[int, dict[str, Team]] = {}
        for season in seasons:
            standings = self.nba_client.get_standings(season)
            all_team_stats[season] = {t.name: t for t in standings}
            print(f"        → {len(standings)} Teams für Saison {season} geladen")

        # Schritt 2: Historische Spiele laden
        print("\n  [2/4] Lade historische Spielergebnisse...")
        all_games = self._fetch_historical_games(seasons, max_games)
        print(f"        → {len(all_games)} abgeschlossene Spiele gefunden")

        if not all_games:
            print("  ⚠️  Keine Spieldaten gefunden – prüfe API-Key.")
            return 0

        # Schritt 3: Advanced Stats berechnen/laden
        print("\n  [3/4] Berechne Advanced Stats (RapidAPI + Fallback)...")
        advanced_stats_cache: dict[str, AdvancedTeamStats] = {}
        for season, teams in all_team_stats.items():
            for team_name, team in teams.items():
                cache_key = f"{team_name}_{season}"
                if cache_key not in advanced_stats_cache:
                    advanced_stats_cache[cache_key] = (
                        self.stats_client.build_advanced_stats_from_basic(
                            team_id=team.team_id,
                            team_name=team.name,
                            wins=team.wins,
                            losses=team.losses,
                            avg_pts_scored=team.avg_points_scored,
                            avg_pts_allowed=team.avg_points_allowed,
                        )
                    )
        print(f"        → {len(advanced_stats_cache)} Team-Advanced-Stats berechnet")

        # Schritt 4: Trainingssamples erstellen
        print("\n  [4/4] Erstelle Trainingssamples...")
        samples = list(self._build_samples(all_games, all_team_stats, advanced_stats_cache))
        print(f"        → {len(samples)} Samples erstellt")

        # CSV speichern
        self._save_to_csv(samples, output_path)
        self._save_metadata(samples, seasons, output_path)

        print(f"\n  ✅ Gespeichert: {output_path}")
        print(f"  ✅ Home-Win-Rate im Datensatz: "
              f"{sum(s.home_team_won for s in samples)/len(samples):.1%}")
        print(f"{'='*60}\n")

        return len(samples)

    def collect_with_progress(
        self,
        seasons: list[int] | None = None,
        max_games: int = 500,
    ) -> list[TrainingSample]:
        """
        Sammelt Trainingsdaten und gibt sie als Liste zurück (für direktes Training).

        Args:
            seasons:   Saisons.
            max_games: Max. Spielanzahl.

        Returns:
            Liste von TrainingSample-Objekten.
        """
        saved = self.collect(seasons, max_games)
        if saved == 0:
            return []
        return self.load_from_csv(TRAINING_DATA_PATH)

    @staticmethod
    def load_from_csv(path: Path = TRAINING_DATA_PATH) -> list[TrainingSample]:
        """
        Lädt gespeicherte Trainingsdaten aus einer CSV-Datei.

        Args:
            path: Pfad zur CSV-Datei.

        Returns:
            Liste von TrainingSample-Objekten.

        Raises:
            FileNotFoundError: Wenn die Datei nicht existiert.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"Trainingsdaten nicht gefunden: {path}\n"
                "Führe zuerst 'python main.py train collect' aus."
            )

        samples = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    sample = TrainingSample(
                        game_id=int(row["game_id"]),
                        game_date=row["game_date"],
                        home_team=row["home_team"],
                        away_team=row["away_team"],
                        home_score=int(row["home_score"]),
                        away_score=int(row["away_score"]),
                        home_win_rate=float(row["home_win_rate"]),
                        home_point_diff=float(row["home_point_diff"]),
                        home_avg_pts_scored=float(row["home_avg_pts_scored"]),
                        home_avg_pts_allowed=float(row["home_avg_pts_allowed"]),
                        home_home_win_rate=float(row["home_home_win_rate"]),
                        home_away_win_rate=float(row["home_away_win_rate"]),
                        home_offensive_rating=float(row["home_offensive_rating"]),
                        home_defensive_rating=float(row["home_defensive_rating"]),
                        home_net_rating=float(row["home_net_rating"]),
                        home_pace=float(row["home_pace"]),
                        home_true_shooting=float(row["home_true_shooting"]),
                        home_last_5_win_rate=float(row["home_last_5_win_rate"]),
                        home_last_10_win_rate=float(row["home_last_10_win_rate"]),
                        home_days_rest=int(row["home_days_rest"]),
                        away_win_rate=float(row["away_win_rate"]),
                        away_point_diff=float(row["away_point_diff"]),
                        away_avg_pts_scored=float(row["away_avg_pts_scored"]),
                        away_avg_pts_allowed=float(row["away_avg_pts_allowed"]),
                        away_home_win_rate=float(row["away_home_win_rate"]),
                        away_away_win_rate=float(row["away_away_win_rate"]),
                        away_offensive_rating=float(row["away_offensive_rating"]),
                        away_defensive_rating=float(row["away_defensive_rating"]),
                        away_net_rating=float(row["away_net_rating"]),
                        away_pace=float(row["away_pace"]),
                        away_true_shooting=float(row["away_true_shooting"]),
                        away_last_5_win_rate=float(row["away_last_5_win_rate"]),
                        away_last_10_win_rate=float(row["away_last_10_win_rate"]),
                        away_days_rest=int(row["away_days_rest"]),
                        diff_win_rate=float(row["diff_win_rate"]),
                        diff_point_diff=float(row["diff_point_diff"]),
                        diff_net_rating=float(row["diff_net_rating"]),
                        diff_last_5=float(row["diff_last_5"]),
                        odds_implied_home_prob=float(row["odds_implied_home_prob"]),
                        home_team_won=int(row["home_team_won"]),
                    )
                    samples.append(sample)
                except (KeyError, ValueError) as exc:
                    logger.warning("Zeile übersprungen: %s", exc)
        return samples

    # ── Private Methoden ──────────────────────────────────────────────────

    def _fetch_historical_games(
        self, seasons: list[int], max_games: int
    ) -> list[Game]:
        """Lädt abgeschlossene Spiele aus den angegebenen Saisons."""
        all_games: list[Game] = []
        games_per_season = max_games // len(seasons)

        for season in seasons:
            if len(all_games) >= max_games:
                break
            games = self._fetch_season_games(season, games_per_season)
            all_games.extend(games)
            self.logger.info("Saison %d: %d Spiele geladen", season, len(games))

        return all_games[:max_games]

    def _fetch_season_games(self, season: int, limit: int) -> list[Game]:
        """Lädt Spiele einer einzelnen Saison (seitenweise)."""
        collected: list[Game] = []
        page = 1

        while len(collected) < limit:
            try:
                response = self.nba_client.get(
                    f"{self.nba_client.base_url}/games",
                    params={
                        "seasons[]": season,
                        "per_page": min(100, limit - len(collected)),
                        "page": page,
                    },
                    headers=self.nba_client._default_headers,
                )
                raw_games = response.get("data", [])
                if not raw_games:
                    break

                for raw in raw_games:
                    try:
                        game = Game.from_api_response(raw)
                        if game.is_final and game.home_score > 0:
                            collected.append(game)
                    except (KeyError, ValueError):
                        continue

                # Pagination
                meta = response.get("meta", {})
                total_pages = meta.get("total_pages", 1)
                if page >= total_pages:
                    break
                page += 1
                time.sleep(0.2)  # Rate-Limiting

            except ApiError as exc:
                self.logger.error("Fehler beim Laden Saison %d, Seite %d: %s",
                                  season, page, exc)
                break

        return collected

    def _build_samples(
        self,
        games: list[Game],
        team_stats: dict[int, dict[str, Team]],
        advanced_stats: dict[str, AdvancedTeamStats],
    ) -> Iterator[TrainingSample]:
        """Erstellt TrainingSample-Objekte aus Spielen und Teamstatistiken."""
        skipped = 0
        for game in games:
            sample = self._game_to_sample(game, team_stats, advanced_stats)
            if sample is not None:
                yield sample
            else:
                skipped += 1

        if skipped > 0:
            self.logger.info("%d Spiele ohne ausreichende Stats übersprungen", skipped)

    def _game_to_sample(
        self,
        game: Game,
        team_stats: dict[int, dict[str, Team]],
        advanced_stats: dict[str, AdvancedTeamStats],
    ) -> TrainingSample | None:
        """Konvertiert ein einzelnes Spiel in ein TrainingSample."""
        # Teamstatistiken der entsprechenden Saison suchen
        season_stats = team_stats.get(game.season, {})

        home_team = self._find_team(game.home_team, season_stats)
        away_team = self._find_team(game.away_team, season_stats)

        if home_team is None or away_team is None:
            return None

        home_adv = advanced_stats.get(f"{home_team.name}_{game.season}")
        away_adv = advanced_stats.get(f"{away_team.name}_{game.season}")

        if home_adv is None:
            home_adv = self.stats_client.build_advanced_stats_from_basic(
                home_team.team_id, home_team.name,
                home_team.wins, home_team.losses,
                home_team.avg_points_scored, home_team.avg_points_allowed,
            )
        if away_adv is None:
            away_adv = self.stats_client.build_advanced_stats_from_basic(
                away_team.team_id, away_team.name,
                away_team.wins, away_team.losses,
                away_team.avg_points_scored, away_team.avg_points_allowed,
            )

        return TrainingSample(
            game_id=game.game_id,
            game_date=game.date,
            home_team=game.home_team,
            away_team=game.away_team,
            home_score=game.home_score,
            away_score=game.away_score,
            # Heimteam
            home_win_rate=home_team.win_rate,
            home_point_diff=home_team.point_differential,
            home_avg_pts_scored=home_team.avg_points_scored,
            home_avg_pts_allowed=home_team.avg_points_allowed,
            home_home_win_rate=home_team.home_win_rate,
            home_away_win_rate=home_team.away_win_rate,
            home_offensive_rating=home_adv.offensive_rating,
            home_defensive_rating=home_adv.defensive_rating,
            home_net_rating=home_adv.net_rating,
            home_pace=home_adv.pace,
            home_true_shooting=home_adv.true_shooting_pct,
            home_last_5_win_rate=home_adv.last_5_win_rate,
            home_last_10_win_rate=home_adv.last_10_win_rate,
            home_days_rest=home_adv.days_since_last_game,
            # Auswärtsteam
            away_win_rate=away_team.win_rate,
            away_point_diff=away_team.point_differential,
            away_avg_pts_scored=away_team.avg_points_scored,
            away_avg_pts_allowed=away_team.avg_points_allowed,
            away_home_win_rate=away_team.home_win_rate,
            away_away_win_rate=away_team.away_win_rate,
            away_offensive_rating=away_adv.offensive_rating,
            away_defensive_rating=away_adv.defensive_rating,
            away_net_rating=away_adv.net_rating,
            away_pace=away_adv.pace,
            away_true_shooting=away_adv.true_shooting_pct,
            away_last_5_win_rate=away_adv.last_5_win_rate,
            away_last_10_win_rate=away_adv.last_10_win_rate,
            away_days_rest=away_adv.days_since_last_game,
            # Differenz-Features
            diff_win_rate=home_team.win_rate - away_team.win_rate,
            diff_point_diff=home_team.point_differential - away_team.point_differential,
            diff_net_rating=home_adv.net_rating - away_adv.net_rating,
            diff_last_5=home_adv.last_5_win_rate - away_adv.last_5_win_rate,
            # Wettquoten (neutral, wenn keine historischen Quoten verfügbar)
            odds_implied_home_prob=0.5,
            # Label
            home_team_won=1 if game.home_score > game.away_score else 0,
        )

    @staticmethod
    def _find_team(team_name: str, season_stats: dict[str, Team]) -> Team | None:
        """Sucht ein Team im Statistik-Dictionary (fuzzy, case-insensitiv)."""
        name_lower = team_name.lower()
        for key, team in season_stats.items():
            if name_lower in key.lower() or key.lower() in name_lower:
                return team
        return None

    @staticmethod
    def _save_to_csv(samples: list[TrainingSample], path: Path) -> None:
        """Speichert Trainingssamples als CSV."""
        if not samples:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
            writer.writeheader()
            writer.writerows(asdict(s) for s in samples)

    @staticmethod
    def _save_metadata(
        samples: list[TrainingSample], seasons: list[int], data_path: Path
    ) -> None:
        """Speichert Metadaten zur Datensammlung als JSON."""
        metadata = {
            "total_samples": len(samples),
            "seasons": seasons,
            "home_win_rate": sum(s.home_team_won for s in samples) / len(samples) if samples else 0,
            "feature_count": len(TrainingSample.get_feature_columns()),
            "features": TrainingSample.get_feature_columns(),
            "data_path": str(data_path),
            "created_at": str(date.today()),
        }
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
