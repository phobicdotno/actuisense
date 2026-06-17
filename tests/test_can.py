"""
CAN-id decode + candump line parsing. Golden vectors taken from real PFC200
can0 captures (e.g. 0x19F21803 = PGN 127512 from source 3, seen when the NGT-1
forwards the AGS Config Status PGN onto the bus).
"""

from actuisense.can import CanFrame, GLOBAL_DEST, parse_can_id, parse_candump_line


def test_parse_can_id_pdu2_broadcast():
    # 0x19F21803: prio 6, PGN 127512 (0x1F218), source 3, broadcast.
    cid = parse_can_id(0x19F21803)
    assert cid.priority == 6
    assert cid.pgn == 127512
    assert cid.source == 3
    assert cid.dest == GLOBAL_DEST


def test_parse_can_id_pdu2_second_vector():
    # 0x19F30703: PGN 127751 from source 3.
    cid = parse_can_id(0x19F30703)
    assert cid.pgn == 127751
    assert cid.source == 3
    assert cid.dest == GLOBAL_DEST


def test_parse_can_id_pdu1_destination_specific():
    # PF=0xEF (239, < 240 -> PDU1): PS is the destination, not part of the PGN.
    # fields: prio 6, dp 0, pf 0xEF, ps(dest) 0x05, src 0x21.
    cid = parse_can_id((6 << 26) | (0xEF << 16) | (0x05 << 8) | 0x21)
    assert cid.priority == 6
    assert cid.pgn == 0xEF00  # 61184 — PS excluded
    assert cid.dest == 0x05
    assert cid.source == 0x21


def test_can_frame_from_raw_decodes_fields():
    f = CanFrame.from_raw(1623456789.123456, 0x19F21803, bytes.fromhex("FFFF7F2701FF0000"))
    assert f.pgn == 127512
    assert f.source == 3
    assert f.data == bytes.fromhex("FFFF7F2701FF0000")


def test_parse_candump_line_log_format():
    f = parse_candump_line("(1623456789.123456) can0 19F21803#FFFF7F2701FF0000")
    assert f is not None
    assert f.timestamp == 1623456789.123456
    assert f.pgn == 127512
    assert f.source == 3
    assert f.data == bytes.fromhex("FFFF7F2701FF0000")


def test_parse_candump_line_empty_data():
    f = parse_candump_line("(1623456789.000000) can0 18EAFF03#")
    assert f is not None
    assert f.data == b""


def test_parse_candump_line_ignores_blank_comment_and_fd():
    assert parse_candump_line("") is None
    assert parse_candump_line("   ") is None
    assert parse_candump_line("# a comment") is None
    # CAN-FD frame (## separator) is not NMEA 2000.
    assert parse_candump_line("(1.0) can0 19F21803##1FFFF") is None


def test_parse_candump_line_rejects_garbage():
    assert parse_candump_line("not a candump line") is None
    assert parse_candump_line("(bad) can0 19F21803#FF") is None
    assert parse_candump_line("(1.0) can0 ZZZ#FF") is None
