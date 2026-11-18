"""Unit tests for motion.actions, using FakeMotorDriver and a fake clock.

No hardware and no real waiting: every action gets a FakeMotorDriver, and
RedAction's times come from FakeClock.
"""

from __future__ import annotations

import pytest

from config import (
    CENTER_DEADBAND_PX,
    IMAGE_CENTER_X,
    IMAGE_HEIGHT,
    SECONDS_PER_180,
    SECONDS_PER_360,
    RedState,
)
from motion import actions
from motion.actions import BlueAction, GreenAction, IdleAction, RedAction, StartupAction
from motion.driver import FakeMotorDriver
from motion.kinematics import rotate_in_place, strafe
from scheduler.dry_run import DryRunMotion

# A non-zero start, as in test_scheduler.py: it catches code that compares
# `now` alone against SECONDS_PER_180.
START = 1000.0

Y = IMAGE_HEIGHT / 2
LEFT_X = IMAGE_CENTER_X - CENTER_DEADBAND_PX - 1
RIGHT_X = IMAGE_CENTER_X + CENTER_DEADBAND_PX + 1


class FakeClock:
    """A clock that only moves when the test advances it."""

    def __init__(self, start: float = START) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def driver() -> FakeMotorDriver:
    return FakeMotorDriver()


# ---------------------------------------------------------------------------
# GreenAction: rotate toward the target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("x", "expected"),
    [
        (LEFT_X, ("set_wheels", rotate_in_place("ccw"))),
        (RIGHT_X, ("set_wheels", rotate_in_place("cw"))),
        (IMAGE_CENTER_X, ("stop", ())),
        (IMAGE_CENTER_X + CENTER_DEADBAND_PX, ("stop", ())),  # on the boundary
        (IMAGE_CENTER_X - CENTER_DEADBAND_PX, ("stop", ())),
    ],
    ids=["left", "right", "centered", "right-boundary", "left-boundary"],
)
def test_green_action_driver_calls(driver, x, expected):
    GreenAction((x, Y), driver=driver)
    assert driver.calls == [expected]


# ---------------------------------------------------------------------------
# BlueAction: strafe toward the target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("x", "expected"),
    [
        (LEFT_X, ("set_wheels", strafe("left"))),
        (RIGHT_X, ("set_wheels", strafe("right"))),
        (IMAGE_CENTER_X, ("stop", ())),
        (IMAGE_CENTER_X + CENTER_DEADBAND_PX, ("stop", ())),
        (IMAGE_CENTER_X - CENTER_DEADBAND_PX, ("stop", ())),
    ],
    ids=["left", "right", "centered", "right-boundary", "left-boundary"],
)
def test_blue_action_driver_calls(driver, x, expected):
    BlueAction((x, Y), driver=driver)
    assert driver.calls == [expected]


def test_green_and_blue_ignore_y(driver):
    GreenAction((RIGHT_X, 0), driver=driver)
    GreenAction((RIGHT_X, IMAGE_HEIGHT - 1), driver=driver)
    assert driver.calls[0] == driver.calls[1]


def test_green_steps_until_centered_then_stops(driver):
    # The target drifts toward center over several passes, as it would while
    # the robot turns toward it.
    for x in (RIGHT_X + 100, RIGHT_X + 50, RIGHT_X, IMAGE_CENTER_X):
        GreenAction((x, Y), driver=driver)
    assert driver.calls == [("set_wheels", rotate_in_place("cw"))] * 3 + [("stop", ())]
    assert driver.wheels == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# IdleAction and StartupAction
# ---------------------------------------------------------------------------

def test_idle_action_stops_the_wheels(driver):
    GreenAction((RIGHT_X, Y), driver=driver)  # leaves the wheels running
    IdleAction(driver=driver)
    assert driver.calls[-1] == ("stop", ())
    assert driver.wheels == (0, 0, 0, 0)


def test_startup_spins_cw_for_seconds_per_360_then_stops(driver):
    events: list[object] = []
    StartupAction(driver=driver, sleep=lambda s: events.append(("sleep", s)))
    assert driver.calls == [("set_wheels", rotate_in_place("cw")), ("stop", ())]
    assert events == [("sleep", SECONDS_PER_360)]


def test_startup_order_is_spin_sleep_stop(driver):
    order: list[str] = []
    original_set, original_stop = driver.set_wheels, driver.stop

    def set_wheels(*speeds: float) -> None:
        order.append("set_wheels")
        original_set(*speeds)

    def stop() -> None:
        order.append("stop")
        original_stop()

    driver.set_wheels, driver.stop = set_wheels, stop  # type: ignore[method-assign]
    StartupAction(driver=driver, sleep=lambda s: order.append("sleep"))
    assert order == ["set_wheels", "sleep", "stop"]


