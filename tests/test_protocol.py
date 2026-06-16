"""
Protocol tests. The golden frames are REAL bytes captured from an Actisense NGT-1
during development (config + readback), so these lock the encoder/decoder to what
the hardware actually accepts and emits.
"""

from actuisense import protocol as p
from actuisense.protocol import Op, OperatingMode, PgnList


def hx(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# --- build_frame golden vectors (exact bytes the NGT-1 accepted) ------------

def test_set_operating_mode_rxall():
    assert p.cmd_set_operating_mode(OperatingMode.RX_ALL) == hx("10 02 a1 03 11 02 00 49 10 03")


def test_tx_pgn_enable_golden():
    assert p.cmd_set_pgn(PgnList.TX, 127512, True) == hx("10 02 a1 06 47 18 f2 01 00 01 06 10 03")
    assert p.cmd_set_pgn(PgnList.TX, 127514, True) == hx("10 02 a1 06 47 1a f2 01 00 01 04 10 03")
    assert p.cmd_set_pgn(PgnList.TX, 127751, True) == hx("10 02 a1 06 47 07 f3 01 00 01 16 10 03")


def test_simple_commands_golden():
    assert p.cmd_activate_pgn_lists() == hx("10 02 a1 01 4b 13 10 03")
    assert p.cmd_get_pgn_list(PgnList.TX) == hx("10 02 a1 01 49 15 10 03")
    assert p.cmd_get_pgn_list(PgnList.RX) == hx("10 02 a1 01 48 16 10 03")
    assert p.cmd_commit_eeprom() == hx("10 02 a1 01 01 5d 10 03")


def test_checksum_makes_total_zero():
    # the byte stream command..crc must sum to 0 mod 256
    frame = p.cmd_set_pgn(PgnList.TX, 127751, True)
    inner = frame[2:-2]  # strip DLE STX ... DLE ETX
    assert sum(inner) % 256 == 0


def test_dle_escaping_in_payload_and_crc():
    # a payload byte equal to DLE (0x10) must be doubled
    f = p.build_frame(p.ACMD_SEND, bytes((0x10, 0x10)))
    body = f[2:-2]
    # command 0xA1, len 0x02, then 0x10 0x10 (each escaped -> doubled)
    assert body[:2] == bytes((0xA1, 0x02))
    assert body.count(0x10) == 4  # two payload DLEs, each doubled


# --- decoder round-trips and real responses ---------------------------------

def test_decode_roundtrip():
    original = p.cmd_set_pgn(PgnList.TX, 130306, True)
    frames = p.decode_all(original)
    assert len(frames) == 1
    f = frames[0]
    assert f.crc_ok
    assert f.command == p.ACMD_SEND
    assert f.opcode == Op.TX_PGN_ENABLE
    # payload = opcode + pgn(LE32) + enable
    assert f.payload == bytes((Op.TX_PGN_ENABLE,)) + p.pgn_le(130306) + bytes((1,))


def test_decode_real_nak_frame():
    # ACMD_RECV with NEGATIVE_ACK opcode -> is_nak (synthetic but well-formed)
    frame = p.build_frame(p.ACMD_RECV, bytes((Op.NEGATIVE_ACK, 0x00)))
    f = p.decode_all(frame)[0]
    assert f.crc_ok and f.is_nak


def test_parse_real_tx_list_response():
    # Real GetTxPGNList part-1 reply captured from the NGT-1 (with our 3 PGNs added).
    raw = hx(
        "10 02 a0 45 49 01 0e 00 07 f9 03 00 00 00 00 00 0e "
        "00 e8 00 00 00 ea 00 00 00 eb 00 00 00 ec 00 00 00 ee 00 00 "
        "00 ed 01 00 00 ee 01 00 00 ef 01 00 11 f0 01 00 14 f0 01 00 "
        "16 f0 01 00 18 f2 01 00 1a f2 01 00 07 f3 01 00 2d 10 03"
    )
    f = p.decode_all(raw)[0]
    assert f.crc_ok
    seq, pgns = p.parse_pgn_list_part1(f)
    assert seq == 1
    assert pgns == [59392, 59904, 60160, 60416, 60928, 126208, 126464,
                    126720, 126993, 126996, 126998, 127512, 127514, 127751]
    # the three we enabled this session are present
    assert {127512, 127514, 127751} <= set(pgns)


def test_two_frames_in_one_stream():
    stream = p.cmd_activate_pgn_lists() + p.cmd_commit_eeprom()
    frames = p.decode_all(stream)
    assert [f.opcode for f in frames] == [Op.ACTIVATE_PGN_ENABLE_LISTS, Op.COMMIT_TO_EEPROM]
