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
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import serial  # pyserial

from . import protocol as proto
from .protocol import Frame, FrameDecoder, OperatingMode, Op, PgnList

# 12-byte response header before payload-specific data:
#   opcode(1) sequence(1) status(2) device-NAME(8)
_HEADER_LEN = 12


@dataclass(frozen=True)
class LogEntry:
    """One command/response exchange, for the activity log (à la NMEA Reader)."""
    seq: int
    time: str       # HH:MM:SS
    action: str     # human label, e.g. "Get Operating Mode"
    result: str     # "OK" | "Timeout" | "NAK" | "Error"
    detail: str = ""  # e.g. "500ms" on timeout, or a short note


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
    def __init__(self, transport: Transport, response_window: float = 1.5,
                 on_log: Optional[Callable[[LogEntry], None]] = None, log_cap: int = 2000):
        self.t = transport
        self.window = response_window
        self._dec = FrameDecoder()
        self._lock = threading.Lock()   # serialise transport access across threads
        self._on_log = on_log
        self._seq = 0
        self._log_cap = log_cap
        self.log_entries: List[LogEntry] = []

    def set_log_callback(self, cb: Optional[Callable[[LogEntry], None]]) -> None:
        self._on_log = cb

    def _log(self, action: str, result: str, detail: str = "") -> None:
        self._seq += 1
        entry = LogEntry(self._seq, time.strftime("%H:%M:%S"), action, result, detail)
        self.log_entries.append(entry)
        if len(self.log_entries) > self._log_cap:
            del self.log_entries[0]
        if self._on_log is not None:
            try:
                self._on_log(entry)
            except Exception:
                pass

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
                window: Optional[float] = None, raise_on_nak: bool = True,
                action: str = "command") -> List[Frame]:
        """Send a frame, collect responses, optionally filter to `want_op`, and log the exchange."""
        win = window if window is not None else self.window
        try:
            with self._lock:
                self._flush_input()
                self.t.write(frame_bytes)
                frames = self._collect(win)
        except Exception as e:  # transport error
            self._log(action, "Error", str(e)[:40])
            raise
        nak = next((f for f in frames if f.is_nak), None)
        if want_op is None:
            matched = frames
            result = "NAK" if nak else "OK"
        else:
            matched = [f for f in frames if f.command == proto.ACMD_RECV and f.opcode == want_op]
            result = "NAK" if nak else ("OK" if matched else "Timeout")
        detail = "%dms" % int(win * 1000) if result == "Timeout" else ("negative ack" if result == "NAK" else "")
        self._log(action, result, detail)
        if nak and raise_on_nak:
            raise NakError(nak.payload[2] if len(nak.payload) > 2 else None)
        return matched if want_op is not None else frames

    @staticmethod
    def _data(frame: Frame) -> bytes:
        """Strip the 12-byte response header, returning the payload-specific data."""
        return frame.payload[_HEADER_LEN:] if len(frame.payload) > _HEADER_LEN else b""

    def read_n2k(self, window: float = 0.2) -> List["proto.N2kMessage"]:
        """Read a short burst of the gateway's live N2K traffic (0x93 frames).

        The Actisense gateway forwards every received N2K message on the 0x93 channel.
        This shares the transport lock with command()/the heartbeat poll, so it reads in
        a brief window and returns whatever N2K messages arrived; command responses and
        other frames are ignored. Not logged (the rate is far too high for the log)."""
        try:
            with self._lock:
                frames = self._collect(window)
        except Exception:
            return []
        return [m for m in (proto.parse_n2k_recv(f) for f in frames) if m is not None]

    # -- high level ---------------------------------------------------------

    def get_operating_mode(self) -> Optional[OperatingMode]:
        frames = self.command(proto.cmd_get_operating_mode(), want_op=Op.OPERATING_MODE,
                              action="Get Operating Mode")
        for f in frames:
            d = self._data(f)
            if len(d) >= 1:
                try:
                    return OperatingMode(d[0])
                except ValueError:
                    return None
        return None

    def set_operating_mode(self, mode: OperatingMode) -> None:
        self.command(proto.cmd_set_operating_mode(mode), want_op=None,
                     action="Set Operating Mode -> %s" % mode.name)

    def set_pgn(self, which: PgnList, pgn: int, enable: bool) -> None:
        self.command(proto.cmd_set_pgn(which, pgn, enable), want_op=None,
                     action="%s %s PGN %d" % ("Enable" if enable else "Disable", which.name, pgn))

    def activate(self) -> None:
        self.command(proto.cmd_activate_pgn_lists(), want_op=None, action="Activate Enable Lists")

    def commit_eeprom(self) -> None:
        self.command(proto.cmd_commit_eeprom(), want_op=None, action="Commit to EEPROM")

    def enable_pgns(self, which: PgnList, pgns: Iterable[int], enable: bool = True,
                    activate: bool = True, commit: bool = False) -> None:
        for pgn in pgns:
            self.set_pgn(which, pgn, enable)
            time.sleep(0.05)
        if activate:
            self.activate()
        if commit:
            self.commit_eeprom()

    def set_pgns_bulk(self, which: PgnList, items: Sequence[Tuple[int, bool]],
                      gap: float = 0.004, drain: float = 0.5) -> None:
        """Fire many Set-PGN commands back-to-back without waiting for each reply.

        The per-command path (`set_pgn`) blocks the full response window per PGN and
        logs one line each, so a select-all of hundreds of PGNs takes minutes and floods
        the Activity Log. This writes every frame with only a tiny inter-frame gap, drains
        whatever the gateway acks at the end, and emits a SINGLE summary log entry. Call
        `activate()` once afterwards to apply the lists.
        """
        items = list(items)
        if not items:
            return
        en = sum(1 for _, e in items if e)
        try:
            with self._lock:
                self._flush_input()
                for pgn, enable in items:
                    self.t.write(proto.cmd_set_pgn(which, pgn, enable))
                    if gap:
                        time.sleep(gap)
                self._collect(drain)  # absorb the trailing acks so they don't bleed into the next read
        except Exception as e:
            self._log("Bulk %s %d PGNs" % (which.name, len(items)), "Error", str(e)[:40])
            raise
        self._log("Bulk %s %d PGNs" % (which.name, len(items)), "OK",
                  "%d enable / %d disable" % (en, len(items) - en))

    def query_pgn(self, which: PgnList, pgn: int, window: float = 0.5) -> Optional[bool]:
        """Query ONE PGN's enable state with the per-PGN command (0x47 Tx / 0x46 Rx),
        early-exiting on the matching reply. Returns True/False, or None if no reply.

        This is the readback path for gateways (the NGX-1) that ignore the bulk list
        query (0x49/0x48) but still answer a per-PGN query.
        """
        op = int(Op.TX_PGN_ENABLE if which == PgnList.TX else Op.RX_PGN_ENABLE)
        with self._lock:
            self._flush_input()
            self.t.write(proto.cmd_get_pgn(which, pgn))
            end = time.monotonic() + window
            while time.monotonic() < end:
                chunk = self.t.read(4096)
                if not chunk:
                    continue
                for f in self._dec.feed(chunk):
                    if f.command == proto.ACMD_RECV and f.opcode == op:
                        parsed = proto.parse_pgn_query(f)
                        if parsed is not None and parsed[0] == pgn:
                            return parsed[1]
        return None

    def get_pgn_list_by_scan(self, which: PgnList, candidates: Sequence[int],
                             progress: Optional[Callable[[int, int], None]] = None,
                             batch: int = 24, batch_window: float = 1.0) -> List[int]:
        """Read the enabled list by querying candidate PGNs -- for gateways (the NGX-1)
        that ignore the bulk list query. PIPELINED: send a batch of per-PGN queries,
        then collect their replies together, so the device's reply latency and its
        0xF2 status-frame flood are paid once per batch, not once per PGN.
        `progress(done, total)` is called per batch, if given.
        """
        op_reply = int(Op.TX_PGN_ENABLE if which == PgnList.TX else Op.RX_PGN_ENABLE)
        results: dict = {}
        total = len(candidates)
        with self._lock:
            self._flush_input(0.1)
            for start in range(0, total, batch):
                chunk_pgns = candidates[start:start + batch]
                for pgn in chunk_pgns:
                    self.t.write(proto.cmd_get_pgn(which, pgn))
                need = set(chunk_pgns)
                end = time.monotonic() + batch_window
                while need and time.monotonic() < end:
                    data = self.t.read(4096)
                    if not data:
                        continue
                    for f in self._dec.feed(data):
                        if f.command == proto.ACMD_RECV and f.opcode == op_reply:
                            parsed = proto.parse_pgn_query(f)
                            if parsed is not None and parsed[0] in need:
                                results[parsed[0]] = parsed[1]
                                need.discard(parsed[0])
                if progress is not None:
                    progress(min(start + batch, total), total)
        enabled = [p for p in candidates if results.get(p)]
        self._log("Scan %s PGN List" % which.name, "OK",
                  "%d of %d enabled (%d unanswered)" % (len(enabled), total, total - len(results)))
        return enabled

    def get_pgn_list(self, which: PgnList, scan_candidates: Optional[Sequence[int]] = None,
                     scan_progress: Optional[Callable[[int, int], None]] = None) -> List[int]:
        """Return the PGNs enabled in the Rx or Tx list.

        Tries the fast bulk query (0x49/0x48, answered by the NGT-1/NGW-1). If that
        yields nothing and `scan_candidates` is given, falls back to a per-PGN scan
        (the NGX-1, which ignores the bulk query and reports a Format-2 structure we
        don't decode).
        """
        want = Op.TX_PGN_ENABLE_LIST if which == PgnList.TX else Op.RX_PGN_ENABLE_LIST
        frames = self.command(proto.cmd_get_pgn_list(which), want_op=want, window=2.0,
                              action="Get %s PGN List" % which.name)
        for f in frames:
            try:
                seq, pgns = proto.parse_pgn_list_part1(f)
            except ValueError:
                continue
            if seq == 1 and pgns:
                return pgns
        if scan_candidates:
            return self.get_pgn_list_by_scan(which, scan_candidates, progress=scan_progress)
        return []

    def raw_query(self, op: Op) -> bytes:
        """Send a no-arg query and return the first matching response's data bytes."""
        frames = self.command(proto.cmd_simple(op), want_op=int(op), action="Query %s" % op.name)
        return self._data(frames[0]) if frames else b""
