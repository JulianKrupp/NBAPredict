"""
Trainingsdaten-Kollektor für das NBA ML-Modell (v4).

Kombiniert Daten aus drei Quellen:
  1. BallDontLie API  – historische Spielergebnisse & Team-Standings
  2. nba_api          – erweiterte Team-Statistiken (Advanced Stats)
  3. The Odds API     – historische Wettquoten als zusätzliches Feature

Änderungen v4 (gegenüber v3):
  - FIX Data Leakage: Neuer _CumulativeTeamTracker + build_samples_cumulative()
    → Stats werden jetzt chronologisch bis zum Spieltag berechnet,
      nicht mehr aus dem Saison-Endstand.
  - FIX Odds-Feature: odds_implied_home_prob aus Features entfernt (war immer 0.5)
    → Feature-Anzahl: 46 → 45
  - Neuer collect()-Ablauf: kein Saison-Endstand mehr nötig (Schritte 2+3 entfallen)
  - MIN_GAMES_THRESHOLD: Spiele werden erst ab 10 gespielten Spielen pro Team genutzt
"""

from __future__ import annotations

import csv
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
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

# v4: Mindestanzahl Spiele pro Team, bevor Samples erstellt werden.
# Frühe Saisonspiele haben zu wenig Daten für stabile Features.
MIN_GAMES_THRESHOLD = 10


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
    # v4: Bleibt im Dataclass für CSV-Kompatibilität, wird aber
    # NICHT als Feature genutzt (siehe get_feature_columns).
    odds_implied_home_prob: float

    # ── Label ─────────────────────────────────────────────────────────
    home_team_won: int

    @classmethod
    def get_feature_columns(cls) -> list[str]:
        """
        Gibt die Namen aller Feature-Spalten zurück (ohne Metadaten und Label).

        v4: odds_implied_home_prob wird aus Features ausgeschlossen,
        weil es im Training immer 0.5 ist (keine historischen Quoten verfügbar).
        Das Feld bleibt im Dataclass für CSV-Kompatibilität.
        """
        all_fields = list(cls.__dataclass_fields__.keys())
        excluded_fields = {
            "game_id", "game_date", "home_team", "away_team",
            "home_score", "away_score", "home_team_won",
            "odds_implied_home_prob",  # v4: entfernt (im Training immer 0.5)
        }
        return [f for f in all_fields if f not in excluded_fields]


# ══════════════════════════════════════════════════════════════════════════════
#  Kumulativer Team-Tracker (v4) — eliminiert Data Leakage
# ══════════════════════════════════════════════════════════════════════════════


