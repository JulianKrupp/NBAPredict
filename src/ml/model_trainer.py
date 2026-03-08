"""
NBA Vorhersagemodell basierend auf Random Forest Classifier.

Das Modell wird auf historischen Spieldaten trainiert und kann
Siegwahrscheinlichkeiten für zukünftige Spiele schätzen.
Zusätzlich wird ein Gradient Boosting Modell als Alternative trainiert,
und das beste Modell per Cross-Validation ausgewählt.
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
from sklearn.model_selection import (
    cross_val_score,
    train_test_split,
    StratifiedKFold,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    accuracy_score,
    roc_auc_score,
    classification_report,
    brier_score_loss,
)

from src.ml.data_collector import TrainingSample, TRAINING_DATA_PATH

logger = logging.getLogger(__name__)

# Modell-Speicherpfade
MODEL_DIR = Path("data/models")
MODEL_PATH = MODEL_DIR / "nba_predictor.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.json"


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
            "model_name": self.model_name,
            "accuracy": round(self.accuracy, 4),
            "roc_auc": round(self.roc_auc, 4),
            "brier_score": round(self.brier_score, 4),
            "cv_accuracy_mean": round(self.cv_accuracy_mean, 4),
            "cv_accuracy_std": round(self.cv_accuracy_std, 4),
            "train_samples": self.train_samples,
            "test_samples": self.test_samples,
            "feature_count": self.feature_count,
            "top_features": [
                {"feature": f, "importance": round(i, 4)}
                for f, i in self.top_features
            ],
        }


class NBAModelTrainer:
    """
    Trainiert und evaluiert mehrere ML-Modelle auf NBA-Trainingsdaten.

    Vergleicht Random Forest, Gradient Boosting und Logistische Regression,
    wählt das beste Modell per Cross-Validation aus und speichert es.
    """

    CANDIDATE_MODELS = {
        "RandomForest": RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        ),
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                C=1.0,
                max_iter=1000,
                random_state=42,
            )),
        ]),
    }

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
        """
        Trainiert alle Kandidatenmodelle und speichert das beste.

        Args:
            samples:   Optionale Liste von Trainingssamples (sonst aus CSV laden).
            data_path: Pfad zur CSV-Datei (falls samples=None).
            test_size: Anteil der Testdaten (0.0–1.0).

        Returns:
            Metriken des besten Modells.

        Raises:
            FileNotFoundError: Wenn keine Trainingsdaten gefunden werden.
            ValueError: Wenn zu wenige Trainingssamples vorhanden sind.
        """
        if samples is None:
            from src.ml.data_collector import TrainingDataCollector
            samples = TrainingDataCollector.load_from_csv(data_path)

        if len(samples) < 50:
            raise ValueError(
                f"Zu wenige Trainingsdaten: {len(samples)} Samples. "
                "Mindestens 50 erforderlich."
            )

        self.logger.info("Starte Training mit %d Samples", len(samples))
        print(f"\n{'='*60}")
        print(f"  🤖 ML-Modell Training")
        print(f"  Samples: {len(samples)} | Features: {len(self.feature_names)}")
        print(f"{'='*60}")

        X, y = self._prepare_data(samples)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )

        print(f"\n  Train: {len(X_train)} | Test: {len(X_test)}")
        print(f"  Home-Win-Rate Train: {y_train.mean():.1%}")

        # Alle Kandidaten evaluieren
        best_model_name, best_model, best_cv_score = self._select_best_model(
            X_train, y_train
        )

        # Finales Training auf allen Trainingsdaten
        print(f"\n  🏆 Bestes Modell: {best_model_name} (CV Accuracy: {best_cv_score:.1%})")
        print("  Trainiere finales Modell...")
        best_model.fit(X_train, y_train)

        # Evaluation auf Testdaten
        metrics = self._evaluate_model(
            best_model, best_model_name, X_train, X_test, y_train, y_test
        )

        # Modell speichern
        self._save_model(best_model, metrics)
        self._print_metrics(metrics)

        return metrics

    def load_model(self) -> Any:
        """
        Lädt das gespeicherte Modell.

        Returns:
            Trainiertes sklearn-Modell.

        Raises:
            FileNotFoundError: Wenn kein trainiertes Modell gefunden wird.
        """
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Kein trainiertes Modell gefunden: {MODEL_PATH}\n"
                "Führe zuerst 'python main.py train model' aus."
            )
        return joblib.load(MODEL_PATH)

    def load_metrics(self) -> dict | None:
        """Lädt gespeicherte Modell-Metriken."""
        if not METRICS_PATH.exists():
            return None
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)

    # ── Private Methoden ─────────────────────────────────────────────────

    def _prepare_data(
        self, samples: list[TrainingSample]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Konvertiert Trainingssamples in numpy-Arrays."""
        from dataclasses import asdict
        X_rows = []
        y_labels = []
        for sample in samples:
            row_dict = asdict(sample)
            features = [row_dict[f] for f in self.feature_names]
            X_rows.append(features)
            y_labels.append(sample.home_team_won)
        return np.array(X_rows, dtype=float), np.array(y_labels, dtype=int)

    def _select_best_model(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> tuple[str, Any, float]:
        """
        Vergleicht alle Kandidatenmodelle per 5-Fold Cross-Validation.

        Returns:
            (Modellname, Modell-Objekt, bester CV-Score)
        """
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        best_name = ""
        best_model = None
        best_score = 0.0

        for name, model in self.CANDIDATE_MODELS.items():
            scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")
            mean_score = scores.mean()
            print(f"  {name:<25} CV Accuracy: {mean_score:.1%} ± {scores.std():.1%}")

            if mean_score > best_score:
                best_score = mean_score
                best_name = name
                best_model = model

        return best_name, best_model, best_score

    def _evaluate_model(
        self,
        model: Any,
        model_name: str,
        X_train: np.ndarray,
        X_test: np.ndarray,
        y_train: np.ndarray,
        y_test: np.ndarray,
    ) -> ModelMetrics:
        """Berechnet alle Evaluationsmetriken auf dem Testset."""
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        accuracy = accuracy_score(y_test, y_pred)
        roc_auc = roc_auc_score(y_test, y_prob)
        brier = brier_score_loss(y_test, y_prob)

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")

        # Feature Importance (nur für baumbasierte Modelle)
        top_features = self._extract_feature_importance(model)

        return ModelMetrics(
            model_name=model_name,
            accuracy=accuracy,
            roc_auc=roc_auc,
            brier_score=brier,
            cv_accuracy_mean=cv_scores.mean(),
            cv_accuracy_std=cv_scores.std(),
            train_samples=len(X_train),
            test_samples=len(X_test),
            feature_count=len(self.feature_names),
            top_features=top_features,
        )

    def _extract_feature_importance(
        self, model: Any, top_n: int = 10
    ) -> list[tuple[str, float]]:
        """Extrahiert die wichtigsten Features (nur baumbasierte Modelle)."""
        try:
            if hasattr(model, "feature_importances_"):
                importances = model.feature_importances_
            elif hasattr(model, "named_steps"):
                clf = model.named_steps.get("clf")
                if hasattr(clf, "coef_"):
                    importances = np.abs(clf.coef_[0])
                else:
                    return []
            else:
                return []

            indices = np.argsort(importances)[::-1][:top_n]
            return [
                (self.feature_names[i], float(importances[i]))
                for i in indices
            ]
        except Exception:
            return []

    def _save_model(self, model: Any, metrics: ModelMetrics) -> None:
        """Speichert Modell und Metriken auf der Festplatte."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        self.logger.info("Modell gespeichert: %s", MODEL_PATH)

    @staticmethod
    def _print_metrics(metrics: ModelMetrics) -> None:
        """Gibt die Modell-Metriken formatiert aus."""
        print(f"\n  {'─'*56}")
        print(f"  📈 Modell-Evaluation: {metrics.model_name}")
        print(f"  {'─'*56}")
        print(f"  Accuracy (Test)  : {metrics.accuracy:.1%}")
        print(f"  ROC-AUC          : {metrics.roc_auc:.4f}")
        print(f"  Brier Score      : {metrics.brier_score:.4f}  (↓ besser)")
        print(f"  CV Accuracy      : {metrics.cv_accuracy_mean:.1%} ± {metrics.cv_accuracy_std:.1%}")
        if metrics.top_features:
            print(f"\n  Top-5 Features:")
            for feat, importance in metrics.top_features[:5]:
                bar = "█" * int(importance * 100)
                print(f"    {feat:<30} {importance:.3f}  {bar}")
        print(f"{'='*60}\n")
