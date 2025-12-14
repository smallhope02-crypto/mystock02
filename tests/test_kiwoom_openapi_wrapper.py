"""Regression tests for KiwoomOpenAPI CommConnect guarding.

These tests ensure the COM wrapper never calls ``CommConnect`` directly
from higher-level helpers and that failures are contained inside the
``_safe_comm_connect`` method without bubbling exceptions.
"""

from typing import List

import pytest

from src.kiwoom_openapi import KiwoomOpenAPI


class _DummyControl:
    """Minimal stub exposing CommConnect for unit testing."""

    def __init__(self):
        self.calls: List[str] = []

    def CommConnect(self) -> None:  # pragma: no cover - invoked indirectly
        self.calls.append("CommConnect")
        raise ValueError("dummy failure")


def _make_enabled_api() -> KiwoomOpenAPI:
    """Helper to create an API instance with a stubbed control set up."""

    api = KiwoomOpenAPI()
    api._control = _DummyControl()
    api.available = True
    api._enabled = True
    return api


def test_safe_comm_connect_captures_exceptions() -> None:
    """CommConnect failures stay within the guard and update init_error."""

    api = _make_enabled_api()

    assert api._safe_comm_connect("test-context") is False
    assert isinstance(api._init_error, ValueError)
    assert getattr(api._control, "calls", []) == ["CommConnect"]


def test_login_and_condition_paths_use_safe_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """login/connect_for_conditions delegate to the shared CommConnect guard."""

    api = _make_enabled_api()
    called_contexts: List[str] = []

    def fake_safe(context: str = "") -> bool:
        called_contexts.append(context)
        return True

    monkeypatch.setattr(api, "_safe_comm_connect", fake_safe)

    assert api.login() is True
    assert api.connect_for_conditions() is True
    assert called_contexts == ["login", "condition-login"]
