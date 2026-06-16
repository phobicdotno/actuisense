#!/usr/bin/env python3
"""
Render a TUI screenshot (SVG) for the README, headlessly, with a fake gateway
preloaded with realistic data. No hardware needed.

Usage:  python tools/gen_screenshot.py
"""

import asyncio
import os

from actuisense.protocol import OperatingMode, PgnList
from actuisense.tui import ActuiSenseApp

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshot.svg")


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
    app = ActuiSenseApp(DemoGateway())
    async with app.run_test(size=(96, 28)) as pilot:
        await app.workers.wait_for_complete()
        app.populate_table("127")  # show the interesting telemetry PGNs
        await pilot.pause()
        svg = app.export_screenshot(title="AcTuiSense")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    asyncio.run(main())
