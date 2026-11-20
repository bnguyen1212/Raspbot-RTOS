"""Unit tests for motion.actions, using FakeMotorDriver and a fake clock.

No hardware and no real waiting: every action gets a FakeMotorDriver (or, in
the default-driver tests, a real RaspbotMotorDriver on a fake Raspbot_Lib),
and RedAction's times come from FakeClock.
"""

from __future__ import annotations

import math

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
from motion.actions import (
    BlueAction,
    GreenAction,
    IdleAction,
    RedAction,
    ShutdownAction,
    StartupAction,
)
from motion.driver import FakeMotorDriver, default_driver
from motion.mecanum import RaspbotMotorDriver
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


def test_red_turning_resends_cw_and_keeps_state(driver):
    # Every call sets the wheels explicitly, so a turning pass sends the same
    # rotation again instead of nothing.
    turning: RedState = {"red_start": START, "red_rearm": True}
    elapsed_values = (0.0, SECONDS_PER_180 / 2, SECONDS_PER_180 - 0.001)
    for elapsed in elapsed_values:
        assert RedAction(turning, START + elapsed, driver=driver) == turning
    assert driver.calls == [("set_wheels", rotate_in_place("cw"))] * len(elapsed_values)


def test_red_finishes_exactly_at_seconds_per_180(driver):
    # "Turning" is now - red_start < SECONDS_PER_180, so reaching it exactly
    # ends the turn. The turn starts at 0.0 so that now - red_start is exactly
    # SECONDS_PER_180: from START, START + x - START can round to just under
    # or just over x, which would make this test pass or fail by luck.
    turning: RedState = {"red_start": 0.0, "red_rearm": True}
    state = RedAction(turning, SECONDS_PER_180, driver=driver)
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

    turning_passes = len(history) - 1  # every pass but the last
    assert driver.calls == [("set_wheels", rotate_in_place("cw"))] * turning_passes + [("stop", ())]
    assert driver.wheels == (0, 0, 0, 0)
    # Stopped on the first pass at or past the limit. The calibrated
    # SECONDS_PER_180 needn't be a multiple of the step, so that pass can land
    # after the limit; the pass before it must still be under it.
    elapsed = clock() - START
    assert elapsed - step < SECONDS_PER_180 <= elapsed
    assert len(history) == math.ceil(SECONDS_PER_180 / step) + 1
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


def test_default_driver_is_the_real_driver_created_once(fake_raspbot_lib):
    # A fake Raspbot_Lib stands in for the board; the driver itself is real.
    GreenAction((RIGHT_X, Y))
    IdleAction()
    assert isinstance(default_driver(), RaspbotMotorDriver)
    assert len(fake_raspbot_lib) == 1  # one Raspbot for every action
    assert fake_raspbot_lib[0].calls[-8:] == [(0, 0), (2, 0), (1, 0), (3, 0)] * 2


# ---------------------------------------------------------------------------
# ShutdownAction
# ---------------------------------------------------------------------------

def test_shutdown_stops_the_given_driver(driver):
    GreenAction((RIGHT_X, Y), driver=driver)
    ShutdownAction(driver=driver)
    assert driver.calls[-1] == ("stop", ())
    assert driver.wheels == (0, 0, 0, 0)


def test_shutdown_is_safe_to_call_repeatedly(driver):
    for _ in range(3):
        ShutdownAction(driver=driver)
    assert driver.calls == [("stop", ())] * 3
    assert driver.wheels == (0, 0, 0, 0)


def test_shutdown_stops_the_existing_default_driver(monkeypatch):
    default = FakeMotorDriver()
    monkeypatch.setattr(actions, "existing_default_driver", lambda: default)
    ShutdownAction()
    ShutdownAction()
    assert default.calls == [("stop", ())] * 2


def test_shutdown_never_creates_a_driver(fake_raspbot_lib):
    # No action has run, so there's no default driver yet.
    ShutdownAction()
    ShutdownAction()
    assert fake_raspbot_lib == []  # the bus was never opened


def test_shutdown_after_a_run_stops_the_same_board(fake_raspbot_lib):
    BlueAction((LEFT_X, Y))
    ShutdownAction()
    assert len(fake_raspbot_lib) == 1
    assert fake_raspbot_lib[0].calls[-8:] == [(0, 0), (2, 0), (1, 0), (3, 0)] * 2


# ---------------------------------------------------------------------------
# Every call sets the wheels explicitly
# ---------------------------------------------------------------------------
# The board keeps running the last command (no watchdog). So every action
# must set the wheels on every call, whatever was running before. Each case
# starts with the wheels left running by something else, then checks the
# action's own call decides what the wheels do.

LEFTOVER = strafe("left")  # what the previous action left running
STOPPED = (0, 0, 0, 0)

EVERY_CALL_CASES = [
    ("idle", lambda d: IdleAction(driver=d), STOPPED),
    ("green-left", lambda d: GreenAction((LEFT_X, Y), driver=d), rotate_in_place("ccw")),
    ("green-right", lambda d: GreenAction((RIGHT_X, Y), driver=d), rotate_in_place("cw")),
    ("green-centered", lambda d: GreenAction((IMAGE_CENTER_X, Y), driver=d), STOPPED),
    ("blue-left", lambda d: BlueAction((LEFT_X, Y), driver=d), strafe("left")),
    ("blue-right", lambda d: BlueAction((RIGHT_X, Y), driver=d), strafe("right")),
    ("blue-centered", lambda d: BlueAction((IMAGE_CENTER_X, Y), driver=d), STOPPED),
    (
        "red-start",
        lambda d: RedAction({"red_start": None, "red_rearm": True}, START, driver=d),
        rotate_in_place("cw"),
    ),
    (
        "red-turning",
        lambda d: RedAction({"red_start": START, "red_rearm": True}, START + 0.1, driver=d),
        rotate_in_place("cw"),
    ),
    (
        "red-finished",
        # From 0.0, so the elapsed time is exactly SECONDS_PER_180 (see
        # test_red_finishes_exactly_at_seconds_per_180).
        lambda d: RedAction({"red_start": 0.0, "red_rearm": True}, SECONDS_PER_180, driver=d),
        STOPPED,
    ),
]


@pytest.mark.parametrize(
    ("action", "expected_wheels"),
    [case[1:] for case in EVERY_CALL_CASES],
    ids=[case[0] for case in EVERY_CALL_CASES],
)
def test_every_per_loop_call_sets_the_wheels_exactly_once(driver, action, expected_wheels):
    driver.set_wheels(*LEFTOVER)
    driver.calls.clear()
    action(driver)
    assert len(driver.calls) == 1
    assert driver.wheels == expected_wheels


def test_startup_sets_the_wheels_and_leaves_them_stopped(driver):
    driver.set_wheels(*LEFTOVER)
    driver.calls.clear()
    StartupAction(driver=driver, sleep=lambda s: None)
    assert [name for name, _ in driver.calls] == ["set_wheels", "stop"]
    assert driver.wheels == STOPPED


def test_shutdown_sets_the_wheels_to_stopped(driver):
    driver.set_wheels(*LEFTOVER)
    driver.calls.clear()
    ShutdownAction(driver=driver)
    assert driver.calls == [("stop", ())]
    assert driver.wheels == STOPPED
