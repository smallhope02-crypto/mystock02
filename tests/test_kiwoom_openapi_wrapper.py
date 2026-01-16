"""Regression tests for the PyQt QAx KiwoomOpenAPI wrapper."""

import pytest

from src.kiwoom_openapi import KiwoomOpenAPI, QAX_AVAILABLE

pytestmark = pytest.mark.skipif(
    not QAX_AVAILABLE, reason="QAxContainer is unavailable in this environment"
)


if QAX_AVAILABLE:
    import sys
    from PyQt5.QtWidgets import QApplication

    def _ensure_app() -> "QApplication":  # type: ignore[name-defined]
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv[:1])
        return app
else:

    def _ensure_app():  # type: ignore[return-type]
        raise RuntimeError("QAx unavailable")


class _DummyControl:
    def __init__(self):
        self.calls = []

    def CommConnect(self):  # pragma: no cover - indirect
        self.calls.append("CommConnect")
        raise ValueError("dummy failure")


def test_safe_comm_connect_captures_exceptions():
    _ensure_app()
    api = KiwoomOpenAPI()
    api._control = _DummyControl()
    api.enabled = True
    api.available = True

    assert api._safe_comm_connect("test-context") is False
    assert isinstance(api._init_error, ValueError)
    assert getattr(api._control, "calls", []) == ["CommConnect"]


def test_login_and_condition_paths_use_safe_guard(monkeypatch):
    _ensure_app()
    api = KiwoomOpenAPI()
    api.enabled = True
    api.available = True
    called = []

    def fake_safe(context: str = "") -> bool:
        called.append(context)
        return True

    monkeypatch.setattr(api, "_safe_comm_connect", fake_safe)

    assert api.login() is True
    assert api.connect_for_conditions() is True
    assert called == ["login", "condition-login"]