class _CumulativeTeamTracker:
    """
    Berechnet Team-Statistiken kumulativ über die Saison.

    Für jedes Spiel liefern die Properties den Zustand VOR dem Spiel.
    Nach dem Spiel wird update() aufgerufen, um das Ergebnis einzurechnen.
    """

    def __init__(self, team_name: str, team_id: int = 0) -> None:
        self.name = team_name
        self.team_id = team_id

        self.wins = 0
        self.losses = 0
        self.home_wins = 0
        self.home_losses = 0
        self.away_wins = 0
        self.away_losses = 0
        self.total_pts_scored = 0
        self.total_pts_allowed = 0
        self.games_played = 0

        self.results: list[bool] = []
        self.game_dates: list[str] = []

    # ── Snapshot: Stats VOR dem aktuellen Spiel ───────────────────────

    @property
    def win_rate(self) -> float:
        return self.wins / self.games_played if self.games_played else 0.5

    @property
    def avg_pts_scored(self) -> float:
        return self.total_pts_scored / self.games_played if self.games_played else 113.0

    @property
    def avg_pts_allowed(self) -> float:
        return self.total_pts_allowed / self.games_played if self.games_played else 113.0

    @property
    def point_diff(self) -> float:
        return self.avg_pts_scored - self.avg_pts_allowed

    @property
    def home_win_rate(self) -> float:
        total = self.home_wins + self.home_losses
        return self.home_wins / total if total else 0.5

    @property
    def away_win_rate(self) -> float:
        total = self.away_wins + self.away_losses
        return self.away_wins / total if total else 0.5

    @property
    def last_5_win_rate(self) -> float:
        r = self.results[-5:]
        return sum(r) / len(r) if r else self.win_rate

    @property
    def last_10_win_rate(self) -> float:
        r = self.results[-10:]
        return sum(r) / len(r) if r else self.win_rate

    @property
    def current_streak(self) -> int:
        """Positiv = Siegesserie, negativ = Niederlagenserie."""
        if not self.results:
            return 0
        streak = 0
        last = self.results[-1]
        for r in reversed(self.results):
            if r == last:
                streak += 1
            else:
                break
        return streak if last else -streak

    @property
    def form_rating(self) -> float:
        """Gewichtete Form aus letzten 5 Spielen."""
        if not self.results:
            return 0.5
        last_5 = self.results[-5:]
        if len(last_5) < 3:
            return self.win_rate
        weights = [0.1, 0.15, 0.2, 0.25, 0.3][-len(last_5):]
        total_w = sum(weights)
        return sum(w * (1.0 if r else 0.0) for w, r in zip(weights, last_5)) / total_w

    def days_rest_before(self, game_date: str) -> int:
        """Ruhetage VOR einem bestimmten Spieldatum."""
        if not self.game_dates:
            return 3  # Saisonstart
        try:
            current = datetime.strptime(game_date[:10], "%Y-%m-%d")
            last = datetime.strptime(self.game_dates[-1][:10], "%Y-%m-%d")
            return max(0, (current - last).days - 1)
        except (ValueError, IndexError):
            return 2

    def games_last_7_days_before(self, game_date: str) -> int:
        """Anzahl Spiele in den letzten 7 Tagen VOR game_date."""
        try:
            current = datetime.strptime(game_date[:10], "%Y-%m-%d")
            cutoff = current - timedelta(days=7)
            return sum(
                1 for d in self.game_dates
                if cutoff <= datetime.strptime(d[:10], "%Y-%m-%d") < current
            )
        except (ValueError, IndexError):
            return 2

    def compute_advanced_stats(self) -> dict:
        """Berechnet Advanced Stats aus kumulativen Basisdaten."""
        pts = self.avg_pts_scored
        allowed = self.avg_pts_allowed

        pace = 98.0 + (pts - 110.0) * 0.3
        off_r = (pts / pace) * 100.0 if pace > 0 else 110.0
        def_r = (allowed / pace) * 100.0 if pace > 0 else 110.0

        pts_factor = pts / 113.0
        ts = max(0.45, min(0.65, 0.555 + (pts_factor - 1.0) * 0.05))

        return {
            "offensive_rating": off_r,
            "defensive_rating": def_r,
            "net_rating": off_r - def_r,
            "pace": pace,
            "true_shooting": ts,
        }

    # ── Update: Nach dem Spiel aufrufen ──────────────────────────────

    def update(
        self,
        pts_scored: int,
        pts_allowed: int,
        is_home: bool,
        won: bool,
        game_date: str,
    ) -> None:
        """Aktualisiert die kumulativen Statistiken NACH dem Spiel."""
        self.games_played += 1
        self.total_pts_scored += pts_scored
        self.total_pts_allowed += pts_allowed
        self.results.append(won)
        self.game_dates.append(game_date)

        if won:
            self.wins += 1
            if is_home:
                self.home_wins += 1
            else:
                self.away_wins += 1
        else:
            self.losses += 1
            if is_home:
                self.home_losses += 1
            else:
                self.away_losses += 1


# ══════════════════════════════════════════════════════════════════════════════
#  Kumulative Sample-Erstellung (v4) — KEIN Data Leakage
# ══════════════════════════════════════════════════════════════════════════════


