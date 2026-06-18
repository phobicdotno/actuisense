"""
Headless TUI tests via Textual's run_test() harness with a fake gateway — verifies
the table populates from the PGN db, RX/TX marks reflect the enabled sets, filtering
narrows rows, and toggling updates state + drives the gateway. No hardware, no async
test plugin (we drive the coroutine with asyncio.run).
"""

import asyncio

from actuisense import protocol as proto
from actuisense.device import Gateway, Transport
from actuisense.protocol import OperatingMode, Op, PgnList
from actuisense.tui import CHECK, UNCHECK, ActuiSenseApp

RESP_MODE_RXALL = bytes.fromhex(
    "10 02 a0 0e 11 01 0e 00 07 f9 03 00 00 00 00 00 02 00 2d 10 03".replace(" ", ""))


class FakeGateway:
    name = "fake-gw"

    def __init__(self):
        self.rx = {60928}
        self.tx = {127512, 127514, 127751}
        self.mode = OperatingMode.RX_ALL
        self.calls = []

    def get_operating_mode(self):
        return self.mode

    def get_pgn_list(self, which, scan_candidates=None, scan_progress=None):
        return sorted(self.tx if which == PgnList.TX else self.rx)

    def set_pgn(self, which, pgn, enable):
        self.calls.append((which, pgn, enable))

    def set_operating_mode(self, m):
        self.mode = m

    def activate(self):
        self.calls.append("activate")

    def commit_eeprom(self):
        self.calls.append("commit")

    def close(self):
        pass


def _run(scenario):
    return asyncio.run(scenario())


def test_connect_populates_enabled_sets():
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.tx_enabled == {127512, 127514, 127751}
            assert app.rx_enabled == {60928}
            assert app.mode == OperatingMode.RX_ALL
    _run(scenario)


def test_toggle_tx_updates_state_and_gateway():
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            # cursor defaults to row 0 = lowest PGN (59392)
            app.action_toggle_tx()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert 59392 in app.tx_enabled
            assert (PgnList.TX, 59392, True) in gw.calls
            assert app.dirty is True
    _run(scenario)


def test_filter_narrows_rows():
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.populate_table("ags")
            await pilot.pause()
            table = app.query_one("#table")
            assert table.row_count >= 2
            assert set(app._row_pgn.values()) >= {127512, 127514}
    _run(scenario)


class LoggingFakeTransport(Transport):
    """Replies to Get-Operating-Mode only; list queries time out (still logged)."""

    def __init__(self):
        self._buf = bytearray()

    def read(self, n=4096):
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def write(self, data):
        for f in proto.decode_all(data):
            if f.opcode == Op.OPERATING_MODE:
                self._buf += RESP_MODE_RXALL

    def close(self):
        pass

    @property
    def name(self):
        return "fakelog"


def test_activity_log_records_exchanges():
    async def scenario():
        gw = Gateway(LoggingFakeTransport(), response_window=0.05)
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            # connect issued: Get Operating Mode (OK) + Get RX/TX lists (Timeout)
            results = {e.result for e in gw.log_entries}
            assert "OK" in results
            assert any(e.action == "Get Operating Mode" for e in gw.log_entries)
            logt = app.query_one("#logtable")
            assert logt.row_count >= 1
    _run(scenario)


def test_commit_calls_gateway():
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app.action_commit()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "commit" in gw.calls
    _run(scenario)


def test_header_click_sorts_column_asc_then_desc():
    from rich.text import Text
    from textual.widgets import DataTable
    from textual.widgets._data_table import ColumnKey

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            ev = DataTable.HeaderSelected(table, ColumnKey("pgn"), 0, Text("PGN"))
            # first click -> ascending numeric
            app.on_data_table_header_selected(ev)
            await pilot.pause()
            asc = [int(table.get_row_at(i)[0]) for i in range(table.row_count)]
            assert asc == sorted(asc)
            # second click on the same header -> descending
            app.on_data_table_header_selected(ev)
            await pilot.pause()
            desc = [int(table.get_row_at(i)[0]) for i in range(table.row_count)]
            assert desc == sorted(desc, reverse=True)
    _run(scenario)


def test_connection_initial_kind_and_serial_detection():
    from actuisense.tui import ConnectionScreen
    assert ConnectionScreen()._looks_serial("/dev/ttyUSB0")
    assert ConnectionScreen()._looks_serial("COM5")
    assert not ConnectionScreen()._looks_serial("10.0.0.202")
    assert not ConnectionScreen()._looks_serial("tcp://host:60002")
    assert ConnectionScreen(current_target="tcp://10.0.0.5:60002")._initial_kind() == "tcp"
    assert ConnectionScreen(current_target="/dev/ttyUSB0")._initial_kind() == "serial"
    assert ConnectionScreen(current_target="10.0.0.202")._initial_kind() == "wago"
    assert ConnectionScreen()._initial_kind() == "serial"


def test_connection_type_switch_drops_mismatched_value():
    from actuisense.tui import ConnectionScreen
    from textual.widgets import Input

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            screen = ConnectionScreen(current_target="/dev/ttyUSB0")
            await app.push_screen(screen)
            await pilot.pause()
            target = screen.query_one("#conn-target", Input)
            assert target.value == "/dev/ttyUSB0"  # serial prefill shown
            screen._apply_type("tcp")              # switch to TCP gateway
            await pilot.pause()
            # the serial path must not linger in the TCP field -> grey placeholder shows
            assert target.value == ""
            screen._apply_type("serial")           # back to serial restores a port
            await pilot.pause()
            assert target.value == "/dev/ttyUSB0"
    _run(scenario)
