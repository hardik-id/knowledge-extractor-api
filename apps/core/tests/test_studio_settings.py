import importlib
import sys
from types import ModuleType

import pytest
from django.conf import settings
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

ORIGIN = "http://localhost:3217"
PRODUCTION_ENV = {
    "DJANGO_SECRET_KEY": "x",
    "DJANGO_ALLOWED_HOSTS": "api.example.com",
    "AUTH_MODE": "entra",
}


def test_studio_settings_have_their_local_defaults() -> None:
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.WS_TICKET_TTL_SECONDS == 30
    assert settings.DOCUMENT_CATALOG == "samples"
    assert settings.DOCUMENT_STORAGE == "samples"
    assert settings.ASSISTANT_AGENT == "scripted"
    assert settings.EXTRACTOR == "scripted"
    assert settings.LLM_PROVIDER == "openai"
    assert settings.OTEL_SDK_DISABLED is True
    assert settings.OTEL_SERVICE_NAME == "knowledge-extractor-api"
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == "http://localhost:4318"
    assert settings.OTEL_RESOURCE_ATTRIBUTES == "deployment.environment=local"
    for name in (
        "DOCUMENT_CATALOG_URL",
        "AZURE_STORAGE_ACCOUNT_URL",
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
    ):
        assert getattr(settings, name) == ""


def _preflight(origin: str) -> HttpResponseBase:
    return Client().options(
        "/nothing",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def _load(module: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key, value in PRODUCTION_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    name = f"config.settings.{module}"
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_local_settings_accept_any_localhost_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = _load("local", monkeypatch)
    with override_settings(
        CORS_ALLOWED_ORIGINS=local.CORS_ALLOWED_ORIGINS,
        CORS_ALLOWED_ORIGIN_REGEXES=local.CORS_ALLOWED_ORIGIN_REGEXES,
    ):
        assert _preflight(ORIGIN)["Access-Control-Allow-Origin"] == ORIGIN
        assert "Access-Control-Allow-Origin" not in _preflight("http://evil.example")
        assert "Access-Control-Allow-Origin" not in _preflight(
            "http://localhost.evil.example"
        )


def test_production_settings_keep_the_explicit_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load("production", monkeypatch)
    assert not getattr(production, "CORS_ALLOWED_ORIGIN_REGEXES", [])
    with override_settings(
        CORS_ALLOWED_ORIGINS=production.CORS_ALLOWED_ORIGINS,
        CORS_ALLOWED_ORIGIN_REGEXES=[],
    ):
        assert "Access-Control-Allow-Origin" not in _preflight(ORIGIN)
