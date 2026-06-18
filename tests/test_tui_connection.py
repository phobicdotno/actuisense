"""
TUI connection-dialog dispatch + WAGO/can0 bus-monitor wiring, driven headlessly.
A fake CandumpSource (fixed line list, monkeypatched over_ssh) stands in for SSH,
so no PLC or paramiko is needed.
"""

import asyncio

from actuisense.protocol import OperatingMode, PgnList
from actuisense.tui import ActuiSenseApp, ConnectionScreen
from actuisense.wago import CandumpSource


class FakeGateway:
    name = "fake-gw"

    def __init__(self):
        self.rx = {60928}
        self.tx = {127512}
        self.mode = OperatingMode.RX_ALL

    def get_operating_mode(self):
        return self.mode

    def get_pgn_list(self, which):
        return sorted(self.tx if which == PgnList.TX else self.rx)

    def set_log_callback(self, cb):
        pass

    def close(self):
        pass


def _run(scenario):
    return asyncio.run(scenario())


def test_disconnected_app_opens_connection_dialog():
    async def scenario():
        app = ActuiSenseApp(None)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ConnectionScreen)
            app.screen.dismiss(None)  # close so the harness tears down cleanly
            await pilot.pause()
    _run(scenario)


def test_on_connection_chosen_routes_by_kind():
    app = ActuiSenseApp(FakeGateway())
    calls = {}
    app.start_bus = lambda *a, **k: calls.__setitem__("bus", (a, k))   # type: ignore[assignment]
    app.start_gateway = lambda spec: calls.__setitem__("gw", spec)     # type: ignore[assignment]
    app._on_connection_chosen({"kind": "wago", "host": "h", "username": "root",
                               "password": "pw", "iface": "can0"})
    app._on_connection_chosen({"kind": "serial", "target": "COM5", "baud": 115200})
    app._on_connection_chosen(None)  # cancel — no-op
    assert calls["gw"] == {"kind": "serial", "target": "COM5", "baud": 115200}
    assert calls["bus"][0] == ("h", "root", "pw", "can0")


def test_bus_monitor_aggregates_frames(monkeypatch):
    lines = [
        "(1.000001) can0 19F21803#FFFF7F2701FF0000",  # PGN 127512 src 3
        "(1.000002) can0 19F21803#0102030405060708",  # same key -> count 2
        "(1.000003) can0 19F30703#0102030405060708",  # PGN 127751 src 3
    ]
    monkeypatch.setattr(
        CandumpSource, "over_ssh",
        classmethod(lambda cls, **kw: cls(lines=iter(lines), name="root@h:can0")))

    async def scenario():
        app = ActuiSenseApp(FakeGateway())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app.start_bus("h", "root", "pw", "can0")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#bustable")
            assert table.row_count == 2          # two distinct (pgn, src) rows
            assert app._bus_rows["127512:3"] == 2
            assert app._bus_rows["127751:3"] == 1
    _run(scenario)


def test_actions_safe_without_gateway():
    # gw=None: gateway-only actions must no-op (notify) rather than crash.
    async def scenario():
        app = ActuiSenseApp(None)
        async with app.run_test() as pilot:
            await pilot.pause()
            if isinstance(app.screen, ConnectionScreen):
                app.screen.dismiss(None)
                await pilot.pause()
            app.action_toggle_tx()
            app.action_activate()
            app.action_commit()
            app.action_cycle_mode()
            await pilot.pause()
            assert app.gw is None  # still disconnected, no exceptions raised
    _run(scenario)


def test_serial_ports_real_device_first(monkeypatch):
    """Ports with a real device (a connected gateway) sort above empty/'n/a' ones."""
    from actuisense import tui

    class _P:
        def __init__(self, dev, desc):
            self.device, self.description = dev, desc

    fake = [_P("/dev/ttyS8", "n/a"), _P("/dev/ttyS0", "n/a"),
            _P("/dev/ttyUSB0", "NGX-1"), _P("/dev/ttyS1", "")]
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: fake)
    ports = tui.list_serial_ports()
    assert ports[0] == ("/dev/ttyUSB0", "NGX-1")            # real device on top
    assert [d for d, _ in ports[1:]] == ["/dev/ttyS0", "/dev/ttyS1", "/dev/ttyS8"]  # rest sorted
