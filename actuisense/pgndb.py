"""
PGN database for the RX/TX filter list.

Bundled `data/pgns.json` carries the NMEA 2000 PGN numbers, human names and frame
type (single vs fast-packet), derived from canboat (see CREDITS.md). The UI uses it
to label rows; PGNs not in the database still work — they show as "(unknown PGN)".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

try:  # Python 3.9+: importlib.resources.files
    from importlib.resources import files as _files
except ImportError:  # pragma: no cover
    _files = None


@dataclass(frozen=True)
class PgnInfo:
    pgn: int
    name: str
    fast: bool = False
    inst: Optional[tuple] = None  # (bit_offset, bit_length) of the Instance field, if any

    @property
    def label(self) -> str:
        return "%d  %s" % (self.pgn, self.name)


def _extract_bits(data: bytes, offset: int, length: int) -> Optional[int]:
    """Read a little-endian bit field of `length` bits at `offset` from `data`.

    NMEA 2000 packs fields LSB-first; returns None if the field runs past the data."""
    val = 0
    for i in range(length):
        bi = (offset + i) // 8
        if bi >= len(data):
            return None
        val |= ((data[bi] >> ((offset + i) % 8)) & 1) << i
    return val


def _load_raw() -> dict:
    if _files is not None:
        data = _files("actuisense").joinpath("data/pgns.json").read_text(encoding="utf-8")
    else:  # pragma: no cover
        import os
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "data", "pgns.json"), encoding="utf-8") as f:
            return json.load(f)
    return json.loads(data)


@lru_cache(maxsize=1)
def _index() -> Dict[int, PgnInfo]:
    raw = _load_raw()
    out: Dict[int, PgnInfo] = {}
    for r in raw.get("pgns", []):
        try:
            n = int(r["pgn"])
        except (KeyError, TypeError, ValueError):
            continue
        inst = r.get("inst")
        inst_t = (int(inst[0]), int(inst[1])) if isinstance(inst, (list, tuple)) and len(inst) == 2 else None
        out[n] = PgnInfo(pgn=n, name=str(r.get("name", "")).strip() or "(no name)",
                         fast=bool(r.get("fast", False)), inst=inst_t)
    return out


class PgnDb:
    """Lookup + search over the bundled PGN catalogue."""

    def __init__(self) -> None:
        self._by_pgn = _index()

    def __len__(self) -> int:
        return len(self._by_pgn)

    def all(self) -> List[PgnInfo]:
        return [self._by_pgn[k] for k in sorted(self._by_pgn)]

    def get(self, pgn: int) -> PgnInfo:
        info = self._by_pgn.get(pgn)
        return info if info is not None else PgnInfo(pgn=pgn, name="(unknown PGN)", fast=False)

    def name(self, pgn: int) -> str:
        return self.get(pgn).name

    def instance(self, pgn: int, data: bytes) -> Optional[int]:
        """The device-instance value carried in this PGN's frame `data`, or None.

        Returns None when the PGN has no Instance field, the frame is too short, or
        the instance reads as the N2K 'unavailable' sentinel (all 1s) -- in which case
        callers should fall back to grouping by source alone."""
        info = self.get(pgn)
        if info.inst is None:
            return None
        offset, length = info.inst
        val = _extract_bits(bytes(data), offset, length)
        if val is None or val == (1 << length) - 1:
            return None
        return val

    def search(self, text: str) -> List[PgnInfo]:
        """Filter by PGN number or case-insensitive substring of the name."""
        t = text.strip().lower()
        if not t:
            return self.all()
        rows = []
        for info in self.all():
            if t in str(info.pgn) or t in info.name.lower():
                rows.append(info)
        return rows