def build_samples_cumulative(
    games: list[Game],
    elo_per_game: dict[int, tuple[float, float]] | None = None,
    min_games: int = MIN_GAMES_THRESHOLD,
) -> list[dict]:
    """
    Erstellt TrainingSamples mit kumulativen Stats (KEIN Data Leakage).

    Für jedes Spiel werden die Team-Statistiken NUR aus vorherigen Spielen
    der Saison berechnet. Das Ergebnis des aktuellen Spiels fließt erst
    NACH der Feature-Erstellung in die Statistiken ein.

    Args:
        games:        Alle historischen Spiele (werden intern sortiert).
        elo_per_game: Elo-Ratings pro Spiel-ID {game_id: (home_elo, away_elo)}.
        min_games:    Mindestanzahl Spiele pro Team, bevor Samples erstellt werden.

    Returns:
        Liste von Dicts, bereit für TrainingSample(**d).
    """
    sorted_games = sorted(games, key=lambda g: g.date)
    trackers: dict[int, dict[str, _CumulativeTeamTracker]] = defaultdict(dict)
    samples: list[dict] = []
    skipped = 0

    for game in sorted_games:
        season = game.season
        h_name, a_name = game.home_team, game.away_team

        # Tracker erstellen falls nötig
        if h_name not in trackers[season]:
            trackers[season][h_name] = _CumulativeTeamTracker(h_name)
        if a_name not in trackers[season]:
            trackers[season][a_name] = _CumulativeTeamTracker(a_name)

        ht = trackers[season][h_name]
        at = trackers[season][a_name]
        home_won = game.home_score > game.away_score

        # Mindest-Spiele nicht erreicht → nur Stats updaten, kein Sample
        if ht.games_played < min_games or at.games_played < min_games:
            ht.update(game.home_score, game.away_score, True, home_won, game.date)
            at.update(game.away_score, game.home_score, False, not home_won, game.date)
            skipped += 1
            continue

        # ── Features aus kumulativen Stats VOR dem Spiel ──────────────
        h_adv = ht.compute_advanced_stats()
        a_adv = at.compute_advanced_stats()
        h_rest = ht.days_rest_before(game.date)
        a_rest = at.days_rest_before(game.date)
        h_g7 = ht.games_last_7_days_before(game.date)
        a_g7 = at.games_last_7_days_before(game.date)
        h_fat = round(h_g7 * 0.15 - h_rest * 0.05, 4)
        a_fat = round(a_g7 * 0.15 - a_rest * 0.05, 4)

        # Elo zum Spielzeitpunkt
        if elo_per_game and game.game_id in elo_per_game:
            h_elo, a_elo = elo_per_game[game.game_id]
        else:
            h_elo, a_elo = 1500.0, 1500.0

        samples.append(dict(
            game_id=game.game_id,
            game_date=game.date,
            home_team=h_name,
            away_team=a_name,
            home_score=game.home_score,
            away_score=game.away_score,

            # ── Heimteam (18 Features) ────────────────────────────────
            home_win_rate=ht.win_rate,
            home_point_diff=ht.point_diff,
            home_avg_pts_scored=ht.avg_pts_scored,
            home_avg_pts_allowed=ht.avg_pts_allowed,
            home_home_win_rate=ht.home_win_rate,
            home_away_win_rate=ht.away_win_rate,
            home_offensive_rating=h_adv["offensive_rating"],
            home_defensive_rating=h_adv["defensive_rating"],
            home_net_rating=h_adv["net_rating"],
            home_pace=h_adv["pace"],
            home_true_shooting=h_adv["true_shooting"],
            home_last_5_win_rate=ht.last_5_win_rate,
            home_last_10_win_rate=ht.last_10_win_rate,
            home_days_rest=h_rest,
            home_current_streak=ht.current_streak,
            home_fatigue_score=h_fat,
            home_form_rating=ht.form_rating,
            home_games_last_7_days=h_g7,

            # ── Auswärtsteam (18 Features) ────────────────────────────
            away_win_rate=at.win_rate,
            away_point_diff=at.point_diff,
            away_avg_pts_scored=at.avg_pts_scored,
            away_avg_pts_allowed=at.avg_pts_allowed,
            away_home_win_rate=at.home_win_rate,
            away_away_win_rate=at.away_win_rate,
            away_offensive_rating=a_adv["offensive_rating"],
            away_defensive_rating=a_adv["defensive_rating"],
            away_net_rating=a_adv["net_rating"],
            away_pace=a_adv["pace"],
            away_true_shooting=a_adv["true_shooting"],
            away_last_5_win_rate=at.last_5_win_rate,
            away_last_10_win_rate=at.last_10_win_rate,
            away_days_rest=a_rest,
            away_current_streak=at.current_streak,
            away_fatigue_score=a_fat,
            away_form_rating=at.form_rating,
            away_games_last_7_days=a_g7,

            # ── Differenz (6 Features) ────────────────────────────────
            diff_win_rate=ht.win_rate - at.win_rate,
            diff_point_diff=ht.point_diff - at.point_diff,
            diff_net_rating=h_adv["net_rating"] - a_adv["net_rating"],
            diff_last_5=ht.last_5_win_rate - at.last_5_win_rate,
            diff_streak=ht.current_streak - at.current_streak,
            diff_fatigue=h_fat - a_fat,

            # ── Elo (3 Features) ──────────────────────────────────────
            home_elo=h_elo,
            away_elo=a_elo,
            diff_elo=h_elo - a_elo,

            # ── Odds (Feld bleibt, wird aber NICHT als Feature genutzt)
            odds_implied_home_prob=0.5,

            # ── Label ─────────────────────────────────────────────────
            home_team_won=1 if home_won else 0,
        ))

        # ── NACH Feature-Erstellung: Stats aktualisieren ─────────────
        ht.update(game.home_score, game.away_score, True, home_won, game.date)
        at.update(game.away_score, game.home_score, False, not home_won, game.date)

    logger.info(
        "Kumulative Samples: %d erstellt, %d übersprungen (min_games=%d)",
        len(samples), skipped, min_games,
    )
    return samples


