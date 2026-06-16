#!/usr/bin/env python3
"""
Regenerate actuisense/data/pgns.json from canboat's PGN database.

Source: https://raw.githubusercontent.com/canboat/canboat/master/docs/canboat.json
(Apache-2.0; see CREDITS.md). We keep only PGN number, a human name, and the
frame type (single vs fast-packet) — just enough to label the RX/TX filter rows.

Name heuristic: a PGN can have several canboat definitions (generic + vendor
variants). We prefer a *generic, non-hex-range* description: skip names starting
with "0x" (address-range placeholders); among the rest pick the shortest
(least vendor-specific); fall back to the first definition.

Usage:  python tools/gen_pgndb.py
"""

import json
import os
import urllib.request

URL = "https://raw.githubusercontent.com/canboat/canboat/master/docs/canboat.json"
OUT = os.path.join(os.path.dirname(__file__), "..", "actuisense", "data", "pgns.json")


def pick_name(candidates):
    # candidates: list of (description, is_fast)
    names = [c[0] for c in candidates if c[0]]
    if not names:
        return "(no name)"
    non_hex = [n for n in names if not n.startswith("0x")]
    # A "Vendor: subtype" name means this PGN is proprietary. Prefer a standard
    # (no-colon) name when one exists; else show a vendor example so the row is
    # still recognisable, tagged proprietary.
    standard = [n for n in non_hex if ":" not in n]
    if standard:
        return min(standard, key=len)
    if non_hex:
        return min(non_hex, key=len) + "  (proprietary)"
    return min(names, key=len)


def main():
    raw = urllib.request.urlopen(URL, timeout=60).read()
    doc = json.loads(raw)
    defs = doc.get("PGNs") or doc.get("pgns") or []

    grouped = {}
    for d in defs:
        n = d.get("PGN")
        if n is None:
            continue
        desc = (d.get("Description") or d.get("Id") or "").strip()
        is_fast = "fast" in (d.get("Type") or "").lower()
        grouped.setdefault(n, []).append((desc, is_fast))

    rows = []
    for n in sorted(grouped):
        cands = grouped[n]
        rows.append({"pgn": n, "name": pick_name(cands),
                     "fast": any(c[1] for c in cands)})

    bundle = {
        "_source": "canboat docs/canboat.json (Apache-2.0)",
        "_note": "PGN number/name/frame-type for the RX/TX filter list",
        "_generated_by": "tools/gen_pgndb.py",
        "version": doc.get("Version", ""),
        "pgns": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=0, ensure_ascii=False)
    print("wrote %d PGNs to %s" % (len(rows), os.path.normpath(OUT)))
    for n in (59392, 60928, 126720, 127512, 127514, 127751):
        nm = next((r["name"] for r in rows if r["pgn"] == n), "?")
        print("  %-7d %s" % (n, nm))


if __name__ == "__main__":
    main()