def test_startup_stops_the_wheels_if_interrupted(driver):
    def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        StartupAction(driver=driver, sleep=interrupted)
    assert driver.calls[-1] == ("stop", ())
    assert driver.wheels == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# RedAction state transitions
# ---------------------------------------------------------------------------

def new_state() -> RedState:
    return {"red_start": None, "red_rearm": True}


def test_red_start_rotates_cw_and_records_now(driver):
    clock = FakeClock()
    state = RedAction(new_state(), clock(), driver=driver)
    assert state == {"red_start": START, "red_rearm": True}
    assert driver.calls == [("set_wheels", rotate_in_place("cw"))]


def test_red_start_leaves_rearm_unchanged(driver):
    state = RedAction({"red_start": None, "red_rearm": False}, START, driver=driver)
    assert state["red_rearm"] is False


def test_red_turning_makes_no_driver_call_and_keeps_state(driver):
    turning: RedState = {"red_start": START, "red_rearm": True}
    for elapsed in (0.0, SECONDS_PER_180 / 2, SECONDS_PER_180 - 0.001):
        assert RedAction(turning, START + elapsed, driver=driver) == turning
    assert driver.calls == []


def test_red_finishes_exactly_at_seconds_per_180(driver):
    # "Turning" is now - red_start < SECONDS_PER_180, so reaching it exactly
    # ends the turn.
    turning: RedState = {"red_start": START, "red_rearm": True}
    state = RedAction(turning, START + SECONDS_PER_180, driver=driver)
    assert state == {"red_start": None, "red_rearm": False}
    assert driver.calls == [("stop", ())]


def test_red_finishes_after_seconds_per_180(driver):
    turning: RedState = {"red_start": START, "red_rearm": True}
    state = RedAction(turning, START + SECONDS_PER_180 + 5, driver=driver)
    assert state == {"red_start": None, "red_rearm": False}
    assert driver.calls == [("stop", ())]


@pytest.mark.parametrize(
    "state",
    [
        {"red_start": None, "red_rearm": True},
        {"red_start": START, "red_rearm": True},
        {"red_start": START - SECONDS_PER_180, "red_rearm": True},
    ],
    ids=["start", "turning", "finished"],
)
def test_red_never_modifies_its_input(driver, state):
    before = dict(state)
    result = RedAction(state, START, driver=driver)
    assert state == before
    assert result is not state


def test_red_full_turn_on_a_fake_clock(driver):
    """Step a whole turn pass by pass, as run_loop would."""
    clock = FakeClock()
    step = 0.25  # exact in binary, so no rounding at the boundary
    state = new_state()
    history = []
    while True:
        state = RedAction(state, clock(), driver=driver)
        history.append(state)
        if state["red_start"] is None:
            break
        clock.advance(step)

    assert driver.calls == [("set_wheels", rotate_in_place("cw")), ("stop", ())]
    assert driver.wheels == (0, 0, 0, 0)
    assert clock() - START == SECONDS_PER_180  # stopped on the first pass at the limit
    assert len(history) == SECONDS_PER_180 / step + 1
    assert all(s == {"red_start": START, "red_rearm": True} for s in history[:-1])
    assert history[-1] == {"red_start": None, "red_rearm": False}


def test_red_matches_the_dry_run_stand_in(driver):
    """--dry-run must time the red turn exactly like the real action."""
    fake = DryRunMotion(log=lambda line: None)
    real_state, fake_state = new_state(), new_state()
    for t in [START + 0.5 * i for i in range(int(SECONDS_PER_180 / 0.5) + 3)]:
        real_state = RedAction(real_state, t, driver=driver)
        fake_state = fake.red_action(fake_state, t)
        assert real_state == fake_state


# ---------------------------------------------------------------------------
# Default driver
# ---------------------------------------------------------------------------

def test_actions_use_default_driver_only_when_none_is_passed(monkeypatch):
    default = FakeMotorDriver()
    monkeypatch.setattr(actions, "default_driver", lambda: default)

    IdleAction()
    GreenAction((RIGHT_X, Y))
    BlueAction((LEFT_X, Y))
    RedAction(new_state(), START)
    StartupAction(sleep=lambda s: None)
    assert len(default.calls) == 6

    passed = FakeMotorDriver()
    GreenAction((RIGHT_X, Y), driver=passed)
    assert len(default.calls) == 6
    assert len(passed.calls) == 1


def test_red_turning_pass_never_looks_up_the_default_driver(monkeypatch):
    def fail() -> FakeMotorDriver:
        raise AssertionError("default_driver() called on a pass with no motion")

    monkeypatch.setattr(actions, "default_driver", fail)
    RedAction({"red_start": START, "red_rearm": True}, START + 0.1)
