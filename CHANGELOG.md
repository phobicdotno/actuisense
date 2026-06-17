# Changelog

All notable changes to AcTuiSense. Format loosely follows Keep a Changelog;
versions are `MAJOR.MINOR.PATCH`.

## [0.3.0] - 2026-06-17

### Added
- **Connection dialog** (`Ctrl+O`, or the *Connection* button): pick a serial port
  (auto-detected ports are listed) + baud rate, a `tcp://` gateway, or a WAGO PLC.
  The TUI can now start **disconnected** (`actuisense tui` with no `-p`) and prompt
  for a connection instead of requiring the port up front.
- **WAGO PLC / can0 listener**: log in to a WAGO PFC200 (or any SocketCAN Linux box)
  with a username + password over SSH and stream `candump <iface>` straight off the
  bus. Raw 29-bit CAN ids are decoded to NMEA 2000 priority / PGN / source / dest.
- **Bus Monitor tab**: live N2K traffic from can0, aggregated one row per PGN/source
  with a hit count and the latest data bytes — the ground truth for what the gateway
  is actually putting on the wire.
- **`actuisense monitor`** CLI subcommand: scriptable, read-only can0 dump
  (`--host`/`--user`/`--password`/`--iface`, optional `-n COUNT`).
- `actuisense.can` (CAN-id decode + `candump -L` parsing) and `actuisense.wago`
  (SSH candump source), both fully unit-tested with golden vectors from real PFC200
  captures and a fake line stream — no hardware needed.
- Optional `wago` extra: `pip install actuisense[wago]` pulls in paramiko (imported
  lazily, so the core install stays serial-only).

## [0.2.0] - 2026-06-17

### Added
- **Activity Log tab** (like NMEA Reader's command log): every gateway exchange is
  recorded with line number, time, action, result (OK / Timeout / NAK / Error) and
  detail (e.g. `500ms` on timeout), colour-coded.
- A periodic **Get-Operating-Mode poll** drives the log and a live link indicator;
  pause/resume with `p`, clear the log from the tab.
- Device layer now logs every `command()` exchange (with an action label) via an
  `on_log` callback + an in-memory `log_entries` buffer, and serialises transport
  access with a lock so the poll and user actions never interleave on the wire.
- Second screenshot (Activity Log) in the README.

## [0.1.0] - 2026-06-16

First working release. Validated end-to-end against a real Actisense NGT-1.

### Added
- `actuisense.protocol` — pure, dependency-free encode/decode of the Actisense BST
  command protocol: frame builder with DLE-escaping + checksum, the full command
  opcode set, payload encoders (operating mode, Rx/Tx PGN enable, list activate,
  delete, default, EEPROM/flash commit), a streaming `FrameDecoder`, and a parser
  for Tx/Rx PGN-enable-list responses. Pinned by golden-vector tests built from
  **real bytes captured from an NGT-1**.
- `actuisense.pgndb` — bundled 339-PGN catalogue (derived from canboat) with lookup
  and search; reproducible via `tools/gen_pgndb.py`.
- `actuisense.device` — serial and `tcp://` transports and a `Gateway` API: read/set
  operating mode, enable/disable Rx/Tx PGNs, read enable lists, activate, commit to
  EEPROM. Response collection filters command replies out of live NMEA 2000 traffic.
- `actuisense.cli` — `info` / `mode` / `enable` / `disable` / `list` / `tui`
  subcommands for scripting.
- `actuisense.tui` — Textual full-screen UI: status bar, filter box, scrollable PGN
  table with per-PGN RX/TX toggle cells, and Activate / Commit-EEPROM / Reload /
  mode actions; all gateway I/O on thread workers. Cross-platform (Linux, macOS,
  Windows PowerShell / Windows Terminal).
- Tests: protocol golden vectors, fake-transport device tests replaying real NGT-1
  responses, and headless Textual pilot tests for the TUI (22 tests).
- CI (GitHub Actions, Python 3.9–3.12) and a generated TUI screenshot.

### Hardware validation (real NGT-1)
- `info` read the live operating mode + Rx (7) and Tx (14) enable lists.
- `enable tx 130306` → list showed 15; `disable tx 130306` → back to 14, with the
  EEPROM-committed 127512/127514/127751 intact.
- The TUI connected to the gateway, populated the table from the live lists, and
  filtered correctly.
