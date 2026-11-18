"""Tests for tools/motion_test.py, with scripted keypresses and a fake driver.

Nothing here touches hardware: conftest.py blocks the real Raspbot_Lib, and
every test drives a DryRunDriver (a FakeMotorDriver).
"""

from __future__ import annotations

import importlib.util
import signal
from pathlib import Path
from types import ModuleType

import pytest

from config import MAX_SPEED

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "motion_test.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("motion_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


class Session:
    """Runs the menu with scripted answers and records what was printed and slept."""

    def __init__(self, *answers: str, sleep=None) -> None:
        self.answers = list(answers)
        self.output: list[str] = []
        self.sleeps: list[float] = []
        self.driver = script.DryRunDriver(write=self.output.append)
        self._sleep = sleep or self.sleeps.append

    def read(self, prompt: str) -> str:
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def run(self, duration: float = 1.5) -> Session:
        script.run_menu(
            self.driver, duration=duration, read=self.read,
            write=self.output.append, sleep=self._sleep,
        )
        return self

    @property
    def calls(self) -> list[tuple[str, tuple[float, ...]]]:
        return self.driver.calls

    @property
    def text(self) -> str:
        return "\n".join(self.output)


# ---------------------------------------------------------------------------
# Whole-robot movements
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5", "6"])
def test_each_movement_runs_once_then_stops(choice):
    s = Session(choice, "", "q").run(duration=0.7)
    move = script.movements()[choice]
    assert s.calls == [("set_wheels", move.speeds), ("stop", ())]
    assert s.sleeps == [0.7]
    assert f"About to: {move.label}" in s.text


def test_every_movement_is_within_max_speed():
    for move in script.movements().values():
        assert max(abs(v) for v in move.speeds) <= MAX_SPEED
        assert max(abs(v) for v in move.speeds) > 0


@pytest.mark.parametrize("answer", ["n", "no", "1", " x "])
def test_anything_but_bare_enter_cancels(answer):
    s = Session("5", answer, "q").run()
    assert s.calls == []
    assert "Cancelled. Nothing moved." in s.text


def test_movement_stops_even_if_it_fails_midway():
    def broken_sleep(seconds: float) -> None:
        raise RuntimeError("boom")

    s = Session("2", "", "q", sleep=broken_sleep)
    with pytest.raises(RuntimeError):
        s.run()
    assert s.calls[-1] == ("stop", ())


def test_stop_needs_no_confirmation():
    s = Session("7", "q").run()
    assert s.calls == [("stop", ())]


def test_check_speed_refuses_above_max():
    with pytest.raises(ValueError):
        script.check_speed((MAX_SPEED + 0.01, 0, 0, 0))


# ---------------------------------------------------------------------------
# Single wheel and hold test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("direction", "sign"), [("f", 1), ("b", -1)])
def test_single_wheel_spins_one_raw_motor_for_one_second(direction, sign):
    s = Session("8", "3", direction, "", "q").run()
    assert s.calls == [("set_motor_raw", (3, sign * script.LOW_SPEED)), ("stop", ())]
    assert s.sleeps == [script.SINGLE_WHEEL_S] == [1.0]


@pytest.mark.parametrize(("motor", "direction"), [("4", "f"), ("-1", "f"), ("x", "f"), ("1", "up")])
def test_single_wheel_rejects_bad_input_without_moving(motor, direction):
    s = Session("8", motor, direction, "", "q").run()
    assert not any(name == "set_motor_raw" for name, _ in s.calls)


def test_hold_test_keeps_spinning_until_enter():
    seen_during_hold: list[list] = []
    s = Session()

    answers = iter(["9", "0", "f", ""])  # menu, ID, direction, confirm

    def read(prompt: str) -> str:
        if prompt.startswith("Press Enter here to stop"):
            seen_during_hold.append(list(s.driver.calls))  # snapshot mid-hold
            return ""
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    script.run_menu(s.driver, read=read, write=s.output.append, sleep=s.sleeps.append)
    # While waiting, the wheel had been started and not stopped.
    assert seen_during_hold == [[("set_motor_raw", (0, script.LOW_SPEED))]]
    assert s.calls[-1] == ("stop", ())
    assert s.sleeps == []  # it waits for Enter, not a timer
    text = "\n".join(s.output)
    assert f"PID is {script.os.getpid()}" in text
    assert "kill -9" in text and "emergency_stop.py" in text


def test_end_of_input_quits_cleanly():
    Session().run()  # no answers: EOFError on the first read


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------

def test_uses_the_shared_stop_handlers():
    # The handler itself is tested in test_stop_on_signal.py.
    from motion import stop_on_signal

    assert script.install_stop_handlers is stop_on_signal.install_stop_handlers


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals (runs on the Pi)")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGINT"])
def test_real_signal_stops_a_dry_run_and_exits(sig):
    """Send a real signal to a --dry-run process waiting at the menu."""
    import subprocess
    import sys
    import time

    proc = subprocess.Popen(
        [sys.executable, "-u", str(SCRIPT), "--dry-run"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        assert proc.stdout is not None
        while "Tip:" not in proc.stdout.readline():  # wait until it's at the menu
            pass
        time.sleep(0.3)  # let it reach input()
        proc.send_signal(getattr(signal, sig))
        out, _ = proc.communicate(timeout=10)
    finally:
        proc.kill()
    signum = getattr(signal, sig)
    assert proc.returncode == 128 + signum
    assert "[dry-run] stop()" in out
    assert f"{sig}: stop sent" in out


# ---------------------------------------------------------------------------
# Command line and startup
# ---------------------------------------------------------------------------

def test_duration_defaults_to_one_and_a_half_seconds():
    assert script.parse_args([]).duration == 1.5


@pytest.mark.parametrize("bad", ["0", "-1", "5.1", "abc"])
def test_duration_must_be_short_and_positive(bad):
    with pytest.raises(SystemExit):
        script.parse_args(["--duration", bad])


def test_real_mode_without_the_library_fails_cleanly(capsys):
    # conftest blocks Raspbot_Lib, as on a laptop.
    assert script.main([]) == 1
    assert "--dry-run" in capsys.readouterr().err


def test_real_mode_builds_the_real_driver(fake_raspbot_lib):
    from motion.mecanum import RaspbotMotorDriver

    assert isinstance(script.make_driver(dry_run=False), RaspbotMotorDriver)
    assert len(fake_raspbot_lib) == 1
