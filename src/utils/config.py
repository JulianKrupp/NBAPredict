"""
Konfigurationsverwaltung für den NBA Tracker.
Lädt Einstellungen aus Umgebungsvariablen oder einer .env-Datei.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """Zentrale Konfigurationsklasse für den NBA Tracker."""

    def __init__(self, env_file: str = ".env") -> None:
        """
        Initialisiert die Konfiguration.

        Args:
            env_file: Pfad zur .env-Datei (relativ zum Projektverzeichnis).
        """
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path)

        # API-Konfiguration
        self.balldontlie_api_key: str = os.getenv("BALLDONTLIE_API_KEY", "")
        self.odds_api_key: str = os.getenv("ODDS_API_KEY", "")
        # API 3 (stats.nba.com via nba_api) benötigt keinen Key

        # API-Basis-URLs
        self.balldontlie_base_url: str = "https://api.balldontlie.io/v1"
        self.odds_api_base_url: str = "https://api.the-odds-api.com/v4"

        # Request-Konfiguration
        self.request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
        self.max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
        self.retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))

        # Logging-Konfiguration
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        self.log_file: str = os.getenv("LOG_FILE", "logs/nba_tracker.log")

        # Cache-Konfiguration (TTL in Sekunden)
        self.cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))

    def validate(self) -> list[str]:
        """
        Überprüft die Konfiguration auf fehlende Pflichtfelder.

        Returns:
            Liste von Fehlermeldungen (leer, wenn alles korrekt).
        """
        warnings = []
        if not self.balldontlie_api_key:
            warnings.append(
                "BALLDONTLIE_API_KEY nicht gesetzt – API-Anfragen könnten fehlschlagen."
            )
        if not self.odds_api_key:
            warnings.append(
                "ODDS_API_KEY nicht gesetzt – Quoten-Daten nicht verfügbar."
            )
        return warnings

    def __repr__(self) -> str:
        return (
            f"Config(balldontlie_key={'***' if self.balldontlie_api_key else 'MISSING'}, "
            f"odds_key={'***' if self.odds_api_key else 'MISSING'}, "
            f"timeout={self.request_timeout}s)"
        )
