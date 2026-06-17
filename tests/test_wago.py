"""
CandumpSource frame decoding + cooperative stop, driven by a fake line stream so
no SSH/hardware is needed. (The over_ssh() factory is a thin paramiko wrapper and
is not exercised here.)
"""

import threading

from actuisense.can import CanFrame
from actuisense.wago import CandumpSource

SAMPLE = [
    "(1623456789.000001) can0 19F21803#FFFF7F2701FF0000",  # PGN 127512
    "garbage that should be skipped",
    "(1623456789.000002) can0 19F30703#0102030405060708",  # PGN 127751
    "",
    "(1623456789.000003) can0 19F21803##deadbeef",  # CAN-FD -> skipped
]


def test_frames_decodes_and_skips_noise():
    src = CandumpSource(lines=iter(SAMPLE))
    frames = list(src.frames())
    assert [f.pgn for f in frames] == [127512, 127751]
    assert all(isinstance(f, CanFrame) for f in frames)
    assert frames[1].data == bytes.fromhex("0102030405060708")


def test_close_stops_iteration():
    # An endless stream; close() mid-flight must end frames().
    src_holder = {}

    def endless():
        i = 0
        while True:
            # Stop the source after a few good frames have been produced.
            if i == 3:
                src_holder["src"].close()
            i += 1
            yield "(1623456789.%06d) can0 19F21803#FFFF7F2701FF0000" % i

    src = CandumpSource(lines=endless())
    src_holder["src"] = src
    frames = list(src.frames())
    # Loop yields lines 1..3 (frames), line 4 triggers close before yield-check.
    assert len(frames) <= 4
    assert frames and frames[0].pgn == 127512


def test_close_invokes_closer_once():
    calls = []
    src = CandumpSource(lines=iter([]), closer=lambda: calls.append(1))
    src.close()
    src.close()  # idempotent — closer must not fire twice
    assert calls == [1]


def test_name_defaults():
    assert CandumpSource(lines=iter([])).name == "can0"
