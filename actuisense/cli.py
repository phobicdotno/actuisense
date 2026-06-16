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


def _add_conn(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-p", "--port", required=True,
                    help="serial device (/dev/ttyUSB0, COM5) or tcp://host[:port]")
    sp.add_argument("-b", "--baud", type=int, default=115200, help="serial baud (default 115200)")


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

    p_raw = sub.add_parser("raw", help="dump raw gateway diagnostic queries (read-only, hex)")
    _add_conn(p_raw)

    p_tui = sub.add_parser("tui", help="launch the full-screen terminal UI")
    _add_conn(p_tui)

    return ap


def _print_list(db: PgnDb, title: str, pgns: List[int]) -> None:
    print("%s (%d):" % (title, len(pgns)))
    for n in pgns:
        print("  %-7d %s" % (n, db.name(n)))


def cmd_info(gw: Gateway, db: PgnDb) -> int:
    print("Gateway: %s" % gw.name)
    mode = gw.get_operating_mode()
    print("Operating mode: %s" % (mode.name if mode else "unknown"))
    _print_list(db, "Rx enabled", gw.get_pgn_list(PgnList.RX))
    _print_list(db, "Tx enabled", gw.get_pgn_list(PgnList.TX))
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
    _print_list(db, "%s enabled" % which.name, gw.get_pgn_list(which))
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


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "tui":
        from .tui import run_tui
        return run_tui(args.port, args.baud)

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
