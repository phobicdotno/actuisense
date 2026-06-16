"""
Device-layer tests using a fake transport that replays REAL NGT-1 responses, so the
parsing path (operating mode, PGN lists, NAK) is exercised end-to-end, no hardware.
"""

import pytest

from actuisense import protocol as proto
from actuisense.device import Gateway, NakError, Transport, open_transport
from actuisense.protocol import OperatingMode, Op, PgnList


def hx(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# Real frames captured from an NGT-1 this session:
RESP_MODE_RXALL = hx("10 02 a0 0e 11 01 0e 00 07 f9 03 00 00 00 00 00 02 00 2d 10 03")
RESP_TX_LIST = hx(
    "10 02 a0 45 49 01 0e 00 07 f9 03 00 00 00 00 00 0e "
    "00 e8 00 00 00 ea 00 00 00 eb 00 00 00 ec 00 00 00 ee 00 00 "
    "00 ed 01 00 00 ee 01 00 00 ef 01 00 11 f0 01 00 14 f0 01 00 "
    "16 f0 01 00 18 f2 01 00 1a f2 01 00 07 f3 01 00 2d 10 03"
)
RESP_NAK = proto.build_frame(proto.ACMD_RECV, bytes((Op.NEGATIVE_ACK, 0x00, 0x46)))


class FakeTransport(Transport):
    """Loads a canned reply into its read buffer when the matching command is written."""

    def __init__(self, replies: dict):
        self._replies = replies          # opcode -> response bytes
        self._buf = bytearray()
        self.written = []

    def read(self, max_bytes: int = 4096) -> bytes:
        if not self._buf:
            return b""
        out = bytes(self._buf[:max_bytes])
        del self._buf[:max_bytes]
        return out

    def write(self, data: bytes) -> None:
        self.written.append(data)
        for f in proto.decode_all(data):
            if f.opcode in self._replies:
                self._buf += self._replies[f.opcode]

    def close(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "fake"


def make_gw(replies):
    return Gateway(FakeTransport(replies), response_window=0.05)


def test_get_operating_mode():
    gw = make_gw({Op.OPERATING_MODE: RESP_MODE_RXALL})
    assert gw.get_operating_mode() == OperatingMode.RX_ALL


def test_get_tx_pgn_list_parses_real_response():
    gw = make_gw({Op.TX_PGN_ENABLE_LIST: RESP_TX_LIST})
    pgns = gw.get_pgn_list(PgnList.TX)
    assert {127512, 127514, 127751}.issubset(set(pgns))
    assert len(pgns) == 14


def test_nak_raises():
    gw = make_gw({Op.TX_PGN_ENABLE: RESP_NAK})
    with pytest.raises(NakError):
        gw.set_pgn(PgnList.TX, 127512, True)


def test_set_pgn_writes_expected_bytes():
    ft = FakeTransport({})
    gw = Gateway(ft, response_window=0.02)
    gw.set_pgn(PgnList.TX, 127751, True)
    assert ft.written[-1] == hx("10 02 a1 06 47 07 f3 01 00 01 16 10 03")


def test_open_transport_tcp_parsing(monkeypatch):
    # don't actually connect -- just verify spec routing
    created = {}

    class FakeTcp:
        def __init__(self, host, port, **kw):
            created["host"], created["port"] = host, port

    monkeypatch.setattr("actuisense.device.TcpTransport", FakeTcp)
    open_transport("tcp://192.168.1.50:60002")
    assert created == {"host": "192.168.1.50", "port": 60002}
