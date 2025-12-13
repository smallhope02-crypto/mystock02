+"""Configuration helpers for API keys and account identifiers.
+
+This module keeps the access point for sensitive credentials in one place.
+Actual secrets are not shipped with the repository; instead they should be
+provided via environment variables. The structure allows plugging in the
+real Kiwoom REST API later.
+"""
+
+import os
+from dataclasses import dataclass
+
+
+@dataclass
+class KiwoomConfig:
+    """Simple container for Kiwoom API credentials.
+
+    TODO: 실제 API 연동 시 보안 저장소나 OS 키체인에서 불러오도록 변경합니다.
+    """
+
+    app_key: str
+    app_secret: str
+    account_no: str
+
+
+def load_config() -> KiwoomConfig:
+    """Load Kiwoom configuration from environment variables.
+
+    Returns
+    -------
+    KiwoomConfig
+        Populated configuration using ``KIWOOM_APP_KEY``, ``KIWOOM_APP_SECRET``,
+        and ``KIWOOM_ACCOUNT_NO`` environment variables.
+    """
+
+    return KiwoomConfig(
+        app_key=os.getenv("KIWOOM_APP_KEY", "demo-key"),
+        app_secret=os.getenv("KIWOOM_APP_SECRET", "demo-secret"),
+        account_no=os.getenv("KIWOOM_ACCOUNT_NO", "00000000"),
+    )
