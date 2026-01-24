"""Convenience launcher for the Mystock02 GUI.

Run this file directly (``python run_gui.py``) if running the module form
(``python -m src.gui_main``) does not work because of PYTHONPATH issues on the
current environment. The script prepends the repository root to ``sys.path``
so that the ``src`` package is importable when the project is unpacked from a
zip archive.
"""

import sys
from pathlib import Path

# Ensure the repository root (where ``src`` lives) is importable.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app_paths import ensure_data_dirs, get_logs_dir
from src.logging_setup import configure_logging
from src.gui_main import main


if __name__ == "__main__":
    ensure_data_dirs()
    configure_logging(get_logs_dir())
    main()
