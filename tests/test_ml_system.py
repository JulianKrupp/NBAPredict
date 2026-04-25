"""
Unit-Tests für das ML-System (v4) – 45 Features (ohne odds_implied_home_prob).
"""

import pytest
import numpy as np
from unittest.mock import MagicMock
from dataclasses import asdict

from src.ml.data_collector import TrainingSample, _CumulativeTeamTracker
from src.ml.model_trainer import NBAModelTrainer, ModelMetrics
from src.ml.ml_predictor import MLPredictor, MLPredictionResult
from src.ml.comparison import OddsVsMLComparison, ComparisonEntry
from src.api.nba_stats_client import AdvancedTeamStats
from src.models.team import Team
from src.api.odds_api_client import GameOdds
from src.utils.config import Config


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config() -> Config:
    config = MagicMock(spec=Config)
    config.balldontlie_api_key = "test"
    config.odds_api_key = "test_odds"
    config.rapidapi_key = ""
    config.balldontlie_base_url = "https://api.balldontlie.io/v1"
    config.odds_api_base_url = "https://api.the-odds-api.com/v4"
    config.request_timeout = 5
    config.max_retries = 1
    config.retry_delay = 0.1
    config.cache_ttl = 60
    return config


def make_sample(home_won: int = 1, **overrides) -> TrainingSample:
    """Erstellt ein Minimal-TrainingSample (v4 mit 45 Features + odds-Feld)."""
    defaults = dict(
        game_id=1, game_date="2025-01-01",
        home_team="A", away_team="B",
        home_score=110, away_score=100,
        # Heimteam – Basis (14)
        home_win_rate=0.6, home_point_diff=5.0,
        home_avg_pts_scored=115.0, home_avg_pts_allowed=110.0,
        home_home_win_rate=0.7, home_away_win_rate=0.5,
        home_offensive_rating=112.0, home_defensive_rating=108.0,
        home_net_rating=4.0, home_pace=98.0, home_true_shooting=0.57,
        home_last_5_win_rate=0.6, home_last_10_win_rate=0.6, home_days_rest=2,
        # Heimteam – v2 (4)
        home_current_streak=2,
        home_fatigue_score=0.15,
        home_form_rating=0.62,
        home_games_last_7_days=2,
        # Auswärtsteam – Basis (14)
        away_win_rate=0.45, away_point_diff=-2.0,
        away_avg_pts_scored=110.0, away_avg_pts_allowed=112.0,
        away_home_win_rate=0.55, away_away_win_rate=0.38,
        away_offensive_rating=108.5, away_defensive_rating=110.5,
        away_net_rating=-2.0, away_pace=97.0, away_true_shooting=0.55,
        away_last_5_win_rate=0.4, away_last_10_win_rate=0.45, away_days_rest=1,
        # Auswärtsteam – v2 (4)
        away_current_streak=-1,
        away_fatigue_score=0.45,
        away_form_rating=0.42,
        away_games_last_7_days=3,
        # Differenz – Basis (4)
        diff_win_rate=0.15, diff_point_diff=7.0,
        diff_net_rating=6.0, diff_last_5=0.2,
        # Differenz – v2 (2)
        diff_streak=3,
        diff_fatigue=-0.30,
        # Elo – v3 (3)
        home_elo=1550.0,
        away_elo=1480.0,
        diff_elo=70.0,
        # Odds (Feld bleibt, wird aber nicht als Feature genutzt) + Label
        odds_implied_home_prob=0.6,
        home_team_won=home_won,
    )
    defaults.update(overrides)
    return TrainingSample(**defaults)


