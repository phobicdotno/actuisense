"""
Transport + high-level gateway API.

`open_transport()` accepts a serial device (`/dev/ttyUSB0`, `COM5`) or a TCP target
(`tcp://host:port`, for networked Actisense units). `Gateway` wraps a transport and
exposes the config operations the CLI and TUI need: read/set operating mode,
enable/disable Rx/Tx PGNs, read the enable lists, activate, and commit to EEPROM.

The gateway streams NMEA 2000 data frames continuously; command responses are
interleaved with them, so every exchange decodes the stream and filters for the
ACMD response opcode it wants.
"""

from __future__ import annotations

import socket
import time
from typing import Iterable, List, Optional, Sequence

import serial  # pyserial

from . import protocol as proto
from .protocol import Frame, FrameDecoder, OperatingMode, Op, PgnList

# 12-byte response header before payload-specific data:
#   opcode(1) sequence(1) status(2) device-NAME(8)
_HEADER_LEN = 12


class GatewayError(Exception):
    pass


class NakError(GatewayError):
    def __init__(self, opcode: Optional[int]):
        super().__init__("gateway returned NEGATIVE_ACK for opcode 0x%02X" %
                         (opcode if opcode is not None else 0))
        self.opcode = opcode


# ---- transports ------------------------------------------------------------

class Transport:
    def read(self, max_bytes: int = 4096) -> bytes: ...  # pragma: no cover
    def write(self, data: bytes) -> None: ...            # pragma: no cover
    def close(self) -> None: ...                         # pragma: no cover

    @property
    def name(self) -> str:                               # pragma: no cover
        return "?"


class SerialTransport(Transport):
    def __init__(self, port: str, baud: int = 115200, read_timeout: float = 0.1):
        self._port = port
        self._ser = serial.Serial(
            port, baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE, timeout=read_timeout,
            rtscts=False, dsrdtr=False, xonxoff=False)

    def read(self, max_bytes: int = 4096) -> bytes:
        return self._ser.read(max_bytes or 1)

    def write(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    @property
    def name(self) -> str:
        return self._port


class TcpTransport(Transport):
    def __init__(self, host: str, port: int, read_timeout: float = 0.1):
        self._host, self._port = host, port
        self._sock = socket.create_connection((host, port), timeout=5)
        self._sock.settimeout(read_timeout)

    def read(self, max_bytes: int = 4096) -> bytes:
        try:
            return self._sock.recv(max_bytes)
        except socket.timeout:
            return b""

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "tcp://%s:%d" % (self._host, self._port)


def open_transport(spec: str, baud: int = 115200) -> Transport:
    """`tcp://host[:port]` -> TCP (default port 60002); anything else -> serial."""
    if spec.startswith("tcp://"):
        rest = spec[len("tcp://"):]
        host, _, port = rest.partition(":")
        return TcpTransport(host, int(port) if port else 60002)
    return SerialTransport(spec, baud=baud)


# ---- gateway ---------------------------------------------------------------

class Gateway:
    def __init__(self, transport: Transport, response_window: float = 1.5):
        self.t = transport
        self.window = response_window
        self._dec = FrameDecoder()

    # context manager
    def __enter__(self) -> "Gateway":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.t.close()

    @property
    def name(self) -> str:
        return self.t.name

    # -- low level ----------------------------------------------------------

    def _flush_input(self, duration: float = 0.05) -> None:
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if not self.t.read(4096):
                break

    def _collect(self, window: float) -> List[Frame]:
        frames: List[Frame] = []
        end = time.monotonic() + window
        while time.monotonic() < end:
            chunk = self.t.read(4096)
            if chunk:
                frames.extend(self._dec.feed(chunk))
        return frames

    def command(self, frame_bytes: bytes, want_op: Optional[int] = None,
                window: Optional[float] = None, raise_on_nak: bool = True) -> List[Frame]:
        """Send a frame, collect responses, optionally filter to `want_op`."""
        self._flush_input()
        self.t.write(frame_bytes)
        frames = self._collect(window if window is not None else self.window)
        for f in frames:
            if raise_on_nak and f.is_nak:
                raise NakError(f.payload[2] if len(f.payload) > 2 else None)
        if want_op is None:
            return frames
        return [f for f in frames if f.command == proto.ACMD_RECV and f.opcode == want_op]

    @staticmethod
    def _data(frame: Frame) -> bytes:
        """Strip the 12-byte response header, returning the payload-specific data."""
        return frame.payload[_HEADER_LEN:] if len(frame.payload) > _HEADER_LEN else b""

    # -- high level ---------------------------------------------------------

    def get_operating_mode(self) -> Optional[OperatingMode]:
        frames = self.command(proto.cmd_get_operating_mode(), want_op=Op.OPERATING_MODE)
        for f in frames:
            d = self._data(f)
            if len(d) >= 1:
                try:
                    return OperatingMode(d[0])
                except ValueError:
                    return None
        return None

    def set_operating_mode(self, mode: OperatingMode) -> None:
        self.command(proto.cmd_set_operating_mode(mode), want_op=None)

    def set_pgn(self, which: PgnList, pgn: int, enable: bool) -> None:
        self.command(proto.cmd_set_pgn(which, pgn, enable), want_op=None)

    def activate(self) -> None:
        self.command(proto.cmd_activate_pgn_lists(), want_op=None)

    def commit_eeprom(self) -> None:
        self.command(proto.cmd_commit_eeprom(), want_op=None)

    def enable_pgns(self, which: PgnList, pgns: Iterable[int], enable: bool = True,
                    activate: bool = True, commit: bool = False) -> None:
        for pgn in pgns:
            self.set_pgn(which, pgn, enable)
            time.sleep(0.05)
        if activate:
            self.activate()
        if commit:
            self.commit_eeprom()

    def get_pgn_list(self, which: PgnList) -> List[int]:
        """Return the PGNs currently enabled in the Rx or Tx list (from response part 1)."""
        want = Op.TX_PGN_ENABLE_LIST if which == PgnList.TX else Op.RX_PGN_ENABLE_LIST
        frames = self.command(proto.cmd_get_pgn_list(which), want_op=want, window=2.0)
        for f in frames:
            try:
                seq, pgns = proto.parse_pgn_list_part1(f)
            except ValueError:
                continue
            if seq == 1:
                return pgns
        return []

    def raw_query(self, op: Op) -> bytes:
        """Send a no-arg query and return the first matching response's data bytes."""
        frames = self.command(proto.cmd_simple(op), want_op=int(op))
        return self._data(frames[0]) if frames else b""
