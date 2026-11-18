"""Unit tests for motion.mecanum.RaspbotMotorDriver, against a fake motor board.

No hardware: the driver gets a FakeRaspbot (tests/conftest.py), either passed
in directly or through a fake Raspbot_Lib module. These tests check the
conversion and the wiring logic only. They can't show that the wiring block
matches the real robot.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest

from config import MAX_SPEED
from motion import mecanum
from motion.mecanum import (
    LIBRARY_FULL_SPEED,
    STOP_REPEAT_GAP_S,
    RaspbotMotorDriver,
    Wheel,
    to_library_speed,
)
from tests.conftest import FakeRaspbot

MAX_LIB = round(MAX_SPEED * LIBRARY_FULL_SPEED)  # 102 at MAX_SPEED = 0.4
ALL_ZERO = [(0, 0), (2, 0), (1, 0), (3, 0)]  # one zero per motor, in wheel order


def make_driver(**kwargs: object) -> tuple[RaspbotMotorDriver, FakeRaspbot, list[float]]:
    board = FakeRaspbot()
    sleeps: list[float] = []
    driver = RaspbotMotorDriver(board=board, sleep=sleeps.append, **kwargs)  # type: ignore[arg-type]
    return driver, board, sleeps


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------

def test_importing_motion_does_not_import_the_library():
    # A fresh interpreter, so the conftest block and earlier imports can't
    # affect the result.
    code = (
        "import sys, motion.mecanum, motion.actions, motion.driver; "
        "assert 'Raspbot_Lib' not in sys.modules, 'imported'; "
        "assert 'smbus' not in sys.modules, 'imported smbus'"
    )
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo_root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_constructor_without_the_library_raises_import_error():
    # conftest blocks the real library, as on a laptop without it.
    with pytest.raises(ImportError):
        RaspbotMotorDriver()


def test_constructor_creates_exactly_one_raspbot(fake_raspbot_lib):
    driver = RaspbotMotorDriver(sleep=lambda s: None)
    driver.set_wheels(0.1, 0.1, 0.1, 0.1)
    driver.stop()
    assert len(fake_raspbot_lib) == 1
    assert len(fake_raspbot_lib[0].calls) == 4 + 8  # all on that one instance


# ---------------------------------------------------------------------------
# to_library_speed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (0.0, 0),
        (0.2, 51),
        (-0.2, -51),
        (MAX_SPEED, MAX_LIB),
        (-MAX_SPEED, -MAX_LIB),
        (0.001, 0),  # rounds to zero
        (0.003, 1),
    ],
)
def test_to_library_speed_scales_and_rounds(speed, expected):
    assert to_library_speed(speed) == expected


@pytest.mark.parametrize("speed", [MAX_SPEED + 0.01, 1.0, 5.0, math.inf])
def test_to_library_speed_clamps_to_max(speed):
    assert to_library_speed(speed) == MAX_LIB
    assert to_library_speed(-speed) == -MAX_LIB


def test_to_library_speed_respects_a_custom_cap():
    assert to_library_speed(1.0, max_speed=1.0) == LIBRARY_FULL_SPEED
    assert to_library_speed(-1.0, max_speed=1.0) == -LIBRARY_FULL_SPEED
    assert to_library_speed(0.5, max_speed=0.1) == round(0.1 * LIBRARY_FULL_SPEED)


@pytest.mark.parametrize("speed", [0.0, 0.2, -0.37, 1.0, 3])
def test_to_library_speed_always_returns_an_int(speed):
    assert type(to_library_speed(speed)) is int


def test_to_library_speed_rejects_nan():
    with pytest.raises(ValueError):
        to_library_speed(math.nan)


# ---------------------------------------------------------------------------
# set_wheels: IDs, inversion, clamping
# ---------------------------------------------------------------------------

def test_set_wheels_sends_each_wheel_to_its_motor_id():
    driver, board, _ = make_driver(max_speed=1.0)
    driver.set_wheels(0.2, 0.4, 0.6, 0.8)  # fl, fr, rl, rr: all different
    # Default wiring guess: fl=0 ("L1"), rl=1 ("L2"), fr=2 ("R1"), rr=3 ("R2").
    assert sorted(board.calls) == [(0, 51), (1, 153), (2, 102), (3, 204)]


def test_set_wheels_sends_ints_only():
    driver, board, _ = make_driver()
    driver.set_wheels(0.123, -0.234, 0.0, 0.399)
    assert all(type(speed) is int for _, speed in board.calls)


def test_set_wheels_clamps_every_wheel():
    driver, board, _ = make_driver()
    driver.set_wheels(1.0, -1.0, 0.9, -0.5)
    assert sorted(board.calls) == [(0, MAX_LIB), (1, MAX_LIB), (2, -MAX_LIB), (3, -MAX_LIB)]


@pytest.mark.parametrize(
    ("name", "position"),
    [("FRONT_LEFT", 0), ("FRONT_RIGHT", 1), ("REAR_LEFT", 2), ("REAR_RIGHT", 3)],
)
def test_inverting_one_wheel_flips_only_that_motor(monkeypatch, name, position):
    original: Wheel = getattr(mecanum, name)
    monkeypatch.setattr(mecanum, name, original._replace(inverted=True))
    driver, board, _ = make_driver()
    driver.set_wheels(0.2, 0.2, 0.2, 0.2)
    sent = dict(board.calls)
    for wheel_name in ("FRONT_LEFT", "FRONT_RIGHT", "REAR_LEFT", "REAR_RIGHT"):
        motor_id = getattr(mecanum, wheel_name).motor_id
        expected = -51 if wheel_name == name else 51
        assert sent[motor_id] == expected, wheel_name


def test_a_nan_speed_sends_nothing():
    driver, board, _ = make_driver()
    with pytest.raises(ValueError):
        driver.set_wheels(0.2, math.nan, 0.2, 0.2)
    assert board.calls == []


def test_duplicate_motor_ids_are_rejected_before_the_bus_opens(monkeypatch, fake_raspbot_lib):
    monkeypatch.setattr(mecanum, "REAR_RIGHT", Wheel(motor_id=0, inverted=False))
    with pytest.raises(ValueError):
        RaspbotMotorDriver()
    assert fake_raspbot_lib == []  # no Raspbot was created


@pytest.mark.parametrize("bad", [0, -0.1, 1.01])
def test_max_speed_out_of_range_is_rejected(bad):
    with pytest.raises(ValueError):
        RaspbotMotorDriver(bad, board=FakeRaspbot())


# ---------------------------------------------------------------------------
# set_motor_raw (diagnostic, used by tools/motion_test.py)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("motor_id", [0, 1, 2, 3])
def test_set_motor_raw_drives_only_that_library_id(motor_id):
    driver, board, _ = make_driver()
    driver.set_motor_raw(motor_id, -0.2)
    assert board.calls == [(motor_id, -51)]


def test_set_motor_raw_ignores_the_wiring_block(monkeypatch):
    # Even with the wheel mapped elsewhere and inverted, ID 0 gets +51.
    monkeypatch.setattr(mecanum, "FRONT_LEFT", Wheel(motor_id=3, inverted=True))
    monkeypatch.setattr(mecanum, "REAR_RIGHT", Wheel(motor_id=0, inverted=True))
    driver, board, _ = make_driver()
    driver.set_motor_raw(0, 0.2)
    assert board.calls == [(0, 51)]


def test_set_motor_raw_clamps_and_sends_an_int():
    driver, board, _ = make_driver()
    driver.set_motor_raw(1, 1.0)
    assert board.calls == [(1, MAX_LIB)]
    assert type(board.calls[0][1]) is int


@pytest.mark.parametrize("bad", [-1, 4, 10])
def test_set_motor_raw_rejects_unknown_ids(bad):
    driver, board, _ = make_driver()
    with pytest.raises(ValueError):
        driver.set_motor_raw(bad, 0.2)
    assert board.calls == []


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

def test_stop_writes_zero_to_all_four_motors_twice_with_a_gap():
    driver, board, sleeps = make_driver()
    driver.stop()
    assert board.calls == ALL_ZERO + ALL_ZERO
    assert sorted(m for m, _ in board.calls[:4]) == [0, 1, 2, 3]
    assert sleeps == [STOP_REPEAT_GAP_S]


def test_stop_is_safe_to_repeat():
    driver, board, _ = make_driver()
    driver.stop()
    driver.stop()
    assert board.calls == (ALL_ZERO + ALL_ZERO) * 2


def test_stop_ignores_inversion(monkeypatch):
    monkeypatch.setattr(mecanum, "FRONT_LEFT", Wheel(motor_id=0, inverted=True))
    driver, board, _ = make_driver()
    driver.stop()
    assert all(speed == 0 for _, speed in board.calls)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

def test_context_manager_stops_on_normal_exit():
    driver, board, _ = make_driver()
    with driver as d:
        assert d is driver
        d.set_wheels(0.2, 0.2, 0.2, 0.2)
    assert board.calls[-8:] == ALL_ZERO + ALL_ZERO


def test_fake_driver_shares_the_context_manager():
    # It's defined on MotorDriver, so the fake (and tools/motion_test.py's
    # dry run) behaves exactly like the real driver.
    from motion.driver import FakeMotorDriver

    fake = FakeMotorDriver()
    with pytest.raises(RuntimeError):
        with fake:
            fake.set_wheels(0.2, 0.2, 0.2, 0.2)
            raise RuntimeError("boom")
    with fake:  # can be entered again
        pass
    assert [name for name, _ in fake.calls] == ["set_wheels", "stop", "stop"]


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_context_manager_stops_and_reraises(error):
    driver, board, _ = make_driver()
    with pytest.raises(type(error)):
        with driver:
            driver.set_wheels(0.2, 0.2, 0.2, 0.2)
            raise error
    assert board.calls[-8:] == ALL_ZERO + ALL_ZERO
