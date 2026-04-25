"""
Logger-Konfiguration für den NBA Tracker.

setup_logger() wird einmal beim Programmstart aufgerufen und konfiguriert das zentrale Python-Logging-System.
Danach kann jedes Modul mit logging.getLogger(__name__) einen eigenen Logger holen — alle landen automatisch beim
Root-Logger und werden von den hier konfigurierten Handlern verarbeitet.
"""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(log_level: str = "INFO", log_file: str = "logs/nba_tracker.log") -> None:
    """
    Richtet den zentralen Logger ein (Datei + Konsole).

    Args:
        log_level: Log-Level als String (z.B. 'INFO', 'DEBUG').
        log_file:  Pfad zur Log-Datei.
    """
    numeric_level = getattr(logging, log_level, logging.INFO)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Konsolen-Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)

    # urllib3 Retry-Warnings unterdrücken – der eigentliche Fehler wird
    # bereits auf ERROR-Level in den API-Clients geloggt.
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    # Verhindert doppelte Handler bei mehrfachem Aufruf
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)

        # Datei-Handler nur außerhalb von Docker (RotatingFileHandler schlägt auf
        # Windows-NTFS-Volumes via WSL2 bei shouldRollover fehl – OSError errno 5)
        if not os.environ.get("FLASK_ENV") == "production":
            # console_handler.setLevel(numeric_level)     # Workaround, wenn man  vollständige logs in Docker möchte
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
