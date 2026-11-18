"""The motor driver interface, a recording fake, and the lazy real default.

motion.actions drives the wheels only through a MotorDriver. Tests pass a
FakeMotorDriver. On the robot the actions fall back to default_driver().

Importing this module never imports the motor library. The real driver will
be imported inside default_driver(), on first use.
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod

from motion.kinematics import WheelSpeeds

# One recorded driver call: ("set_wheels", (fl, fr, rl, rr)) or ("stop", ()).
DriverCall = tuple[str, tuple[float, ...]]


class MotorDriver(ABC):
    """Sets the four mecanum wheel speeds.

    Speeds are signed and in the motor library's units. They come from
    motion.kinematics, which has already applied each wheel's polarity
    (SIGN_*), so an implementation passes them through unchanged.

    Both methods must return right away (no waiting): the per-loop actions
    call them on every pass.
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

    Creating it is the one-time motor hardware init (opening the I2C bus).
    The cache keeps a single driver for the whole run, so the bus isn't
    reopened on every loop pass.

    Raises:
        NotImplementedError: always, until the real driver is written.
    """
    # TODO: write the Yahboom-backed driver in its own module and import it
    # here, inside the function, so importing motion/ never loads the library:
    #     from motion.raspbot_driver import RaspbotMotorDriver
    #     return RaspbotMotorDriver()
    raise NotImplementedError(
        "the real MotorDriver isn't written yet; pass driver=FakeMotorDriver() "
        "or use main.py --dry-run"
    )