# ══════════════════════════════════════════════════════════════════════════════
#  TrainingDataCollector
# ══════════════════════════════════════════════════════════════════════════════


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
        max_games: int = 5000,
        output_path: Path = TRAINING_DATA_PATH,
    ) -> int:
        """
        Sammelt Trainingsdaten und speichert sie als CSV.

        v4: Nutzt kumulative Stats statt Saison-Endstand.
        """
        if seasons is None:
            seasons = [2021, 2022, 2023, 2024]

        print(f"\n{'='*60}")
        print(f"  Trainingsdaten sammeln (v4 – kumulative Stats)")
        print(f"  Saisons: {seasons} | Max. Spiele: {max_games}")
        print(f"{'='*60}")

        # Schritt 1: Spiele laden
        print("\n  [1/3] Lade Spielergebnisse (BallDontLie)...")
        all_games = self._fetch_historical_games(seasons, max_games)
        if not all_games:
            print("  Fehler: Keine Spiele geladen.")
            return 0
        print(f"        → {len(all_games)} Spiele geladen")

        # Schritt 2: Elo-Ratings berechnen
        print("\n  [2/3] Berechne Elo-Ratings...")
        elo_per_game = calculate_elo_per_game(all_games)
        print(f"        → Elo für {len(elo_per_game)} Spiele berechnet")

        # Schritt 3: Kumulative Samples erstellen (KEIN Saison-Endstand!)
        print("\n  [3/3] Erstelle kumulative Trainingssamples...")
        sample_dicts = build_samples_cumulative(all_games, elo_per_game)
        print(f"        → {len(sample_dicts)} Samples erstellt")

        if not sample_dicts:
            print("  Fehler: Keine Samples erstellt.")
            return 0

        # In TrainingSample-Objekte konvertieren
        samples = [TrainingSample(**d) for d in sample_dicts]

        # CSV speichern
        self._save_to_csv(samples, output_path)
        self._save_metadata(samples, seasons, output_path)

        home_wr = sum(s.home_team_won for s in samples) / len(samples)
        print(f"\n  Gespeichert: {output_path}")
        print(f"  Home-Win-Rate im Datensatz: {home_wr:.1%}")
        print(f"  Feature-Anzahl: {len(TrainingSample.get_feature_columns())} (ohne odds)")
        print(f"{'='*60}\n")

        return len(samples)

    def collect_with_progress(
        self,
        seasons: list[int] | None = None,
        max_games: int = 5000,
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
            "version": "v4_cumulative",
        }
        METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
