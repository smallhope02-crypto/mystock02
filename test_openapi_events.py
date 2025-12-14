"""Simple sanity checker for KHOpenAPI COM event creation.

Run manually on Windows 32-bit environments with OpenAPI installed::

    python test_openapi_events.py

It will attempt to create the control via DispatchWithEvents and print the
result. Tracebacks are printed to help diagnose metaclass or registration
issues.
"""

import platform
import traceback

import pytest

try:
    from win32com.client import DispatchWithEvents
    HAS_WIN32COM = True
except Exception as exc:  # pragma: no cover - platform dependent
    HAS_WIN32COM = False
    print("win32com is not available:", exc)
    pytest.skip("win32com not available; OpenAPI control test skipped", allow_module_level=True)


class DummyHandler:
    """Minimal event sink placeholder used for DispatchWithEvents."""

    pass


def main() -> None:
    print("Python:", platform.python_version(), platform.architecture())
    print("Trying DispatchWithEvents('KHOPENAPI.KHOpenAPICtrl.1', DummyHandler) ...")
    try:
        obj = DispatchWithEvents("KHOPENAPI.KHOpenAPICtrl.1", DummyHandler)
        print("OK, created:", type(obj))
    except Exception:
        print("DispatchWithEvents failed; full traceback below:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
