"""Tests for the human-readable PGN-list save/load format (pure, no I/O)."""

from actuisense.pgnfile import dump_lists, parse_lists


def test_roundtrip_preserves_sets():
    rx = {60928, 59392, 126992}
    tx = {127245, 130306}
    text = dump_lists(rx, tx, when="2026-06-18T00:00:00", gateway="NGX-1", mode="FILTER")
    got_rx, got_tx = parse_lists(text)
    assert got_rx == rx
    assert got_tx == tx


def test_dump_is_human_readable_and_sorted():
    text = dump_lists({126992, 59392}, {130306, 127245})
    lines = text.splitlines()
    assert "[RX]" in lines and "[TX]" in lines
    rx_i, tx_i = lines.index("[RX]"), lines.index("[TX]")
    rx_pgns = [int(l.split("#")[0]) for l in lines[rx_i + 1:tx_i] if l.strip()]
    assert rx_pgns == sorted(rx_pgns)  # sorted ascending within a section


def test_parse_is_lenient():
    text = (
        "# a comment\n"
        "59392 stray-before-section\n"  # ignored: no section yet
        "[rx]\n"
        "60928   # ISO Address Claim\n"
        "\n"
        "  # blank + comment lines skipped\n"
        "[Tx]\n"
        "127245\n"
        "130306 # Wind Data\n"
    )
    rx, tx = parse_lists(text)
    assert rx == {60928}
    assert tx == {127245, 130306}


def test_parse_rejects_non_numeric_pgn():
    import pytest
    with pytest.raises(ValueError):
        parse_lists("[RX]\nnot-a-number\n")


def test_dump_without_db_omits_names():
    text = dump_lists({60928}, set())
    assert "60928" in text
    assert "#" in text  # header comments still present
    # the PGN line itself has no trailing name comment
    pgn_line = [l for l in text.splitlines() if l.strip() == "60928"]
    assert pgn_line == ["60928"]