def make_team(name: str = "Team", wins: int = 40, losses: int = 20,
              avg_pts: float = 113.0, avg_allowed: float = 108.0) -> Team:
    return Team(
        team_id=1, name=name, abbreviation="TST",
        wins=wins, losses=losses,
        avg_points_scored=avg_pts, avg_points_allowed=avg_allowed,
        home_wins=22, home_losses=10, away_wins=18, away_losses=10,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  TrainingSample Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTrainingSample:
    """Tests für das TrainingSample-Datenmodell (v4)."""

    def test_get_feature_columns_returns_list(self):
        features = TrainingSample.get_feature_columns()
        assert isinstance(features, list)
        assert len(features) > 0

    def test_feature_count_is_45(self):
        """v4 hat 45 Feature-Spalten (46 v3 - odds_implied_home_prob)."""
        features = TrainingSample.get_feature_columns()
        assert len(features) == 45

    def test_feature_columns_exclude_metadata(self):
        features = TrainingSample.get_feature_columns()
        meta = {"game_id", "game_date", "home_team", "away_team",
                "home_score", "away_score", "home_team_won"}
        for meta_field in meta:
            assert meta_field not in features

    def test_odds_not_in_features(self):
        """odds_implied_home_prob darf nicht als Feature genutzt werden."""
        features = TrainingSample.get_feature_columns()
        assert "odds_implied_home_prob" not in features, (
            "odds_implied_home_prob sollte aus Features ausgeschlossen sein, "
            "weil es im Training immer 0.5 ist."
        )

    def test_feature_columns_include_key_stats(self):
        features = TrainingSample.get_feature_columns()
        required = [
            "home_win_rate", "away_win_rate",
            "home_net_rating", "away_net_rating",
            "diff_win_rate",
        ]
        for req in required:
            assert req in features, f"Feature '{req}' fehlt"

    def test_v2_features_present(self):
        """Alle v2-Features sind enthalten."""
        features = TrainingSample.get_feature_columns()
        v2_features = [
            "home_current_streak", "home_fatigue_score",
            "home_form_rating", "home_games_last_7_days",
            "away_current_streak", "away_fatigue_score",
            "away_form_rating", "away_games_last_7_days",
            "diff_streak", "diff_fatigue",
        ]
        for feat in v2_features:
            assert feat in features, f"v2-Feature '{feat}' fehlt"

    def test_elo_features_present(self):
        """Alle Elo-Features sind enthalten."""
        features = TrainingSample.get_feature_columns()
        for feat in ("home_elo", "away_elo", "diff_elo"):
            assert feat in features, f"Elo-Feature '{feat}' fehlt"

    def test_sample_creation_with_all_fields(self):
        sample = make_sample()
        assert sample.home_team_won == 1
        assert sample.home_win_rate == pytest.approx(0.6)
        assert sample.home_current_streak == 2
        assert sample.diff_fatigue == pytest.approx(-0.30)
        assert sample.home_elo == pytest.approx(1550.0)
        assert sample.diff_elo == pytest.approx(70.0)

    def test_asdict_contains_all_fields(self):
        sample = make_sample()
        d = asdict(sample)
        assert "home_team_won" in d
        assert "home_current_streak" in d
        assert "diff_streak" in d
        assert "diff_fatigue" in d
        assert "home_elo" in d
        assert "away_elo" in d
        assert "diff_elo" in d
        # odds-Feld existiert weiterhin im Dataclass
        assert "odds_implied_home_prob" in d


# ══════════════════════════════════════════════════════════════════════════════
#  _CumulativeTeamTracker Tests (v4 – Data Leakage Fix)
# ══════════════════════════════════════════════════════════════════════════════


class TestCumulativeTeamTracker:
    """Tests für den kumulativen Stats-Tracker."""

    def test_initial_state_uses_defaults(self):
        """Vor dem ersten Spiel: Default-Werte."""
        tracker = _CumulativeTeamTracker("Test Team")
        assert tracker.win_rate == 0.5
        assert tracker.games_played == 0
        assert tracker.avg_pts_scored == 113.0  # NBA-Durchschnitt
        assert tracker.current_streak == 0

    def test_stats_update_after_win(self):
        """Nach einem Sieg: Stats korrekt aktualisiert."""
        tracker = _CumulativeTeamTracker("Test Team")
        tracker.update(110, 100, True, True, "2024-10-22")
        assert tracker.win_rate == 1.0
        assert tracker.games_played == 1
        assert tracker.avg_pts_scored == 110.0
        assert tracker.current_streak == 1

    def test_stats_update_after_loss(self):
        """Nach einer Niederlage: Stats korrekt aktualisiert."""
        tracker = _CumulativeTeamTracker("Test Team")
        tracker.update(95, 105, True, False, "2024-10-22")
        assert tracker.win_rate == 0.0
        assert tracker.current_streak == -1

    def test_cumulative_no_leakage(self):
        """Kumulative Stats dürfen KEINE zukünftigen Spiele enthalten."""
        tracker = _CumulativeTeamTracker("Test Team")

        # Spiel 1: Sieg
        tracker.update(110, 100, True, True, "2024-10-22")
        assert tracker.win_rate == 1.0  # 1/1

        # Spiel 2: Niederlage
        tracker.update(95, 105, False, False, "2024-10-24")
        assert tracker.win_rate == 0.5  # 1/2
        assert tracker.avg_pts_scored == 102.5  # (110+95)/2

        # Spiel 3: Sieg
        tracker.update(120, 110, True, True, "2024-10-26")
        assert tracker.win_rate == pytest.approx(2 / 3)  # 2/3
        assert tracker.current_streak == 1

    def test_home_away_win_rate_tracked_separately(self):
        """Heim- und Auswärts-Win-Rate werden getrennt gezählt."""
        tracker = _CumulativeTeamTracker("Test Team")
        tracker.update(110, 100, True, True, "2024-10-22")    # Heimsieg
        tracker.update(95, 105, False, False, "2024-10-24")   # Auswärtsniederlage
        assert tracker.home_win_rate == 1.0  # 1/1 Heim
        assert tracker.away_win_rate == 0.0  # 0/1 Auswärts

    def test_days_rest_before(self):
        """Ruhetage werden korrekt berechnet."""
        tracker = _CumulativeTeamTracker("Test Team")
        tracker.update(110, 100, True, True, "2024-10-22")
        rest = tracker.days_rest_before("2024-10-25")
        assert rest == 2  # 25 - 22 - 1 = 2

    def test_last_5_win_rate(self):
        """Letzte-5-Spiele-Quote wird korrekt berechnet."""
        tracker = _CumulativeTeamTracker("Test Team")
        for i in range(10):
            won = i >= 5  # Erste 5 verloren, letzte 5 gewonnen
            tracker.update(100 + i, 100, True, won, f"2024-10-{22+i}")
        assert tracker.last_5_win_rate == 1.0

    def test_form_rating(self):
        """Form-Rating gewichtet neuere Spiele stärker."""
        tracker = _CumulativeTeamTracker("Test Team")
        # 4 Niederlagen, dann 1 Sieg (neuestes Spiel)
        for i in range(4):
            tracker.update(95, 105, True, False, f"2024-10-{22+i}")
        tracker.update(120, 100, True, True, "2024-10-26")
        # Neuester Sieg hat höchstes Gewicht → Rating > 0.2 (= 1/5)
        assert tracker.form_rating > 0.2

    def test_advanced_stats_not_on_tracker(self):
        """_CumulativeTeamTracker hat keine compute_advanced_stats mehr."""
        tracker = _CumulativeTeamTracker("Test Team")
        assert not hasattr(tracker, "compute_advanced_stats")


# ══════════════════════════════════════════════════════════════════════════════
#  NBAModelTrainer Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestNBAModelTrainer:

    def _make_samples(self, n: int = 100) -> list[TrainingSample]:
        samples = []
        for i in range(n):
            samples.append(make_sample(
                home_won=i % 2,
                home_win_rate=0.4 + (i % 5) * 0.05,
                away_win_rate=0.3 + (i % 4) * 0.05,
                home_net_rating=-5.0 + i * 0.15,
                away_net_rating=-3.0 + i * 0.10,
                home_elo=1450.0 + i * 1.0,
                away_elo=1550.0 - i * 0.5,
                diff_elo=(1450.0 + i) - (1550.0 - i * 0.5),
            ))
        return samples

    def test_train_returns_metrics(self, tmp_path):
        samples = self._make_samples(100)
        trainer = NBAModelTrainer()
        # Temporäre Pfade setzen
        import src.ml.model_trainer as mt
        orig_model = mt.MODEL_PATH
        orig_metrics = mt.METRICS_PATH
        mt.MODEL_PATH = tmp_path / "model.joblib"
        mt.METRICS_PATH = tmp_path / "metrics.json"
        mt.MODEL_DIR = tmp_path

        try:
            metrics = trainer.train(samples=samples, test_size=0.3)
            assert isinstance(metrics, ModelMetrics)
            assert 0.0 <= metrics.accuracy <= 1.0
            assert metrics.feature_count == 45  # v4: 45 statt 46
        finally:
            mt.MODEL_PATH = orig_model
            mt.METRICS_PATH = orig_metrics

    def test_feature_names_match_sample_columns(self):
        trainer = NBAModelTrainer()
        expected = TrainingSample.get_feature_columns()
        assert trainer.feature_names == expected


# ══════════════════════════════════════════════════════════════════════════════
#  MLPredictor Tests
# ══════════════════════════════════════════════════════════════════════════════


def _make_adv_stats(name: str) -> AdvancedTeamStats:
    return AdvancedTeamStats(
        team_id=1, team_name=name,
        offensive_rating=112.0, defensive_rating=108.0,
        net_rating=4.0, pace=98.0, true_shooting_pct=0.57,
    )


def _predictor_with_cache(config, *team_names) -> MLPredictor:
    """Erstellt MLPredictor mit vorbeladenem Advanced-Stats-Cache."""
    predictor = MLPredictor(config)
    predictor._adv_stats_cache = {name: _make_adv_stats(name) for name in team_names}
    predictor._elo_cache = {name: 1500.0 for name in team_names}
    return predictor


class TestMLPredictor:

    def test_predict_returns_ml_prediction_result(self, mock_config):
        predictor = _predictor_with_cache(mock_config, "Lakers", "Celtics")
        home = make_team("Lakers", wins=50, losses=20)
        away = make_team("Celtics", wins=45, losses=25)
        result = predictor.predict(home, away)
        assert isinstance(result, MLPredictionResult)

    def test_predict_winner_is_home_or_away(self, mock_config):
        predictor = _predictor_with_cache(mock_config, "A", "B")
        result = predictor.predict(make_team("A"), make_team("B"))
        assert result.ml_predicted_winner in ("home", "away")

    def test_predict_probability_in_valid_range(self, mock_config):
        predictor = _predictor_with_cache(mock_config, "A", "B")
        result = predictor.predict(make_team("A"), make_team("B"))
        assert 0.0 <= result.ml_home_win_probability <= 1.0

    def test_predict_with_odds_sets_odds_probability(self, mock_config):
        predictor = _predictor_with_cache(mock_config, "A", "B")
        odds = GameOdds(home_team="A", away_team="B", odds_home=1.80, odds_away=2.10)
        result = predictor.predict(make_team("A"), make_team("B"), odds=odds)
        assert result.odds_home_win_probability is not None
        assert 0.0 < result.odds_home_win_probability < 1.0

    def test_consensus_agreement_count_is_1_to_2(self, mock_config):
        predictor = _predictor_with_cache(mock_config, "A", "B")
        result = predictor.predict(make_team("A"), make_team("B"))
        assert 1 <= result.consensus_agreement_count <= 2

    def test_build_feature_vector_has_correct_length(self, mock_config):
        """Feature-Vektor hat exakt 45 Einträge (v4 ohne odds)."""
        predictor = _predictor_with_cache(mock_config, "A", "B")
        home = make_team("A")
        away = make_team("B")
        home_adv = predictor._get_advanced_stats(home)
        away_adv = predictor._get_advanced_stats(away)
        vector = predictor._build_feature_vector(home, away, home_adv, away_adv)
        expected_length = len(TrainingSample.get_feature_columns())
        assert len(vector) == expected_length
        assert expected_length == 45

    def test_get_advanced_stats_raises_if_team_not_found(self, mock_config):
        """RuntimeError wenn Team nicht im Cache."""
        predictor = MLPredictor(mock_config)
        predictor._adv_stats_cache = {}
        with pytest.raises(RuntimeError, match="Advanced Stats"):
            predictor._get_advanced_stats(make_team("Unbekannt"))


# ══════════════════════════════════════════════════════════════════════════════
#  ComparisonEntry Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestComparisonEntry:

    def _make_entry(self, ml_home=0.65, odds_home_raw=1.67, odds_away_raw=2.50):
        odds_h = 1.0 / odds_home_raw
        odds_a = 1.0 / odds_away_raw
        total = odds_h + odds_a
        return ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=ml_home, ml_away_prob=1 - ml_home,
            ml_winner="home" if ml_home >= 0.5 else "away",
            odds_home_prob=odds_h / total, odds_away_prob=odds_a / total,
            odds_winner="home" if (odds_h / total) >= 0.5 else "away",
            odds_home_raw=odds_home_raw, odds_away_raw=odds_away_raw,
            prob_difference=abs(ml_home - odds_h / total),
        )

    def test_ev_home_positive_when_ml_overestimates(self):
        entry = self._make_entry(ml_home=0.75, odds_home_raw=1.80)
        assert entry.ev_home == pytest.approx(0.75 * 1.80 - 1.0, abs=0.001)

    def test_ev_away_computed_correctly(self):
        entry = self._make_entry(ml_home=0.40, odds_away_raw=2.10)
        assert entry.ev_away == pytest.approx(0.60 * 2.10 - 1.0, abs=0.001)

    def test_edge_home_positive_when_ml_higher_than_odds(self):
        entry = self._make_entry(ml_home=0.70, odds_home_raw=1.80)
        assert entry.edge_home > 0

    def test_normalize_odds_removes_vig(self):
        h, a = OddsVsMLComparison._normalize_odds(1.90, 2.00)
        assert pytest.approx(h + a, abs=0.001) == 1.0
        assert h > a


