"""Unit tests for scheduler.loop: TimerCheck, round_robin and run_loop.

No hardware and no real waiting: TimerCheck takes both times as arguments,
so the tests just pass made-up numbers, and run_loop gets fake tasks plus a
fake clock (see FakeRobot below).
"""

import pytest

from config import SECONDS_PER_180, TIMEOUT_SECONDS
from scheduler.loop import TimerCheck, round_robin, run_loop

# Any start value works. time.monotonic() has no fixed zero point, so only the
# difference between two readings matters. A non-zero start catches a bug
# where the code compares `now` alone against the timeout.
START = 1000.0


# ---------------------------------------------------------------------------
# TimerCheck
# ---------------------------------------------------------------------------
# Inputs are built from TIMEOUT_SECONDS, not hard-coded, so these tests stay
# correct if the timeout in config.py is tuned later.

def test_timer_check_false_when_no_time_elapsed():
    assert TimerCheck(START, START) is False


def test_timer_check_false_before_timeout():
    assert TimerCheck(START, START + TIMEOUT_SECONDS / 2) is False


def test_timer_check_false_at_exactly_timeout():
    # The contract says "exceeded", so reaching the limit exactly isn't enough.
    assert TimerCheck(START, START + TIMEOUT_SECONDS) is False


def test_timer_check_true_just_after_timeout():
    assert TimerCheck(START, START + TIMEOUT_SECONDS + 0.001) is True


def test_timer_check_true_long_after_timeout():
    assert TimerCheck(START, START + TIMEOUT_SECONDS * 10) is True


# ---------------------------------------------------------------------------
# round_robin
# ---------------------------------------------------------------------------

def test_round_robin_runs_each_task_once_in_order():
    ran = []

    def task_a():
        ran.append("a")

    def task_b():
        ran.append("b")

    def task_c():
        ran.append("c")

    round_robin([task_a, task_b, task_c])

    assert ran == ["a", "b", "c"]


def test_round_robin_runs_the_same_task_each_time_it_appears():
    ran = []

    def task():
        ran.append("x")

    round_robin([task, task])

    assert ran == ["x", "x"]


def test_round_robin_with_no_tasks_does_nothing():
    round_robin([])  # must not raise


def test_round_robin_returns_none():
    assert round_robin([lambda: None]) is None


# ---------------------------------------------------------------------------
# run_loop
# ---------------------------------------------------------------------------
# Each loop pass "takes" FRAME_DT seconds of fake time (capture_frame moves
# the fake clock forward). Picking FRAME_DT = SECONDS_PER_180 / 3.5 means a red
# turn always finishes on the 4th pass after it starts. 3.5 isn't a whole
# number, so float rounding can never land exactly on the SECONDS_PER_180
# boundary and make the tests flaky.
FRAME_DT = SECONDS_PER_180 / 3.5

# What the fake RedAction reports on each pass of one complete red turn.
TURN = ["red-start", "red-turning", "red-turning", "red-turning", "red-done"]

RED = ("red", (100.0, 50.0))
IDLE = (None, None)


