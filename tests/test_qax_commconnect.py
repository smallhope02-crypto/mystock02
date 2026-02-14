"""Manual QAx CommConnect diagnostic script.

Run ``python -m tests.test_qax_commconnect`` on a Windows 32bit PyQt5 environment
with Kiwoom OpenAPI+ installed to verify that the QAx control can log in and
emit ``OnEventConnect``.
"""

import sys
import traceback

import pytest

try:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QAxContainer import QAxWidget
    from PyQt5.QtCore import QTimer
except Exception as exc:  # pragma: no cover - runtime/CI guard
    pytestmark = pytest.mark.skip(reason=f"PyQt5 QAx unavailable: {exc}")
else:
    pytestmark = pytest.mark.skip(reason="Manual Windows-only QAx diagnostic; not for CI")


def _main() -> None:
    app = QApplication(sys.argv)
    ax = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
    ax.setWindowTitle("Kiwoom OpenAPI QAx Test")

    def on_login(err: int) -> None:
        print(f"[QAxTest] OnEventConnect err={err}")
        QMessageBox.information(ax, "CommConnect 결과", f"OnEventConnect err={err}")

    try:
        ax.OnEventConnect.connect(on_login)
    except Exception:
        traceback.print_exc()
    print("[QAxTest] CommConnect 호출")
    try:
        ax.dynamicCall("CommConnect()")
    except Exception:
        traceback.print_exc()

    # Safety exit after 60 seconds if the login dialog stays open.
    def shutdown():
        print("[QAxTest] 타임아웃으로 종료")
        app.quit()

    QTimer.singleShot(60_000, shutdown)
    ax.show()
    app.exec_()


if __name__ == "__main__":  # pragma: no cover - manual run only
    _main()
