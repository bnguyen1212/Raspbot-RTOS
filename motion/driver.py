"""The motor driver interface, a recording fake, and the lazy real default.

motion.actions drives the wheels only through a MotorDriver. Tests pass a
FakeMotorDriver. On the robot, the actions fall back to default_driver(),
which is motion.mecanum.RaspbotMotorDriver.

Importing this module never imports the motor library. motion.mecanum (and,
through it, Raspbot_Lib) is imported inside default_driver(), on first use.
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod

from motion.kinematics import WheelSpeeds

# One recorded driver call: ("set_wheels", (fl, fr, rl, rr)) or ("stop", ()).
DriverCall = tuple[str, tuple[float, ...]]


class MotorDriver(ABC):
    """Sets the four mecanum wheel speeds.

    Speeds are normalized and signed: 1.0 is full speed forward, -1.0 full
    speed backward, as logical wheel directions from motion.kinematics. A
    hardware implementation does the rest: it maps wheels to motor IDs, applies
    any wiring inversions, and clamps to config.MAX_SPEED.

    The board keeps running the last speeds it was sent (there's no watchdog),
    so callers must not assume the wheels stop on their own.

    Neither method waits for the wheels to reach the new speed. A real stop()
    may pause for a few milliseconds (see motion.mecanum).
    """

    @abstractmethod
    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None:
        """Start each wheel turning at the given speed. They keep turning until changed."""

    @abstractmethod
    def stop(self) -> None:
        """Stop all four wheels. Must be safe to call when they're already stopped."""


class FakeMotorDriver(MotorDriver):
    """MotorDriver for tests: records every call and never touches hardware.

    Attributes:
        calls: every call so far, in order, as DriverCall tuples.
        wheels: the speeds the wheels would be turning at right now
            (all zero at the start and after stop()).
    """

    def __init__(self) -> None:
        self.calls: list[DriverCall] = []
        self.wheels: WheelSpeeds = (0, 0, 0, 0)

    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None:
        self.wheels = (front_left, front_right, rear_left, rear_right)
        self.calls.append(("set_wheels", self.wheels))

    def stop(self) -> None:
        self.wheels = (0, 0, 0, 0)
        self.calls.append(("stop", ()))


@functools.cache
def default_driver() -> MotorDriver:
    """The robot's real MotorDriver, created on the first call and reused after.

    Creating it opens the I2C bus (the one-time motor hardware init). The
    cache keeps a single driver, and so a single Raspbot, for the whole run.
    If creating it raises, nothing is cached and the next call tries again.

    Returns:
        motion.mecanum.RaspbotMotorDriver with the default config.MAX_SPEED.

    Raises:
        ImportError: if Raspbot_Lib isn't installed (for example on a laptop;
            use main.py --dry-run there).
    """
    # Imported here so that importing motion/ never loads Raspbot_Lib.
    from motion.mecanum import RaspbotMotorDriver

    return RaspbotMotorDriver()


def existing_default_driver() -> MotorDriver | None:
    """The default driver if default_driver() has already created it, else None.

    It never creates a driver, so it never opens the I2C bus. ShutdownAction
    uses it: if no driver exists, this process never sent the wheels a
    command. (The board keeps the last command it got, so wheels left running
    by an earlier process need tools/emergency_stop.py.)
    """
    if default_driver.cache_info().currsize == 0:
        return None
    return default_driver()
