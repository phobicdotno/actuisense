"""
BstFt firmware-transfer tests. The golden vectors are the exact frames logged by
Actisense Toolkit during a real NGX-1 update (3.032 -> 3.068) and recovered from a
raw HHD sniff of the data frames -- see docs/reverse-engineering/bstft/. No hardware.
"""
import zlib

import pytest

from actuisense import protocol as proto
from actuisense.protocol import FrameDecoder, decode_all


def _one(frame_bytes):
    frames = decode_all(frame_bytes)
    assert len(frames) == 1
    assert frames[0].crc_ok
    return frames[0]


# ---- MDT_START -------------------------------------------------------------

def test_mdt_start_golden():
    # Captured: TX MDT_START [54]  00 00 44 ...(11 zeros)... C8 9A 10 20 00 00 20 00 02 11 00 <filename>
    name = "NGX-1-Release-v3.068.1986.zip"
    expected_payload = bytes.fromhex(
        "000044" + "00" * 11 + "c8" + "9a102000" + "002000021100"
    ) + name.encode("ascii")
    assert len(expected_payload) == 54
    f = _one(proto.build_mdt_start(2101402, name))
    assert f.command == proto.MDT
    assert f.payload == expected_payload
    # the size field is little-endian at offset 15
    assert int.from_bytes(f.payload[15:19], "little") == 2101402


# ---- MDT_DATA --------------------------------------------------------------

@pytest.mark.parametrize("offset", [0, 200, 400, 600, 2101400])
def test_mdt_data_header(offset):
    chunk = bytes(range(200))[: min(200, 2101402 - offset)]
    f = _one(proto.build_mdt_data(offset, chunk))
    assert f.command == proto.FT
    # payload: [subtype 0x00][00 00][offset LE32][flag 00][chunk...]
    assert f.payload[0] == proto.Ft.DATA
    assert f.payload[1:3] == b"\x00\x00"
    assert int.from_bytes(f.payload[3:7], "little") == offset
    assert f.payload[7] == 0x00
    assert f.payload[8:] == chunk


def test_mdt_data_offset0_matches_capture():
    # Captured first DATA frame body: c1 d0 00 00 00 00 00 00 00 00 50 4b 03 04 ...
    chunk = bytes.fromhex("504b0304")  # "PK\x03\x04" zip local-file header
    f = _one(proto.build_mdt_data(0, chunk))
    assert f.payload.hex() == "0000000000000000" + "504b0304"


# ---- MDT_END ---------------------------------------------------------------

def test_mdt_end_golden():
    # Captured: TX MDT_END [22]  01 ...(13 zeros)... 9A 10 20 00 41 06 34 C2
    f = _one(proto.build_mdt_end(2101402, 0xC2340641))
    assert f.command == proto.MDT
    assert f.payload.hex() == "01" + "00" * 13 + "9a102000" + "410634c2"
    assert int.from_bytes(f.payload[14:18], "little") == 2101402
    assert int.from_bytes(f.payload[18:22], "little") == 0xC2340641


# ---- RX parsing ------------------------------------------------------------

def test_parse_mdt_response_start_and_end():
    name = bytes.fromhex("3b002ee70400000000000000")  # 8-byte NAME region etc.
    start = _one(proto.build_frame(proto.MDT, bytes((0x00, 0x01)) + name))
    end = _one(proto.build_frame(proto.MDT, bytes((0x01, 0x01)) + name))
    assert proto.parse_mdt_response(start) == (0x00, 0x01)   # Start, OK
    assert proto.parse_mdt_response(end) == (0x01, 0x01)     # End, OK


def test_parse_ft_ack_xon_xoff():
    ack = _one(proto.build_frame(proto.FT, bytes.fromhex("010000" + "c8000000" + "0100000000")))
    xoff = _one(proto.build_frame(proto.FT, bytes.fromhex("110000" + "58fc0000" + "0100000000")))
    xon = _one(proto.build_frame(proto.FT, bytes.fromhex("100000" + "58fc0000" + "0100000000")))
    assert proto.parse_ft(ack) == (proto.Ft.ACK, 200)
    assert proto.parse_ft(xoff) == (proto.Ft.XOFF, 0xFC58)
    assert proto.parse_ft(xon) == (proto.Ft.XON, 0xFC58)
    # non-FT frame -> None
    assert proto.parse_ft(_one(proto.cmd_get_operating_mode())) is None


# ---- end-to-end push over a fake transport ---------------------------------

class _FakeDevice:
    """Minimal NGX stand-in: ACKs MDT_START and MDT_END, records data frames."""

    def __init__(self):
        self.written = bytearray()
        self._out = bytearray()
        self._dec = FrameDecoder()

    def write(self, data):
        self.written += data
        for f in self._dec.feed(data):
            if f.command == proto.MDT:
                if len(f.payload) >= 3 and f.payload[2] == 0x44:          # START request
                    self._out += proto.build_frame(proto.MDT, bytes((0x00, 0x01)) + bytes(12))
                elif f.payload[:1] == b"\x01":                            # END request
                    self._out += proto.build_frame(proto.MDT, bytes((0x01, 0x01)) + bytes(12))

    def read(self, n=4096):
        if self._out:
            out = bytes(self._out[:n]); del self._out[:n]; return out
        return b""

    def close(self):
        pass

    @property
    def name(self):
        return "fake"


def test_push_firmware_streams_whole_file_and_acks():
    from actuisense.device import Gateway
    data = bytes((i * 7 + 3) & 0xFF for i in range(2050))   # 11 chunks (10x200 + 1x50)
    dev = _FakeDevice()
    gw = Gateway(dev)
    progress = []
    crc = gw.push_firmware(data, "fw.zip", crc=0xC2340641, progress=lambda s, t: progress.append((s, t)))
    assert crc == 0xC2340641

    # Reassemble exactly what the device received from the DATA frames.
    frames = decode_all(bytes(dev.written))
    data_frames = [f for f in frames if f.command == proto.FT]
    assert len(data_frames) == (len(data) + 199) // 200      # 11 chunks
    rebuilt = bytearray(len(data))
    for f in data_frames:
        off = int.from_bytes(f.payload[3:7], "little")
        rebuilt[off:off + len(f.payload) - 8] = f.payload[8:]
    assert bytes(rebuilt) == data

    # START and END frames present, and progress reached 100%.
    mdt = [f for f in frames if f.command == proto.MDT]
    assert any(f.payload[2:3] == b"\x44" for f in mdt)        # START
    assert any(f.payload[:1] == b"\x01" for f in mdt)         # END
    assert progress[-1] == (len(data), len(data))


def test_push_firmware_default_crc_is_placeholder_zlib():
    data = b"hello firmware" * 20
    assert proto.firmware_crc(data) == zlib.crc32(data) & 0xFFFFFFFF
