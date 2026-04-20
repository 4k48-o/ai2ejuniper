"""Tests for webhook SSRF protection."""

import pytest
from fastapi import HTTPException

from juniper_ai.app.api.routes.webhooks import _validate_webhook_url


def test_rejects_http_url():
    with pytest.raises(HTTPException) as exc_info:
        _validate_webhook_url("http://example.com/webhook")
    assert exc_info.value.status_code == 400


def test_rejects_localhost():
    with pytest.raises(HTTPException) as exc_info:
        _validate_webhook_url("https://localhost/webhook")
    assert exc_info.value.status_code == 400


def test_rejects_private_ip():
    with pytest.raises(HTTPException) as exc_info:
        _validate_webhook_url("https://192.168.1.1/webhook")
    assert exc_info.value.status_code == 400


def test_rejects_loopback():
    with pytest.raises(HTTPException) as exc_info:
        _validate_webhook_url("https://127.0.0.1/webhook")
    assert exc_info.value.status_code == 400


def test_accepts_valid_https_url():
    # Should not raise
    _validate_webhook_url("https://api.example.com/webhook")
