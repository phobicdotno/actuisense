# Changelog

All notable changes to AcTuiSense. Format loosely follows Keep a Changelog;
versions are `MAJOR.MINOR.PATCH`.

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
