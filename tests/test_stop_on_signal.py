"""Unit tests for motion.stop_on_signal.

Handlers are captured instead of installed, and os._exit is replaced, so no
test really changes signal handling or exits. Real signals are sent to the
tools' --dry-run processes in test_motion_test.py and
test_spin_calibration.py (POSIX only).
"""

from __future__ import annotations

import signal

from motion import stop_on_signal
from motion.driver import FakeMotorDriver


def captured_handlers(monkeypatch, driver, output):
    handlers: dict[int, object] = {}
    monkeypatch.setattr(
        stop_on_signal.signal, "signal", lambda sig, h: handlers.__setitem__(sig, h)
    )
    stop_on_signal.install_stop_handlers(driver, write=output.append)
    return handlers


def test_handlers_cover_sigint_sigterm_and_sighup_where_available(monkeypatch):
    handlers = captured_handlers(monkeypatch, FakeMotorDriver(), [])
    expected = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGHUP"):
        expected.add(signal.SIGHUP)
    assert set(handlers) == expected


def test_handler_stops_then_exits_without_raising(monkeypatch):
    output: list[str] = []
    driver = FakeMotorDriver()
    handlers = captured_handlers(monkeypatch, driver, output)
    exits: list[int] = []
    monkeypatch.setattr(stop_on_signal.os, "_exit", exits.append)

    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert driver.calls == [("stop", ())]
    assert exits == [128 + signal.SIGTERM]
    assert "SIGTERM: stop sent" in output[-1]


def test_handler_ignores_further_signals_while_stopping(monkeypatch):
    installed: list[tuple[int, object]] = []
    monkeypatch.setattr(stop_on_signal.signal, "signal", lambda sig, h: installed.append((sig, h)))
    monkeypatch.setattr(stop_on_signal.os, "_exit", lambda code: None)
    stop_on_signal.install_stop_handlers(FakeMotorDriver(), write=lambda m: None)
    handler = installed[0][1]
    installed.clear()

    handler(signal.SIGINT, None)  # type: ignore[operator]
    assert {sig for sig, _ in installed} == set(stop_on_signal.STOP_SIGNALS)
    assert all(h is signal.SIG_IGN for _, h in installed)


def test_handler_still_exits_if_stop_fails(monkeypatch):
    output: list[str] = []
    driver = FakeMotorDriver()

    def broken_stop() -> None:
        raise OSError("I2C bus gone")

    driver.stop = broken_stop  # type: ignore[method-assign]
    handlers = captured_handlers(monkeypatch, driver, output)
    exits: list[int] = []
    monkeypatch.setattr(stop_on_signal.os, "_exit", exits.append)

    handlers[signal.SIGINT](signal.SIGINT, None)
    assert exits == [128 + signal.SIGINT]
    assert "FAILED" in output[-1] and "emergency_stop.py" in output[-1]
