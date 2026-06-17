"""
Actisense BST (Binary Serial Transport) protocol.

Pure, dependency-free encode/decode for the command protocol spoken by Actisense
NMEA 2000 gateways (NGT-1, NGW-1, NGX-1, and the BST-compatible parts of newer units).
No I/O lives here -- this module only turns commands into bytes and bytes back
into frames, so it is fully unit-testable without hardware.

Frame on the wire:

    DLE STX <command> <len> <payload...> <crc> DLE ETX

  - DLE=0x10, STX=0x02, ETX=0x03
  - <len> is the length of the *unescaped* payload
  - any of <len>, a payload byte, or <crc> equal to DLE (0x10) is escaped by
    doubling it: 0x10 -> 0x10 0x10
  - <crc> makes (command + len + sum(payload) + crc) == 0 (mod 256)

The <command> byte selects the channel:
  0x94 N2kMsgSend / 0x93 N2kMsgRecv  -- NMEA 2000 data frames
  0xA1 ACmdSend   / 0xA0 ACmdRecv    -- gateway command/response; payload[0] is an
                                        opcode from `Op` below.

Command set and byte layouts are documented Actisense facts, cross-checked against
canboat `actisense-serial.c` (Apache-2.0) and timmathews/argo `actisense/commands.go`
(GPL-3.0). See CREDITS.md. This is a clean re-implementation, not a copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterator, List, Optional, Tuple

DLE = 0x10
STX = 0x02
ETX = 0x03

# Channel/command bytes
N2K_MSG_RECV = 0x93
N2K_MSG_SEND = 0x94
ACMD_RECV = 0xA0
ACMD_SEND = 0xA1


class Op(IntEnum):
    """Gateway command opcodes (payload[0] when command byte is ACMD_SEND/RECV)."""

    # iota group from 0x00
    REINIT_MAIN_APP = 0x00
    COMMIT_TO_EEPROM = 0x01
    COMMIT_TO_FLASH = 0x02

    # iota group from 0x10
    HARDWARE_INFO = 0x10
    OPERATING_MODE = 0x11
    PORT_BAUD_CFG = 0x12
    PORT_PCODE_CFG = 0x13
    PORT_DUP_DELETE = 0x14
    TOTAL_TIME = 0x15
    HARDWARE_BAUD = 0x16

    # iota group from 0x40
    SUPPORTED_PGN_LIST = 0x40
    PRODUCT_INFO_N2K = 0x41
    CAN_CONFIG = 0x42
    CAN_INFO_FIELD1 = 0x43
    CAN_INFO_FIELD2 = 0x44
    CAN_INFO_FIELD3 = 0x45
    RX_PGN_ENABLE = 0x46
    TX_PGN_ENABLE = 0x47
    RX_PGN_ENABLE_LIST = 0x48
    TX_PGN_ENABLE_LIST = 0x49
    DELETE_PGN_ENABLE_LIST = 0x4A
    ACTIVATE_PGN_ENABLE_LISTS = 0x4B
    DEFAULT_PGN_ENABLE_LIST = 0x4C
    PARAMS_PGN_ENABLE_LISTS = 0x4D
    RX_PGN_ENABLE_LIST_F2 = 0x4E
    TX_PGN_ENABLE_LIST_F2 = 0x4F

    # iota group from 0xF0
    STARTUP_STATUS = 0xF0
    ERROR_REPORT = 0xF1
    SYSTEM_STATUS = 0xF2
    NEGATIVE_ACK = 0xF4


class OperatingMode(IntEnum):
    FILTER = 1   # apply the Rx PGN enable list
    RX_ALL = 2   # receive every PGN, ignore the Rx list


class PgnList(IntEnum):
    RX = 0
    TX = 1


def crc_of(command: int, payload: bytes) -> int:
    """Two's-complement checksum byte: (cmd + len + sum(payload) + crc) % 256 == 0."""
    total = (command + len(payload) + sum(payload)) & 0xFF
    return (256 - total) & 0xFF


def build_frame(command: int, payload: bytes = b"") -> bytes:
    """Encode one BST frame, escaping DLE in len/payload/crc exactly as the device parser expects."""
    if len(payload) > 0xFF:
        raise ValueError("payload too long for a single BST frame (max 255 bytes)")
    out = bytearray((DLE, STX, command))
    ln = len(payload)
    out.append(ln)
    if ln == DLE:
        out.append(DLE)
    for b in payload:
        if b == DLE:
            out.append(DLE)
        out.append(b)
    crc = crc_of(command, payload)
    if crc == DLE:
        out.append(DLE)
    out.append(crc)
    out += bytes((DLE, ETX))
    return bytes(out)


# ---- payload encoders ------------------------------------------------------

def pgn_le(pgn: int) -> bytes:
    """PGN as 4 little-endian bytes (the device only uses the low 3, but argo sends 4)."""
    return bytes((pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF, (pgn >> 24) & 0xFF))


def cmd_set_operating_mode(mode: OperatingMode) -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.OPERATING_MODE, int(mode) & 0xFF, (int(mode) >> 8) & 0xFF)))


def cmd_get_operating_mode() -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.OPERATING_MODE,)))


def cmd_set_pgn(which: PgnList, pgn: int, enable: bool) -> bytes:
    op = Op.TX_PGN_ENABLE if which == PgnList.TX else Op.RX_PGN_ENABLE
    return build_frame(ACMD_SEND, bytes((op,)) + pgn_le(pgn) + bytes((1 if enable else 0,)))


