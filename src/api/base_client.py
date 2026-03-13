"""HTTP-Basis mit Retry-Logik und einfachem In-Memory-Cache."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.config import Config


class ApiError(Exception):
    """Fehler bei einem API-Aufruf."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseApiClient:
    """
    Gemeinsame Basis für alle API-Clients.

    Kümmert sich um Session-Management, Retries bei temporären Fehlern
    (429, 5xx) und einen TTL-basierten Cache, damit identische Requests
    nicht mehrfach abgefeuert werden.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._session = self._build_session()
        self._cache: dict[str, tuple[Any, float]] = {}

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        """GET-Request mit Cache. Wirft ApiError bei HTTP-Fehlern."""
        cache_key = self._build_cache_key(url, params)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            self.logger.debug("Cache-Hit: %s", url)
            return cached

        data = self._execute_request(url, params, headers)
        self._set_in_cache(cache_key, data)
        return data

    def clear_cache(self) -> None:
        self._cache.clear()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _execute_request(self, url: str, params: dict | None, headers: dict | None) -> Any:
        try:
            self.logger.debug("GET %s | params=%s", url, params)
            resp = self._session.get(
                url, params=params, headers=headers,
                timeout=self.config.request_timeout,
            )
            self._raise_for_status(resp)
            return resp.json()
        except requests.exceptions.ConnectionError as exc:
            raise ApiError(f"Verbindungsfehler: {exc}") from exc
        except requests.exceptions.Timeout:
            raise ApiError(f"Timeout nach {self.config.request_timeout}s für {url}")
        except requests.exceptions.JSONDecodeError:
            raise ApiError(f"Ungültige JSON-Antwort von {url}")

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.status_code == 401:
            raise ApiError("Authentifizierungsfehler – API-Key prüfen.", 401)
        if response.status_code == 403:
            raise ApiError("Zugriff verweigert (fehlender Key oder Rate-Limit).", 403)
        if response.status_code == 404:
            raise ApiError(f"Ressource nicht gefunden: {response.url}", 404)
        if response.status_code == 429:
            raise ApiError("Rate-Limit erreicht.", 429)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise ApiError(str(exc), response.status_code) from exc

    def _build_cache_key(self, url: str, params: dict | None) -> str:
        param_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        return f"{url}?{param_str}"

    def _get_from_cache(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.time() - ts > self.config.cache_ttl:
            del self._cache[key]
            return None
        return value

    def _set_in_cache(self, key: str, value: Any) -> None:
        self._cache[key] = (value, time.time())
