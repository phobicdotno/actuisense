"""
Full-screen terminal UI (Textual) — the cross-platform equivalent of Actisense NMEA
Reader's Hardware Configuration page, with three tabs:

  • PGN Filter   — a scrollable table of every PGN with toggleable RX/TX enable cells,
                   plus operating-mode / activate / commit actions.
  • Activity Log — a running log of every gateway exchange (line, time, action,
                   result OK/Timeout/NAK, detail), like NMEA Reader's command log,
                   fed by a periodic Get-Operating-Mode poll plus your own actions.
  • Bus Monitor  — live raw NMEA 2000 traffic read straight off a WAGO PLC's can0
                   interface over SSH (candump), aggregated per PGN/source.

A Connection dialog (Ctrl+O) picks the source: a serial port + baud, a TCP gateway,
or a WAGO PLC (username/password → can0). The app can start disconnected and prompt
for a connection, so no port has to be known up front.

Serial/TCP/SSH I/O blocks, so every gateway call and the bus reader run in Textual
thread workers; the UI thread only renders. The app is constructed with an optional
gateway object, which lets it be driven headlessly in tests with a fake gateway.
"""

from __future__ import annotations

from typing import Optional, Set

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label,
                             Select, Static, TabbedContent, TabPane)

from . import __version__
from .pgndb import PgnDb
from .protocol import OperatingMode, PgnList

CHECK = "[X]"
UNCHECK = "[ ]"
POLL_INTERVAL = 2.0          # seconds between Get-Operating-Mode heartbeats
LOG_VIEW_MAX = 500           # max rows kept in the visible log table
BUS_VIEW_MAX = 400           # max distinct PGN/source rows in the bus monitor

_RESULT_STYLE = {"OK": "green", "Timeout": "yellow", "NAK": "red bold", "Error": "red bold"}

# Serial speeds offered in the Connection dialog (NGT-1 is 115200; others vary).
BAUD_RATES = (4800, 9600, 19200, 38400, 57600, 115200, 230400)


def list_serial_ports():
    """Return ``[(device, description)]`` for every serial port, or ``[]``.

    Best-effort: pyserial is a hard dependency, but a bare/headless host may have
    no ports (or the import may fail), so failures degrade to an empty list.
    """
    try:
        from serial.tools import list_ports
    except Exception:  # pragma: no cover — pyserial missing
        return []
    ports = [(p.device, p.description or "") for p in list_ports.comports()]
    # Sort ports that report a real device (a connected gateway, e.g. "NGX-1") to
    # the top; the empty / "n/a" legacy ports (ttyS0..ttySN) sink to the bottom.
    # Stable within each group, then by device name.
    def _has_device(desc: str) -> bool:
        d = desc.strip().lower()
        return bool(d) and d != "n/a"
    ports.sort(key=lambda dd: (not _has_device(dd[1]), dd[0]))
    return ports