def cmd_get_pgn(which: PgnList, pgn: int) -> bytes:
    op = Op.TX_PGN_ENABLE if which == PgnList.TX else Op.RX_PGN_ENABLE
    return build_frame(ACMD_SEND, bytes((op,)) + pgn_le(pgn))


def cmd_get_pgn_list(which: PgnList) -> bytes:
    op = Op.TX_PGN_ENABLE_LIST if which == PgnList.TX else Op.RX_PGN_ENABLE_LIST
    return build_frame(ACMD_SEND, bytes((op,)))


def cmd_delete_pgn_list(which: PgnList) -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.DELETE_PGN_ENABLE_LIST, int(which))))


def cmd_activate_pgn_lists() -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.ACTIVATE_PGN_ENABLE_LISTS,)))


def cmd_default_pgn_list(list_id: int) -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.DEFAULT_PGN_ENABLE_LIST, list_id & 0xFF)))


def cmd_commit_eeprom() -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.COMMIT_TO_EEPROM,)))


def cmd_commit_flash() -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.COMMIT_TO_FLASH,)))


def cmd_reinit_main_app() -> bytes:
    return build_frame(ACMD_SEND, bytes((Op.REINIT_MAIN_APP,)))


def cmd_simple(op: Op) -> bytes:
    """Query commands that take no argument (HARDWARE_INFO, PRODUCT_INFO_N2K, ...)."""
    return build_frame(ACMD_SEND, bytes((int(op),)))


# ---- frame decoding --------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    command: int
    payload: bytes
    crc_ok: bool

    @property
    def opcode(self) -> Optional[int]:
        """For ACMD frames, payload[0] is the echoed opcode."""
        return self.payload[0] if self.payload else None

    @property
    def is_nak(self) -> bool:
        return self.command == ACMD_RECV and self.opcode == Op.NEGATIVE_ACK


class FrameDecoder:
    """Feed raw bytes; yields complete `Frame`s. Mirrors canboat's readNGT1Byte state machine."""

    _IDLE, _MSG, _ESC = 0, 1, 2

    def __init__(self) -> None:
        self._state = self._IDLE
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[Frame]:
        for b in data:
            f = self._step(b)
            if f is not None:
                yield f

    def _step(self, b: int) -> Optional[Frame]:
        if self._state == self._ESC:
            if b == STX:
                self._buf = bytearray()
                self._state = self._MSG
            elif b == ETX:
                frame = self._finish()
                self._state = self._IDLE
                return frame
            elif b == DLE:
                self._buf.append(DLE)
                self._state = self._MSG
            else:  # unexpected char after DLE -> resync
                self._state = self._IDLE
        elif self._state == self._MSG:
            if b == DLE:
                self._state = self._ESC
            else:
                self._buf.append(b)
        else:  # _IDLE
            if b == DLE:
                self._state = self._ESC
        return None

    def _finish(self) -> Optional[Frame]:
        buf = self._buf
        if len(buf) < 3:  # need command + len + crc minimum
            return None
        command = buf[0]
        ln = buf[1]
        if len(buf) != ln + 3:
            return Frame(command, bytes(buf[2:-1]), crc_ok=False)
        payload = bytes(buf[2:2 + ln])
        crc_ok = (sum(buf) & 0xFF) == 0
        return Frame(command, payload, crc_ok)


def decode_all(data: bytes) -> List[Frame]:
    return list(FrameDecoder().feed(data))


def parse_pgn_list_part1(frame: Frame) -> Tuple[int, List[int]]:
    """
    Parse the first part (sequence 1) of a Tx/Rx PGN-enable-list response into the
    set of enabled PGNs. Layout (observed on NGT-1 firmware): after the opcode and a
    1-byte sequence, 2 status bytes, an 8-byte device NAME, a 1-byte count, then
    `count` entries of 4 bytes each: PGN as little-endian 24-bit + 1 trailing byte.

    Returns (sequence, [pgns]). Raises ValueError if it is not a list response.
    """
    if frame.command != ACMD_RECV or frame.opcode not in (Op.RX_PGN_ENABLE_LIST, Op.TX_PGN_ENABLE_LIST):
        raise ValueError("not a PGN-enable-list response")
    p = frame.payload
    seq = p[1] if len(p) > 1 else 0
    # opcode(1) seq(1) status(2) name(8) count(1) -> entries start at 13
    idx = 13
    if len(p) <= idx:
        return seq, []
    count = p[idx - 1]
    pgns: List[int] = []
    for i in range(count):
        off = idx + i * 4
        if off + 3 > len(p):
            break
        pgn = p[off] | (p[off + 1] << 8) | (p[off + 2] << 16)
        pgns.append(pgn)
    return seq, pgns


def parse_pgn_query(frame: Frame) -> Optional[Tuple[int, bool]]:
    """
    Parse a per-PGN enable-state reply (opcode TX_PGN_ENABLE 0x47 / RX_PGN_ENABLE
    0x46) into (pgn, enabled). After the 12-byte header (opcode, seq, 2 status, 8
    NAME) the payload is the PGN as little-endian 24-bit (+1 pad) then a 1-byte
    enable flag. This is how the NGX-1 reports a PGN's state -- it answers the
    per-PGN query even though it ignores the bulk list query (0x49/0x48).

    Returns None if `frame` is not such a reply.
    """
    if frame.command != ACMD_RECV or frame.opcode not in (Op.TX_PGN_ENABLE, Op.RX_PGN_ENABLE):
        return None
    p = frame.payload
    if len(p) < 17:  # 12 header + pgn(4) + enable(1)
        return None
    pgn = p[12] | (p[13] << 8) | (p[14] << 16)
    return pgn, bool(p[16])
