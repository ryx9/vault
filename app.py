#!/usr/bin/env python3
"""Entry point. `python app.py` opens the dashboard — nothing else required."""

from __future__ import annotations

import config
import ui


def main() -> None:
    config.ensure_dirs()
    ui.run()


if __name__ == "__main__":
    main()
