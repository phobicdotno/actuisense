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

    @property
    def label(self) -> str:
        return "%d  %s" % (self.pgn, self.name)


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
        out[n] = PgnInfo(pgn=n, name=str(r.get("name", "")).strip() or "(no name)",
                         fast=bool(r.get("fast", False)))
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
