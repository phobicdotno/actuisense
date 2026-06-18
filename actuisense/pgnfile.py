"""Human-readable save/load of the Rx/Tx PGN enable lists.

The on-disk format is a small annotated text file with two sections::

    # AcTuiSense PGN enable lists
    # saved: 2026-06-18T12:34:56
    # gateway: NGX-1
    # mode: FILTER
    #
    # One PGN per line under [RX] / [TX]; text after '#' is a comment (the name).
    [RX]
    59392    # ISO Acknowledgment
    60928    # ISO Address Claim

    [TX]
    127245   # Rudder
    130306   # Wind Data

Loading ignores comments, blank lines and the name annotations -- only the PGN
numbers under each section are read -- so a hand-edited file round-trips cleanly.
These are pure functions (no file I/O) to keep them trivially testable; callers
read/write the text.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set, Tuple

_RX_HEADER = "[RX]"
_TX_HEADER = "[TX]"


def dump_lists(rx: Iterable[int], tx: Iterable[int], db=None, *,
               gateway: Optional[str] = None, mode: Optional[str] = None,
               when: Optional[str] = None) -> str:
    """Render the enabled RX/TX PGN sets as the annotated text format above.

    `db` (a PgnDb) is optional; when given, each PGN line gets a `# name` comment.
    `when` lets the caller pass a fixed timestamp (else it is omitted) so the output
    is deterministic for tests.
    """
    def _name(pgn: int) -> str:
        if db is None:
            return ""
        try:
            return db.name(pgn) or ""
        except Exception:
            return ""

    lines = ["# AcTuiSense PGN enable lists"]
    if when:
        lines.append("# saved: %s" % when)
    if gateway:
        lines.append("# gateway: %s" % gateway)
    if mode:
        lines.append("# mode: %s" % mode)
    lines.append("#")
    lines.append("# One PGN per line under [RX] / [TX]; text after '#' is a comment.")

    for header, pgns in ((_RX_HEADER, rx), (_TX_HEADER, tx)):
        lines.append("")
        lines.append(header)
        for pgn in sorted(set(pgns)):
            name = _name(pgn)
            lines.append("%-8d # %s" % (pgn, name) if name else str(pgn))
    return "\n".join(lines) + "\n"


def parse_lists(text: str) -> Tuple[Set[int], Set[int]]:
    """Parse the text format back into (rx_set, tx_set).

    Lenient: blank lines and `#` comments are skipped, inline `# name` annotations
    are stripped, section headers are matched case-insensitively, and any PGN line
    outside a known section is ignored. A non-numeric PGN token raises ValueError.
    """
    rx: Set[int] = set()
    tx: Set[int] = set()
    target: Optional[Set[int]] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low == _RX_HEADER.lower():
            target = rx
            continue
        if low == _TX_HEADER.lower():
            target = tx
            continue
        token = line.split("#", 1)[0].strip()
        if not token:
            continue
        if target is None:
            continue  # a PGN before any [RX]/[TX] header -- ignore
        target.add(int(token))
    return rx, tx
