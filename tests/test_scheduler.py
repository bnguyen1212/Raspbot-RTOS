"""Unit tests for scheduler.loop: TimerCheck and round_robin.

No hardware and no real waiting: TimerCheck takes both times as arguments,
so the tests just pass made-up numbers.
"""

from config import TIMEOUT_SECONDS
from scheduler.loop import TimerCheck, round_robin

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
