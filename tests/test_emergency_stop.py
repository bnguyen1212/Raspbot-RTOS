"""Tests for tools/emergency_stop.py, against a fake Raspbot_Lib.

tools/ isn't a package (the script must stand alone), so it's loaded from
its file path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "emergency_stop.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("emergency_stop", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_writes_zero_to_motors_0_to_3_twice(fake_raspbot_lib, monkeypatch, capsys):
    script = load_script()
    monkeypatch.setattr(script.time, "sleep", lambda s: None)
    assert script.main() == 0
    assert len(fake_raspbot_lib) == 1
    assert fake_raspbot_lib[0].calls == [(0, 0), (1, 0), (2, 0), (3, 0)] * 2
    out = capsys.readouterr().out
    assert "pass 2: Ctrl_Muto(3, 0)" in out
    assert "I2C error" in out  # tells the user what to look for


def test_reports_a_missing_library(capsys):
    # conftest blocks the real library, as on a laptop.
    assert load_script().main() == 1
    assert "cannot import Raspbot_Lib" in capsys.readouterr().err


def test_imports_nothing_from_the_repo():
    source = SCRIPT.read_text(encoding="utf-8")
    for package in ("config", "motion", "scheduler", "vision", "main"):
        assert f"import {package}" not in source
        assert f"from {package}" not in source
