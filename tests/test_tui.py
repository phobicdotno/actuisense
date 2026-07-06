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

    def set_pgns_bulk(self, which, items):
        for pgn, enable in items:
            self.calls.append((which, pgn, enable))

    def set_operating_mode(self, m):
        self.mode = m

    def activate(self):
        self.calls.append("activate")

    def commit_eeprom(self):
        self.calls.append("commit")

    def push_firmware(self, data, filename, *, crc=None, progress=None, **kw):
        if progress is not None:
            progress(len(data) // 2, len(data))
            progress(len(data), len(data))
        self.calls.append(("fw", filename, len(data), crc))
        return crc if crc is not None else 0xDEADBEEF

    def get_product_info(self):
        return ["NGX-1: Dual Gateway [Core]", "x.xxx, 3.068", "NGX-1-USB [C]", "321326"]

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
            app._stop_gw_bus()  # the gateway N2K stream loops forever; stop it before waiting
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


def test_footer_shortcuts_follow_tab_and_connection():
    """check_action hides off-tab shortcuts, hides the Firmware jump on the Firmware
    tab itself, and hides all gateway actions while no gateway is connected."""
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tc = app.query_one("TabbedContent")
            # PGN Filter tab: list shortcuts shown, and 'u' jumps to Firmware
            assert app.check_action("toggle_rx", ())
            assert app.check_action("clear_shown", ())
            assert app.check_action("firmware", ())
            # Bus Monitor tab: list shortcuts hidden, filter + firmware shown
            tc.active = "bustab"
            await pilot.pause()
            assert not app.check_action("toggle_rx", ())
            assert not app.check_action("activate", ())
            assert app.check_action("focus_filter", ())
            assert app.check_action("firmware", ())
            # Firmware tab: the jump-to-Firmware shortcut is pointless here
            tc.active = "fwtab"
            await pilot.pause()
            assert not app.check_action("firmware", ())
            assert app.check_action("connection", ())
    _run(scenario)


def test_footer_hides_gateway_shortcuts_when_disconnected():
    async def scenario():
        app = ActuiSenseApp(None)  # starts disconnected (Connection dialog opens)
        async with app.run_test() as pilot:
            await pilot.pause()
            for action in ("toggle_rx", "activate", "commit", "cycle_mode",
                           "firmware", "toggle_poll"):
                assert not app.check_action(action, ())
            assert app.check_action("connection", ())
            assert app.check_action("quit", ())
    _run(scenario)


def test_clear_shown_disables_all_enabled_pgns():
    """Shift+C unconditionally clears RX+TX for the shown PGNs from any mixed state
    in one pass (no select-all-first toggle dance), and is a no-op when all clear."""
    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.rx_enabled and app.tx_enabled  # mixed state from the fake gw
            app.action_clear_shown()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.rx_enabled == set()
            assert app.tx_enabled == set()
            assert app.dirty is True
            assert (PgnList.RX, 60928, False) in gw.calls
            for pgn in (127512, 127514, 127751):
                assert (PgnList.TX, pgn, False) in gw.calls
            # nothing enabled -> a second press writes nothing more
            n_calls = len(gw.calls)
            app.action_clear_shown()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(gw.calls) == n_calls
    _run(scenario)


def test_activity_log_view_is_trimmed_to_cap():
    """The visible log table must stay at LOG_VIEW_MAX rows, dropping the oldest."""
    from actuisense.device import LogEntry
    from actuisense.tui import LOG_VIEW_MAX

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            extra = 25
            for i in range(1, LOG_VIEW_MAX + extra + 1):
                app._append_log(LogEntry(i, "00:00:00", "poll", "OK"))
            await pilot.pause()
            logt = app.query_one("#logtable")
            assert logt.row_count == LOG_VIEW_MAX
            # the oldest rows were the ones dropped
            assert int(logt.get_row_at(0)[0]) == extra + 1
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
    # Python 3.9: Textual widgets create asyncio primitives at construction, which
    # need a current event loop (and earlier asyncio.run() calls left none set).
    # Later Pythons construct them lazily, so this is a no-op there.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        assert ConnectionScreen()._looks_serial("/dev/ttyUSB0")
        assert ConnectionScreen()._looks_serial("COM5")
        assert not ConnectionScreen()._looks_serial("10.0.0.202")
        assert not ConnectionScreen()._looks_serial("tcp://host:60002")
        assert ConnectionScreen(current_target="tcp://10.0.0.5:60002")._initial_kind() == "tcp"
        assert ConnectionScreen(current_target="/dev/ttyUSB0")._initial_kind() == "serial"
        assert ConnectionScreen(current_target="10.0.0.202")._initial_kind() == "wago"
        assert ConnectionScreen()._initial_kind() == "serial"
    finally:
        asyncio.set_event_loop(None)
        loop.close()


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


def _bus_frame(pgn, src, data=b"\x01\x02"):
    from types import SimpleNamespace
    return SimpleNamespace(pgn=pgn, source=src, timestamp=12345.678, data=data)


def test_bus_monitor_filter_narrows_and_restores():
    from textual.widgets import DataTable

    async def scenario():
        app = ActuiSenseApp(FakeGateway())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            bt = app.query_one("#bustable", DataTable)
            for f in (_bus_frame(127488, 104), _bus_frame(127493, 104),
                      _bus_frame(65284, 5), _bus_frame(127488, 104)):
                app._bus_push(f)
            await pilot.pause()
            assert bt.row_count == 3  # three distinct pgn:src, last is a repeat
            app._apply_bus_filter("127488")
            await pilot.pause()
            assert bt.row_count == 1
            # a non-matching frame stays hidden; a matching one updates in place
            app._bus_push(_bus_frame(60928, 7))
            app._bus_push(_bus_frame(127488, 104))
            await pilot.pause()
            assert bt.row_count == 1
            app._apply_bus_filter("")
            await pilot.pause()
            assert bt.row_count == 4  # the hidden 60928:7 now appears too
    _run(scenario)


def test_footer_shortcuts_are_tab_aware():
    from textual.widgets import TabbedContent

    async def scenario():
        app = ActuiSenseApp(FakeGateway())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tc = app.query_one(TabbedContent)
            vis = lambda a: app.check_action(a, ())
            tc.active = "filtertab"
            await pilot.pause()
            assert vis("toggle_rx") is True and vis("commit") is True
            assert vis("quit") is True  # global
            tc.active = "bustab"
            await pilot.pause()
            # False (not None) so Textual drops them from the footer entirely
            assert vis("toggle_rx") is False and vis("commit") is False
            assert vis("focus_filter") is True  # bus monitor has a filter too
            tc.active = "logtab"
            await pilot.pause()
            assert vis("toggle_poll") is True and vis("toggle_rx") is False
    _run(scenario)


def test_tabs_follow_connection_mode():
    from textual.widgets import TabbedContent

    class _FakeBusSource:
        name = "can0@10.0.0.202"

        def frames(self):
            return iter([])

        def close(self):
            pass

    async def scenario():
        app = ActuiSenseApp(FakeGateway())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tc = app.query_one(TabbedContent)
            hidden = lambda tid: not tc.get_tab(tid).display
            # gateway connected -> all three tabs (Bus Monitor fed by the gateway stream)
            assert not hidden("bustab")
            assert not hidden("filtertab") and not hidden("logtab")
            assert tc.active == "filtertab"
            # switch to WAGO bus-monitor mode -> only Bus Monitor remains
            app._stop_bus()
            app.gw = None
            app._bus_source = _FakeBusSource()
            app._update_tabs()
            await pilot.pause()
            assert hidden("filtertab") and hidden("logtab")
            assert not hidden("bustab")
            assert tc.active == "bustab"
    _run(scenario)


def test_tui_save_then_load_roundtrip(tmp_path):
    from actuisense.protocol import PgnList
    path = str(tmp_path / "lists.txt")

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.rx_enabled = {60928, 59392}
            app.tx_enabled = {127245, 130306}
            app._do_save_lists(path)
            await pilot.pause()
            text = open(path, encoding="utf-8").read()
            assert "[RX]" in text and "60928" in text and "127245" in text
            # change state, then load the file back -> sets restored, gateway written
            app.rx_enabled = set()
            app.tx_enabled = set()
            gw.calls.clear()
            app._do_load_lists(path)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.rx_enabled == {60928, 59392}
            assert app.tx_enabled == {127245, 130306}
            assert app.dirty is True
            # the gateway actually received the enable writes from the load
            assert (PgnList.RX, 60928, True) in gw.calls
            assert (PgnList.TX, 127245, True) in gw.calls
    _run(scenario)


def test_bus_monitor_splits_rows_by_instance():
    from types import SimpleNamespace
    from textual.widgets import DataTable

    def f(pgn, src, inst):
        return SimpleNamespace(pgn=pgn, source=src, timestamp=1.0,
                               data=bytes([inst, 0, 0, 0, 0, 0, 0, 0]))

    async def scenario():
        app = ActuiSenseApp(FakeGateway())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            bt = app.query_one("#bustable", DataTable)
            # PGN 127488 from one source, four engine instances (2 motors + 2 gensets),
            # with instance 0 and 1 repeated.
            for inst in (0, 1, 2, 3, 0, 1):
                app._bus_push(f(127488, 104, inst))
            # 126992 System Time has no instance field -> one row regardless of byte 0
            app._bus_push(f(126992, 104, 0))
            app._bus_push(f(126992, 104, 9))
            await pilot.pause()
            assert bt.row_count == 5  # 4 engine instances + 1 collapsed System Time
            by_inst = {bt.get_row_at(i)[4]: bt.get_row_at(i) for i in range(bt.row_count)}
            assert set(by_inst) == {"0", "1", "2", "3", ""}
            assert by_inst["0"][5] == "2"  # instance 0 counted twice
            assert by_inst[""][5] == "2"   # System Time collapsed, counted twice
    _run(scenario)


def test_gateway_n2k_stream_feeds_bus_monitor():
    from actuisense.protocol import N2kMessage
    from textual.widgets import DataTable, TabbedContent

    class N2kGateway(FakeGateway):
        """A gateway that emits two engine frames (instances 0 and 1) once."""
        def __init__(self):
            super().__init__()
            self._msgs = [
                N2kMessage(priority=6, pgn=127488, dest=255, source=104,
                           timestamp=0, data=bytes([0])),
                N2kMessage(priority=6, pgn=127488, dest=255, source=104,
                           timestamp=0, data=bytes([1])),
            ]

        def read_n2k(self, window=0.2):
            out, self._msgs = self._msgs, []
            return out

    async def scenario():
        app = ActuiSenseApp(N2kGateway())
        async with app.run_test() as pilot:
            await pilot.pause()
            tc = app.query_one(TabbedContent)
            assert tc.get_tab("bustab").display  # Bus Monitor visible on a gateway
            bt = app.query_one("#bustable", DataTable)
            # the reader auto-started on mount; wait for it to push, then stop it
            for _ in range(50):
                await pilot.pause()
                if bt.row_count >= 2:
                    break
            app._stop_gw_bus()
            await pilot.pause()
            assert bt.row_count == 2  # two engine instances split into two rows
    _run(scenario)


def test_firmware_tab_flashes_via_worker(tmp_path):
    from textual.widgets import Input, ProgressBar, TabbedContent

    async def scenario():
        zip_path = tmp_path / "NGX-1-Release-vX.zip"
        zip_path.write_bytes(b"PK\x03\x04" + bytes(496))  # 500 bytes total
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            # Firmware tab is present and selectable when a gateway is connected
            tc = app.query_one(TabbedContent)
            app.action_firmware()
            await pilot.pause()
            assert tc.active == "fwtab"
            # drive the flash through the worker
            app.query_one("#fw-path", Input).value = str(zip_path)
            app.query_one("#fw-crc", Input).value = "0xC2340641"
            app._start_flash()
            await app.workers.wait_for_complete()
            await pilot.pause()
            fw = [c for c in gw.calls if isinstance(c, tuple) and c and c[0] == "fw"]
            assert fw, "push_firmware was not called"
            assert fw[0][1] == zip_path.name        # filename basename
            assert fw[0][2] == 500                   # size streamed
            assert fw[0][3] == 0xC2340641            # crc override passed through
            assert app.poll_paused is False          # polling restored after the transfer
            assert app.query_one("#fw-progress", ProgressBar).total == 500
    _run(scenario)


def test_firmware_tab_reads_current_fw_on_connect():
    from textual.widgets import Static

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            cur = app.query_one("#fw-current", Static)
            assert "3.068" in str(cur.render())   # firmware version shown
    _run(scenario)


def test_firmware_flash_blocked_on_wrong_baud(tmp_path):
    """Pre-flight guard: a serial link not at FW_BAUD blocks the flash outright."""
    from textual.widgets import Input, Static

    async def scenario():
        zip_path = tmp_path / "NGX-1-Release-vX.zip"
        zip_path.write_bytes(bytes(500))
        gw = FakeGateway()
        gw.baud = 38400                     # drifted link
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.action_firmware()
            await pilot.pause()
            app.query_one("#fw-path", Input).value = str(zip_path)
            app.query_one("#fw-crc", Input).value = "0xC2340641"
            app._start_flash()
            await app.workers.wait_for_complete()
            await pilot.pause()
            fw = [c for c in gw.calls if isinstance(c, tuple) and c and c[0] == "fw"]
            assert not fw, "flash must be blocked at the wrong baud"
            status = str(app.query_one("#fw-status", Static).render())
            assert "38400" in status and "115200" in status
    _run(scenario)


def test_subtitle_shows_mode_and_baud():
    async def scenario():
        gw = FakeGateway()
        gw.baud = 115200
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.render_status()
            assert "MODE: RX_ALL" in app.sub_title
            assert "115200 baud" in app.sub_title
    _run(scenario)


def test_subtitle_omits_baud_without_serial_link():
    async def scenario():
        gw = FakeGateway()                  # no .baud attr (TCP/mock)
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.render_status()
            assert "MODE: RX_ALL" in app.sub_title
            assert "baud" not in app.sub_title
    _run(scenario)


def test_busload_meter():
    from actuisense.tui import _BusLoad
    m = _BusLoad(window=3.0)
    assert m.load() == 0.0
    for _ in range(100):       # 100 single-frame (8-byte) messages
        m.add(8)
    assert 0 < m.load() <= 100
    # a fast-packet message (28 bytes) counts as more than one CAN frame
    m2 = _BusLoad()
    m2.add(28)
    assert m2._ev[0][1] > _BusLoad.BITS_PER_FRAME


def test_status_line_shows_bus_load():
    from textual.widgets import Label

    async def scenario():
        gw = FakeGateway()
        app = ActuiSenseApp(gw)
        async with app.run_test() as pilot:
            app._stop_gw_bus()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.render_status()
            await pilot.pause()
            assert "N2K bus" in str(app.query_one("#status", Label).render())
    _run(scenario)
