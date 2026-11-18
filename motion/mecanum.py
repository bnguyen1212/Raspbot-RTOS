"""The real MotorDriver for the Yahboom RASPBOT V2, built on Raspbot_Lib.

This is the ONLY module that imports Raspbot_Lib. It imports it lazily,
inside RaspbotMotorDriver's constructor, so importing this module on a laptop
without the library (or without smbus) works. Nothing touches the I2C bus
until a RaspbotMotorDriver is created.

NOTHING IN THIS FILE HAS BEEN RUN ON THE ROBOT. The wiring block below is a
guess taken from a comment in the library's source and must be checked
physically.

Known library behavior, from reading Raspbot_Lib's source (0.0.2):
- Raspbot() opens I2C bus 1 (address 0x2B) as soon as it's constructed, and
  never closes it. This driver creates exactly one Raspbot and reuses it.
- Ctrl_Muto(motor_id, speed) takes a signed speed in -255..255. The library
  doesn't convert types, so this module always sends Python ints.
- Every library I/O method wraps its I2C write in a bare `except:` that only
  prints a message. I2C errors never reach this code, so a failed write
  (including a failed stop) CANNOT be detected here. The bare `except:` also
  catches KeyboardInterrupt, so a Ctrl-C that lands during a write is
  swallowed.
- The library has no stop method and no watchdog. As far as the source shows,
  the board keeps running the last speed it was sent until it gets another.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from types import TracebackType
from typing import Final, NamedTuple, Protocol

from config import MAX_SPEED
from motion.driver import MotorDriver


class Wheel(NamedTuple):
    """How one logical wheel maps onto the motor board."""

    motor_id: int   # the ID passed to Raspbot.Ctrl_Muto
    inverted: bool  # True if a positive speed drives this wheel backward


# ===========================================================================
# VERIFY ON ROBOT -- wheel wiring. NOT VERIFIED: none of this has been
# checked on hardware.
#
# Motor IDs: the library's commented motor test labels them 0 = "L1",
# 1 = "L2", 2 = "R1", 3 = "R2". Nothing in the library says whether "1" means
# front or rear. The guess below is L1/R1 = front and L2/R2 = rear.
#
# Inverted: whether the library's "forward" (a positive speed) spins this
# wheel backward. Nothing in the library says, so all start as False.
#
# How to check (wheels off the ground): command one wheel at a time at a low
# speed and watch which wheel turns and which way. Fix motor_id first, then
# inverted.
# ===========================================================================
FRONT_LEFT: Final[Wheel] = Wheel(motor_id=0, inverted=False)   # library "L1"
REAR_LEFT: Final[Wheel] = Wheel(motor_id=1, inverted=False)    # library "L2"
FRONT_RIGHT: Final[Wheel] = Wheel(motor_id=2, inverted=False)  # library "R1"
REAR_RIGHT: Final[Wheel] = Wheel(motor_id=3, inverted=False)   # library "R2"
# ===========================================================================

# Ctrl_Muto's speed range is -255..255 (from the library source).
LIBRARY_FULL_SPEED: Final[int] = 255

# The motor IDs the board accepts (from the library's motor test comment).
ALL_MOTOR_IDS: Final[frozenset[int]] = frozenset({0, 1, 2, 3})

# stop() sends its zeros twice, this many seconds apart. A failed write
# can't be detected (see the module docstring), so the second pass is the
# only protection against one dropped stop.
STOP_REPEAT_GAP_S: Final[float] = 0.005


class MotorBoard(Protocol):
    """The one Raspbot_Lib.Raspbot method this driver uses."""

    def Ctrl_Muto(self, motor_id: int, motor_speed: int) -> None: ...


def to_library_speed(speed: float, max_speed: float = MAX_SPEED) -> int:
    """Convert a normalized wheel speed to Ctrl_Muto's -255..255 integer.

    Clamps to +/-max_speed first, then scales so 1.0 is 255, rounds, and
    returns a Python int (never a float).

    Args:
        speed: normalized speed (1.0 = full speed forward).
        max_speed: the safety cap, default config.MAX_SPEED.

    Returns:
        int in [-round(max_speed * 255), round(max_speed * 255)].

    Raises:
        ValueError: if `speed` is NaN, which can't be clamped meaningfully.
    """
    if math.isnan(speed):
        raise ValueError("wheel speed is NaN")
    clamped = max(-max_speed, min(max_speed, speed))
    return int(round(clamped * LIBRARY_FULL_SPEED))


class RaspbotMotorDriver(MotorDriver):
    """MotorDriver that drives the RASPBOT V2's four mecanum wheels.

    Use it as a context manager to guarantee the wheels are stopped however
    the block ends, including on an exception or KeyboardInterrupt:

        with RaspbotMotorDriver() as driver:
            driver.set_wheels(0.1, 0.1, 0.1, 0.1)
            ...

    The guarantee only covers what reaches Python: if the library swallows a
    KeyboardInterrupt or an I2C error, nothing here can see it.

    Args:
        max_speed: safety cap on every wheel speed, default config.MAX_SPEED.
            Must be in (0, 1.0].
        board: the motor board to drive. None (the default) imports
            Raspbot_Lib and creates one Raspbot, which opens the I2C bus.
            Tests pass a fake.
        sleep: how stop() waits between its two passes. Tests pass a fake.

    Raises:
        ValueError: if `max_speed` is out of range, or the wiring block doesn't
            map the four wheels to four distinct motor IDs 0-3.
        ImportError: if Raspbot_Lib (or its smbus dependency) isn't installed.
    """

    def __init__(
        self,
        max_speed: float = MAX_SPEED,
        *,
        board: MotorBoard | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < max_speed <= 1.0:
            raise ValueError(f"max_speed must be in (0, 1.0], got {max_speed!r}")
        # Read the wiring block now, so it's checked before the bus is opened.
        # Order: (front_left, front_right, rear_left, rear_right), matching
        # set_wheels and motion.kinematics.WheelSpeeds.
        wheels = (FRONT_LEFT, FRONT_RIGHT, REAR_LEFT, REAR_RIGHT)
        ids = [wheel.motor_id for wheel in wheels]
        if sorted(ids) != sorted(ALL_MOTOR_IDS):
            # A duplicate ID would leave one motor that nothing, not even
            # stop(), ever writes to.
            raise ValueError(f"wheel motor IDs must be 0, 1, 2, 3 once each, got {ids}")

        if board is None:
            # The only Raspbot_Lib import in the project. It's done here, not
            # at the top of the file, so importing motion/ never needs the
            # library. Raspbot() opens I2C bus 1 right away.
            from Raspbot_Lib import Raspbot

            board = Raspbot()

        self._board: MotorBoard = board
        self._wheels = wheels
        self._max_speed = max_speed
        self._sleep = sleep

    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None:
        """Send all four wheel speeds (normalized, clamped to max_speed).

        Makes one Ctrl_Muto call per wheel. Raspbot_Lib swallows I2C errors,
        so a write that fails is not reported.
        """
        speeds = (front_left, front_right, rear_left, rear_right)
        # Convert all four first, so a bad value (NaN) sends nothing rather
        # than leaving the wheels half updated.
        commands = []
        for wheel, speed in zip(self._wheels, speeds):
            signed = -speed if wheel.inverted else speed
            commands.append((wheel.motor_id, to_library_speed(signed, self._max_speed)))
        for motor_id, library_speed in commands:
            self._board.Ctrl_Muto(motor_id, library_speed)

    def stop(self) -> None:
        """Write speed 0 to all four motors, twice, STOP_REPEAT_GAP_S apart.

        Safe to call any number of times. Raspbot_Lib swallows I2C errors, so
        a stop that fails CANNOT be detected here. The second pass is a
        precaution against one dropped write, not a confirmation.
        """
        self._write_zeros()
        self._sleep(STOP_REPEAT_GAP_S)
        self._write_zeros()

    def _write_zeros(self) -> None:
        for wheel in self._wheels:
            self._board.Ctrl_Muto(wheel.motor_id, 0)

    def __enter__(self) -> RaspbotMotorDriver:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the wheels. Any exception (KeyboardInterrupt too) still propagates."""
        self.stop()
