"""
Command-line interface. Scriptable counterpart to the TUI:

    actuisense info   -p /dev/ttyUSB0
    actuisense mode   rxall -p COM5 --commit
    actuisense enable tx 127512 127514 127751 -p /dev/ttyUSB0 --commit
    actuisense disable rx 130306 -p /dev/ttyUSB0
    actuisense list   tx -p /dev/ttyUSB0
    actuisense tui    -p tcp://192.168.1.50:60002
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .device import Gateway, GatewayError, open_transport
from .pgndb import PgnDb
from .protocol import OperatingMode, PgnList

_WHICH = {"rx": PgnList.RX, "tx": PgnList.TX}
_MODE = {"filter": OperatingMode.FILTER, "rxall": OperatingMode.RX_ALL}


def _add_conn(sp: argparse.ArgumentParser, required: bool = True) -> None:
    sp.add_argument("-p", "--port", required=required, default=None,
                    help="serial device (/dev/ttyUSB0, COM5) or tcp://host[:port]")
    sp.add_argument("-b", "--baud", type=int, default=115200, help="serial baud (default 115200)")


def _add_wago(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--host", required=True, help="WAGO PLC host/IP (e.g. 10.0.0.202)")
    sp.add_argument("-u", "--user", required=True, help="SSH username (e.g. root)")
    sp.add_argument("-P", "--password", required=True, help="SSH password")
    sp.add_argument("--iface", default="can0", help="CAN interface to listen on (default can0)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="actuisense",
                                 description="Configure Actisense NMEA 2000 gateways from the terminal.")
    ap.add_argument("--version", action="version", version="actuisense " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="show hardware/operating mode and the Rx/Tx PGN lists")
    _add_conn(p_info)

    p_mode = sub.add_parser("mode", help="set operating mode (filter | rxall)")
    p_mode.add_argument("mode", choices=_MODE.keys())
    _add_conn(p_mode)
    p_mode.add_argument("--commit", action="store_true", help="persist to EEPROM")

    for name, help_ in (("enable", "enable PGNs in the Rx/Tx list"),
                        ("disable", "disable PGNs in the Rx/Tx list")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("which", choices=_WHICH.keys())
        p.add_argument("pgns", nargs="+", type=int, help="one or more PGN numbers")
        _add_conn(p)
        p.add_argument("--commit", action="store_true", help="persist to EEPROM")

    p_list = sub.add_parser("list", help="print the enabled PGNs in a list")
    p_list.add_argument("which", choices=_WHICH.keys())
    _add_conn(p_list)

    p_save = sub.add_parser("save", help="save the Rx/Tx enable lists to a human-readable file")
    p_save.add_argument("file", help="output file path")
    _add_conn(p_save)

    p_load = sub.add_parser("load", help="load Rx/Tx enable lists from a file and apply them")
    p_load.add_argument("file", help="input file path")
    _add_conn(p_load)
    p_load.add_argument("--commit", action="store_true", help="persist to EEPROM")

    p_raw = sub.add_parser("raw", help="dump raw gateway diagnostic queries (read-only, hex)")
    _add_conn(p_raw)

    p_tui = sub.add_parser("tui", help="launch the full-screen terminal UI")
    _add_conn(p_tui, required=False)  # no -p: start disconnected, pick via Connection dialog

    p_mon = sub.add_parser(
        "monitor",
        help="listen on a WAGO PLC's can0 over SSH and print decoded N2K frames")
    _add_wago(p_mon)
    p_mon.add_argument("-n", "--count", type=int, default=0,
                       help="stop after N frames (0 = run until Ctrl+C)")

    return ap


def _print_list(db: PgnDb, title: str, pgns: List[int]) -> None:
    print("%s (%d):" % (title, len(pgns)))
    for n in pgns:
        print("  %-7d %s" % (n, db.name(n)))


def _scan_progress(done: int, total: int) -> None:
    """Stderr progress shown only when a gateway needs the slow per-PGN scan (NGX-1)."""
    if done < total:
        print("  scanning PGNs %d/%d ..." % (done, total), end="\r", file=sys.stderr, flush=True)
    else:
        print(" " * 40, end="\r", file=sys.stderr, flush=True)  # clear the line


def cmd_info(gw: Gateway, db: PgnDb) -> int:
    print("Gateway: %s" % gw.name)
    mode = gw.get_operating_mode()
    print("Operating mode: %s" % (mode.name if mode else "unknown"))
    cands = [i.pgn for i in db.all()]
    if mode == OperatingMode.RX_ALL:
        print("Rx enabled: (RX_ALL -- the Rx list is not applied; all PGNs are received)")
    else:
        _print_list(db, "Rx enabled",
                    gw.get_pgn_list(PgnList.RX, scan_candidates=cands, scan_progress=_scan_progress))
    _print_list(db, "Tx enabled",
                gw.get_pgn_list(PgnList.TX, scan_candidates=cands, scan_progress=_scan_progress))
    return 0


def cmd_mode(gw: Gateway, mode: OperatingMode, commit: bool) -> int:
    gw.set_operating_mode(mode)
    print("Operating mode set to %s" % mode.name)
    if commit:
        gw.commit_eeprom()
        print("Committed to EEPROM.")
    return 0


def cmd_enable(gw: Gateway, db: PgnDb, which: PgnList, pgns: List[int],
               enable: bool, commit: bool) -> int:
    verb = "Enabling" if enable else "Disabling"
    print("%s in %s list: %s" % (verb, which.name, ", ".join(str(p) for p in pgns)))
    gw.enable_pgns(which, pgns, enable=enable, activate=True, commit=commit)
    for p in pgns:
        print("  %-7d %s" % (p, db.name(p)))
    print("Activated." + ("  Committed to EEPROM." if commit else "  (RAM only -- add --commit to persist)"))
    return 0


def cmd_list(gw: Gateway, db: PgnDb, which: PgnList) -> int:
    cands = [i.pgn for i in db.all()]
    _print_list(db, "%s enabled" % which.name,
                gw.get_pgn_list(which, scan_candidates=cands, scan_progress=_scan_progress))
    return 0


def cmd_save(gw: Gateway, db: PgnDb, path: str) -> int:
    """Read both enable lists off the gateway and write them to a readable file."""
    import datetime

    from .pgnfile import dump_lists
    cands = [i.pgn for i in db.all()]
    rx = gw.get_pgn_list(PgnList.RX, scan_candidates=cands, scan_progress=_scan_progress)
    tx = gw.get_pgn_list(PgnList.TX, scan_candidates=cands, scan_progress=_scan_progress)
    mode = gw.get_operating_mode()
    text = dump_lists(rx, tx, db, gateway=gw.name,
                      mode=(mode.name if mode else None),
                      when=datetime.datetime.now().isoformat(timespec="seconds"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("Saved %d RX + %d TX PGNs to %s" % (len(set(rx)), len(set(tx)), path))
    return 0


def cmd_load(gw: Gateway, db: PgnDb, path: str, commit: bool) -> int:
    """Make the gateway's enable lists match a saved file (enable missing, disable extra)."""
    from .pgnfile import parse_lists
    with open(path, "r", encoding="utf-8") as f:
        rx_want, tx_want = parse_lists(f.read())
    cands = [i.pgn for i in db.all()]
    changed = 0
    for which, want in ((PgnList.RX, rx_want), (PgnList.TX, tx_want)):
        cur = set(gw.get_pgn_list(which, scan_candidates=cands, scan_progress=_scan_progress))
        to_enable = sorted(want - cur)
        to_disable = sorted(cur - want)
        if not to_enable and not to_disable:
            print("%s: already matches (%d PGNs)" % (which.name, len(want)))
            continue
        gw.set_pgns_bulk(which, [(p, True) for p in to_enable] + [(p, False) for p in to_disable])
        gw.activate()
        changed += len(to_enable) + len(to_disable)
        print("%s: +%d enabled, -%d disabled (now %d)"
              % (which.name, len(to_enable), len(to_disable), len(want)))
    if changed and commit:
        gw.commit_eeprom()
        print("Committed to EEPROM.")
    elif changed:
        print("(RAM only -- add --commit to persist)")
    return 0


