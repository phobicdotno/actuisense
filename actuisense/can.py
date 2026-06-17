"""
Raw CAN <-> NMEA 2000 helpers for the can0 bus monitor.

Unlike the Actisense BST protocol in :mod:`actuisense.protocol` (which wraps
already-assembled N2K messages in DLE/STX framing), this module deals with raw
CAN frames as they appear on the wire / in ``candump`` output: a 29-bit extended
identifier plus up to 8 data bytes.

NMEA 2000 rides J1939 addressing, so the 29-bit CAN id encodes priority, PGN,
source and destination. The decode here is the canonical J1939
``getISO11783BitsFromCanId`` split, cross-checked against canboat. No I/O lives
here, so it is fully unit-testable without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GLOBAL_DEST = 0xFF


@dataclass(frozen=True)
class CanId:
    """The J1939/N2K fields carried in a 29-bit extended CAN identifier."""

    priority: int
    pgn: int
    source: int
    dest: int  # 0xFF == global/broadcast (PDU2 messages are always global)


def parse_can_id(can_id: int) -> CanId:
    """Split a 29-bit extended CAN id into (priority, PGN, source, dest).

    PDU1 (PF < 240): the PDU-specific byte is the destination address and is NOT
    part of the PGN. PDU2 (PF >= 240): the PDU-specific byte is a group extension
    that IS part of the PGN, and the message is broadcast (dest 0xFF).
    """
    can_id &= 0x1FFFFFFF
    source = can_id & 0xFF
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    rdp = (can_id >> 24) & 0x03  # reserved + data-page bits
    priority = (can_id >> 26) & 0x07
    if pf < 240:  # PDU1 — destination-specific
        dest = ps
        pgn = (rdp << 16) | (pf << 8)
    else:  # PDU2 — broadcast, PS is a group extension
        dest = GLOBAL_DEST
        pgn = (rdp << 16) | (pf << 8) | ps
    return CanId(priority=priority, pgn=pgn, source=source, dest=dest)


@dataclass(frozen=True)
class CanFrame:
    """One raw CAN frame off can0, decoded to N2K fields."""

    timestamp: float
    can_id: int
    data: bytes
    priority: int
    pgn: int
    source: int
    dest: int

    @classmethod
    def from_raw(cls, timestamp: float, can_id: int, data: bytes) -> "CanFrame":
        bits = parse_can_id(can_id)
        return cls(
            timestamp=timestamp,
            can_id=can_id,
            data=data,
            priority=bits.priority,
            pgn=bits.pgn,
            source=bits.source,
            dest=bits.dest,
        )


def parse_candump_line(line: str) -> Optional[CanFrame]:
    """Parse one line of ``candump -L`` log output into a :class:`CanFrame`.

    The ``-L`` (log) format is::

        (1623456789.123456) can0 09F80103#FFFF7F2701FF0000

    i.e. ``(epoch.micros) <iface> <hexid>#<hexdata>``. Standard (11-bit) ids are
    3 hex digits, extended (29-bit) ids 8 — N2K is always extended. CAN-FD frames
    use ``##`` and a flags nibble; those are not NMEA 2000, so they are ignored.
    Returns ``None`` for blank lines, comments, or anything that does not parse.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split()
    if len(parts) < 3:
        return None
    ts_tok, _iface, frame_tok = parts[0], parts[1], parts[2]
    if not (ts_tok.startswith("(") and ts_tok.endswith(")")):
        return None
    try:
        timestamp = float(ts_tok[1:-1])
    except ValueError:
        return None
    if "##" in frame_tok:  # CAN-FD — not N2K
        return None
    id_tok, sep, data_tok = frame_tok.partition("#")
    if not sep:
        return None
    try:
        can_id = int(id_tok, 16)
    except ValueError:
        return None
    # 'R' marks a remote-transmission-request frame (no data); skip it.
    if data_tok.startswith(("R", "r")):
        return None
    try:
        data = bytes.fromhex(data_tok)
    except ValueError:
        return None
    return CanFrame.from_raw(timestamp, can_id, data)


__all__ = ["CanId", "CanFrame", "parse_can_id", "parse_candump_line", "GLOBAL_DEST"]
