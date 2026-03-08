"""
Basis-HTTP-Client mit Retry-Logik, Timeout-Behandlung und einfachem In-Memory-Cache.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.config import Config


class ApiError(Exception):
    """Wird ausgelöst, wenn ein API-Aufruf fehlschlägt."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseApiClient:
    """
    Abstrakter Basis-HTTP-Client.
    Stellt Session-Management, Retry-Logik und einen einfachen TTL-Cache bereit.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._session = self._build_session()
        self._cache: dict[str, tuple[Any, float]] = {}

    # ── Öffentliche Methoden ──────────────────────────────────────────────

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        """
        Führt einen HTTP-GET-Request aus (mit Cache).

        Args:
            url:     Ziel-URL.
            params:  Query-Parameter.
            headers: Zusätzliche HTTP-Header.

        Returns:
            Geparste JSON-Antwort.

        Raises:
            ApiError: Bei HTTP-Fehlern oder Verbindungsproblemen.
        """
        cache_key = self._build_cache_key(url, params)
        cached_response = self._get_from_cache(cache_key)
        if cached_response is not None:
            self.logger.debug("Cache-Hit für: %s", url)
            return cached_response

        response_data = self._execute_request(url, params, headers)
        self._set_in_cache(cache_key, response_data)
        return response_data

    def clear_cache(self) -> None:
        """Leert den gesamten In-Memory-Cache."""
        self._cache.clear()
        self.logger.debug("Cache geleert.")

    # ── Private Methoden ─────────────────────────────────────────────────

    def _build_session(self) -> requests.Session:
        """Erstellt eine requests.Session mit automatischen Retries."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _execute_request(
        self, url: str, params: dict | None, headers: dict | None
    ) -> Any:
        """Führt den eigentlichen HTTP-Request aus und behandelt Fehler."""
        try:
            self.logger.debug("GET %s | params=%s", url, params)
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.request_timeout,
            )
            self._raise_for_status(response)
            return response.json()

        except requests.exceptions.ConnectionError as exc:
            raise ApiError(f"Verbindungsfehler: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise ApiError(
                f"Timeout nach {self.config.request_timeout}s für {url}"
            ) from exc
        except requests.exceptions.JSONDecodeError as exc:
            raise ApiError(f"Ungültige JSON-Antwort von {url}") from exc

    def _raise_for_status(self, response: requests.Response) -> None:
        """Wirft ApiError bei HTTP-Fehlercodes."""
        if response.status_code == 401:
            raise ApiError("Authentifizierungsfehler – API-Key ungültig.", 401)
        if response.status_code == 403:
            raise ApiError("Zugriff verweigert – API-Key fehlt oder Rate-Limit.", 403)
        if response.status_code == 404:
            raise ApiError(f"Ressource nicht gefunden: {response.url}", 404)
        if response.status_code == 429:
            raise ApiError("Rate-Limit überschritten – bitte später erneut versuchen.", 429)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise ApiError(str(exc), response.status_code) from exc

    def _build_cache_key(self, url: str, params: dict | None) -> str:
        """Erstellt einen eindeutigen Cache-Schlüssel."""
        param_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        return f"{url}?{param_str}"

    def _get_from_cache(self, key: str) -> Any | None:
        """Gibt einen gecachten Wert zurück, falls noch gültig."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, timestamp = entry
        if time.time() - timestamp > self.config.cache_ttl:
            del self._cache[key]
            return None
        return value

    def _set_in_cache(self, key: str, value: Any) -> None:
        """Speichert einen Wert im Cache."""
        self._cache[key] = (value, time.time())