# ══════════════════════════════════════════════════════════════════════════════
#  Elo Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestElo:

    def test_calculate_elo_ratings_basic(self):
        from src.ml.elo import calculate_elo_ratings
        from src.models.game import Game

        games = [
            Game(game_id=1, home_team="A", away_team="B",
                 home_score=110, away_score=100, status="Final", date="2025-01-01"),
            Game(game_id=2, home_team="B", away_team="A",
                 home_score=105, away_score=95, status="Final", date="2025-01-02"),
        ]
        elo = calculate_elo_ratings(games)
        assert "A" in elo
        assert "B" in elo

    def test_elo_per_game_returns_before_values(self):
        from src.ml.elo import calculate_elo_per_game
        from src.models.game import Game

        games = [
            Game(game_id=1, home_team="A", away_team="B",
                 home_score=110, away_score=100, status="Final", date="2025-01-01"),
        ]
        per_game = calculate_elo_per_game(games)
        assert 1 in per_game
        h_elo, a_elo = per_game[1]
        assert h_elo == pytest.approx(1500.0)
        assert a_elo == pytest.approx(1500.0)

    def test_winner_gains_elo(self):
        from src.ml.elo import calculate_elo_ratings
        from src.models.game import Game

        games = [
            Game(game_id=1, home_team="Winner", away_team="Loser",
                 home_score=120, away_score=90, status="Final", date="2025-01-01"),
        ]
        elo = calculate_elo_ratings(games)
        assert elo["Winner"] > 1500.0
        assert elo["Loser"] < 1500.0
