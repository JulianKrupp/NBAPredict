"""
Logger-Konfiguration für den NBA Tracker.
"""

import logging
import logging.handlers
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

    # Datei-Handler (rotierend, max. 5 MB pro Datei, 3 Backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)

    # Verhindert doppelte Handler bei mehrfachem Aufruf
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)
