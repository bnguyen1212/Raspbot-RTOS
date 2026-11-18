"""Tests for tools/spin_calibration.py, with scripted input and a fake driver.

No hardware: conftest.py blocks the real Raspbot_Lib, and every test drives a
FakeMotorDriver.
"""

from __future__ import annotations

import importlib.util
import signal
from pathlib import Path
from types import ModuleType

import pytest

from config import MAX_SPEED, ROTATE_SPEED, SECONDS_PER_360
from motion.actions import RedAction, StartupAction
from motion.driver import FakeMotorDriver
from motion.kinematics import rotate_in_place

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "spin_calibration.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("spin_calibration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


class FakeTime:
    """sleep() advances the clock instead of waiting."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def run(settings, *answers: str, driver=None, sleep=None):
    driver = driver or FakeMotorDriver()
    fake_time = FakeTime()
    output: list[str] = []
    queue = list(answers)

    def read(prompt: str) -> str:
        output.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    trials = script.run_trials(
        driver, settings, read=read, write=output.append,
        sleep=sleep or fake_time.sleep, clock=fake_time.clock,
    )
    return trials, driver, fake_time, "\n".join(output)


def settings(seconds=4.0, direction="left", speed=ROTATE_SPEED, repeat=1):
    return script.Settings(seconds, direction, speed, repeat)


# ---------------------------------------------------------------------------
# Same rotation path as the actions
# ---------------------------------------------------------------------------

def test_right_at_default_speed_sends_exactly_what_the_actions_send():
    trials, driver, _, _ = run(settings(direction="right"), "", "")
    startup = FakeMotorDriver()
    StartupAction(driver=startup, sleep=lambda s: None)
    red = FakeMotorDriver()
    RedAction({"red_start": None, "red_rearm": True}, 0.0, driver=red)

    spin_command = driver.calls[0]
    assert spin_command == startup.calls[0] == red.calls[0]
    assert spin_command == ("set_wheels", rotate_in_place("cw"))


def test_left_uses_the_same_helper_counterclockwise():
    _, driver, _, _ = run(settings(direction="left"), "", "")
    assert driver.calls[0] == ("set_wheels", rotate_in_place("ccw", ROTATE_SPEED))


def test_custom_speed_goes_through_the_same_helper():
    _, driver, _, _ = run(settings(direction="right", speed=0.3), "", "")
    assert driver.calls[0] == ("set_wheels", rotate_in_place("cw", 0.3))


def test_script_calls_the_actions_timed_spin(monkeypatch):
    seen = []

    def fake_timed_spin(*args, **kwargs):
        seen.append((args, kwargs))
        kwargs["sleep"](args[1])

    monkeypatch.setattr(script, "timed_spin", fake_timed_spin)
    run(settings(seconds=2.5, direction="right", speed=0.25), "", "")
    (args, kwargs), = seen
    assert args[1] == 2.5
    assert kwargs["direction"] == "cw" and kwargs["speed"] == 0.25


# ---------------------------------------------------------------------------
# One trial
# ---------------------------------------------------------------------------

def test_one_trial_spins_for_the_duration_then_stops():
    trials, driver, fake_time, text = run(settings(seconds=4.0), "", "92 deg")
    names = [name for name, _ in driver.calls]
    assert names[0] == "set_wheels"
    assert set(names[1:]) == {"stop"}  # timed_spin's stop, then the with-block's
    assert fake_time.sleeps == [4.0, script.SETTLE_S]
    assert trials == [script.Trial(1, 4.0, 4.0, "left", ROTATE_SPEED, "92 deg")]
    assert "duration 4.000 s requested, 4.000 s measured" in text
    assert "direction left, speed 0.2" in text


def test_nothing_moves_unless_enter_is_pressed():
    trials, driver, _, text = run(settings(), "n")
    assert driver.calls == []
    assert trials == []
    assert "Stopping here" in text


def test_spin_stops_even_if_it_fails_midway():
    driver = FakeMotorDriver()

    def broken_sleep(seconds: float) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run(settings(), "", driver=driver, sleep=broken_sleep)
    assert driver.calls[-1] == ("stop", ())
    assert driver.wheels == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# --repeat
# ---------------------------------------------------------------------------

def test_repeat_runs_n_trials_each_with_its_own_prompt_and_note():
    trials, driver, _, text = run(settings(repeat=3), "", "88", "", "", "", "91")
    assert [t.number for t in trials] == [1, 2, 3]
    assert [t.note for t in trials] == ["88", "", "91"]
    assert [name for name, _ in driver.calls].count("set_wheels") == 3
    for n in (1, 2, 3):
        assert f"Trial {n}/3" in text


def test_repeat_can_be_stopped_early():
    trials, driver, _, _ = run(settings(repeat=5), "", "90", "q")
    assert len(trials) == 1
    assert [name for name, _ in driver.calls].count("set_wheels") == 1


def test_end_of_input_keeps_the_trials_already_run():
    trials, _, _, _ = run(settings(repeat=3), "", "90", "")  # input ends at note 2
    assert [t.number for t in trials] == [1, 2]
    assert trials[1].note == ""


def test_csv_log_has_one_row_per_trial():
    trials = [
        script.Trial(1, 4.0, 4.0012, "left", 0.2, "88 deg, slipped"),
        script.Trial(2, 4.0, 3.9999, "left", 0.2, ""),
    ]
    assert script.csv_log(trials) == [
        "trial,seconds,measured_s,direction,speed,note",
        "1,4.000,4.001,left,0.2,88 deg; slipped",
        "2,4.000,4.000,left,0.2,",
    ]


# ---------------------------------------------------------------------------
# Settings, warnings and the command line
# ---------------------------------------------------------------------------

def test_defaults():
    args = script.parse_args(["4"])
    assert (args.seconds, args.direction, args.speed, args.repeat, args.dry_run) == (
        4.0, "left", ROTATE_SPEED, 1, False,
    )


@pytest.mark.parametrize("speed", [str(MAX_SPEED + 0.01), "1.0", "0", "-0.1"])
def test_speed_above_max_or_not_positive_is_rejected(speed):
    with pytest.raises(SystemExit):
        script.parse_args(["4", "--speed", speed])


def test_speed_at_max_is_allowed():
    assert script.parse_args(["4", "--speed", str(MAX_SPEED)]).speed == MAX_SPEED


@pytest.mark.parametrize(
    "argv",
    [["0"], ["-1"], [str(script.MAX_SECONDS + 1)], ["4", "--direction", "up"], ["4", "--repeat", "0"]],
)
def test_bad_arguments_are_rejected(argv):
    with pytest.raises(SystemExit):
        script.parse_args(argv)


def test_warns_when_settings_differ_from_the_actions():
    plain = "\n".join(script.describe(settings(direction="right")))
    assert "turn right (cw)" not in plain and "isn't config.ROTATE_SPEED" not in plain

    left = "\n".join(script.describe(settings(direction="left")))
    assert "StartupAction and RedAction turn right (cw)" in left

    fast = "\n".join(script.describe(settings(direction="right", speed=0.3)))
    assert "isn't config.ROTATE_SPEED" in fast


def test_describe_shows_the_current_config():
    text = "\n".join(script.describe(settings()))
    assert f"SECONDS_PER_360 = {SECONDS_PER_360}" in text


def test_real_mode_without_the_library_fails_cleanly(capsys):
    # conftest blocks Raspbot_Lib, as on a laptop.
    assert script.main(["4"]) == 1
    assert "--dry-run" in capsys.readouterr().err


def test_real_mode_uses_the_actions_default_driver(fake_raspbot_lib, monkeypatch):
    from motion import driver as driver_module

    handled, ran = [], []
    monkeypatch.setattr(script, "install_stop_handlers", lambda d: handled.append(d))
    monkeypatch.setattr(script, "run_trials", lambda d, s: ran.append(d) or [])
    assert script.main(["1"]) == 0
    assert handled == ran == [driver_module.default_driver()]
    assert len(fake_raspbot_lib) == 1


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals (runs on the Pi)")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGINT"])
def test_real_signal_stops_a_dry_run_and_exits(sig):
    """Send a real signal to a --dry-run process waiting at the Enter prompt."""
    import subprocess
    import sys
    import time

    proc = subprocess.Popen(
        [sys.executable, "-u", str(SCRIPT), "3", "--dry-run"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        assert proc.stdout is not None
        while "Ctrl-C at any time" not in proc.stdout.readline():
            pass
        time.sleep(0.3)  # let it reach input()
        proc.send_signal(getattr(signal, sig))
        out, _ = proc.communicate(timeout=10)
    finally:
        proc.kill()
    assert proc.returncode == 128 + getattr(signal, sig)
    assert "[dry-run] stop()" in out
    assert f"{sig}: stop sent" in out
