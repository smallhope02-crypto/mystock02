"""Configuration helpers for API keys and default settings."""

import os
from dataclasses import dataclass


@dataclass
class AppConfig:
    """Simple container for Kiwoom API credentials and account numbers."""

    app_key: str
    app_secret: str
    account_no: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables with sensible defaults."""
        return cls(
            app_key=os.getenv("KIWOOM_APP_KEY", "demo_app_key"),
            app_secret=os.getenv("KIWOOM_APP_SECRET", "demo_app_secret"),
            account_no=os.getenv("KIWOOM_ACCOUNT_NO", "00000000"),
        )


def load_config() -> AppConfig:
    """Convenience wrapper used by the GUI to reload environment values."""

    return AppConfig.from_env()
