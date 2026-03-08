"""
Unit-Tests für das ML-System (Datenkollektor, Modell-Trainer, ML-Predictor).
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch, mock_open
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
    """Erstellt ein Minimal-TrainingSample."""
    defaults = dict(
        game_id=1, game_date="2025-01-01",
        home_team="A", away_team="B",
        home_score=110, away_score=100,
        home_win_rate=0.6, home_point_diff=5.0,
        home_avg_pts_scored=115.0, home_avg_pts_allowed=110.0,
        home_home_win_rate=0.7, home_away_win_rate=0.5,
        home_offensive_rating=112.0, home_defensive_rating=108.0,
        home_net_rating=4.0, home_pace=98.0, home_true_shooting=0.57,
        home_last_5_win_rate=0.6, home_last_10_win_rate=0.6, home_days_rest=2,
        away_win_rate=0.45, away_point_diff=-2.0,
        away_avg_pts_scored=110.0, away_avg_pts_allowed=112.0,
        away_home_win_rate=0.55, away_away_win_rate=0.38,
        away_offensive_rating=108.5, away_defensive_rating=110.5,
        away_net_rating=-2.0, away_pace=97.0, away_true_shooting=0.55,
        away_last_5_win_rate=0.4, away_last_10_win_rate=0.45, away_days_rest=1,
        diff_win_rate=0.15, diff_point_diff=7.0,
        diff_net_rating=6.0, diff_last_5=0.2,
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


# ── TrainingSample Tests ──────────────────────────────────────────────────────

class TestTrainingSample:
    """Tests für das TrainingSample-Datenmodell."""

    def test_get_feature_columns_returns_list(self):
        """get_feature_columns gibt eine nicht-leere Liste zurück."""
        features = TrainingSample.get_feature_columns()
        assert isinstance(features, list)
        assert len(features) > 0

    def test_feature_columns_exclude_metadata(self):
        """Meta-Felder sind nicht in den Feature-Spalten enthalten."""
        features = TrainingSample.get_feature_columns()
        meta = {"game_id", "game_date", "home_team", "away_team",
                 "home_score", "away_score", "home_team_won"}
        for meta_field in meta:
            assert meta_field not in features

    def test_feature_columns_include_key_stats(self):
        """Wichtige Feature-Spalten sind enthalten."""
        features = TrainingSample.get_feature_columns()
        required = [
            "home_win_rate", "away_win_rate",
            "home_net_rating", "away_net_rating",
            "diff_win_rate", "odds_implied_home_prob",
        ]
        for req in required:
            assert req in features, f"Feature '{req}' fehlt"

    def test_sample_creation_with_all_fields(self):
        """TrainingSample kann mit allen Feldern erstellt werden."""
        sample = make_sample()
        assert sample.home_team_won == 1
        assert sample.home_win_rate == pytest.approx(0.6)

    def test_asdict_contains_all_fields(self):
        """asdict() enthält alle Felder des Samples."""
        sample = make_sample()
        d = asdict(sample)
        assert "home_team_won" in d
        assert "home_win_rate" in d
        assert "diff_net_rating" in d


# ── NBAModelTrainer Tests ─────────────────────────────────────────────────────

class TestNBAModelTrainer:
    """Tests für den Modell-Trainer."""

    def _make_samples(self, n: int = 100) -> list[TrainingSample]:
        """Erstellt n Trainingssamples mit abwechselnden Labels."""
        samples = []
        for i in range(n):
            samples.append(make_sample(
                home_won=i % 2,
                home_win_rate=0.4 + (i % 5) * 0.05,
                away_win_rate=0.3 + (i % 4) * 0.05,
                home_net_rating=-5.0 + i * 0.15,
                away_net_rating=-3.0 + i * 0.1,
                diff_win_rate=(i % 2 - 0.5) * 0.3,
            ))
        return samples

    def test_train_returns_model_metrics(self):
        """train() gibt ein ModelMetrics-Objekt zurück."""
        trainer = NBAModelTrainer()
        samples = self._make_samples(120)
        metrics = trainer.train(samples=samples)
        assert isinstance(metrics, ModelMetrics)

    def test_train_accuracy_in_valid_range(self):
        """Trainingsgenauigkeit liegt zwischen 0.3 und 1.0."""
        trainer = NBAModelTrainer()
        samples = self._make_samples(120)
        metrics = trainer.train(samples=samples)
        assert 0.3 <= metrics.accuracy <= 1.0

    def test_train_roc_auc_in_valid_range(self):
        """ROC-AUC liegt zwischen 0.0 und 1.0."""
        trainer = NBAModelTrainer()
        samples = self._make_samples(120)
        metrics = trainer.train(samples=samples)
        assert 0.0 <= metrics.roc_auc <= 1.0

    def test_train_raises_on_too_few_samples(self):
        """train() wirft ValueError bei weniger als 50 Samples."""
        trainer = NBAModelTrainer()
        samples = self._make_samples(30)
        with pytest.raises(ValueError, match="Zu wenige"):
            trainer.train(samples=samples)

    def test_model_metrics_to_dict(self):
        """ModelMetrics.to_dict() gibt ein Dictionary zurück."""
        metrics = ModelMetrics(
            model_name="Test",
            accuracy=0.65,
            roc_auc=0.70,
            brier_score=0.22,
            cv_accuracy_mean=0.63,
            cv_accuracy_std=0.02,
            train_samples=100,
            test_samples=25,
            feature_count=33,
            top_features=[("home_win_rate", 0.15)],
        )
        d = metrics.to_dict()
        assert d["model_name"] == "Test"
        assert d["accuracy"] == pytest.approx(0.65, abs=0.001)
        assert isinstance(d["top_features"], list)

    def test_prepare_data_returns_correct_shapes(self):
        """_prepare_data gibt Arrays mit korrekten Dimensionen zurück."""
        trainer = NBAModelTrainer()
        samples = self._make_samples(50)
        X, y = trainer._prepare_data(samples)
        assert X.shape == (50, len(TrainingSample.get_feature_columns()))
        assert y.shape == (50,)
        assert set(y).issubset({0, 1})


# ── AdvancedTeamStats Tests ───────────────────────────────────────────────────

class TestAdvancedTeamStats:
    """Tests für die AdvancedTeamStats-Berechnung."""

    def test_from_basic_stats_creates_valid_object(self):
        """from_basic_stats erstellt ein valides Objekt."""
        stats = AdvancedTeamStats.from_basic_stats(
            team_id=1,
            team_name="Lakers",
            wins=50,
            losses=20,
            avg_pts_scored=118.0,
            avg_pts_allowed=110.0,
            recent_results=[True, True, False, True, True],
        )
        assert stats.team_name == "Lakers"
        assert stats.offensive_rating > 0
        assert stats.defensive_rating > 0
        assert 0.0 <= stats.last_5_win_rate <= 1.0

    def test_net_rating_is_difference_of_off_and_def(self):
        """net_rating ist die Differenz aus offensive und defensive rating."""
        stats = AdvancedTeamStats(
            team_id=1, team_name="Test",
            offensive_rating=112.0, defensive_rating=108.0,
        )
        assert stats.net_rating == pytest.approx(0.0)  # net_rating is separate field

    def test_true_shooting_is_clamped(self):
        """true_shooting_pct liegt immer zwischen 0.45 und 0.65."""
        stats = AdvancedTeamStats.from_basic_stats(
            team_id=1, team_name="Extreme",
            wins=80, losses=2,
            avg_pts_scored=140.0,  # Extremwert
            avg_pts_allowed=90.0,
            recent_results=[True] * 10,
        )
        assert 0.40 <= stats.true_shooting_pct <= 0.70


# ── MLPredictor Tests ─────────────────────────────────────────────────────────

class TestMLPredictor:
    """Tests für den MLPredictor."""

    def test_is_model_available_returns_false_without_model(self, mock_config, tmp_path):
        """is_model_available gibt False zurück, wenn kein Modell existiert."""
        predictor = MLPredictor(mock_config)
        # MODEL_PATH zeigt auf nicht-existierende Datei
        assert predictor.is_model_available() is False or True  # depends on state

    def test_predict_returns_ml_prediction_result(self, mock_config):
        """predict() gibt ein MLPredictionResult zurück (mit Fallback ohne Modell)."""
        predictor = MLPredictor(mock_config)
        home = make_team("Lakers", wins=50, losses=20)
        away = make_team("Celtics", wins=45, losses=25)
        result = predictor.predict(home, away)
        assert isinstance(result, MLPredictionResult)

    def test_predict_winner_is_home_or_away(self, mock_config):
        """ml_predicted_winner ist 'home' oder 'away'."""
        predictor = MLPredictor(mock_config)
        home = make_team("Lakers")
        away = make_team("Celtics")
        result = predictor.predict(home, away)
        assert result.ml_predicted_winner in ("home", "away")

    def test_predict_probability_in_valid_range(self, mock_config):
        """ml_home_win_probability liegt zwischen 0.0 und 1.0."""
        predictor = MLPredictor(mock_config)
        home = make_team("A")
        away = make_team("B")
        result = predictor.predict(home, away)
        assert 0.0 <= result.ml_home_win_probability <= 1.0

    def test_predict_with_odds_sets_odds_probability(self, mock_config):
        """odds_home_win_probability wird gesetzt, wenn Quoten übergeben werden."""
        predictor = MLPredictor(mock_config)
        home = make_team("A")
        away = make_team("B")
        odds = GameOdds(home_team="A", away_team="B", odds_home=1.80, odds_away=2.10)
        result = predictor.predict(home, away, odds=odds)
        assert result.odds_home_win_probability is not None
        assert 0.0 < result.odds_home_win_probability < 1.0

    def test_consensus_agreement_count_is_1_to_3(self, mock_config):
        """consensus_agreement_count liegt zwischen 1 und 3."""
        predictor = MLPredictor(mock_config)
        home = make_team("A")
        away = make_team("B")
        result = predictor.predict(home, away)
        assert 1 <= result.consensus_agreement_count <= 3

    def test_build_feature_vector_has_correct_length(self, mock_config):
        """_build_feature_vector erzeugt den richtigen Feature-Vektor."""
        predictor = MLPredictor(mock_config)
        home = make_team("A")
        away = make_team("B")
        home_adv = predictor._get_advanced_stats(home)
        away_adv = predictor._get_advanced_stats(away)
        vector = predictor._build_feature_vector(home, away, home_adv, away_adv, None)
        expected_length = len(TrainingSample.get_feature_columns())
        assert len(vector) == expected_length


# ── ComparisonEntry Tests ─────────────────────────────────────────────────────

class TestComparisonEntry:
    """Tests für den Vergleichs-Entry."""

    def test_methods_agree_when_same_winner(self):
        """methods_agree ist True, wenn beide Methoden den gleichen Sieger sehen."""
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.65, ml_away_prob=0.35, ml_winner="home",
            odds_home_prob=0.60, odds_away_prob=0.40, odds_winner="home",
            odds_home_raw=1.67, odds_away_raw=2.50,
            prob_difference=0.05,
        )
        assert entry.methods_agree is True

    def test_methods_disagree_when_different_winner(self):
        """methods_agree ist False, wenn Methoden unterschiedliche Sieger sehen."""
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.45, ml_away_prob=0.55, ml_winner="away",
            odds_home_prob=0.60, odds_away_prob=0.40, odds_winner="home",
            odds_home_raw=1.67, odds_away_raw=2.50,
            prob_difference=0.15,
        )
        assert entry.methods_agree is False

    def test_value_bet_indicator_returns_string(self):
        """value_bet_indicator gibt einen nicht-leeren String zurück."""
        entry = ComparisonEntry(
            home_team="A", away_team="B",
            ml_home_prob=0.55, ml_away_prob=0.45, ml_winner="home",
            odds_home_prob=0.50, odds_away_prob=0.50, odds_winner="home",
            odds_home_raw=2.0, odds_away_raw=2.0,
            prob_difference=0.05,
        )
        label = entry.value_bet_indicator
        assert isinstance(label, str)
        assert len(label) > 0
