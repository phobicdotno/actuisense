from actuisense.pgndb import PgnDb, PgnInfo


def test_db_loads_and_has_known_pgns():
    db = PgnDb()
    assert len(db) > 200
    assert db.name(60928) == "ISO Address Claim"
    assert "AGS Status" in db.name(127514)


def test_unknown_pgn_is_synthesised():
    db = PgnDb()
    info = db.get(999999)
    assert isinstance(info, PgnInfo)
    assert info.pgn == 999999
    assert "unknown" in info.name.lower()


def test_search_by_number_and_name():
    db = PgnDb()
    by_num = db.search("127512")
    assert any(i.pgn == 127512 for i in by_num)
    by_name = db.search("ags")
    pgns = {i.pgn for i in by_name}
    assert {127512, 127514}.issubset(pgns)


def test_all_is_sorted():
    db = PgnDb()
    pgns = [i.pgn for i in db.all()]
    assert pgns == sorted(pgns)


def test_instance_extraction_from_frame_data():
    db = PgnDb()
    # 127488 Engine Parameters, Rapid Update: Engine Instance = data byte 0 (8 bits)
    assert db.instance(127488, bytes([0, 0x10, 0x20])) == 0
    assert db.instance(127488, bytes([1, 0x10, 0x20])) == 1
    assert db.instance(127488, bytes([3])) == 3
    # 130312 Temperature: Instance is byte 1 (after the SID byte)
    assert db.instance(130312, bytes([0x55, 2, 0x00])) == 2
    # 127505 Fluid Level: Instance is the low nibble of byte 0 (4 bits)
    assert db.instance(127505, bytes([0x35])) == 5
    # 0xFF (all-ones) is the N2K 'unavailable' sentinel -> None
    assert db.instance(127488, bytes([0xFF])) is None
    # a PGN with no Instance field, or too-short data -> None
    assert db.instance(126992, bytes([1, 2, 3])) is None
    assert db.instance(127488, b"") is None
