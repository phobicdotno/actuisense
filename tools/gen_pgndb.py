#!/usr/bin/env python3
"""
Regenerate actuisense/data/pgns.json from canboat's PGN database.

Source: https://raw.githubusercontent.com/canboat/canboat/master/docs/canboat.json
(Apache-2.0; see CREDITS.md). We keep PGN number, a human name, the frame type
(single vs fast-packet), and — when the PGN carries one — the bit position of its
Instance field, so the bus monitor can split e.g. two engines reporting the same
PGN into separate rows. That is just enough to label the RX/TX filter rows and to
group bus traffic by device instance.

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


def _instance_field(d):
    """Return [bit_offset, bit_length] of the PGN's Instance field, or None.

    canboat names every instance field with an Id ending in 'instance'
    (instance, engineInstance, batteryInstance, dataSourceInstance, ...). We take
    the first one so two devices reporting the same PGN can be told apart by it.
    """
    for f in d.get("Fields", []):
        fid = (f.get("Id") or "").lower()
        if fid.endswith("instance"):
            off, length = f.get("BitOffset"), f.get("BitLength")
            if isinstance(off, int) and isinstance(length, int):
                return [off, length]
    return None


def main():
    raw = urllib.request.urlopen(URL, timeout=60).read()
    doc = json.loads(raw)
    defs = doc.get("PGNs") or doc.get("pgns") or []

    grouped = {}
    instances = {}
    for d in defs:
        n = d.get("PGN")
        if n is None:
            continue
        desc = (d.get("Description") or d.get("Id") or "").strip()
        is_fast = "fast" in (d.get("Type") or "").lower()
        grouped.setdefault(n, []).append((desc, is_fast))
        if n not in instances:
            inst = _instance_field(d)
            if inst is not None:
                instances[n] = inst

    rows = []
    for n in sorted(grouped):
        cands = grouped[n]
        row = {"pgn": n, "name": pick_name(cands), "fast": any(c[1] for c in cands)}
        if n in instances:
            row["inst"] = instances[n]  # [bit_offset, bit_length] of the Instance field
        rows.append(row)

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