class FakeRobot:
    """Fake versions of every task run_loop needs, plus a fake clock.

    - self.time is the fake clock. capture_frame() moves it forward by
      FRAME_DT, so each loop pass takes FRAME_DT seconds of fake time.
    - self.calls records every task call, in order, as (name, *args).
    - self.actions records just the one action taken per pass, as a label.
    - The fake ColorLocator returns the results in `script`, one per pass.

    How the run ends:
    - script=None: vision always reports idle, and the loop runs until
      TimerCheck sees TIMEOUT_SECONDS of fake time pass.
    - script=[...]: once the last scripted pass's action has run, the clock
      jumps far ahead, so TimerCheck stops the loop on the very next check.
      That way a test gets exactly len(script) passes.
    """

    START_TIME = 1000.0

    def __init__(self, script=None):
        self.time = self.START_TIME
        self.script = None if script is None else list(script)
        self.calls = []
        self.actions = []

    # -- the clock -----------------------------------------------------------
    def clock(self):
        return self.time

    def _end_of_pass(self):
        """Called at the end of every action (the last task in a pass)."""
        if self.script is not None and not self.script:
            self.time += TIMEOUT_SECONDS * 10

    # -- startup and vision --------------------------------------------------
    def startup_action(self):
        self.calls.append(("startup_action",))

    def capture_frame(self):
        self.time += FRAME_DT
        frame = object()  # a unique stand-in for an image
        self.calls.append(("capture_frame", frame))
        return frame

    def color_counter(self, frame):
        counts = {"frame": frame}  # unique per pass, so data flow is checkable
        self.calls.append(("color_counter", frame, counts))
        return counts

    def color_locator(self, counts, frame):
        self.calls.append(("color_locator", counts, frame))
        if self.script:
            return self.script.pop(0)
        return IDLE

    # -- actions -------------------------------------------------------------
    def idle_action(self):
        self.calls.append(("idle_action",))
        self.actions.append("idle")
        self._end_of_pass()

    def green_action(self, p_vector):
        self.calls.append(("green_action", p_vector))
        self.actions.append("green")
        self._end_of_pass()

    def blue_action(self, p_vector):
        self.calls.append(("blue_action", p_vector))
        self.actions.append("blue")
        self._end_of_pass()

    def red_action(self, state, now):
        """Behaves like the RedAction table in docs/task_contracts.md."""
        self.calls.append(("red_action", dict(state), now))
        if state["red_start"] is None:
            self.actions.append("red-start")
            new_state = {**state, "red_start": now}
        elif now - state["red_start"] < SECONDS_PER_180:
            self.actions.append("red-turning")
            new_state = {**state}
        else:
            self.actions.append("red-done")
            new_state = {"red_start": None, "red_rearm": False}
        self._end_of_pass()
        return new_state

    # -- running -------------------------------------------------------------
    def run(self, **overrides):
        """Call run_loop with every fake task. `overrides` replaces any of them."""
        tasks = dict(
            startup_action=self.startup_action,
            capture_frame=self.capture_frame,
            color_counter=self.color_counter,
            color_locator=self.color_locator,
            idle_action=self.idle_action,
            color_actions={"green": self.green_action, "blue": self.blue_action},
            red_action=self.red_action,
            clock=self.clock,
        )
        tasks.update(overrides)
        run_loop({"red_start": None, "red_rearm": True}, **tasks)

    def names(self):
        return [call[0] for call in self.calls]

    def passes(self):
        return self.names().count("capture_frame")


# -- timing and order ---------------------------------------------------------

def test_run_loop_stops_once_timeout_has_passed():
    robot = FakeRobot()  # always idle; only the timeout can stop it
    robot.run()

    # It kept going until just past TIMEOUT_SECONDS of fake time, then stopped.
    # Elapsed time is read off the fake clock -- the same numbers TimerCheck
    # saw -- rather than computed as passes * FRAME_DT, which can round
    # differently and land exactly on the boundary.
    elapsed = robot.time - FakeRobot.START_TIME
    assert elapsed > TIMEOUT_SECONDS
    assert elapsed <= TIMEOUT_SECONDS + FRAME_DT


def test_startup_runs_exactly_once_before_the_first_pass():
    robot = FakeRobot()
    robot.run()
    assert robot.names().count("startup_action") == 1
    assert robot.names()[0] == "startup_action"


def test_startup_time_does_not_count_against_the_timeout():
    """The contract takes start_time after StartupAction, so a slow startup
    spin doesn't eat into the run's time budget."""
    robot = FakeRobot()

    startup_takes = TIMEOUT_SECONDS * 5  # far longer than the whole budget

    def slow_startup():
        robot.time += startup_takes

    robot.run(startup_action=slow_startup)

    # Still a full-length run after startup, not an immediate stop.
    loop_time = robot.time - (FakeRobot.START_TIME + startup_takes)
    assert loop_time > TIMEOUT_SECONDS
    assert robot.passes() > 1


