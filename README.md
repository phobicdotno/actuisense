# AcTuiSense

A cross-platform **terminal UI to configure Actisense NMEA 2000 gateways**
(NGT-1, NGW-1) over a serial port or TCP — the open, scriptable alternative to the
Windows-only **Actisense NMEA Reader → Hardware Configuration**.

Runs anywhere Python runs: **Linux, macOS, and Windows (PowerShell / Windows
Terminal)**.

![AcTuiSense PGN filter tab](docs/screenshot.svg)

**Activity Log tab** — every gateway exchange (line, time, action, result, detail),
fed by a live Get-Operating-Mode poll plus your own actions, just like NMEA Reader's
command log:

![AcTuiSense activity log tab](docs/screenshot-log.svg)

> Validated end-to-end against a real **Actisense NGT-1** — reading the operating
> mode and Rx/Tx enable lists, toggling per-PGN filters, activating, and committing
> to EEPROM.

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

## Settings coverage

| Setting | CLI | TUI | Notes |
|---|---|---|---|
| Operating mode (Filter / Receive-All) | `mode` | `m` | the `0x11` command |
| Per-PGN **Rx** enable (all 339 PGNs) | `enable/disable rx` | `r` | `0x46` |
| Per-PGN **Tx** enable (all 339 PGNs) | `enable/disable tx` | `t` | `0x47` |
| Activate enable lists | implicit | `a` | `0x4B` |
| Commit to EEPROM (persist) | `--commit` | `c` | `0x01` |
| Read current Rx/Tx lists & mode | `info` / `list` | on connect | parsed |
| Raw diagnostic queries (hw/product/total-time) | `raw` | — | read-only hex; vendor-binary fields are **not** guessed |
| Activity log of every exchange (+ live poll) | — | Activity Log tab | line/time/action/result/detail; `p` pauses polling |

Deliberately **not** wired up yet: serial/CAN baud change, NMEA 0183 P-code, and
duplicate-filtering — these can disrupt the link, and their payloads are not
publicly specified, so they are left out rather than guessed. Device model/firmware
identification (via N2K PGN 126996) is a planned addition. The `protocol` module
already encodes the full Actisense command set, so adding these is straightforward
once each is verified against hardware.

## Status

Early but working: the protocol codec is validated against real NGT-1 captures
(see the tests). See [CHANGELOG.md](CHANGELOG.md) for what's wired up.

## License

MIT — see [LICENSE](LICENSE).