class ConnectionScreen(ModalScreen):
    """Pick a connection: a serial port + baud, a TCP gateway, or a WAGO PLC (can0).

    Dismisses with a ``spec`` dict ``{"kind": "serial"|"tcp"|"wago", ...}`` on
    Connect, or ``None`` on Cancel.
    """

    CSS = """
    ConnectionScreen { align: center middle; }
    #conn-dialog {
        width: 76; height: auto; max-height: 90%; padding: 1 2;
        border: round $accent; background: $surface;
    }
    .conn-group { height: auto; }
    #conn-title { text-style: bold; margin-bottom: 1; }
    .conn-label { color: $accent; margin-top: 1; }
    #conn-buttons { height: auto; margin-top: 1; }
    #conn-dialog Button { margin: 0 1 0 0; }
    #conn-result { margin-top: 1; height: auto; min-height: 1; }
    Select, Input { margin-bottom: 0; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_target: Optional[str] = None,
                 current_baud: Optional[int] = None) -> None:
        super().__init__()
        self._current_target = current_target
        self._current_baud = current_baud if current_baud in BAUD_RATES else 115200
        self._first_real = None  # first detected serial port with a real device

    def compose(self) -> ComposeResult:
        ports = list_serial_ports()
        detected = [("%s  %s" % (dev, desc)).rstrip() for dev, desc in ports]
        detected_opts = [(label, dev) for label, (dev, _d) in zip(detected, ports)]
        # list_serial_ports() puts ports with a real device first, so the first one
        # (if any) is the connected gateway -- pre-fill the target with it.
        first_real = next((dev for dev, desc in ports
                           if desc.strip() and desc.strip().lower() != "n/a"), None)
        self._first_real = first_real
        with VerticalScroll(id="conn-dialog"):
            yield Static("Connection", id="conn-title")

            yield Static("Type", classes="conn-label")
            yield Select(
                [("Serial port", "serial"), ("TCP gateway", "tcp"),
                 ("WAGO PLC (can0)", "wago")],
                value=self._initial_kind(), allow_blank=False, id="conn-type")

            # Serial-only: detected ports list.
            with Vertical(id="conn-serial-group", classes="conn-group"):
                yield Static("Detected serial ports", classes="conn-label")
                yield Select(detected_opts, prompt="(none — type a port/host below)",
                             id="conn-detected")

            yield Static("Port / host", classes="conn-label", id="conn-target-label")
            yield Input(
                value=self._current_target or first_real or "",
                placeholder="/dev/ttyUSB0  •  tcp://host:60002  •  10.0.0.202",
                id="conn-target")

            # Serial-only: baud rate.
            with Vertical(id="conn-baud-group", classes="conn-group"):
                yield Static("Speed (baud)", classes="conn-label")
                yield Select([(str(b), b) for b in BAUD_RATES],
                             value=self._current_baud, allow_blank=False, id="conn-baud")

            # WAGO-only: SSH login (stacked so every field is visible).
            with Vertical(id="conn-wago-group", classes="conn-group"):
                yield Static("WAGO PLC login (can0 only)", classes="conn-label")
                yield Input(placeholder="username (e.g. root)", id="conn-user")
                yield Input(placeholder="password (e.g. wago)", password=True, id="conn-pass")
                yield Input(value="can0", placeholder="iface (e.g. can0)", id="conn-iface")

            with Horizontal(id="conn-buttons"):
                yield Button("Connect", id="conn-connect", variant="success")
                yield Button("Cancel", id="conn-cancel")
            yield Static("", id="conn-result", markup=False)

    def on_mount(self) -> None:
        self._apply_type(str(self.query_one("#conn-type", Select).value))

    def _apply_type(self, kind: str) -> None:
        """Show only the fields relevant to the selected connection Type, and match
        the Port/host label + placeholder to it."""
        self.query_one("#conn-serial-group").display = (kind == "serial")
        self.query_one("#conn-baud-group").display = (kind == "serial")
        self.query_one("#conn-wago-group").display = (kind == "wago")
        label = {"serial": "Serial port", "tcp": "Host (tcp://host:port or host)",
                 "wago": "PLC host / IP"}.get(kind, "Port / host")
        self.query_one("#conn-target-label", Static).update(label)
        placeholder = {"serial": "/dev/ttyUSB0   •   COM5",
                       "tcp": "tcp://host:60002   •   host:port",
                       "wago": "10.0.0.202   (PLC IP)"}.get(kind, "/dev/ttyUSB0")
        target = self.query_one("#conn-target", Input)
        target.placeholder = placeholder
        # Don't let a value meant for one type linger in another (e.g. a serial path
        # showing in the TCP field). Keep the current value only if it fits the new
        # type, else fall back to the remembered last target, else clear it so the
        # grey placeholder suggestion shows.
        target.value = self._value_for_kind(kind)

    def _initial_kind(self) -> str:
        """Default the Type selector to the last connection's kind, so its address is
        shown on open. last_target is distinguishable: tcp -> 'tcp://...', serial ->
        a device path, wago -> a bare host/IP."""
        rem = (self._current_target or "").strip()
        if rem.startswith("tcp://"):
            return "tcp"
        if self._looks_serial(rem):
            return "serial"
        if rem:
            return "wago"  # a remembered bare host/IP only comes from a WAGO connect
        return "serial"

    @staticmethod
    def _looks_serial(s: str) -> bool:
        s = s.strip().lower()
        return s.startswith("/dev/") or (s.startswith("com") and s[3:].isdigit())

    def _value_for_kind(self, kind: str) -> str:
        cur = self.query_one("#conn-target", Input).value.strip()
        remembered = (self._current_target or "").strip()
        if kind == "serial":
            if self._looks_serial(cur):
                return cur
            if self._looks_serial(remembered):
                return remembered
            return self._first_real or ""
        # tcp / wago want a host or IP, never a serial device path.
        if cur and not self._looks_serial(cur):
            return cur
        if remembered and not self._looks_serial(remembered):
            return remembered
        return ""

    def _set_result(self, text: str) -> None:
        self.query_one("#conn-result", Static).update(text)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "conn-detected" and event.value is not Select.BLANK:
            # Picking a detected port fills the target field.
            self.query_one("#conn-target", Input).value = str(event.value)
        elif event.select.id == "conn-type":
            self._apply_type(str(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "conn-cancel":
            self.action_cancel()
        elif event.button.id == "conn-connect":
            self._connect()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _value(self, wid: str) -> str:
        return self.query_one(wid, Input).value.strip()

    def _connect(self) -> None:
        kind = self.query_one("#conn-type", Select).value
        target = self._value("#conn-target")
        if kind == "wago":
            host = target
            user = self._value("#conn-user")
            password = self.query_one("#conn-pass", Input).value  # keep spaces
            iface = self._value("#conn-iface") or "can0"
            if not host or not user:
                self._set_result("WAGO needs a host and a username.")
                return
            self.dismiss({"kind": "wago", "host": host, "username": user,
                          "password": password, "iface": iface})
            return
        if not target:
            self._set_result("Enter a serial port or host.")
            return
        if kind == "tcp":
            spec = target if target.startswith("tcp://") else "tcp://" + target
            self.dismiss({"kind": "tcp", "target": spec})
            return
        baud = int(self.query_one("#conn-baud", Select).value)
        self.dismiss({"kind": "serial", "target": target, "baud": baud})


class FilenameScreen(ModalScreen):
    """Prompt for a file path. Dismisses with the path string, or None on cancel."""

    CSS = """
    FilenameScreen { align: center middle; }
    #fn-dialog { width: 72; height: auto; padding: 1 2; border: round $accent; background: $surface; }
    #fn-title { text-style: bold; margin-bottom: 1; }
    #fn-buttons { height: auto; margin-top: 1; }
    #fn-dialog Button { margin: 0 1 0 0; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, default: str = "") -> None:
        super().__init__()
        self._title = title
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="fn-dialog"):
            yield Static(self._title, id="fn-title")
            yield Input(value=self._default, placeholder="path/to/lists.txt", id="fn-input")
            with Horizontal(id="fn-buttons"):
                yield Button("OK", id="fn-ok", variant="success")
                yield Button("Cancel", id="fn-cancel")

    def on_mount(self) -> None:
        self.query_one("#fn-input", Input).focus()

    def _submit(self) -> None:
        self.dismiss(self.query_one("#fn-input", Input).value.strip() or None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit() if event.button.id == "fn-ok" else self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ActuiSenseApp(App):
    TITLE = "AcTuiSense"
    SUB_TITLE = "v%s   •   2026 © Karstein Kvistad" % __version__
    CSS = """
    #status { height: 1; padding: 0 1; background: $boost; color: $text; }
    #filterbar, #busfilterbar { height: 3; }
    #filter, #busfilter { width: 1fr; }
    DataTable { height: 1fr; }
    #actions, #logactions { height: 3; align: left middle; }
    #actions Button, #logactions Button { margin: 0 1 0 0; }
    """

    BINDINGS = [
        Binding("r", "toggle_rx", "RX"),
        Binding("t", "toggle_tx", "TX"),
        Binding("b", "toggle_both", "Both"),
        Binding("R", "select_all_rx", "All RX"),    # Shift+R: select/clear all (shown) RX
        Binding("T", "select_all_tx", "All TX"),    # Shift+T: select/clear all (shown) TX
        Binding("B", "select_all_both", "All Both"),  # Shift+B: select/clear all (shown) RX+TX
        Binding("a", "activate", "Activate"),
        Binding("c", "commit", "Commit EEPROM"),
        Binding("s", "save_lists", "Save"),
        Binding("l", "load_lists", "Load"),
        Binding("f5", "reload", "Reload"),
        Binding("m", "cycle_mode", "Mode"),
        Binding("p", "toggle_poll", "Pause poll"),
        Binding("ctrl+o", "connection", "Connection"),
        Binding("ctrl+f", "focus_filter", "Filter"),
        Binding("q", "quit", "Quit"),
    ]

    # Which tab(s) each action is useful on; actions not listed are global (shown
    # everywhere). Drives check_action() so the Footer only shows relevant shortcuts.
    _TAB_ACTIONS = {
        "toggle_rx": {"filtertab"}, "toggle_tx": {"filtertab"},
        "toggle_both": {"filtertab"}, "select_all_rx": {"filtertab"},
        "select_all_tx": {"filtertab"}, "select_all_both": {"filtertab"},
        "activate": {"filtertab"}, "commit": {"filtertab"},
        "save_lists": {"filtertab"}, "load_lists": {"filtertab"},
        "cycle_mode": {"filtertab"}, "reload": {"filtertab"},
        "focus_filter": {"filtertab", "bustab"},
        "toggle_poll": {"filtertab", "logtab"},
    }

    def __init__(self, gateway=None, db: Optional[PgnDb] = None):
        super().__init__()
        self.gw = gateway
        self.db = db or PgnDb()
        self.rx_enabled: Set[int] = set()
        self.tx_enabled: Set[int] = set()
        self.mode: Optional[OperatingMode] = None
        self.dirty = False
        self.poll_paused = False
        self._polling = False
        self._row_pgn = {}
        self._log_rows = 0
        self._sort_state = {}  # table id -> (column_key, reverse) for header-click sort
        # Bus monitor (WAGO/can0) state.
        self._bus_source = None
        self._bus_rows = {}   # key "pgn:src" -> running count
        self._bus_data = {}   # key -> (ts, pgn, name, src, cnt, hexdata) for repopulation
        self._bus_shown = set()  # keys currently displayed (after the bus filter)
        self._bus_filter = ""
        self.last_target: Optional[str] = None
        self.last_baud: Optional[int] = None

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("connecting…", id="status")
        with TabbedContent(initial="filtertab"):
            with TabPane("PGN Filter", id="filtertab"):
                with Horizontal(id="filterbar"):
                    yield Input(placeholder="filter PGNs (number or name)…", id="filter")
                table = DataTable(id="table", cursor_type="row", zebra_stripes=True)
                table.add_column("PGN", key="pgn", width=8)
                table.add_column("Name", key="name")
                table.add_column("RX", key="rx", width=5)
                table.add_column("TX", key="tx", width=5)
                yield table
                with Horizontal(id="actions"):
                    yield Button("Activate (a)", id="activate", variant="primary")
                    yield Button("Commit → EEPROM (c)", id="commit", variant="warning")
                    yield Button("Save (s)", id="save")
                    yield Button("Load (l)", id="load")
                    yield Button("Reload (F5)", id="reload")
                    yield Button("Mode (m)", id="mode")
                    yield Button("Connection (^O)", id="connect")
            with TabPane("Bus Monitor", id="bustab"):
                with Horizontal(id="busfilterbar"):
                    yield Input(placeholder="filter PGNs (number or name)…", id="busfilter")
                bust = DataTable(id="bustable", cursor_type="row", zebra_stripes=True)
                bust.add_column("Time", key="time", width=12)
                bust.add_column("PGN", key="pgn", width=8)
                bust.add_column("Name", key="name", width=34)
                bust.add_column("Src", key="src", width=5)
                bust.add_column("Cnt", key="cnt", width=7)
                bust.add_column("Data (hex)", key="data")
                yield bust
            with TabPane("Activity Log", id="logtab"):
                logt = DataTable(id="logtable", cursor_type="row", zebra_stripes=True)
                logt.add_column("Li…", key="seq", width=6)
                logt.add_column("Time", key="time", width=10)
                logt.add_column("Action", key="action", width=34)
                logt.add_column("Result", key="result", width=10)
                logt.add_column("Detail", key="detail")
                yield logt
                with Horizontal(id="logactions"):
                    yield Button("Pause polling (p)", id="poll")
                    yield Button("Clear log", id="clearlog")
        yield Footer()

    def on_mount(self) -> None:
        if self.gw is not None and hasattr(self.gw, "set_log_callback"):
            self.gw.set_log_callback(self._on_gw_log)
        self.populate_table("")
        self.set_interval(POLL_INTERVAL, self.poll)
        self._update_tabs()
        if self.gw is not None:
            self.connect()
        else:
            self.set_status("not connected — press Ctrl+O to choose a connection")
            self.action_connection()

    def on_unmount(self) -> None:
        self._stop_bus()

    # -- tab-aware shortcuts ------------------------------------------------

    def _active_tab(self) -> str:
        try:
            return str(self.query_one(TabbedContent).active)
        except Exception:
            return "filtertab"

    def check_action(self, action: str, parameters):
        """Hide (and disable) bindings that aren't useful on the current tab, so the
        Footer only lists the shortcuts relevant to what's open."""
        tabs = self._TAB_ACTIONS.get(action)
        if tabs is None:
            return True  # global binding (connection, quit, palette)
        return True if self._active_tab() in tabs else None

    def on_tabbed_content_tab_activated(self, event) -> None:
        self.refresh_bindings()

    def _update_tabs(self) -> None:
        """Show only the tabs that apply to the current connection. WAGO bus-monitor
        mode (no Actisense gateway) hides the gateway-only PGN Filter and Activity Log
        tabs; a gateway connection hides the WAGO-only Bus Monitor; with nothing
        connected, all tabs are shown so a connection can be chosen."""
        try:
            tc = self.query_one(TabbedContent)
        except Exception:
            return
        bus = self._bus_source is not None
        gw = self.gw is not None
        if bus and not gw:           # WAGO bus monitor only
            tc.show_tab("bustab")
            tc.hide_tab("filtertab")
            tc.hide_tab("logtab")
            tc.active = "bustab"
        elif gw:                     # Actisense gateway
            tc.show_tab("filtertab")
            tc.show_tab("logtab")
            tc.hide_tab("bustab")
            if tc.active == "bustab":
                tc.active = "filtertab"
        else:                        # nothing connected yet
            tc.show_tab("filtertab")
            tc.show_tab("bustab")
            tc.show_tab("logtab")
        self.refresh_bindings()

    # -- PGN table ----------------------------------------------------------

    def populate_table(self, flt: str) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        self._row_pgn.clear()
        for info in self.db.search(flt):
            key = str(info.pgn)
            self._row_pgn[key] = info.pgn
            table.add_row(
                str(info.pgn), info.name,
                CHECK if info.pgn in self.rx_enabled else UNCHECK,
                CHECK if info.pgn in self.tx_enabled else UNCHECK,
                key=key,
            )

    def refresh_marks(self) -> None:
        table = self.query_one("#table", DataTable)
        for key, pgn in self._row_pgn.items():
            table.update_cell(key, "rx", CHECK if pgn in self.rx_enabled else UNCHECK)
            table.update_cell(key, "tx", CHECK if pgn in self.tx_enabled else UNCHECK)

    # -- column sorting -----------------------------------------------------

    @staticmethod
    def _sort_key(value):
        """Sort numerically when the whole cell parses as a number, else by text.

        Cells hold plain strings or Rich ``Text`` (e.g. coloured log results); ``str``
        flattens both. Columns are homogeneous (PGN/Src/Cnt/Time always numeric, names
        always text), so a column never mixes the two key types in one sort."""
        s = str(value).strip()
        try:
            return (0, float(s))
        except ValueError:
            return (1, s.lower())

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Click a column header to sort by it; click the same header to flip asc/desc."""
        table = event.data_table
        col = event.column_key
        prev_col, prev_rev = self._sort_state.get(table.id, (None, False))
        reverse = (not prev_rev) if col == prev_col else False
        self._sort_state[table.id] = (col, reverse)
        table.sort(col, key=self._sort_key, reverse=reverse)

    # -- status & log -------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.query_one("#status", Label).update(text)

    def render_status(self) -> None:
        if self.gw is None:
            bus = self._bus_source.name if self._bus_source is not None else None
            self.set_status("bus monitor: %s" % bus if bus else
                            "not connected — press Ctrl+O")
            return
        mode = self.mode.name if self.mode else "?"
        flags = ("  ●UNSAVED" if self.dirty else "") + ("  ‖poll paused" if self.poll_paused else "")
        self.set_status("%s   mode=%s   RX:%d  TX:%d%s"
                        % (self.gw.name, mode, len(self.rx_enabled), len(self.tx_enabled), flags))

    def _on_gw_log(self, entry) -> None:
        # called from a worker thread -> marshal to the UI thread
        self.call_from_thread(self._append_log, entry)

    def _append_log(self, entry) -> None:
        try:
            table = self.query_one("#logtable", DataTable)
        except Exception:
            return
        style = _RESULT_STYLE.get(entry.result, "")
        table.add_row(str(entry.seq), entry.time, entry.action,
                      Text(entry.result, style=style), entry.detail)
        self._log_rows += 1
        if self._log_rows > LOG_VIEW_MAX:
            try:
                table.remove_row(table.get_row_at(0))
            except Exception:
                pass
            else:
                self._log_rows -= 1
        try:
            table.scroll_end(animate=False)
        except Exception:
            pass

    # -- workers (threaded gateway I/O) ------------------------------------

    @work(exclusive=True, thread=True)
    def connect(self) -> None:
        if self.gw is None:
            return
        self.call_from_thread(self.set_status, "reading gateway…")
        try:
            mode = self.gw.get_operating_mode()
            cands = [i.pgn for i in self.db.all()]

            def _prog(done: int, total: int) -> None:
                self.call_from_thread(self.set_status, "scanning PGNs %d/%d…" % (done, total))

            tx = set(self.gw.get_pgn_list(PgnList.TX, scan_candidates=cands, scan_progress=_prog))
            rx = set(self.gw.get_pgn_list(PgnList.RX, scan_candidates=cands, scan_progress=_prog))
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, "ERROR: %s" % e)
            return
        self.mode, self.rx_enabled, self.tx_enabled = mode, rx, tx
        self.dirty = False
        self.call_from_thread(self.refresh_marks)
        self.call_from_thread(self.render_status)

    @work(group="poll", thread=True)
    def poll(self) -> None:
        # re-entrancy guard instead of exclusive-cancel: skip if a poll is in flight,
        # so we never cancel a worker mid serial-read.
        if self.gw is None or self.poll_paused or self._polling:
            return
        self._polling = True
        try:
            m = self.gw.get_operating_mode()
            if m is not None:
                self.mode = m
            self.call_from_thread(self.render_status)
        except Exception:
            pass
        finally:
            self._polling = False

    @work(thread=True)
    def push_pgn(self, which: PgnList, pgn: int, enable: bool) -> None:
        try:
            self.gw.set_pgn(which, pgn, enable)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, "set_pgn failed: %s" % e, severity="error")

    @work(exclusive=True, thread=True)
    def do_activate(self) -> None:
        try:
            self.gw.activate()
            self.call_from_thread(self.notify, "Enable lists activated.")
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, "activate failed: %s" % e, severity="error")

    @work(exclusive=True, thread=True)
    def do_commit(self) -> None:
        try:
            self.gw.activate()
            self.gw.commit_eeprom()
            self.dirty = False
            self.call_from_thread(self.render_status)
            self.call_from_thread(self.notify, "Committed to EEPROM.")
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, "commit failed: %s" % e, severity="error")

    @work(thread=True)
    def do_set_mode(self, mode: OperatingMode) -> None:
        try:
            self.gw.set_operating_mode(mode)
            self.mode = mode
            self.dirty = True
            self.call_from_thread(self.render_status)
            self.call_from_thread(self.notify, "Operating mode -> %s" % mode.name)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, "mode change failed: %s" % e, severity="error")

    # -- bus monitor (WAGO / can0) -----------------------------------------

    @work(group="bus", thread=True)
    def run_bus_monitor(self) -> None:
        source = self._bus_source
        if source is None:
            return
        try:
            for frame in source.frames():
                self.call_from_thread(self._bus_push, frame)
        except Exception as e:  # noqa: BLE001 — surface SSH/stream errors, then stop
            self.call_from_thread(self.notify, "bus monitor stopped: %s" % e, severity="error")
            self.call_from_thread(self.render_status)

    def _bus_push(self, frame) -> None:
        try:
            table = self.query_one("#bustable", DataTable)
        except Exception:
            return
        key = "%d:%d" % (frame.pgn, frame.source)
        ts = "%.3f" % (frame.timestamp % 100000)
        name = self.db.name(frame.pgn)
        hexdata = frame.data.hex(" ")
        if key in self._bus_rows:
            cnt = self._bus_rows[key] + 1
        else:
            if len(self._bus_rows) >= BUS_VIEW_MAX:
                return  # cap distinct rows; ignore further new PGN/source pairs
            cnt = 1
        self._bus_rows[key] = cnt
        self._bus_data[key] = (ts, str(frame.pgn), name, str(frame.source), str(cnt), hexdata)
        self._bus_render_row(table, key)

    def _bus_match(self, key: str) -> bool:
        """A bus row matches if the filter is empty, or appears in its PGN or name."""
        f = self._bus_filter.strip().lower()
        if not f:
            return True
        _ts, pgn, name, _src, _cnt, _data = self._bus_data[key]
        return f in pgn or f in name.lower()

    def _bus_render_row(self, table: DataTable, key: str) -> None:
        """Add/update/remove a single bus row so the table reflects the active filter."""
        if self._bus_match(key):
            row = self._bus_data[key]
            if key in self._bus_shown:
                table.update_cell(key, "time", row[0])
                table.update_cell(key, "cnt", row[4])
                table.update_cell(key, "data", row[5])
            else:
                table.add_row(*row, key=key)
                self._bus_shown.add(key)
        elif key in self._bus_shown:
            try:
                table.remove_row(key)
            except Exception:
                pass
            self._bus_shown.discard(key)

    def _apply_bus_filter(self, flt: str) -> None:
        self._bus_filter = flt
        try:
            table = self.query_one("#bustable", DataTable)
        except Exception:
            return
        table.clear()
        self._bus_shown.clear()
        for key in self._bus_data:
            if self._bus_match(key):
                table.add_row(*self._bus_data[key], key=key)
                self._bus_shown.add(key)

    def _stop_bus(self) -> None:
        if self._bus_source is not None:
            try:
                self._bus_source.close()
            except Exception:
                pass
            self._bus_source = None

    # -- connection ---------------------------------------------------------

    def action_connection(self) -> None:
        if isinstance(self.screen, ConnectionScreen):
            return
        self.push_screen(
            ConnectionScreen(current_target=self.last_target, current_baud=self.last_baud),
            self._on_connection_chosen,
        )

    def _on_connection_chosen(self, spec) -> None:
        if not spec:
            return
        kind = spec.get("kind")
        if kind == "wago":
            self.start_bus(spec["host"], spec["username"], spec["password"],
                           spec.get("iface", "can0"))
        elif kind in ("serial", "tcp"):
            self.start_gateway(spec)

    def start_gateway(self, spec) -> None:
        """Open a serial/TCP gateway from a connection spec and read its state."""
        from .device import Gateway, open_transport
        target = spec["target"]
        baud = int(spec.get("baud", 115200))
        self._stop_bus()  # leaving WAGO bus-monitor mode, if we were in it
        try:
            transport = open_transport(target, baud=baud)
        except Exception as e:  # noqa: BLE001
            self.notify("cannot open %s: %s" % (target, e), severity="error")
            self.set_status("connection failed: %s" % target)
            return
        # Replace any previous gateway.
        if self.gw is not None:
            try:
                self.gw.close()
            except Exception:
                pass
        self.gw = Gateway(transport)
        if hasattr(self.gw, "set_log_callback"):
            self.gw.set_log_callback(self._on_gw_log)
        self.last_target = target
        self.last_baud = baud if spec["kind"] == "serial" else self.last_baud
        self.notify("Connected: %s" % self.gw.name)
        self._update_tabs()
        self.connect()

    def start_bus(self, host: str, username: str, password: str, iface: str = "can0") -> None:
        """Start streaming can0 from a WAGO PLC over SSH into the Bus Monitor tab."""
        from .wago import CandumpSource, WagoError
        self._stop_bus()
        self._bus_rows.clear()
        self._bus_data.clear()
        self._bus_shown.clear()
        try:
            self.query_one("#bustable", DataTable).clear()
        except Exception:
            pass
        try:
            source = CandumpSource.over_ssh(host=host, username=username,
                                            password=password, iface=iface)
        except WagoError as e:
            self.notify(str(e), severity="error")
            self.set_status("WAGO connection failed")
            return
        except Exception as e:  # noqa: BLE001
            self.notify("WAGO connection failed: %s" % e, severity="error")
            self.set_status("WAGO connection failed")
            return
        # Entering bus-monitor mode: drop any Actisense gateway so the PGN Filter /
        # Activity Log tabs (which only mean anything with a gateway) are removed.
        if self.gw is not None:
            try:
                self.gw.close()
            except Exception:
                pass
            self.gw = None
        self._bus_source = source
        self.last_target = host
        self._update_tabs()
        self.notify("Listening on %s" % source.name)
        self.render_status()
        self.run_bus_monitor()

    # -- interactions -------------------------------------------------------

    def _highlighted_pgn(self) -> Optional[int]:
        table = self.query_one("#table", DataTable)
        if table.row_count == 0:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:  # noqa: BLE001
            return None
        return self._row_pgn.get(key)

    def _toggle(self, which: PgnList) -> None:
        if self.gw is None:
            self.notify("no gateway connected (bus monitor only)", severity="warning")
            return
        pgn = self._highlighted_pgn()
        if pgn is None:
            return
        enabled = self.tx_enabled if which == PgnList.TX else self.rx_enabled
        now_on = pgn not in enabled
        (enabled.add if now_on else enabled.discard)(pgn)
        self.dirty = True
        self.refresh_marks()
        self.render_status()
        self.push_pgn(which, pgn, now_on)

    def action_toggle_rx(self) -> None:
        self._toggle(PgnList.RX)

    def action_toggle_tx(self) -> None:
        self._toggle(PgnList.TX)

    def action_toggle_both(self) -> None:
        """Toggle RX and TX together for the highlighted PGN (key: b)."""
        if self.gw is None:
            self.notify("no gateway connected (bus monitor only)", severity="warning")
            return
        pgn = self._highlighted_pgn()
        if pgn is None:
            return
        target = not (pgn in self.rx_enabled and pgn in self.tx_enabled)  # on unless both already on
        for which, enabled in ((PgnList.RX, self.rx_enabled), (PgnList.TX, self.tx_enabled)):
            if target and pgn not in enabled:
                enabled.add(pgn); self.push_pgn(which, pgn, True)
            elif not target and pgn in enabled:
                enabled.discard(pgn); self.push_pgn(which, pgn, False)
        self.dirty = True
        self.refresh_marks()
        self.render_status()

    def _select_all(self, which: PgnList) -> None:
        """Select (or, if already all selected, clear) the RX or TX box for every PGN
        currently shown in the table -- so a filter + Shift+R/T acts on that subset."""
        if self.gw is None:
            self.notify("no gateway connected", severity="warning")
            return
        enabled = self.tx_enabled if which == PgnList.TX else self.rx_enabled
        pgns = list(self._row_pgn.values())
        if not pgns:
            return
        target = not all(p in enabled for p in pgns)  # all on -> clear; else select all
        to_push = []
        for pgn in pgns:
            if target and pgn not in enabled:
                enabled.add(pgn); to_push.append((pgn, True))
            elif not target and pgn in enabled:
                enabled.discard(pgn); to_push.append((pgn, False))
        if not to_push:
            return
        self.dirty = True
        self.refresh_marks()
        self.render_status()
        self.set_status("%s %s for %d PGN(s) (writing to gateway…)"
                        % ("Selected" if target else "Cleared", which.name, len(to_push)))
        self._push_many(which, to_push)

    @work(thread=True, group="push")
    def _push_many(self, which: PgnList, items) -> None:
        """Bulk-write a batch of enable/disable commands off the UI thread.

        One fire-and-forget burst with a single summary log line, instead of a blocking
        per-PGN command (which took minutes and flooded the Activity Log for select-all)."""
        try:
            self.gw.set_pgns_bulk(which, items)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, "bulk set_pgn failed: %s" % e, severity="error")
            return
        self.call_from_thread(self.render_status)

    def action_select_all_rx(self) -> None:
        self._select_all(PgnList.RX)

    def action_select_all_tx(self) -> None:
        self._select_all(PgnList.TX)

    def action_select_all_both(self) -> None:
        """Select (or, if every shown PGN already has both on, clear) BOTH RX and TX
        for every PGN currently shown -- the filtered subset (key: Shift+B)."""
        if self.gw is None:
            self.notify("no gateway connected", severity="warning")
            return
        pgns = list(self._row_pgn.values())
        if not pgns:
            return
        target = not all(p in self.rx_enabled and p in self.tx_enabled for p in pgns)
        push_rx, push_tx = [], []
        for pgn in pgns:
            in_rx, in_tx = pgn in self.rx_enabled, pgn in self.tx_enabled
            if target:
                if not in_rx:
                    self.rx_enabled.add(pgn); push_rx.append((pgn, True))
                if not in_tx:
                    self.tx_enabled.add(pgn); push_tx.append((pgn, True))
            else:
                if in_rx:
                    self.rx_enabled.discard(pgn); push_rx.append((pgn, False))
                if in_tx:
                    self.tx_enabled.discard(pgn); push_tx.append((pgn, False))
        if not (push_rx or push_tx):
            return
        self.dirty = True
        self.refresh_marks()
        self.render_status()
        self.set_status("%s RX+TX for %d PGN(s) (writing to gateway…)"
                        % ("Selected" if target else "Cleared", len(pgns)))
        if push_rx:
            self._push_many(PgnList.RX, push_rx)
        if push_tx:
            self._push_many(PgnList.TX, push_tx)

    def action_activate(self) -> None:
        if self.gw is None:
            self.notify("no gateway connected", severity="warning")
            return
        self.do_activate()

    def action_commit(self) -> None:
        if self.gw is None:
            self.notify("no gateway connected", severity="warning")
            return
        self.do_commit()

    def action_reload(self) -> None:
        if self.gw is None:
            self.action_connection()
            return
        self.connect()

    def action_save_lists(self) -> None:
        if self.gw is None:
            self.notify("no gateway connected (bus monitor only)", severity="warning")
            return
        self.push_screen(FilenameScreen("Save RX/TX lists to file",
                                        default="actuisense-lists.txt"),
                         self._do_save_lists)

    def _do_save_lists(self, path) -> None:
        if not path:
            return
        import datetime

        from .pgnfile import dump_lists
        text = dump_lists(self.rx_enabled, self.tx_enabled, self.db,
                          gateway=(self.gw.name if self.gw else None),
                          mode=(self.mode.name if self.mode else None),
                          when=datetime.datetime.now().isoformat(timespec="seconds"))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            self.notify("save failed: %s" % e, severity="error")
            return
        self.notify("Saved %d RX + %d TX PGNs to %s"
                    % (len(self.rx_enabled), len(self.tx_enabled), path))

    def action_load_lists(self) -> None:
        if self.gw is None:
            self.notify("no gateway connected (bus monitor only)", severity="warning")
            return
        self.push_screen(FilenameScreen("Load RX/TX lists from file",
                                        default="actuisense-lists.txt"),
                         self._do_load_lists)

    def _do_load_lists(self, path) -> None:
        if not path:
            return
        from .pgnfile import parse_lists
        try:
            with open(path, "r", encoding="utf-8") as f:
                rx_want, tx_want = parse_lists(f.read())
        except OSError as e:
            self.notify("load failed: %s" % e, severity="error")
            return
        except ValueError as e:
            self.notify("bad list file: %s" % e, severity="error")
            return
        for which, want, enabled in ((PgnList.RX, rx_want, self.rx_enabled),
                                     (PgnList.TX, tx_want, self.tx_enabled)):
            to_push = ([(p, True) for p in sorted(want - enabled)]
                       + [(p, False) for p in sorted(enabled - want)])
            if not to_push:
                continue
            enabled.clear()
            enabled.update(want)
            self._push_many(which, to_push)
        self.dirty = True
        self.refresh_marks()
        self.render_status()
        self.notify("Loaded %d RX + %d TX PGNs — press Activate (a) to apply"
                    % (len(rx_want), len(tx_want)))

    def action_cycle_mode(self) -> None:
        if self.gw is None:
            self.notify("no gateway connected", severity="warning")
            return
        nxt = OperatingMode.FILTER if self.mode == OperatingMode.RX_ALL else OperatingMode.RX_ALL
        self.do_set_mode(nxt)

    def action_focus_filter(self) -> None:
        wid = "#busfilter" if self._active_tab() == "bustab" else "#filter"
        try:
            self.query_one(wid, Input).focus()
        except Exception:
            pass

    def action_toggle_poll(self) -> None:
        self.poll_paused = not self.poll_paused
        try:
            self.query_one("#poll", Button).label = "Resume polling (p)" if self.poll_paused else "Pause polling (p)"
        except Exception:
            pass
        self.render_status()

    def action_clear_log(self) -> None:
        self.query_one("#logtable", DataTable).clear()
        self._log_rows = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.populate_table(event.value)
        elif event.input.id == "busfilter":
            self._apply_bus_filter(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {"activate": self.action_activate, "commit": self.action_commit,
         "reload": self.action_reload, "mode": self.action_cycle_mode,
         "connect": self.action_connection, "save": self.action_save_lists,
         "load": self.action_load_lists,
         "poll": self.action_toggle_poll, "clearlog": self.action_clear_log,
         }.get(event.button.id, lambda: None)()


def run_tui(port: Optional[str] = None, baud: int = 115200) -> int:
    """Launch the TUI.

    With ``port`` given, opens that serial/TCP gateway up front (old behaviour).
    Without it, the app starts disconnected and opens the Connection dialog so the
    user can pick a serial port + baud, a TCP gateway, or a WAGO PLC (can0).
    """
    from .device import Gateway, open_transport
    gw = None
    if port:
        try:
            transport = open_transport(port, baud=baud)
        except Exception as e:  # noqa: BLE001
            print("error: cannot open %s: %s" % (port, e))
            return 2
        gw = Gateway(transport)
    app = ActuiSenseApp(gw)
    app.last_target = port
    app.last_baud = baud

    import os
    import signal
    import sys

    def _restore_terminal() -> None:
        """Put the terminal back to a sane state after the TUI. Covers the cases
        where Textual's own teardown was skipped (kill, or a stuck worker thread):
        mouse reporting off, cursor visible, normal cursor keys/keypad, and cooked
        line mode (so arrow keys stop printing as raw ``^[[A``)."""
        try:
            sys.stdout.write(
                "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l"  # mouse off
                "\x1b[?25h"   # show cursor
                "\x1b[?1l"    # normal (not application) cursor keys
                "\x1b>")      # normal keypad
            sys.stdout.flush()
        except Exception:
            pass
        try:
            if os.name == "posix" and sys.stdout.isatty():
                os.system("stty sane </dev/tty >/dev/tty 2>/dev/null")
        except Exception:
            pass

    # A SIGTERM/SIGHUP kill otherwise skips cleanup; ask Textual to exit cleanly
    # (falls back to an interrupt) so the `finally` below restores the terminal.
    def _signal_exit(_signum, _frame):
        try:
            app.exit()
        except Exception:
            raise KeyboardInterrupt

    _prev = {}
    for _sig_name in ("SIGTERM", "SIGHUP"):
        _sig = getattr(signal, _sig_name, None)
        if _sig is not None:
            try:
                _prev[_sig] = signal.signal(_sig, _signal_exit)
            except (ValueError, OSError):  # not main thread / unsupported
                pass
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        for _sig, _handler in _prev.items():
            try:
                signal.signal(_sig, _handler)
            except (ValueError, OSError):
                pass
        if gw is not None:
            try:
                gw.close()
            except Exception:
                pass
        try:
            app._stop_bus()
        except Exception:
            pass
        _restore_terminal()

    # Textual @work threads doing blocking serial/SSH I/O can keep the interpreter
    # from exiting (atexit join() hangs, leaving the terminal half-restored and
    # needing Ctrl-C). The terminal is already restored above, so exit hard.
    sys.stdout.flush()
    os._exit(0)