def test_tasks_run_in_fixed_order_every_pass():
    robot = FakeRobot(script=[("green", (1.0, 2.0)), IDLE])
    robot.run()

    one_pass = ["capture_frame", "color_counter", "color_locator"]
    assert robot.names() == (
        ["startup_action"]
        + one_pass + ["green_action"]
        + one_pass + ["idle_action"]
    )


def test_each_task_gets_the_previous_tasks_output():
    robot = FakeRobot(script=[("blue", (7.0, 8.0))])
    robot.run()

    _, frame = robot.calls[1]                     # capture_frame
    _, counter_frame, counts = robot.calls[2]     # color_counter
    _, locator_counts, locator_frame = robot.calls[3]  # color_locator

    assert counter_frame is frame
    assert locator_counts is counts
    assert locator_frame is frame                 # the SAME frame, per contract
    assert robot.calls[4] == ("blue_action", (7.0, 8.0))


# -- dispatch: one action per pass ---------------------------------------------

@pytest.mark.parametrize(
    "vision_result, expected_call",
    [
        (("green", (400.0, 240.0)), ("green_action", (400.0, 240.0))),
        (("blue", (10.0, 20.0)), ("blue_action", (10.0, 20.0))),
        (IDLE, ("idle_action",)),
        (("purple", (1.0, 1.0)), ("idle_action",)),  # unknown color -> idle
    ],
)
def test_vision_result_dispatches_exactly_one_action(vision_result, expected_call):
    robot = FakeRobot(script=[vision_result])
    robot.run()
    actions = [call for call in robot.calls if call[0].endswith("_action")
               and call[0] != "startup_action"]
    assert actions == [expected_call]


# -- dispatch: the red-turn sequence -------------------------------------------

def test_red_card_starts_a_turn_with_the_fake_clock_time():
    robot = FakeRobot(script=[RED])
    robot.run()
    assert robot.actions == ["red-start"]
    _, state_passed_in, now = robot.calls[-1]
    assert state_passed_in == {"red_start": None, "red_rearm": True}
    # The fake clock's time on the first pass, not the real time.
    assert now == pytest.approx(FakeRobot.START_TIME + FRAME_DT)


def test_turn_keeps_going_whatever_vision_reports():
    """Once started, RedAction runs every pass until the turn finishes, even
    if the card disappears or another color shows up."""
    robot = FakeRobot(script=[RED, IDLE, ("green", (1.0, 1.0)), ("blue", (1.0, 1.0)), IDLE, IDLE])
    robot.run()
    assert robot.actions == TURN + ["idle"]


def test_no_new_turn_while_the_same_red_card_stays_visible():
    robot = FakeRobot(script=[RED] * 8)
    robot.run()
    assert robot.actions == TURN + ["idle", "idle", "idle"]


def test_red_card_starts_a_new_turn_after_it_leaves_and_returns():
    robot = FakeRobot(script=[RED] * 5 + [IDLE, RED])
    robot.run()
    assert robot.actions == TURN + ["idle", "red-start"]


def test_any_other_color_also_rearms_red():
    robot = FakeRobot(script=[RED] * 5 + [("green", (1.0, 1.0)), RED])
    robot.run()
    assert robot.actions == TURN + ["green", "red-start"]


def test_turn_ending_on_a_non_red_frame_still_needs_a_later_non_red_frame():
    """Rearm runs before dispatch, so on the pass where the turn finishes,
    RedAction's red_rearm=False wins. A red card on the very next pass must
    not start another turn; only a later non-red frame rearms."""
    robot = FakeRobot(script=[RED, IDLE, IDLE, IDLE, IDLE, RED, IDLE, RED])
    robot.run()
    assert robot.actions == TURN + ["idle", "idle", "red-start"]
