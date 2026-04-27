"""Konfiguration aus .env-Datei / Umgebungsvariablen."""

import os
from pathlib import Path

from dotenv import load_dotenv


class Config:
    def __init__(self, env_file: str = ".env") -> None:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path)

        self.balldontlie_api_key: str = os.getenv("BALLDONTLIE_API_KEY", "")
        self.odds_api_key: str        = os.getenv("ODDS_API_KEY", "")

        self.balldontlie_base_url: str = "https://api.balldontlie.io/v1"
        self.odds_api_base_url: str    = "https://api.the-odds-api.com/v4"

        self.request_timeout: int  = int(os.getenv("REQUEST_TIMEOUT", "10"))
        self.max_retries: int      = int(os.getenv("MAX_RETRIES", "3"))
        self.retry_delay: float    = float(os.getenv("RETRY_DELAY", "1.0"))

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        self.log_file: str  = os.getenv("LOG_FILE", "logs/nba_tracker.log")

        self.cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))

    def validate(self) -> list[str]:
        """Gibt eine Liste fehlender Keys zurück (leer = alles okay)."""
        warnings = []
        if not self.balldontlie_api_key:
            warnings.append("BALLDONTLIE_API_KEY fehlt – API-Anfragen schlagen fehl.")
        if not self.odds_api_key:
            warnings.append("ODDS_API_KEY fehlt – Wettquoten nicht verfügbar.")
        return warnings

    def __repr__(self) -> str:
        return (
            f"Config(bdl={'***' if self.balldontlie_api_key else 'MISSING'}, "
            f"odds={'***' if self.odds_api_key else 'MISSING'}, "
            f"timeout={self.request_timeout}s)"
        )
