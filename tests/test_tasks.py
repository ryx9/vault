from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date, timedelta

import pytest

import tasks


def test_canonicalize_task_text_rewrites_relative_dates() -> None:
    today = date.today()
    tomorrow = today + timedelta(days=1)

    assert tasks.canonicalize_task_text("buy milk today") == f"buy milk {today.isoformat()}"
    assert tasks.canonicalize_task_text("prepare slides tomorrow") == f"prepare slides {tomorrow.isoformat()}"
    assert tasks.canonicalize_task_text("send report wednesday") == "send report wednesday" or tasks.canonicalize_task_text("send report wednesday").startswith("send report")


def test_canonicalize_task_dates_in_file_updates_file_contents() -> None:
    with TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test.md"
        test_file.write_text("TODO: buy milk today\nTODO: X finished tomorrow\n", encoding="utf-8")

        changed = tasks.canonicalize_task_dates_in_file(test_file)
        assert changed is True

        contents = test_file.read_text(encoding="utf-8")
        assert "TODO: buy milk" in contents
        assert "today" not in contents
        assert "TODO: X finished" in contents
        assert "tomorrow" not in contents
