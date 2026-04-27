"""
Unit-Tests für die ML-Pipeline (src/ml/pipeline.py).

Schwerpunkt: Status-Persistenz, Retrain-Entscheidungslogik und Fehlerpfade
in run(). Echtes Training wird über Mocks für TrainingDataCollector und
NBAModelTrainer vermieden – getestet wird die Pipeline-Steuerung selbst.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.ml import pipeline as pipeline_module
from src.ml.data_collector import _compute_fatigue, default_training_seasons
from src.ml.model_trainer import ModelMetrics
from src.ml.pipeline import MLPipeline

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def status_path(tmp_path, monkeypatch):
    """Leitet PIPELINE_STATUS_PATH auf eine temporäre Datei um."""
    path = tmp_path / "pipeline_status.json"
    monkeypatch.setattr(pipeline_module, "PIPELINE_STATUS_PATH", path)
    return path


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.balldontlie_api_key = "test"
    return cfg


def _make_metrics(model_id: str, roc_auc: float) -> ModelMetrics:
    return ModelMetrics(
        model_id=model_id,
        model_name=model_id.title(),
        accuracy=0.65,
        roc_auc=roc_auc,
        brier_score=0.22,
        cv_accuracy_mean=0.64,
        cv_accuracy_std=0.02,
        train_samples=800,
        test_samples=200,
        feature_count=45,
    )


# ── Status-Lesen ─────────────────────────────────────────────────────────────

class TestGetStatus:
    """get_status() liefert Default-Status, wenn keine Datei existiert."""

    def test_default_status_when_file_missing(self, status_path):
        assert not status_path.exists()
        status = MLPipeline().get_status()

        assert status["running"] is False
        assert status["last_trained_month"] is None
        assert status["models"] == []
        assert status["winner"] == ""
        assert status["error"] == ""

    def test_reads_existing_status_file(self, status_path):
        status_path.write_text(json.dumps({
            "running": True,
            "step": "Modelle trainieren",
            "last_trained_month": "2025-03",
            "winner": "xgboost",
        }), encoding="utf-8")

        status = MLPipeline().get_status()
        assert status["running"] is True
        assert status["step"] == "Modelle trainieren"
        assert status["winner"] == "xgboost"


# ── Retrain-Logik ────────────────────────────────────────────────────────────

class TestShouldRetrain:
    """should_retrain() vergleicht aktuellen Monat mit last_trained_month."""

    def test_retrain_when_no_history(self, status_path):
        # Kein Status vorhanden → Retrain erforderlich
        assert MLPipeline().should_retrain() is True

    def test_no_retrain_when_current_month_matches(self, status_path):
        current = datetime.now().strftime("%Y-%m")
        status_path.write_text(
            json.dumps({"last_trained_month": current}), encoding="utf-8"
        )
        assert MLPipeline().should_retrain() is False

    def test_retrain_when_month_outdated(self, status_path):
        status_path.write_text(
            json.dumps({"last_trained_month": "2020-01"}), encoding="utf-8"
        )
        assert MLPipeline().should_retrain() is True


class TestIsRunning:
    def test_returns_false_when_no_status(self, status_path):
        assert MLPipeline().is_running() is False

    def test_returns_running_flag(self, status_path):
        status_path.write_text(json.dumps({"running": True}), encoding="utf-8")
        assert MLPipeline().is_running() is True


# ── _update_status ───────────────────────────────────────────────────────────

class TestUpdateStatus:
    """_update_status() persistiert Felder und behält bestehende Werte bei."""

    def test_creates_file_with_new_fields(self, status_path):
        MLPipeline()._update_status(running=True, step="los geht's")
        data = json.loads(status_path.read_text(encoding="utf-8"))

        assert data["running"] is True
        assert data["step"] == "los geht's"
        # Default-Felder bleiben erhalten
        assert data["last_trained_month"] is None

    def test_merges_with_existing_status(self, status_path):
        pipeline = MLPipeline()
        pipeline._update_status(running=True, winner="xgboost")
        pipeline._update_status(running=False, step="Fertig")

        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["running"] is False
        assert data["step"] == "Fertig"
        # winner aus erstem Update bleibt erhalten
        assert data["winner"] == "xgboost"


# ── run() – Pipeline-Ausführung ──────────────────────────────────────────────

class TestRun:
    """Tests für run() mit gemockten Collector & Trainer."""

    def test_raises_when_config_is_none(self, status_path):
        with pytest.raises(ValueError, match="config"):
            MLPipeline().run(config=None)

    def test_returns_empty_when_no_samples(self, status_path, mock_config):
        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls:
            collector = mock_collector_cls.return_value
            collector.collect_with_progress.return_value = []

            result = MLPipeline().run(seasons=[2024], max_games=10, config=mock_config)

        assert result == []
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["running"] is False
        assert "Keine Trainingsdaten" in status["error"]

    def test_returns_empty_when_no_metrics(self, status_path, mock_config):
        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls, \
             patch("src.ml.pipeline.NBAModelTrainer") as mock_trainer_cls:
            mock_collector_cls.return_value.collect_with_progress.return_value = ["s1", "s2"]
            mock_trainer_cls.return_value.train_all.return_value = []

            result = MLPipeline().run(seasons=[2024], max_games=10, config=mock_config)

        assert result == []
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert "Kein Modell" in status["error"]

    def test_picks_best_by_roc_auc(self, status_path, mock_config):
        metrics_list = [
            _make_metrics("logistic_regression", roc_auc=0.70),
            _make_metrics("xgboost", roc_auc=0.72),
            _make_metrics("random_forest", roc_auc=0.68),
        ]

        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls, \
             patch("src.ml.pipeline.NBAModelTrainer") as mock_trainer_cls:
            mock_collector_cls.return_value.collect_with_progress.return_value = ["s1"]
            mock_trainer_cls.return_value.train_all.return_value = metrics_list

            result = MLPipeline().run(seasons=[2024], max_games=10, config=mock_config)

        assert len(result) == 3
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["winner"] == "xgboost"
        assert status["running"] is False
        assert status["step"] == "Fertig"
        assert status["last_trained_month"] == datetime.now().strftime("%Y-%m")
        # Alle Modelle landen in der Liste
        assert {m["model_id"] for m in status["models"]} == {
            "logistic_regression", "xgboost", "random_forest"
        }

    def test_progress_callback_invoked(self, status_path, mock_config):
        callback = MagicMock()
        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls, \
             patch("src.ml.pipeline.NBAModelTrainer") as mock_trainer_cls:
            mock_collector_cls.return_value.collect_with_progress.return_value = ["s1"]
            mock_trainer_cls.return_value.train_all.return_value = [
                _make_metrics("logistic_regression", roc_auc=0.7)
            ]

            MLPipeline().run(
                seasons=[2024], max_games=10, config=mock_config,
                progress_callback=callback,
            )

        # Callback wurde mindestens für Datensammlung und Training aufgerufen
        assert callback.call_count >= 2
        messages = [c.args[0] for c in callback.call_args_list]
        assert any("Trainingsdaten" in m for m in messages)
        assert any("Modelle trainieren" in m for m in messages)

    def test_records_error_on_exception(self, status_path, mock_config):
        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls:
            mock_collector_cls.return_value.collect_with_progress.side_effect = \
                RuntimeError("API kaputt")

            with pytest.raises(RuntimeError, match="API kaputt"):
                MLPipeline().run(seasons=[2024], max_games=10, config=mock_config)

        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["running"] is False
        assert status["error"] == "API kaputt"


# ── Hilfsfunktionen aus data_collector ───────────────────────────────────────

class TestDefaultTrainingSeasons:
    """default_training_seasons() berechnet die letzten n NBA-Saisons."""

    def test_returns_n_consecutive_years(self):
        seasons = default_training_seasons(n=4)
        assert len(seasons) == 4
        # Aufsteigend und lückenlos
        assert seasons == sorted(seasons)
        assert seasons[-1] - seasons[0] == 3

    def test_october_starts_new_season(self, monkeypatch):
        """Im Oktober beginnt die neue NBA-Saison X = Kalenderjahr."""
        import datetime as dt

        from src.ml import data_collector

        class FakeDate(dt.date):
            @classmethod
            def today(cls):
                return dt.date(2026, 10, 15)

        monkeypatch.setattr(data_collector, "date", FakeDate)
        # Oktober 2026 → aktuelle Saison = 2026
        assert default_training_seasons(n=2) == [2025, 2026]

    def test_september_still_uses_previous_season(self, monkeypatch):
        """Im September läuft Saison X-1 noch."""
        import datetime as dt

        from src.ml import data_collector

        class FakeDate(dt.date):
            @classmethod
            def today(cls):
                return dt.date(2026, 9, 30)

        monkeypatch.setattr(data_collector, "date", FakeDate)
        # September 2026 → aktuelle Saison = 2025
        assert default_training_seasons(n=2) == [2024, 2025]


class TestComputeFatigue:
    """Validiert die Ermüdungs-Berechnung gegen die dokumentierte Formel."""

    def test_three_or_more_rest_days_means_no_rest_fatigue(self):
        # Bei ≥3 Ruhetagen + ≤2 Spiele/7 Tage = 0
        assert _compute_fatigue(days_rest=3, games_last_7=2) == 0.0
        assert _compute_fatigue(days_rest=5, games_last_7=1) == 0.0

    def test_back_to_back_is_high_fatigue(self):
        # 0 Ruhetage = vollständige rest_fatigue
        result = _compute_fatigue(days_rest=0, games_last_7=2)
        assert result == pytest.approx(0.65)

    def test_dense_schedule_increases_fatigue(self):
        low = _compute_fatigue(days_rest=2, games_last_7=2)
        high = _compute_fatigue(days_rest=2, games_last_7=4)
        assert high > low

    def test_extreme_case_close_to_one(self):
        result = _compute_fatigue(days_rest=0, games_last_7=4)
        assert result == pytest.approx(1.0)


# Original test_uses_default_seasons_when_none neu definiert
class TestRunDefaultSeasons:
    def test_uses_default_seasons_when_none(self, status_path, mock_config):
        """Bei seasons=None werden default_training_seasons() verwendet."""
        with patch("src.ml.data_collector.TrainingDataCollector") as mock_collector_cls, \
             patch("src.ml.pipeline.NBAModelTrainer") as mock_trainer_cls, \
             patch("src.ml.pipeline.default_training_seasons", return_value=[2099]):
            mock_collector_cls.return_value.collect_with_progress.return_value = ["s"]
            mock_trainer_cls.return_value.train_all.return_value = [
                _make_metrics("logistic_regression", roc_auc=0.7)
            ]

            MLPipeline().run(config=mock_config, max_games=5)

            # Collector wurde mit den Default-Saisons aufgerufen
            call_kwargs = mock_collector_cls.return_value.collect_with_progress.call_args.kwargs
            assert call_kwargs["seasons"] == [2099]
