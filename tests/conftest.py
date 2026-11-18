"""Shared test fixtures. The main job is to keep the tests away from real motors.

Every test runs with the real Raspbot_Lib blocked (importing it raises
ImportError), even on the robot. So no test can open the I2C bus or move a
wheel. Tests that need a motor board use the `fake_raspbot_lib` fixture,
which puts a recording fake in its place.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import pytest

from motion.driver import default_driver


class FakeRaspbot:
    """Stands in for Raspbot_Lib.Raspbot. Records every Ctrl_Muto call.

    Like the real I2C write, it rejects anything but a Python int, so a
    test fails if the driver ever sends a float.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def Ctrl_Muto(self, motor_id: int, motor_speed: int) -> None:
        if type(motor_id) is not int or type(motor_speed) is not int:
            raise TypeError(f"Ctrl_Muto({motor_id!r}, {motor_speed!r}): ints only")
        self.calls.append((motor_id, motor_speed))


@pytest.fixture(autouse=True)
def _no_real_motor_library(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Block the real Raspbot_Lib and start each test with no cached driver."""
    monkeypatch.setitem(sys.modules, "Raspbot_Lib", None)  # import -> ImportError
    default_driver.cache_clear()
    yield
    default_driver.cache_clear()


@pytest.fixture
def fake_raspbot_lib(monkeypatch: pytest.MonkeyPatch) -> list[FakeRaspbot]:
    """Install a fake Raspbot_Lib module.

    Returns:
        The list of every FakeRaspbot the code under test creates, in order.
    """
    instances: list[FakeRaspbot] = []

    class Raspbot(FakeRaspbot):
        def __init__(self) -> None:
            super().__init__()
            instances.append(self)

    module = types.ModuleType("Raspbot_Lib")
    module.Raspbot = Raspbot  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "Raspbot_Lib", module)
    return instances
