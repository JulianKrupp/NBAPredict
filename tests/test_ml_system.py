"""
Unit-Tests für das ML-System (v3) – 46 Features inkl. Elo.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock
from dataclasses import asdict

from src.ml.data_collector import TrainingSample
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
    """Erstellt ein Minimal-TrainingSample (v3 mit 46 Features)."""
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
        # Odds + Label
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
    """Tests für das TrainingSample-Datenmodell (v3)."""

    def test_get_feature_columns_returns_list(self):
        features = TrainingSample.get_feature_columns()
        assert isinstance(features, list)
        assert len(features) > 0

    def test_feature_count_is_46(self):
        """v3 hat 46 Feature-Spalten (43 v2 + 3 Elo)."""
        features = TrainingSample.get_feature_columns()
        assert len(features) == 46

    def test_feature_columns_exclude_metadata(self):
        features = TrainingSample.get_feature_columns()
        meta = {"game_id", "game_date", "home_team", "away_team",
                "home_score", "away_score", "home_team_won"}
        for meta_field in meta:
            assert meta_field not in features

    def test_feature_columns_include_key_stats(self):
        features = TrainingSample.get_feature_columns()
        required = [
            "home_win_rate", "away_win_rate",
            "home_net_rating", "away_net_rating",
            "diff_win_rate", "odds_implied_home_prob",
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
            assert metrics.feature_count == 46
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


class TestMLPredictor:

    def test_predict_returns_ml_prediction_result(self, mock_config):
        predictor = MLPredictor(mock_config)
        home = make_team("Lakers", wins=50, losses=20)
        away = make_team("Celtics", wins=45, losses=25)
        result = predictor.predict(home, away)
        assert isinstance(result, MLPredictionResult)

    def test_predict_winner_is_home_or_away(self, mock_config):
        predictor = MLPredictor(mock_config)
        result = predictor.predict(make_team("A"), make_team("B"))
        assert result.ml_predicted_winner in ("home", "away")

    def test_predict_probability_in_valid_range(self, mock_config):
        predictor = MLPredictor(mock_config)
        result = predictor.predict(make_team("A"), make_team("B"))
        assert 0.0 <= result.ml_home_win_probability <= 1.0

    def test_predict_with_odds_sets_odds_probability(self, mock_config):
        predictor = MLPredictor(mock_config)
        odds = GameOdds(home_team="A", away_team="B", odds_home=1.80, odds_away=2.10)
        result = predictor.predict(make_team("A"), make_team("B"), odds=odds)
        assert result.odds_home_win_probability is not None
        assert 0.0 < result.odds_home_win_probability < 1.0

    def test_consensus_agreement_count_is_1_to_3(self, mock_config):
        predictor = MLPredictor(mock_config)
        result = predictor.predict(make_team("A"), make_team("B"))
        assert 1 <= result.consensus_agreement_count <= 3

    def test_build_feature_vector_has_correct_length(self, mock_config):
        """Feature-Vektor hat exakt 46 Einträge (v3 mit Elo)."""
        predictor = MLPredictor(mock_config)
        # Elo-Cache manuell setzen damit kein API-Call nötig
        predictor._elo_cache = {"A": 1550.0, "B": 1480.0}
        home = make_team("A")
        away = make_team("B")
        home_adv = predictor._get_advanced_stats(home)
        away_adv = predictor._get_advanced_stats(away)
        vector = predictor._build_feature_vector(home, away, home_adv, away_adv, None)
        expected_length = len(TrainingSample.get_feature_columns())
        assert len(vector) == expected_length
        assert expected_length == 46


# ══════════════════════════════════════════════════════════════════════════════
#  ComparisonEntry Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestComparisonEntry:

    def test_methods_agree_when_same_winner(self):
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.65, ml_away_prob=0.35, ml_winner="home",
            odds_home_prob=0.60, odds_away_prob=0.40, odds_winner="home",
            odds_home_raw=1.67, odds_away_raw=2.50,
            prob_difference=0.05,
        )
        assert entry.methods_agree is True

    def test_methods_disagree_when_different_winner(self):
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.45, ml_away_prob=0.55, ml_winner="away",
            odds_home_prob=0.60, odds_away_prob=0.40, odds_winner="home",
            odds_home_raw=1.67, odds_away_raw=2.50,
            prob_difference=0.15,
        )
        assert entry.methods_agree is False

    def test_value_bet_indicator_returns_string(self):
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.55, ml_away_prob=0.45, ml_winner="home",
            odds_home_prob=0.50, odds_away_prob=0.50, odds_winner="home",
            odds_home_raw=2.0, odds_away_raw=2.0,
            prob_difference=0.05,
        )
        assert isinstance(entry.value_bet_indicator, str)
        assert len(entry.value_bet_indicator) > 0

    def test_normalize_odds_removes_vig(self):
        h, a = OddsVsMLComparison._normalize_odds(1.90, 2.00)
        assert pytest.approx(h + a, abs=0.001) == 1.0
        assert h > a  # Niedrigere Quote = höhere Wahrscheinlichkeit


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
        # Vor dem ersten Spiel sollten beide bei 1500 starten
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
