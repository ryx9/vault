#!/usr/bin/env python3
"""Entry point. `python app.py` opens the dashboard — nothing else required."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import threading
import ui
import embeddings


def main() -> None:
    config.ensure_dirs()
    preload_thread = threading.Thread(
        target=embeddings.preload_model,
        name="embeddings-preload",
        daemon=True,
    )
    preload_thread.start()
    ui.run()


if __name__ == "__main__":
    main()
