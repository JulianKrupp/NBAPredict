"""
Multi-Modell-Training für die NBA-Spielvorhersage.

Vier Modelle (mit Literaturbelegen):
  1. Logistic Regression  – Kvam & Sokol (2006), J. Quantitative Analysis in Sports
  2. Random Forest        – Bunker & Thabtah (2019), Applied Computing and Informatics
  3. XGBoost              – Chen & Guestrin (2016), KDD; Zimmermann (2016), IJCAI
  4. MLP Neural Network   – Loeffelholz et al. (2009), J. Quantitative Analysis in Sports

Optimiert auf neg_brier_score (Kalibrierung), da kalibrierte Wahrscheinlichkeiten
für die EV-Berechnung wichtiger sind als pure Accuracy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import (
    cross_val_score,
    train_test_split,
    StratifiedKFold,
)
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss

try:
    from xgboost import XGBClassifier
    _XGBOOST_AVAILABLE = True
except ImportError:
    _XGBOOST_AVAILABLE = False

from src.ml.data_collector import TrainingSample, TRAINING_DATA_PATH

MODEL_DIR = Path("data/models")
ACTIVE_MODEL_PATH = MODEL_DIR / "active_model.json"
PIPELINE_STATUS_PATH = MODEL_DIR / "pipeline_status.json"

# Legacy-Pfad – abwärtskompatibel falls active_model.json fehlt
MODEL_PATH = MODEL_DIR / "nba_predictor.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.json"

SCORING_METRIC = "neg_brier_score"


# ── Modell-Definitionen ────────────────────────────────────────────────────────

def _build_logistic_regression() -> Any:
    """Pipeline: StandardScaler + LogisticRegression."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=42)),
    ])


def _build_random_forest() -> Any:
    """
    Random Forest – ensemble of decision trees.
    Hyperparameter: n_estimators=300, max_depth=15, min_samples_leaf=5.
    Kein Scaler erforderlich (baumbasiert).
    """
    return RandomForestClassifier(
        n_estimators=300,
        max_depth=15,
        min_samples_leaf=5,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )


def _build_xgboost() -> Any:
    """
    XGBoost – Gradient Boosted Trees.
    Hyperparameter: n_estimators=300, lr=0.05, max_depth=5, subsample=0.8.
    Kein Scaler erforderlich.
    """
    return XGBClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )


def _build_mlp() -> Any:
    """
    Multi-Layer Perceptron: 128→64→32 Neuronen, ReLU, Early Stopping.
    StandardScaler ist für neuronale Netze erforderlich.
    """
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            activation="relu",
            alpha=0.001,
            max_iter=1000,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=20,
        )),
    ])


MODELS_CONFIG: list[dict] = [
    {
        "id":    "logistic_regression",
        "name":  "Logistic Regression",
        "ref":   "Kvam & Sokol (2006), J. Quantitative Analysis in Sports",
        "build": _build_logistic_regression,
    },
    {
        "id":    "random_forest",
        "name":  "Random Forest",
        "ref":   "Bunker & Thabtah (2019), Applied Computing and Informatics",
        "build": _build_random_forest,
    },
    {
        "id":    "xgboost",
        "name":  "XGBoost",
        "ref":   "Chen & Guestrin (2016), KDD; Zimmermann (2016), IJCAI",
        "build": _build_xgboost if _XGBOOST_AVAILABLE else None,
    },
    {
        "id":    "mlp",
        "name":  "Neural Network (MLP)",
        "ref":   "Loeffelholz et al. (2009), J. Quantitative Analysis in Sports",
        "build": _build_mlp,
    },
]


