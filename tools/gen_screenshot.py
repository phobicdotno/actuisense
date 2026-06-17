#!/usr/bin/env python3
"""
Render a TUI screenshot (SVG) for the README, headlessly, with a fake gateway
preloaded with realistic data. No hardware needed.

Usage:  python tools/gen_screenshot.py
"""

import asyncio
import os

from actuisense.device import LogEntry
from actuisense.protocol import OperatingMode, PgnList
from actuisense.tui import ActuiSenseApp
from textual.widgets import TabbedContent

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")
OUT = os.path.join(DOCS, "screenshot.svg")
OUT_LOG = os.path.join(DOCS, "screenshot-log.svg")

DEMO_LOG = [
    ("Get Operating Mode", "OK", ""),
    ("Get RX PGN List", "OK", ""),
    ("Get TX PGN List", "OK", ""),
    ("Enable TX PGN 127514", "OK", ""),
    ("Enable TX PGN 127751", "OK", ""),
    ("Activate Enable Lists", "OK", ""),
    ("Get Operating Mode", "OK", ""),
    ("Commit to EEPROM", "OK", ""),
    ("Get Operating Mode", "OK", ""),
    ("Disable RX PGN 130306", "OK", ""),
    ("Get Operating Mode", "Timeout", "500ms"),
    ("Get Operating Mode", "OK", ""),
]


class DemoGateway:
    name = "/dev/ttyUSB0 @115200"

    def __init__(self):
        self.mode = OperatingMode.RX_ALL
        self.rx = {59904, 60928, 126992, 127245, 127250, 127251, 128267, 129025, 129029}
        self.tx = {60928, 126208, 126993, 126996, 127250, 127488, 127489,
                   127505, 127508, 127512, 127514, 127751, 130306, 130312}

    def get_operating_mode(self):
        return self.mode

    def get_pgn_list(self, which):
        return sorted(self.tx if which == PgnList.TX else self.rx)

    def set_pgn(self, which, pgn, enable):
        pass

    def set_operating_mode(self, m):
        self.mode = m

    def activate(self):
        pass

    def commit_eeprom(self):
        pass

    def close(self):
        pass


async def main():
    os.makedirs(DOCS, exist_ok=True)
    app = ActuiSenseApp(DemoGateway())
    async with app.run_test(size=(96, 28)) as pilot:
        await app.workers.wait_for_complete()
        # --- PGN Filter tab ---
        app.populate_table("127")  # show the interesting telemetry PGNs
        await pilot.pause()
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(app.export_screenshot(title="AcTuiSense — PGN Filter"))
        print("wrote", os.path.normpath(OUT))
        # --- Activity Log tab ---
        for i, (action, result, detail) in enumerate(DEMO_LOG, 1):
            app._append_log(LogEntry(i, "07:45:%02d" % (30 + i), action, result, detail))
        app.query_one(TabbedContent).active = "logtab"
        await pilot.pause()
        with open(OUT_LOG, "w", encoding="utf-8") as f:
            f.write(app.export_screenshot(title="AcTuiSense — Activity Log"))
        print("wrote", os.path.normpath(OUT_LOG))


if __name__ == "__main__":
    asyncio.run(main())
