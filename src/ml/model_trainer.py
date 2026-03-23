"""
Modelltraining für die NBA-Spielvorhersage (v3).

Vier Kandidaten werden per Grid Search + 5-Fold Stratified CV verglichen:
  - Random Forest
  - Gradient Boosting (sklearn)
  - XGBoost (falls installiert)
  - Logistische Regression

Optimierungsziel: neg_brier_score (Kalibrierung statt Accuracy).
Das beste Modell wird gespeichert und kann per load_model() geladen werden.
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
    GridSearchCV,
    cross_val_score,
    train_test_split,
    StratifiedKFold,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss

from src.ml.data_collector import TrainingSample, TRAINING_DATA_PATH

logger = logging.getLogger(__name__)

MODEL_DIR = Path("data/models")
MODEL_PATH = MODEL_DIR / "nba_predictor.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.json"

# ── Scoring-Metrik ────────────────────────────────────────────────────────────
# neg_brier_score: Optimiert auf Kalibrierung statt Accuracy.
# Kalibrierte Wahrscheinlichkeiten sind für Wettempfehlungen wichtiger
# als reine Trefferquote. Niedriger Brier Score = besser kalibriert.
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


def _check_xgboost() -> bool:
    """Prüft ob XGBoost installiert ist."""
    try:
        import xgboost  # noqa: F401
        return True
    except ImportError:
        return False


HAS_XGBOOST = _check_xgboost()


class NBAModelTrainer:
    """
    Trainiert und evaluiert ML-Modelle auf NBA-Spielhistorie.

    Bei ausreichend Daten (>1000 Samples) wird Grid Search für
    Hyperparameter-Optimierung verwendet. Bei wenigen Daten
    werden feste, konservative Hyperparameter genutzt.
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
        """
        Trainiert alle Kandidatenmodelle und speichert das beste.

        Bei >1000 Samples wird Grid Search verwendet, sonst feste Parameter.
        Scoring: neg_brier_score (Kalibrierung).
        """
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
        print(f"  🤖 ML-Modell Training (v3)")
        print(f"  Samples: {len(samples)} | Features: {len(self.feature_names)}")
        print(f"  Scoring: {SCORING_METRIC}")
        if HAS_XGBOOST:
            print(f"  XGBoost: ✅ verfügbar")
        else:
            print(f"  XGBoost: ❌ nicht installiert (pip install xgboost)")
        print(f"{'='*60}")

        X, y = self._prepare_data(samples)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )

        print(f"\n  Train: {len(X_train)} | Test: {len(X_test)}")
        print(f"  Home-Win-Rate Train: {y_train.mean():.1%}")

        use_grid_search = len(X_train) >= 1000
        if use_grid_search:
            print(f"\n  📊 Grid Search aktiv (>1000 Samples)")
            best_name, best_model, best_cv = self._select_best_model_grid(X_train, y_train)
        else:
            print(f"\n  ⚡ Feste Parameter (< 1000 Samples)")
            best_name, best_model, best_cv = self._select_best_model_fixed(X_train, y_train)

        print(f"\n  🏆 Gewinner: {best_name} (CV Score: {best_cv:.4f})")
        print("  Finales Training...")

        # Grid Search gibt bereits gefitteten Estimator zurück
        if not use_grid_search:
            best_model.fit(X_train, y_train)

        metrics = self._evaluate_model(
            best_model, best_name, X_train, X_test, y_train, y_test
        )
        self._save_model(best_model, metrics)
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

    # ── Modellauswahl: Grid Search (>1000 Samples) ───────────────────────

    def _select_best_model_grid(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> tuple[str, Any, float]:
        """
        Grid Search über alle Kandidaten mit Hyperparameter-Tuning.
        Gibt das beste bereits gefittete Modell zurück.
        """
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        configs: dict[str, dict] = {
            "GradientBoosting": {
                "model": GradientBoostingClassifier(random_state=42),
                "params": {
                    "n_estimators": [150, 300],
                    "max_depth": [3, 5],
                    "learning_rate": [0.03, 0.08],
                    "subsample": [0.8],
                    "min_samples_leaf": [5],
                },
            },
            "RandomForest": {
                "model": RandomForestClassifier(
                    class_weight="balanced", random_state=42, n_jobs=-1
                ),
                "params": {
                    "n_estimators": [200, 400],
                    "max_depth": [6, 10],
                    "min_samples_leaf": [5],
                },
            },
            "LogisticRegression": {
                "model": Pipeline([
                    ("scaler", StandardScaler()),
                    ("clf", LogisticRegression(max_iter=1000, random_state=42)),
                ]),
                "params": {
                    "clf__C": [0.1, 1.0, 10.0],
                },
            },
        }

        if HAS_XGBOOST:
            import xgboost as xgb
            configs["XGBoost"] = {
                "model": xgb.XGBClassifier(
                    eval_metric="logloss", random_state=42,
                    n_jobs=-1, verbosity=0,
                ),
                "params": {
                    "n_estimators": [200, 400],
                    "max_depth": [4, 6],
                    "learning_rate": [0.03, 0.08],
                    "subsample": [0.8],
                    "reg_alpha": [0.1],
                    "reg_lambda": [1.0],
                },
            }

        best_name, best_model, best_score = "", None, float("-inf")

        for name, cfg in configs.items():
            print(f"  Grid Search: {name}...", end=" ", flush=True)
            grid = GridSearchCV(
                cfg["model"], cfg["params"],
                cv=cv, scoring=SCORING_METRIC,
                n_jobs=-1, verbose=0,
            )
            grid.fit(X_train, y_train)
            score = grid.best_score_
            print(f"Score: {score:.4f} | {grid.best_params_}")

            if score > best_score:
                best_score = score
                best_name = name
                best_model = grid.best_estimator_

        return best_name, best_model, best_score

    # ── Modellauswahl: Feste Parameter (<1000 Samples) ───────────────────

    def _select_best_model_fixed(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> tuple[str, Any, float]:
        """
        Vergleicht Kandidaten mit festen Hyperparametern per CV.
        Für kleine Datensätze wo Grid Search overfitting riskiert.
        """
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        candidates: dict[str, Any] = {
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

        if HAS_XGBOOST:
            import xgboost as xgb
            candidates["XGBoost"] = xgb.XGBClassifier(
                n_estimators=300, max_depth=5, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=1.0,
                eval_metric="logloss", random_state=42,
                n_jobs=-1, verbosity=0,
            )

        best_name, best_model, best_score = "", None, float("-inf")

        for name, model in candidates.items():
            scores = cross_val_score(
                model, X_train, y_train, cv=cv, scoring=SCORING_METRIC
            )
            mean_score = scores.mean()
            print(f"  {name:<25} CV: {mean_score:.4f} ± {scores.std():.4f}")

            if mean_score > best_score:
                best_score = mean_score
                best_name = name
                best_model = model

        return best_name, best_model, best_score

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
        """Extrahiert die wichtigsten Features."""
        try:
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
            elif hasattr(model, "named_steps"):
                clf = model.named_steps.get("clf")
                if hasattr(clf, "coef_"):
                    imp = np.abs(clf.coef_[0])
                else:
                    return []
            else:
                return []

            indices = np.argsort(imp)[::-1][:top_n]
            return [
                (self.feature_names[i], float(imp[i]))
                for i in indices
            ]
        except Exception:
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
