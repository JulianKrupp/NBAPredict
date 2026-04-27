"""
Unit-Tests für BaseApiClient – Cache, Circuit Breaker und Fehlerbehandlung.

Kein echter Netzwerk-Traffic: requests.Session.get wird gemockt.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.api import base_client as base_client_module
from src.api.base_client import ApiError, BaseApiClient

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    cfg = MagicMock()
    cfg.max_retries = 0
    cfg.retry_delay = 0.0
    cfg.request_timeout = 1
    cfg.cache_ttl = 60
    return cfg


@pytest.fixture
def client(config, monkeypatch):
    """Frischer Client + zurückgesetzter globaler Offline-Zustand."""
    monkeypatch.setattr(base_client_module, "_global_offline_until", 0.0)
    return BaseApiClient(config)


def _make_response(status_code: int = 200, json_data: dict | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.url = "https://example.com/test"
    resp.json.return_value = json_data or {"ok": True}
    resp.raise_for_status = MagicMock()
    return resp


# ── Cache ────────────────────────────────────────────────────────────────────

class TestCache:
    def test_second_call_hits_cache(self, client):
        with patch.object(client._session, "get",
                          return_value=_make_response(json_data={"a": 1})) as mock_get:
            r1 = client.get("https://example.com/test")
            r2 = client.get("https://example.com/test")

        assert r1 == r2 == {"a": 1}
        assert mock_get.call_count == 1  # Nur ein echter Request

    def test_different_params_use_separate_cache_entries(self, client):
        with patch.object(client._session, "get",
                          return_value=_make_response(json_data={"x": 1})) as mock_get:
            client.get("https://example.com/x", params={"a": "1"})
            client.get("https://example.com/x", params={"a": "2"})

        assert mock_get.call_count == 2

    def test_cache_expires_after_ttl(self, client, config):
        config.cache_ttl = 1
        with patch.object(client._session, "get",
                          return_value=_make_response()) as mock_get:
            client.get("https://example.com/x")
            # Cache-Eintrag manuell auf alt setzen
            key = next(iter(client._cache))
            value, _ = client._cache[key]
            client._cache[key] = (value, time.time() - 5)

            client.get("https://example.com/x")

        assert mock_get.call_count == 2

    def test_clear_cache_forces_refetch(self, client):
        with patch.object(client._session, "get",
                          return_value=_make_response()) as mock_get:
            client.get("https://example.com/x")
            client.clear_cache()
            client.get("https://example.com/x")

        assert mock_get.call_count == 2


# ── HTTP-Fehler ──────────────────────────────────────────────────────────────

class TestHttpErrors:
    @pytest.mark.parametrize("code,fragment", [
        (401, "Authentifizierung"),
        (403, "Zugriff verweigert"),
        (404, "nicht gefunden"),
        (429, "Rate-Limit"),
    ])
    def test_specific_status_codes_raise_apierror(self, client, code, fragment):
        with patch.object(client._session, "get",
                          return_value=_make_response(status_code=code)), \
             pytest.raises(ApiError, match=fragment) as exc_info:
            client.get("https://example.com/x")

        assert exc_info.value.status_code == code

    def test_timeout_raises_apierror(self, client):
        with patch.object(client._session, "get",
                          side_effect=requests.exceptions.Timeout()), \
             pytest.raises(ApiError, match="Timeout"):
            client.get("https://example.com/x")


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_connection_error_activates_offline(self, client):
        with patch.object(client._session, "get",
                          side_effect=requests.exceptions.ConnectionError("DNS down")), \
             pytest.raises(ApiError, match="Verbindungsfehler"):
            client.get("https://example.com/x")

        assert client.is_offline is True

    def test_offline_blocks_subsequent_requests(self, client):
        # Künstlich offline schalten
        client._offline_until = time.time() + 30

        with patch.object(client._session, "get") as mock_get, \
             pytest.raises(ApiError, match="nicht erreichbar"):
            client.get("https://example.com/x")

        # Kein echter HTTP-Request während Offline-Phase
        mock_get.assert_not_called()

    def test_offline_state_clears_after_success(self, client):
        client._offline_until = time.time() - 1  # Cooldown abgelaufen

        with patch.object(client._session, "get",
                          return_value=_make_response()):
            client.get("https://example.com/x")

        assert client._offline_until == 0.0
