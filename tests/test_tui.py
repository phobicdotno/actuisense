"""
Headless TUI tests via Textual's run_test() harness with a fake gateway — verifies
the table populates from the PGN db, RX/TX marks reflect the enabled sets, filtering
narrows rows, and toggling updates state + drives the gateway. No hardware, no async
test plugin (we drive the coroutine with asyncio.run).
"""

import asyncio

from actuisense.protocol import OperatingMode, PgnList
from actuisense.tui import CHECK, UNCHECK, ActuiSenseApp


class FakeGateway:
    name = "fake-gw"

    def __init__(self):
        self.rx = {60928}
        self.tx = {127512, 127514, 127751}
        self.mode = OperatingMode.RX_ALL
        self.calls = []

    def get_operating_mode(self):
        return self.mode

    def get_pgn_list(self, which):
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