@dataclass
class ModelMetrics:
    """Bewertungsmetriken eines trainierten Modells."""
    model_id: str
    model_name: str
    accuracy: float
    roc_auc: float
    brier_score: float
    cv_accuracy_mean: float
    cv_accuracy_std: float
    train_samples: int
    test_samples: int
    feature_count: int
    trained_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    top_features: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model_id":         self.model_id,
            "model_name":       self.model_name,
            "trained_at":       self.trained_at,
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
    Trainiert mehrere ML-Modelle auf NBA-Spielhistorie und wählt das beste aus.

    Modelle: Logistic Regression, Random Forest, XGBoost, MLP.
    Auswahlkriterium: ROC-AUC (robuster als Accuracy für Wahrscheinlichkeitsschätzung).
    Jedes Modell wird einzeln als <model_id>.joblib gespeichert.
    Das beste Modell wird in active_model.json referenziert.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.feature_names: list[str] = TrainingSample.get_feature_columns()

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def train_all(
        self,
        samples: list[TrainingSample] | None = None,
        data_path: Path = TRAINING_DATA_PATH,
        test_size: float = 0.2,
    ) -> list[ModelMetrics]:
        """
        Trainiert alle konfigurierten Modelle, speichert sie und aktualisiert
        active_model.json auf das Modell mit dem höchsten ROC-AUC.

        Returns: Liste der Metriken aller erfolgreich trainierten Modelle.
        """
        if samples is None:
            from src.ml.data_collector import TrainingDataCollector
            samples = TrainingDataCollector.load_from_csv(data_path)

        if len(samples) < 50:
            raise ValueError(
                f"Zu wenige Trainingsdaten: {len(samples)} Samples. "
                "Mindestens 50 erforderlich."
            )

        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"  NBA ML-Pipeline – {len(MODELS_CONFIG)} Modelle")
        print(f"  Samples: {len(samples)} | Features: {len(self.feature_names)}")
        print(f"{'='*60}")

        X, y = self._prepare_data(samples)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )
        print(f"  Train: {len(X_train)} | Test: {len(X_test)}")
        print(f"  Home-Win-Rate Train: {y_train.mean():.1%}\n")

        all_metrics: list[ModelMetrics] = []

        for cfg in MODELS_CONFIG:
            if cfg["build"] is None:
                self.logger.warning("Modell %s übersprungen (nicht verfügbar).", cfg["id"])
                continue
            try:
                print(f"  ── {cfg['name']} ({cfg['ref']})")
                model = cfg["build"]()
                model.fit(X_train, y_train)

                metrics = self._evaluate_model(
                    model, cfg["id"], cfg["name"], X_train, X_test, y_train, y_test
                )
                self._save_single_model(cfg["id"], model, metrics)
                self._print_metrics(metrics)
                all_metrics.append(metrics)

            except Exception as exc:
                self.logger.error("Fehler beim Training von %s: %s", cfg["name"], exc)
                print(f"     ✗ Fehler: {exc}")

        if all_metrics:
            best = max(all_metrics, key=lambda m: m.roc_auc)
            self._update_active_model(best)
            print(f"\n  ✅ Bestes Modell: {best.model_name}")
            print(f"     Accuracy: {best.accuracy:.1%} | ROC-AUC: {best.roc_auc:.3f}")

        return all_metrics

    def train(
        self,
        samples: list[TrainingSample] | None = None,
        data_path: Path = TRAINING_DATA_PATH,
        test_size: float = 0.2,
    ) -> ModelMetrics:
        """
        Abwärtskompatibel: trainiert alle Modelle, gibt das beste zurück.
        Wird von main.py verwendet.
        """
        all_metrics = self.train_all(samples=samples, data_path=data_path, test_size=test_size)
        if not all_metrics:
            raise RuntimeError("Kein Modell konnte erfolgreich trainiert werden.")
        return max(all_metrics, key=lambda m: m.roc_auc)

    def load_model(self, model_id: str | None = None) -> Any:
        """
        Lädt ein gespeichertes Modell.
        model_id=None → lädt das aktive Modell (aus active_model.json).
        """
        if model_id is None:
            model_id = self._get_active_model_id()
        path = MODEL_DIR / f"{model_id}.joblib"
        if not path.exists():
            # Legacy-Fallback
            if MODEL_PATH.exists():
                return joblib.load(MODEL_PATH)
            raise FileNotFoundError(
                f"Kein Modell '{model_id}' unter {path}. Erst 'train all' ausführen."
            )
        return joblib.load(path)

    def load_metrics(self, model_id: str | None = None) -> dict | None:
        """Lädt Metriken eines Modells (None → aktives Modell)."""
        if model_id is None:
            model_id = self._get_active_model_id()
        path = MODEL_DIR / f"{model_id}_metrics.json"
        if not path.exists():
            # Legacy-Fallback
            if METRICS_PATH.exists():
                with open(METRICS_PATH, encoding="utf-8") as f:
                    return json.load(f)
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_all_metrics(self) -> list[dict]:
        """Lädt Metriken aller trainierten Modelle."""
        result = []
        for cfg in MODELS_CONFIG:
            path = MODEL_DIR / f"{cfg['id']}_metrics.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    result.append(json.load(f))
        return result

    def get_active_model_info(self) -> dict | None:
        """Gibt Informationen zum aktuell aktiven Modell zurück."""
        if not ACTIVE_MODEL_PATH.exists():
            return None
        with open(ACTIVE_MODEL_PATH, encoding="utf-8") as f:
            return json.load(f)

    # ── Private Methoden ──────────────────────────────────────────────────

    def _get_active_model_id(self) -> str:
        """Liest die aktive Modell-ID aus active_model.json."""
        if ACTIVE_MODEL_PATH.exists():
            with open(ACTIVE_MODEL_PATH, encoding="utf-8") as f:
                return json.load(f).get("model_id", "logistic_regression")
        return "logistic_regression"

    def _prepare_data(
        self, samples: list[TrainingSample]
    ) -> tuple[np.ndarray, np.ndarray]:
        from dataclasses import asdict
        X, y = [], []
        for s in samples:
            row = asdict(s)
            X.append([row[f] for f in self.feature_names])
            y.append(s.home_team_won)
        return np.array(X, dtype=float), np.array(y, dtype=int)

    def _evaluate_model(
        self, model: Any, model_id: str, name: str,
        X_train: np.ndarray, X_test: np.ndarray,
        y_train: np.ndarray, y_test: np.ndarray,
    ) -> ModelMetrics:
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy")

        return ModelMetrics(
            model_id=model_id,
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
        """Extrahiert Feature-Importance für verschiedene Modelltypen."""
        try:
            # Pipeline → clf-Schritt extrahieren
            clf = model.named_steps.get("clf") if hasattr(model, "named_steps") else model

            if hasattr(clf, "coef_"):  # Logistic Regression
                imp = np.abs(clf.coef_[0])
            elif hasattr(clf, "feature_importances_"):  # RF, XGBoost
                imp = clf.feature_importances_
            else:  # MLP: kein direktes Feature-Importance
                return []

            indices = np.argsort(imp)[::-1][:top_n]
            return [(self.feature_names[i], float(imp[i])) for i in indices]
        except Exception:
            return []

    def _save_single_model(self, model_id: str, model: Any, metrics: ModelMetrics) -> None:
        """Speichert ein einzelnes Modell und seine Metriken."""
        model_path = MODEL_DIR / f"{model_id}.joblib"
        metrics_path = MODEL_DIR / f"{model_id}_metrics.json"

        joblib.dump(model, model_path)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)

        self.logger.info("Modell gespeichert: %s", model_path)

    def _update_active_model(self, best: ModelMetrics) -> None:
        """Aktualisiert active_model.json auf das beste Modell."""
        info = {
            "model_id":   best.model_id,
            "model_name": best.model_name,
            "accuracy":   round(best.accuracy, 4),
            "roc_auc":    round(best.roc_auc, 4),
            "brier_score": round(best.brier_score, 4),
            "trained_at": best.trained_at,
        }
        with open(ACTIVE_MODEL_PATH, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)

        # Legacy-Kompatibilität: auch als nba_predictor.joblib speichern
        src = MODEL_DIR / f"{best.model_id}.joblib"
        if src.exists():
            import shutil
            shutil.copy2(src, MODEL_PATH)
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)

        self.logger.info("Aktives Modell: %s (ROC-AUC %.3f)", best.model_name, best.roc_auc)

    @staticmethod
    def _print_metrics(metrics: ModelMetrics) -> None:
        print(f"     Accuracy: {metrics.accuracy:.1%}  |  "
              f"ROC-AUC: {metrics.roc_auc:.3f}  |  "
              f"Brier: {metrics.brier_score:.3f}  |  "
              f"CV: {metrics.cv_accuracy_mean:.1%} ±{metrics.cv_accuracy_std:.1%}")
        if metrics.top_features:
            top = ", ".join(f"{f}={i:.3f}" for f, i in metrics.top_features[:3])
            print(f"     Top-3: {top}")
