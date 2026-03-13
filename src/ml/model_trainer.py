"""
Modelltraining für die Spielvorhersage.

Drei Kandidaten (Random Forest, Gradient Boosting, Logistische Regression)
werden per 5-Fold Stratified CV verglichen. Das beste Modell wird
gespeichert und kann danach per load_model() geladen werden.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split, StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss

from src.ml.data_collector import TrainingSample, TRAINING_DATA_PATH

logger = logging.getLogger(__name__)

MODEL_DIR   = Path("data/models")
MODEL_PATH  = MODEL_DIR / "nba_predictor.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.json"


@dataclass
class ModelMetrics:
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
    Trainiert und evaluiert drei ML-Modelle auf NBA-Spielhistorie.

    Hyperparameter wurden manuell gewählt – bei 300–500 Samples ist
    aufwändiges Tuning (Grid Search) wegen Overfitting-Risiko nicht sinnvoll.
    """

    CANDIDATE_MODELS = {
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=8, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.05,
            subsample=0.8, random_state=42,
        ),
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=42)),
        ]),
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.feature_names: list[str] = TrainingSample.get_feature_columns()

    def train(
        self,
        samples: list[TrainingSample] | None = None,
        data_path: Path = TRAINING_DATA_PATH,
        test_size: float = 0.2,
    ) -> ModelMetrics:
        """Trainiert alle Kandidaten, wählt das beste per CV und speichert es."""
        if samples is None:
            from src.ml.data_collector import TrainingDataCollector
            samples = TrainingDataCollector.load_from_csv(data_path)

        if len(samples) < 50:
            raise ValueError(f"Zu wenige Samples: {len(samples)} (min. 50 erforderlich).")

        self.logger.info("Training mit %d Samples gestartet.", len(samples))
        print(f"\n{'='*60}")
        print(f"  Training  |  {len(samples)} Samples  |  {len(self.feature_names)} Features")
        print(f"{'='*60}")

        X, y = self._prepare_data(samples)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )
        print(f"  Train: {len(X_train)}  |  Test: {len(X_test)}")

        best_name, best_model, best_cv = self._select_best_model(X_train, y_train)
        print(f"\n  Gewinner: {best_name} (CV: {best_cv:.1%})")
        print("  Finales Training...")
        best_model.fit(X_train, y_train)

        metrics = self._evaluate_model(best_model, best_name, X_train, X_test, y_train, y_test)
        self._save_model(best_model, metrics)
        self._print_metrics(metrics)
        return metrics

    def load_model(self) -> Any:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Kein Modell unter {MODEL_PATH}. Erst 'train model' ausführen."
            )
        return joblib.load(MODEL_PATH)

    def load_metrics(self) -> dict | None:
        if not METRICS_PATH.exists():
            return None
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _prepare_data(self, samples: list[TrainingSample]) -> tuple[np.ndarray, np.ndarray]:
        from dataclasses import asdict
        X, y = [], []
        for s in samples:
            row = asdict(s)
            X.append([row[f] for f in self.feature_names])
            y.append(s.home_team_won)
        return np.array(X, dtype=float), np.array(y, dtype=int)

    def _select_best_model(self, X_train: np.ndarray, y_train: np.ndarray) -> tuple[str, Any, float]:
        # Stratified, damit die Klassenverteilung in jedem Fold gleich bleibt
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        best_name, best_model, best_score = "", None, 0.0

        for name, model in self.CANDIDATE_MODELS.items():
            scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")
            print(f"  {name:<25} CV: {scores.mean():.1%} ± {scores.std():.1%}")
            if scores.mean() > best_score:
                best_score = scores.mean()
                best_name  = name
                best_model = model

        return best_name, best_model, best_score

    def _evaluate_model(
        self, model: Any, name: str,
        X_train: np.ndarray, X_test: np.ndarray,
        y_train: np.ndarray, y_test: np.ndarray,
    ) -> ModelMetrics:
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")

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

    def _extract_feature_importance(self, model: Any, top_n: int = 10) -> list[tuple[str, float]]:
        try:
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
            elif hasattr(model, "named_steps"):
                clf = model.named_steps.get("clf")
                imp = np.abs(clf.coef_[0]) if hasattr(clf, "coef_") else None
                if imp is None:
                    return []
            else:
                return []
            indices = np.argsort(imp)[::-1][:top_n]
            return [(self.feature_names[i], float(imp[i])) for i in indices]
        except Exception:
            return []

    def _save_model(self, model: Any, metrics: ModelMetrics) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        self.logger.info("Modell gespeichert: %s", MODEL_PATH)

    @staticmethod
    def _print_metrics(metrics: ModelMetrics) -> None:
        print(f"\n  Accuracy:   {metrics.accuracy:.1%}")
        print(f"  ROC-AUC:    {metrics.roc_auc:.3f}")
        print(f"  Brier Score:{metrics.brier_score:.3f}")
        if metrics.top_features:
            print("  Top-Features:")
            for feat, imp in metrics.top_features[:5]:
                print(f"    {feat:<30} {imp:.3f}")
