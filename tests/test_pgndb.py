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