def cmd_raw(gw: Gateway) -> int:
    """Read-only dump of the gateway's diagnostic queries as hex.

    These payloads are vendor-binary; AcTuiSense does not guess their field
    meanings. Shown raw so you can inspect them (and so a future parser has data).
    """
    from .protocol import Op
    print("Gateway: %s  (raw diagnostic queries -- read only)" % gw.name)
    for op in (Op.HARDWARE_INFO, Op.PRODUCT_INFO_N2K, Op.SUPPORTED_PGN_LIST,
               Op.TOTAL_TIME, Op.OPERATING_MODE):
        data = gw.raw_query(op)
        print("  %-18s [%3d]  %s" % (op.name, len(data), data.hex(" ") or "(no reply)"))
    return 0


def cmd_monitor(db: PgnDb, host: str, user: str, password: str, iface: str, count: int) -> int:
    """SSH into a WAGO PLC, run candump on `iface`, and print decoded N2K frames.

    Read-only: this never writes to the bus or the gateway. Stops after `count`
    frames (if > 0) or on Ctrl+C.
    """
    from .wago import CandumpSource, WagoError
    try:
        source = CandumpSource.over_ssh(host=host, username=user, password=password, iface=iface)
    except WagoError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    print("Listening on %s  (Ctrl+C to stop)" % source.name)
    print("%-16s %-7s %-3s %-3s  %s" % ("time", "pgn", "src", "dst", "data"))
    n = 0
    try:
        for f in source.frames():
            print("%-16.6f %-7d %-3d %-3d  %s  %s"
                  % (f.timestamp, f.pgn, f.source, f.dest, f.data.hex(" "), db.name(f.pgn)))
            n += 1
            if count and n >= count:
                break
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        source.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "tui":
        from .tui import run_tui
        return run_tui(args.port, args.baud)

    if args.cmd == "monitor":
        return cmd_monitor(PgnDb(), args.host, args.user, args.password, args.iface, args.count)

    db = PgnDb()
    try:
        transport = open_transport(args.port, baud=args.baud)
    except Exception as e:
        print("error: cannot open %s: %s" % (args.port, e), file=sys.stderr)
        return 2

    try:
        with Gateway(transport) as gw:
            if args.cmd == "info":
                return cmd_info(gw, db)
            if args.cmd == "mode":
                return cmd_mode(gw, _MODE[args.mode], args.commit)
            if args.cmd == "enable":
                return cmd_enable(gw, db, _WHICH[args.which], args.pgns, True, args.commit)
            if args.cmd == "disable":
                return cmd_enable(gw, db, _WHICH[args.which], args.pgns, False, args.commit)
            if args.cmd == "list":
                return cmd_list(gw, db, _WHICH[args.which])
            if args.cmd == "save":
                return cmd_save(gw, db, args.file)
            if args.cmd == "load":
                return cmd_load(gw, db, args.file, args.commit)
            if args.cmd == "raw":
                return cmd_raw(gw)
    except GatewayError as e:
        print("gateway error: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
