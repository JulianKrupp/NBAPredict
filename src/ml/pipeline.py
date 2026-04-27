"""
ML-Pipeline – steuert das monatliche Modell-Retraining.

Ablauf:
  1. Trainingsdaten sammeln (TrainingDataCollector)
  2. Alle Modelle trainieren (NBAModelTrainer.train_all)
  3. Bestes Modell nach ROC-AUC als aktives Modell setzen
  4. Status in pipeline_status.json persistieren

Trigger:
  - Manuell über POST /api/pipeline/trigger
  - Automatisch am Anfang jedes neuen Kalendermonats (Server-Startup + stündliche Prüfung)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from src.ml.data_collector import DEFAULT_MAX_GAMES, default_training_seasons
from src.ml.model_trainer import (
    MODEL_DIR,
    PIPELINE_STATUS_PATH,
    ModelMetrics,
    NBAModelTrainer,
)

if TYPE_CHECKING:
    from src.utils.config import Config

logger = logging.getLogger(__name__)


class MLPipeline:
    """
    Verwaltet den kompletten ML-Lebenszyklus:
    Status lesen/schreiben, Retrain-Bedarf prüfen, Pipeline ausführen.
    """

    # ── Status-Management ─────────────────────────────────────────────────

    def get_status(self) -> dict:
        """
        Gibt den aktuellen Pipeline-Status zurück.
        Felder: running, step, started_at, finished_at, last_trained_month,
                models, winner, error.
        """
        if not PIPELINE_STATUS_PATH.exists():
            return {
                "running": False,
                "step": "",
                "started_at": None,
                "finished_at": None,
                "last_trained_month": None,
                "models": [],
                "winner": "",
                "error": "",
            }
        with open(PIPELINE_STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)

    def should_retrain(self) -> bool:
        """
        True, wenn der aktuelle Kalendermonat noch kein Training hatte.
        Beispiel: last_trained_month="2025-01", aktueller Monat="2025-02" → True.
        """
        status = self.get_status()
        last = status.get("last_trained_month")
        current = datetime.now().strftime("%Y-%m")
        return last != current

    def is_running(self) -> bool:
        return self.get_status().get("running", False)

    # ── Pipeline ausführen ────────────────────────────────────────────────

    def run(
        self,
        seasons: list[int] | None = None,
        max_games: int = DEFAULT_MAX_GAMES,
        config: Config | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[ModelMetrics]:
        """
        Führt die komplette Pipeline aus:
          1. Trainingsdaten sammeln
          2. Alle Modelle trainieren
          3. Aktives Modell aktualisieren
          4. Status persistieren

        Gibt die Metriken aller trainierten Modelle zurück.
        """
        from src.ml.data_collector import TrainingDataCollector

        if config is None:
            raise ValueError("config darf nicht None sein.")
        if seasons is None:
            seasons = default_training_seasons()

        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Pipeline startet: Saisons %s, max. %d Spiele", seasons, max_games
        )
        self._update_status(
            running=True,
            step=f"Trainingsdaten sammeln (Saisons {seasons[0]}–{seasons[-1]})...",
            started_at=datetime.now().isoformat(timespec="seconds"),
            finished_at=None,
            error="",
            models=[],
            winner="",
        )

        try:
            # Schritt 1: Daten sammeln
            step_msg = f"Trainingsdaten sammeln (Saisons {seasons[0]}–{seasons[-1]}, max. {max_games} Spiele)..."
            if progress_callback:
                progress_callback(step_msg)
            self._update_status(step=step_msg)

            collector = TrainingDataCollector(config)
            samples = collector.collect_with_progress(seasons=seasons, max_games=max_games)

            if not samples:
                self._update_status(
                    running=False,
                    step="",
                    error="Keine Trainingsdaten gesammelt",
                )
                return []

            # Schritt 2: Alle Modelle trainieren
            step_msg = f"Modelle trainieren ({len(samples)} Samples)..."
            self._update_status(step=step_msg)
            if progress_callback:
                progress_callback(step_msg)

            trainer = NBAModelTrainer()
            all_metrics = trainer.train_all(samples=samples)

            if not all_metrics:
                self._update_status(
                    running=False,
                    step="",
                    error="Kein Modell konnte trainiert werden",
                )
                return []

            # Schritt 3: Status persistieren
            best = max(all_metrics, key=lambda m: m.roc_auc)
            current_month = datetime.now().strftime("%Y-%m")

            self._update_status(
                running=False,
                step="Fertig",
                finished_at=datetime.now().isoformat(timespec="seconds"),
                last_trained_month=current_month,
                models=[m.to_dict() for m in all_metrics],
                winner=best.model_id,
                error="",
            )

            logger.info(
                "Pipeline abgeschlossen. Bestes Modell: %s (ROC-AUC %.3f)",
                best.model_name, best.roc_auc,
            )
            return all_metrics

        except Exception as exc:
            logger.error("Pipeline-Fehler: %s", exc)
            self._update_status(
                running=False,
                step="",
                error=str(exc),
            )
            raise

    # ── Interne Hilfsmethoden ─────────────────────────────────────────────

    def _update_status(self, **kwargs) -> None:
        """Aktualisiert pipeline_status.json mit den übergebenen Feldern."""
        status = self.get_status()
        status.update(kwargs)
        with open(PIPELINE_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
