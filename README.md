# AcTuiSense

A cross-platform **terminal UI to configure Actisense NMEA 2000 gateways**
(NGT-1, NGW-1) over a serial port or TCP — the open, scriptable alternative to the
Windows-only **Actisense NMEA Reader → Hardware Configuration**.

Runs anywhere Python runs: **Linux, macOS, and Windows (PowerShell / Windows
Terminal)**.

```
┌─ AcTuiSense ───────────────── /dev/ttyUSB0 @115200 ─┐
│ Model: NGT-1-USB   FW 2.690   NAME 0x…03            │
│ Operating mode: ( ) Filter   (•) Receive-All        │
│                                                     │
│  PGN      Name                        RX   TX       │
│  126992   System Time                 [x]  [ ]      │
│  127245   Rudder                       [x]  [ ]      │
│  127250   Vessel Heading              [x]  [x]      │
│  127512   AGS Configuration Status    [ ]  [x]      │
│  127514   AGS Status                  [ ]  [x]      │
│  127751   DC Voltage/Current          [ ]  [x]      │
│  …                                                  │
│ [Activate] [Commit→EEPROM] [Reload] [Filter: ____ ] │
└─────────────────────────────────────────────────────┘
```

## Why

The NGT-1 will only **transmit** a PGN onto the bus if that PGN is in its **Tx PGN
Enable List**, and only **receives** the PGNs in its **Rx PGN Enable List** when in
Filter mode. By default these lists are minimal, so injected/forwarded application
PGNs are silently dropped. Actisense ships a Windows GUI to edit these lists;
AcTuiSense does the same job from any terminal, plus a plain CLI for automation.

> Heads-up: this writes to your gateway's configuration (and optionally its
> EEPROM). It is an independent project, **not affiliated with Actisense**. See
> [CREDITS.md](CREDITS.md) for protocol provenance.

## Install

```bash
pip install actuisense          # once published
# or from a checkout:
pip install -e .
```

Requires Python ≥ 3.9, `pyserial`, and `textual`.

## Use

### TUI

```bash
actuisense tui -p /dev/ttyUSB0          # Linux/macOS serial
actuisense tui -p COM5                   # Windows
actuisense tui -p tcp://192.168.1.50:60002   # networked gateway (e.g. W2K-1)
```

Arrow keys / mouse to move, **space** toggles the RX or TX box on the focused PGN,
type in the filter box to narrow the list, then **Commit → EEPROM** to persist.

### CLI (scriptable, no UI)

```bash
actuisense info        -p /dev/ttyUSB0           # hardware + operating mode + lists
actuisense enable  tx 127512 127514 127751 -p /dev/ttyUSB0 --commit
actuisense disable rx 130306 -p /dev/ttyUSB0
actuisense mode rxall  -p /dev/ttyUSB0           # or: filter
actuisense list tx     -p /dev/ttyUSB0
```

## Status

Early but working: the protocol codec is validated against real NGT-1 captures
(see the tests). See [CHANGELOG.md](CHANGELOG.md) for what's wired up.

## License

MIT — see [LICENSE](LICENSE).
