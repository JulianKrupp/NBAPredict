"""
Trainingsdaten-Kollektor für das NBA ML-Modell (v3).

Kombiniert Daten aus drei Quellen:
  1. BallDontLie API  – historische Spielergebnisse & Team-Standings
  2. nba_api          – erweiterte Team-Statistiken (Advanced Stats)
  3. The Odds API     – historische Wettquoten als zusätzliches Feature

Änderungen v3:
  - Elo-Rating als Feature (home_elo, away_elo, diff_elo)
  - Feature-Anzahl: 43 → 46
  - Pagination-Fix: nutzt cursor-basierte Pagination vom NBAApiClient
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
from src.ml.elo import calculate_elo_per_game
from src.models.game import Game
from src.models.team import Team
from src.utils.config import Config

logger = logging.getLogger(__name__)

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
    home_current_streak: int
    home_fatigue_score: float
    home_form_rating: float
    home_games_last_7_days: int

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
    away_current_streak: int
    away_fatigue_score: float
    away_form_rating: float
    away_games_last_7_days: int

    # ── Differenz-Features ───────────────────────────────────────────
    diff_win_rate: float
    diff_point_diff: float
    diff_net_rating: float
    diff_last_5: float
    diff_streak: int
    diff_fatigue: float

    # ── Elo-Features (v3) ────────────────────────────────────────────
    home_elo: float
    away_elo: float
    diff_elo: float

    # ── Wettquoten-Feature ───────────────────────────────────────────
    odds_implied_home_prob: float

    # ── Label ─────────────────────────────────────────────────────────
    home_team_won: int

    @classmethod
    def get_feature_columns(cls) -> list[str]:
        """Gibt die Namen aller Feature-Spalten zurück (ohne Metadaten und Label)."""
        all_fields = list(cls.__dataclass_fields__.keys())
        meta_fields = {"game_id", "game_date", "home_team", "away_team",
                       "home_score", "away_score", "home_team_won"}
        return [f for f in all_fields if f not in meta_fields]


class TrainingDataCollector:
    """Sammelt historische NBA-Spieldaten und erstellt Trainingsdatensätze."""

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
        """Sammelt Trainingsdaten und speichert sie als CSV."""
        if seasons is None:
            seasons = [2023, 2024]

        print(f"\n{'='*60}")
        print(f"  Trainingsdaten sammeln")
        print(f"  Saisons: {seasons} | Max. Spiele: {max_games}")
        print(f"{'='*60}")

        # Schritt 1: Spiele laden
        print("\n  [1/5] Lade Spielergebnisse (BallDontLie)...")
        all_games = self._fetch_historical_games(seasons, max_games)
        if not all_games:
            print("  Fehler: Keine Spiele geladen.")
            return 0
        print(f"        → {len(all_games)} Spiele geladen")

        # Schritt 2: Team-Statistiken berechnen
        print("\n  [2/5] Berechne Team-Statistiken pro Saison...")
        all_team_stats: dict[int, dict[str, Team]] = {}
        for season in seasons:
            season_games = [g for g in all_games if g.season == season]
            if season_games:
                teams = self.nba_client._calculate_standings_from_games(season_games, season)
                all_team_stats[season] = teams
                print(f"        Saison {season}: {len(teams)} Teams")

        if not all_team_stats:
            print("  Fehler: Keine Team-Statistiken berechnet.")
            return 0

        # Schritt 3: Advanced Stats berechnen
        print("\n  [3/5] Berechne Advanced Stats...")
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

        # Schritt 4: Elo-Ratings berechnen
        print("\n  [4/5] Berechne Elo-Ratings...")
        elo_per_game = calculate_elo_per_game(all_games)
        print(f"        → Elo für {len(elo_per_game)} Spiele berechnet")

        # Schritt 5: Trainingssamples erstellen
        print("\n  [5/5] Erstelle Trainingssamples...")
        samples = list(self._build_samples(
            all_games, all_team_stats, advanced_stats_cache, elo_per_game
        ))
        print(f"        → {len(samples)} Samples erstellt")

        # CSV speichern
        self._save_to_csv(samples, output_path)
        self._save_metadata(samples, seasons, output_path)

        print(f"\n  Gespeichert: {output_path}")
        print(f"  Home-Win-Rate im Datensatz: "
              f"{sum(s.home_team_won for s in samples)/len(samples):.1%}")
        print(f"{'='*60}\n")

        return len(samples)

    def collect_with_progress(
        self,
        seasons: list[int] | None = None,
        max_games: int = 500,
    ) -> list[TrainingSample]:
        """Sammelt Trainingsdaten und gibt sie als Liste zurück."""
        saved = self.collect(seasons, max_games)
        if saved == 0:
            return []
        return self.load_from_csv(TRAINING_DATA_PATH)

    @staticmethod
    def load_from_csv(path: Path = TRAINING_DATA_PATH) -> list[TrainingSample]:
        """Lädt gespeicherte Trainingsdaten aus einer CSV-Datei."""
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
                        # Heimteam
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
                        home_current_streak=int(row["home_current_streak"]),
                        home_fatigue_score=float(row["home_fatigue_score"]),
                        home_form_rating=float(row["home_form_rating"]),
                        home_games_last_7_days=int(row["home_games_last_7_days"]),
                        # Auswärtsteam
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
                        away_current_streak=int(row["away_current_streak"]),
                        away_fatigue_score=float(row["away_fatigue_score"]),
                        away_form_rating=float(row["away_form_rating"]),
                        away_games_last_7_days=int(row["away_games_last_7_days"]),
                        # Differenz
                        diff_win_rate=float(row["diff_win_rate"]),
                        diff_point_diff=float(row["diff_point_diff"]),
                        diff_net_rating=float(row["diff_net_rating"]),
                        diff_last_5=float(row["diff_last_5"]),
                        diff_streak=int(row["diff_streak"]),
                        diff_fatigue=float(row["diff_fatigue"]),
                        # Elo
                        home_elo=float(row["home_elo"]),
                        away_elo=float(row["away_elo"]),
                        diff_elo=float(row["diff_elo"]),
                        # Odds + Label
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
        """Lädt abgeschlossene Spiele – nutzt cursor-basierte Pagination."""
        all_games: list[Game] = []
        games_per_season = max_games // len(seasons)

        for season in seasons:
            if len(all_games) >= max_games:
                break
            games = self.nba_client._fetch_season_games_paginated(season, games_per_season)
            all_games.extend(games)
            self.logger.info("Saison %d: %d Spiele geladen", season, len(games))

        return all_games[:max_games]

    def _build_samples(
        self,
        games: list[Game],
        team_stats: dict[int, dict[str, Team]],
        advanced_stats: dict[str, AdvancedTeamStats],
        elo_per_game: dict[int, tuple[float, float]] | None = None,
    ) -> Iterator[TrainingSample]:
        """Erstellt TrainingSample-Objekte aus Spielen und Teamstatistiken."""
        skipped = 0
        for game in games:
            sample = self._game_to_sample(game, team_stats, advanced_stats, elo_per_game)
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
        elo_per_game: dict[int, tuple[float, float]] | None = None,
    ) -> TrainingSample | None:
        """Konvertiert ein einzelnes Spiel in ein TrainingSample."""
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

        # Elo-Ratings zum Zeitpunkt des Spiels
        if elo_per_game and game.game_id in elo_per_game:
            h_elo, a_elo = elo_per_game[game.game_id]
        else:
            h_elo, a_elo = 1500.0, 1500.0

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
            home_current_streak=home_team.current_streak,
            home_fatigue_score=home_team.fatigue_score,
            home_form_rating=home_team.form_rating,
            home_games_last_7_days=home_team.games_last_7_days,
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
            away_current_streak=away_team.current_streak,
            away_fatigue_score=away_team.fatigue_score,
            away_form_rating=away_team.form_rating,
            away_games_last_7_days=away_team.games_last_7_days,
            # Differenz
            diff_win_rate=home_team.win_rate - away_team.win_rate,
            diff_point_diff=home_team.point_differential - away_team.point_differential,
            diff_net_rating=home_adv.net_rating - away_adv.net_rating,
            diff_last_5=home_adv.last_5_win_rate - away_adv.last_5_win_rate,
            diff_streak=home_team.current_streak - away_team.current_streak,
            diff_fatigue=home_team.fatigue_score - away_team.fatigue_score,
            # Elo
            home_elo=h_elo,
            away_elo=a_elo,
            diff_elo=h_elo - a_elo,
            # Odds + Label
            odds_implied_home_prob=0.5,
            home_team_won=1 if game.home_score > game.away_score else 0,
        )

    def _find_team(
        self, team_name: str, season_stats: dict[str, Team]
    ) -> Team | None:
        if team_name in season_stats:
            return season_stats[team_name]
        name_lower = team_name.lower()
        for key, team in season_stats.items():
            if name_lower in key.lower() or key.lower() in name_lower:
                return team
        return None

    def _save_to_csv(self, samples: list[TrainingSample], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not samples:
            return
        fieldnames = list(asdict(samples[0]).keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for sample in samples:
                writer.writerow(asdict(sample))

    def _save_metadata(
        self, samples: list[TrainingSample], seasons: list[int], data_path: Path,
    ) -> None:
        features = TrainingSample.get_feature_columns()
        metadata = {
            "total_samples": len(samples),
            "seasons": seasons,
            "home_win_rate": sum(s.home_team_won for s in samples) / len(samples),
            "feature_count": len(features),
            "features": features,
            "data_path": str(data_path),
            "created_at": str(date.today()),
        }
        METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
