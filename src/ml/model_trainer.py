"""
Modelltraining für die NBA-Spielvorhersage.

Logistische Regression mit StandardScaler, optimiert auf neg_brier_score.
Kalibrierte Wahrscheinlichkeiten sind entscheidend für die EV-Berechnung.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import (
    GridSearchCV,
    cross_val_score,
    train_test_split,
    StratifiedKFold,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss

from src.ml.data_collector import TrainingSample, TRAINING_DATA_PATH

MODEL_DIR = Path("data/models")
MODEL_PATH = MODEL_DIR / "nba_predictor.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.json"

# Optimiert auf Kalibrierung statt Accuracy.
# Kalibrierte Wahrscheinlichkeiten sind für EV-Berechnung wichtiger als Trefferquote.
SCORING_METRIC = "neg_brier_score"


@dataclass
class ModelMetrics:
    """Bewertungsmetriken des trainierten Modells."""
    model_name: str
    accuracy: float
    roc_auc: float
    brier_score: float
    cv_accuracy_mean: float
    cv_accuracy_std: float
    train_samples: int
    test_samples: int
    feature_count: int
    top_features: list[tuple[str, float]]

    def to_dict(self) -> dict:
        return {
            "model_name":       self.model_name,
            "trained_at":       datetime.now().isoformat(timespec="seconds"),
            "accuracy":         round(self.accuracy, 4),
            "roc_auc":          round(self.roc_auc, 4),
            "brier_score":      round(self.brier_score, 4),
            "cv_accuracy_mean": round(self.cv_accuracy_mean, 4),
            "cv_accuracy_std":  round(self.cv_accuracy_std, 4),
            "train_samples":    self.train_samples,
            "test_samples":     self.test_samples,
            "feature_count":    self.feature_count,
            "top_features": [
                {"feature": f, "importance": round(i, 4)}
                for f, i in self.top_features
            ],
        }


class NBAModelTrainer:
    """
    Trainiert ein Logistic-Regression-Modell auf NBA-Spielhistorie.

    Bei >1000 Samples wird Grid Search für C-Tuning verwendet.
    StandardScaler normiert die Features (erforderlich für LR).
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.feature_names: list[str] = TrainingSample.get_feature_columns()

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def train(
        self,
        samples: list[TrainingSample] | None = None,
        data_path: Path = TRAINING_DATA_PATH,
        test_size: float = 0.2,
    ) -> ModelMetrics:
        """Trainiert LogReg und speichert das Modell."""
        if samples is None:
            from src.ml.data_collector import TrainingDataCollector
            samples = TrainingDataCollector.load_from_csv(data_path)

        if len(samples) < 50:
            raise ValueError(
                f"Zu wenige Trainingsdaten: {len(samples)} Samples. "
                "Mindestens 50 erforderlich."
            )

        self.logger.info("Training mit %d Samples gestartet.", len(samples))
        print(f"\n{'='*60}")
        print(f"  NBA ML-Training – Logistische Regression")
        print(f"  Samples: {len(samples)} | Features: {len(self.feature_names)}")
        print(f"  Scoring: {SCORING_METRIC}")
        print(f"{'='*60}")

        X, y = self._prepare_data(samples)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )

        print(f"\n  Train: {len(X_train)} | Test: {len(X_test)}")
        print(f"  Home-Win-Rate Train: {y_train.mean():.1%}")

        model = self._train_logreg(X_train, y_train)
        metrics = self._evaluate_model(
            model, "LogisticRegression", X_train, X_test, y_train, y_test
        )
        self._save_model(model, metrics)
        self._print_metrics(metrics)
        return metrics

    def load_model(self) -> Any:
        """Lädt das gespeicherte Modell."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Kein Modell unter {MODEL_PATH}. Erst 'train model' ausführen."
            )
        return joblib.load(MODEL_PATH)

    def load_metrics(self) -> dict | None:
        """Lädt gespeicherte Modell-Metriken."""
        if not METRICS_PATH.exists():
            return None
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)

    # ── Training ──────────────────────────────────────────────────────────

    def _train_logreg(self, X_train: np.ndarray, y_train: np.ndarray) -> Any:
        """
        Trainiert Logistic Regression mit StandardScaler.
        Bei >1000 Samples: Grid Search über C ∈ {0.1, 1.0, 10.0}.
        """
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, random_state=42)),
        ])

        if len(X_train) >= 1000:
            print("\n  Grid Search (C-Tuning)...", end=" ", flush=True)
            grid = GridSearchCV(
                pipeline,
                {"clf__C": [0.1, 1.0, 10.0]},
                cv=cv, scoring=SCORING_METRIC, n_jobs=-1, verbose=0,
            )
            grid.fit(X_train, y_train)
            best_c = grid.best_params_["clf__C"]
            print(f"Best C={best_c} | Score: {grid.best_score_:.4f}")
            return grid.best_estimator_
        else:
            print("\n  Feste Parameter (< 1000 Samples, C=1.0)")
            pipeline.fit(X_train, y_train)
            return pipeline

    # ── Evaluation & Speichern ────────────────────────────────────────────

    def _prepare_data(
        self, samples: list[TrainingSample]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Konvertiert Trainingssamples in numpy-Arrays."""
        from dataclasses import asdict
        X, y = [], []
        for s in samples:
            row = asdict(s)
            X.append([row[f] for f in self.feature_names])
            y.append(s.home_team_won)
        return np.array(X, dtype=float), np.array(y, dtype=int)

    def _evaluate_model(
        self, model: Any, name: str,
        X_train: np.ndarray, X_test: np.ndarray,
        y_train: np.ndarray, y_test: np.ndarray,
    ) -> ModelMetrics:
        """Berechnet alle Evaluationsmetriken auf dem Testset."""
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        cv_scores = cross_val_score(
            model, X_train, y_train, cv=cv, scoring="accuracy"
        )

        return ModelMetrics(
            model_name=name,
            accuracy=accuracy_score(y_test, y_pred),
            roc_auc=roc_auc_score(y_test, y_prob),
            brier_score=brier_score_loss(y_test, y_prob),
            cv_accuracy_mean=cv_scores.mean(),
            cv_accuracy_std=cv_scores.std(),
            train_samples=len(X_train),
            test_samples=len(X_test),
            feature_count=len(self.feature_names),
            top_features=self._extract_feature_importance(model),
        )

    def _extract_feature_importance(
        self, model: Any, top_n: int = 10
    ) -> list[tuple[str, float]]:
        """Extrahiert die wichtigsten Features aus den LR-Koeffizienten."""
        try:
            clf = model.named_steps.get("clf")
            if hasattr(clf, "coef_"):
                imp = np.abs(clf.coef_[0])
                indices = np.argsort(imp)[::-1][:top_n]
                return [(self.feature_names[i], float(imp[i])) for i in indices]
        except Exception:
            pass
        return []

    def _save_model(self, model: Any, metrics: ModelMetrics) -> None:
        """Speichert Modell und Metriken."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        self.logger.info("Modell gespeichert: %s", MODEL_PATH)

    @staticmethod
    def _print_metrics(metrics: ModelMetrics) -> None:
        """Gibt die Modell-Metriken formatiert aus."""
        print(f"\n  {'─'*50}")
        print(f"  Accuracy:    {metrics.accuracy:.1%}")
        print(f"  ROC-AUC:     {metrics.roc_auc:.3f}")
        print(f"  Brier Score: {metrics.brier_score:.3f}")
        print(f"  CV Accuracy: {metrics.cv_accuracy_mean:.1%} ± {metrics.cv_accuracy_std:.1%}")
        if metrics.top_features:
            print(f"  Top-Features:")
            for feat, imp in metrics.top_features[:5]:
                print(f"    {feat:<30} {imp:.3f}")
        print(f"  {'─'*50}\n")
