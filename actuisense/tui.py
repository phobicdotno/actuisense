"""
Full-screen terminal UI (Textual) — the cross-platform equivalent of Actisense NMEA
Reader's Hardware Configuration page, with two tabs:

  • PGN Filter   — a scrollable table of every PGN with toggleable RX/TX enable cells,
                   plus operating-mode / activate / commit actions.
  • Activity Log — a running log of every gateway exchange (line, time, action,
                   result OK/Timeout/NAK, detail), like NMEA Reader's command log,
                   fed by a periodic Get-Operating-Mode poll plus your own actions.

Serial/TCP I/O blocks, so every gateway call runs in a Textual thread worker; the UI
thread only renders. The app is constructed with a gateway object, which lets it be
driven headlessly in tests with a fake gateway.
"""

from __future__ import annotations

from typing import Optional, Set

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label,
                             TabbedContent, TabPane)

from .pgndb import PgnDb
from .protocol import OperatingMode, PgnList

CHECK = "[X]"
UNCHECK = "[ ]"
POLL_INTERVAL = 2.0          # seconds between Get-Operating-Mode heartbeats
LOG_VIEW_MAX = 500           # max rows kept in the visible log table

_RESULT_STYLE = {"OK": "green", "Timeout": "yellow", "NAK": "red bold", "Error": "red bold"}


class ActuiSenseApp(App):
    TITLE = "AcTuiSense"
    CSS = """
    #status { height: 1; padding: 0 1; background: $boost; color: $text; }
    #filterbar { height: 3; }
    #filter { width: 1fr; }
    DataTable { height: 1fr; }
    #actions, #logactions { height: 3; align: left middle; }
    #actions Button, #logactions Button { margin: 0 1 0 0; }
    """

    BINDINGS = [
        Binding("r", "toggle_rx", "Toggle RX"),
        Binding("t", "toggle_tx", "Toggle TX"),
        Binding("space", "toggle_tx", "Toggle TX", show=False),
        Binding("a", "activate", "Activate"),
        Binding("c", "commit", "Commit EEPROM"),
        Binding("f5", "reload", "Reload"),
        Binding("m", "cycle_mode", "Mode"),
        Binding("p", "toggle_poll", "Pause poll"),
        Binding("ctrl+f", "focus_filter", "Filter"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, gateway, db: Optional[PgnDb] = None):
        super().__init__()
        self.gw = gateway
        self.db = db or PgnDb()
        self.rx_enabled: Set[int] = set()
        self.tx_enabled: Set[int] = set()
        self.mode: Optional[OperatingMode] = None
        self.dirty = False
        self.poll_paused = False
        self._row_pgn = {}
        self._log_rows = 0

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
                    yield Button("Reload (F5)", id="reload")
                    yield Button("Mode (m)", id="mode")
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
        if hasattr(self.gw, "set_log_callback"):
            self.gw.set_log_callback(self._on_gw_log)
        self.populate_table("")
        self.connect()
        self.set_interval(POLL_INTERVAL, self.poll)

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

    # -- status & log -------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.query_one("#status", Label).update(text)

    def render_status(self) -> None:
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
        self.call_from_thread(self.set_status, "reading gateway…")
        try:
            mode = self.gw.get_operating_mode()
            rx = set(self.gw.get_pgn_list(PgnList.RX))
            tx = set(self.gw.get_pgn_list(PgnList.TX))
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, "ERROR: %s" % e)
            return
        self.mode, self.rx_enabled, self.tx_enabled = mode, rx, tx
        self.dirty = False
        self.call_from_thread(self.refresh_marks)
        self.call_from_thread(self.render_status)

    @work(group="poll", exclusive=True, thread=True)
    def poll(self) -> None:
        if self.poll_paused:
            return
        try:
            m = self.gw.get_operating_mode()
        except Exception:
            return
        if m is not None:
            self.mode = m
        self.call_from_thread(self.render_status)

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

    def action_activate(self) -> None:
        self.do_activate()

    def action_commit(self) -> None:
        self.do_commit()

    def action_reload(self) -> None:
        self.connect()

    def action_cycle_mode(self) -> None:
        nxt = OperatingMode.FILTER if self.mode == OperatingMode.RX_ALL else OperatingMode.RX_ALL
        self.do_set_mode(nxt)

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {"activate": self.action_activate, "commit": self.action_commit,
         "reload": self.action_reload, "mode": self.action_cycle_mode,
         "poll": self.action_toggle_poll, "clearlog": self.action_clear_log,
         }.get(event.button.id, lambda: None)()


def run_tui(port: str, baud: int = 115200) -> int:
    from .device import Gateway, open_transport
    try:
        transport = open_transport(port, baud=baud)
    except Exception as e:  # noqa: BLE001
        print("error: cannot open %s: %s" % (port, e))
        return 2
    gw = Gateway(transport)
    try:
        ActuiSenseApp(gw).run()
    finally:
        gw.close()
    return 0
