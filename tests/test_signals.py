"""Unit tests for scheduler.signals.

Handlers are captured instead of installed, and os._exit is replaced, so no
test really changes signal handling or exits. Real signals are sent to
--dry-run processes in test_main.py, test_motion_test.py and
test_spin_calibration.py (POSIX only).
"""

from __future__ import annotations

import signal

from motion.driver import FakeMotorDriver
from scheduler import signals


def captured_handlers(monkeypatch, stop, output, release=None):
    handlers: dict[int, object] = {}
    monkeypatch.setattr(signals.signal, "signal", lambda sig, h: handlers.__setitem__(sig, h))
    signals.install_stop_handlers(stop, release=release, write=output.append)
    return handlers


def fake_exit(monkeypatch) -> list[int]:
    exits: list[int] = []
    monkeypatch.setattr(signals.os, "_exit", exits.append)
    return exits


def test_handlers_cover_sigint_sigterm_and_sighup_where_available(monkeypatch):
    handlers = captured_handlers(monkeypatch, FakeMotorDriver().stop, [])
    expected = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGHUP"):
        expected.add(signal.SIGHUP)
    assert set(handlers) == expected


def test_handler_stops_then_exits_without_raising(monkeypatch):
    output: list[str] = []
    driver = FakeMotorDriver()
    handlers = captured_handlers(monkeypatch, driver.stop, output)
    exits = fake_exit(monkeypatch)

    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert driver.calls == [("stop", ())]
    assert exits == [128 + signal.SIGTERM]
    assert "SIGTERM: stop sent" in output[-1]


def test_handler_stops_before_it_releases(monkeypatch):
    order: list[str] = []
    handlers = captured_handlers(
        monkeypatch, lambda: order.append("stop"), [], release=lambda: order.append("release")
    )
    exits = fake_exit(monkeypatch)

    handlers[signal.SIGINT](signal.SIGINT, None)
    assert order == ["stop", "release"]
    assert exits == [128 + signal.SIGINT]


def test_handler_ignores_further_signals_while_stopping(monkeypatch):
    installed: list[tuple[int, object]] = []
    monkeypatch.setattr(signals.signal, "signal", lambda sig, h: installed.append((sig, h)))
    monkeypatch.setattr(signals.os, "_exit", lambda code: None)
    signals.install_stop_handlers(FakeMotorDriver().stop, write=lambda m: None)
    handler = installed[0][1]
    installed.clear()

    handler(signal.SIGINT, None)  # type: ignore[operator]
    assert {sig for sig, _ in installed} == set(signals.STOP_SIGNALS)
    assert all(h is signal.SIG_IGN for _, h in installed)


def test_handler_still_exits_if_stop_fails(monkeypatch):
    output: list[str] = []

    def broken_stop() -> None:
        raise OSError("I2C bus gone")

    handlers = captured_handlers(monkeypatch, broken_stop, output)
    exits = fake_exit(monkeypatch)

    handlers[signal.SIGINT](signal.SIGINT, None)
    assert exits == [128 + signal.SIGINT]
    assert "FAILED" in output[-1] and "emergency_stop.py" in output[-1]


def test_handler_still_exits_if_release_fails(monkeypatch):
    driver = FakeMotorDriver()

    def broken_release() -> None:
        raise RuntimeError("camera gone")

    handlers = captured_handlers(monkeypatch, driver.stop, [], release=broken_release)
    exits = fake_exit(monkeypatch)

    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert driver.calls == [("stop", ())]
    assert exits == [128 + signal.SIGTERM]


def test_handler_still_exits_when_the_terminal_is_gone(monkeypatch):
    """After SIGHUP, writing to the closed terminal can raise EIO. The handler
    must still reach os._exit, or the loop would resume with signals ignored."""
    driver = FakeMotorDriver()

    def dead_terminal(message: str) -> None:
        raise OSError(5, "Input/output error")

    handlers: dict[int, object] = {}
    monkeypatch.setattr(signals.signal, "signal", lambda sig, h: handlers.__setitem__(sig, h))
    signals.install_stop_handlers(driver.stop, write=dead_terminal)
    exits = fake_exit(monkeypatch)

    sig = getattr(signal, "SIGHUP", signal.SIGTERM)
    handlers[sig](sig, None)  # type: ignore[operator]
    assert driver.calls == [("stop", ())]
    assert exits == [128 + sig]


def test_install_returns_previous_handlers_and_restore_puts_them_back():
    before = {sig: signal.getsignal(sig) for sig in signals.STOP_SIGNALS}
    previous = signals.install_stop_handlers(lambda: None, write=lambda m: None)
    try:
        assert previous == before
        assert all(signal.getsignal(sig) is not before[sig] for sig in signals.STOP_SIGNALS)
    finally:
        signals.restore_handlers(previous)
    assert {sig: signal.getsignal(sig) for sig in signals.STOP_SIGNALS} == before


def test_restore_turns_an_unknown_previous_handler_into_the_default(monkeypatch):
    installed: list[tuple[int, object]] = []
    monkeypatch.setattr(signals.signal, "signal", lambda sig, h: installed.append((sig, h)))
    signals.restore_handlers({signal.SIGTERM: None})
    assert installed == [(signal.SIGTERM, signal.SIG_DFL)]
