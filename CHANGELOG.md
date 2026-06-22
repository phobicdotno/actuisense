# Changelog

All notable changes to AcTuiSense. Format loosely follows Keep a Changelog;
versions are `MAJOR.MINOR.PATCH`.

## [0.5.5] - 2026-06-22

### Changed
- **Firmware tab layout**: a blank line above the Browse / Flash / Read button row, and
  the progress bar is now full-width (spans the remaining space to the right) with a
  line of padding above/below — a clearer, bigger update readout.

## [0.5.4] - 2026-06-22

### Added
- **NMEA 2000 bus-load indicator** in the TUI status bar ("N2K bus ~X%"), like NMEA
  Reader's. Estimated from the gateway's forwarded N2K stream (CAN frame count per
  message at ~128 bits/extended frame over a rolling 3 s window, as a fraction of the
  250 kbit/s bus); updates ~1×/s. Works for both a connected gateway and the WAGO can0
  Bus Monitor.

## [0.5.3] - 2026-06-22

### Added
- **Convert operating mode** (`OperatingMode.CONVERT = 0x04`), confirmed by sniffing
  NMEA Reader's mode dropdown (`A1 11 04 00`). `actuisense mode convert` now sets the
  NGX-1 into NMEA 0183↔2000 conversion mode directly — no NMEA Reader / power-cycle
  needed — and the TUI mode cycle (`m`) now rotates Filter → Receive-All → Convert.
  (Full map: Filter/"Transfer Normal" = 1, Receive-All = 2, Convert = 4.)

## [0.5.2] - 2026-06-22

### Added
- **TUI Firmware tab: "Browse…" file picker** — a modal `DirectoryTree` (filtered to
  directories + `.zip`) to pick the firmware file instead of typing the path.
- **TUI Firmware tab: current firmware readout** — the gateway's installed version is
  read from N2K Product Information (PGN 126996) and shown as
  "current firmware: <version> • <description> • S/N <serial>", auto-populated on
  connect and refreshable with a **Read current** button. New
  `protocol.parse_product_info_strings()` and `Gateway.get_product_info()`.

## [0.5.1] - 2026-06-22

### Added
- **Filename-based CRC auto-fill** for firmware files whose CRC we've observed from a
  Toolkit `*-bstft.log`. `actuisense fw <file>` and the TUI Firmware tab now look the
  CRC up by (filename, size) and use it automatically — no `--crc` needed — for the
  known files: `NGX-1-Release-v3.068.1986.zip` → `0xC2340641` and
  `NGX-1-Release-v3.032.1743-Beta.zip` → `0x9469623D`. Unknown files still fall back to
  the placeholder (a mismatch is safely rejected by the device).

### Notes
- The Actisense CRC-32 algorithm is still unrecovered: it's a non-standard polynomial,
  and a reveng search over our two captured (file → CRC) pairs reports "give 4 or more
  samples". Two more distinct firmware transfers (logged) would let reveng solve it, at
  which point the lookup table is replaced by a computed CRC for any file.

## [0.5.0] - 2026-06-22

### Added
- **Firmware update (`actuisense fw`) for the NGX-1 / WGX-1.** Pushes an Actisense
  firmware `.zip` to the gateway over the reverse-engineered **BstFt** protocol, with a
  live progress bar (percent, KB, rate, ETA), XON/XOFF flow control, and a confirmation
  prompt. The whole `.zip` is streamed in 200-byte windows; the device unwraps and
  decrypts the inner `.actp` itself.
  ```bash
  actuisense fw NGX-1-Release-v3.068.1986.zip -p COM5 --crc 0xC2340641
  ```
  Protocol: `MDT_START` (size + filename) → `0xC1` DATA frames → `MDT_END` (size + CRC32),
  fully documented in `docs/reverse-engineering/bstft/`. New `protocol.build_mdt_start/
  build_mdt_data/build_mdt_end/parse_ft/parse_mdt_response` and `Gateway.push_firmware`,
  all covered by golden-vector tests against a real Toolkit transfer (no hardware needed).
- **Firmware tab in the TUI** (its own top tab, `u` to jump to it): path + optional CRC
  fields, a Flash button, and a live `ProgressBar`. The transfer runs on a worker thread
  with polling paused for the duration; progress and result are shown inline.

### Known limitation
- The end-of-transfer **CRC32 algorithm is not yet confirmed** — the value Toolkit logs
  matches no catalogued CRC-32 over the file, and the polynomial can't be recovered from a
  single capture. Until a second different-file transfer is captured to solve it,
  `firmware_crc()` returns a placeholder (plain zlib) and the device will *reject* a
  mismatched image (safe — nothing is flashed). Pass the known CRC via `--crc 0x…` (from a
  Toolkit `*-bstft.log`) for a guaranteed accept.

## [0.4.3] - 2026-06-19

### Fixed
- **Bus Monitor over can0 now streams in real time.** The remote `candump` was started
  on a plain SSH channel (no PTY), so glibc block-buffered its stdout (~4-8 KB) and the
  monitor stayed empty until kilobytes of frames accumulated, then arrived as a burst —
  it looked stalled at NMEA 2000 rates. The SSH session now requests a PTY
  (`channel.get_pty`), so candump line-buffers and each frame is delivered immediately.

### Changed
- The can0 connection type is relabelled **"WAGO PLC / Linux (can0)"** (was "WAGO PLC
  (can0)") and its dialog text now reflects that any Linux host exposing a SocketCAN
  interface over SSH works, not just a WAGO PLC (e.g. an Ubuntu box with a candleLight /
  gs_usb adapter). The internal connection kind is unchanged.

## [0.4.2] - 2026-06-18

### Added
- **The Bus Monitor now works on a serial/TCP Actisense gateway**, not just WAGO. The
  gateway forwards every received NMEA 2000 message on its `0x93` channel; a background
  reader decodes those (`protocol.parse_n2k_recv`, byte layout per canboat
  `actisense-serial.c`) and feeds the same Bus Monitor (PGN/source/instance split,
  filter, Inst column). The reader shares the transport lock with the heartbeat poll and
  user commands, reading in short bursts so it never blocks a config write.

### Changed
- A gateway connection now shows **all three tabs** again (PGN Filter, Bus Monitor,
  Activity Log) — the Bus Monitor is no longer hidden on serial/TCP, since it is now fed
  by the gateway's own N2K stream. WAGO mode still shows only the Bus Monitor.

## [0.4.1] - 2026-06-18

### Added
- **Bus Monitor splits rows by device instance.** Two engines (or two generators)
  reporting the same PGN from the same source address are now separate rows, keyed by
  their Instance field, with a new **Inst** column. Instance bit positions come from
  canboat (62 PGNs: engine, battery, fluid level, AC/DC, temperature, ...), bundled into
  `data/pgns.json`; `PgnDb.instance()` reads the value from the frame. PGNs without an
  instance field, or an "unavailable" instance, collapse to one row as before.

### Fixed
- **WAGO mode no longer shows the gateway-only shortcuts** (`r`/`t`/`b`/Activate/Commit/
  ...) in the footer. Textual only drops a binding from the footer when `check_action`
  returns `False` (returning `None` keeps it shown but dimmed), so the tab-aware filter
  now returns `False` for off-tab actions.

### Docs
- Note that the gateway path is validated against a real **NGX-1** as well as the NGT-1.

## [0.4.0] - 2026-06-18

### Added
- **Save/load the Rx/Tx enable lists to a human-readable file.**
  - TUI: `s` / `Save` writes the current RX/TX lists to a file; `l` / `Load` reads one
    back, writes the difference to the gateway and stages it (press Activate to apply).
  - CLI: `actuisense save <file> -p <port>` and `actuisense load <file> -p <port>
    [--commit]`. Load makes the gateway match the file (enables missing PGNs, disables
    extras).
  - Format is an annotated text file with `[RX]` / `[TX]` sections, one PGN per line with
    its name as a `#` comment. Hand-editable: comments, blank lines and the name
    annotations are ignored on load, so only the PGN numbers matter. New module
    `actuisense.pgnfile` (pure encode/decode, unit-tested).

### Note
- The Actisense gateways cap how many PGNs a list can hold: ~38 per list for the legacy
  Format-1 path (BST single-frame limit), 74 on the fast-packet path, up to 250 Rx / 150
  Tx on newer firmware's Format 2. A loaded file larger than the cap will be truncated by
  the device -- press Reload (F5) to see what it actually kept.

## [0.3.12] - 2026-06-18

### Changed
- **Tabs now follow the connection.** Connecting to a WAGO PLC (can0 bus monitor) shows
  only the Bus Monitor tab; connecting to an Actisense gateway shows the PGN Filter and
  Activity Log and hides the Bus Monitor. This removes the confusion where, in WAGO
  bus-monitor mode (no Actisense gateway), the PGN Filter showed the whole PGN catalogue
  with empty RX/TX boxes and the Activity Log stayed empty -- neither has a data source
  without a gateway. The two connection modes are now mutually exclusive: starting one
  closes the other.

## [0.3.11] - 2026-06-18

### Added
- **Bus Monitor now has a filter box** (like the PGN Filter tab): type a PGN number or
  name to narrow the live rows. New frames respect the active filter; clearing it brings
  every captured row back.
- **`Ctrl+F` focuses whichever filter belongs to the open tab** (PGN Filter or Bus
  Monitor).

### Changed
- **The footer only lists shortcuts useful on the current tab.** RX/TX toggles,
  select-all, Activate, Commit, Reload and Mode show only on the PGN Filter tab; the Bus
  Monitor and Activity Log tabs show only their relevant keys. Connection/Quit stay
  global.

## [0.3.10] - 2026-06-18

### Fixed
- **Connection dialog no longer carries a value across to the wrong Type.** Switching
  Type (e.g. Serial -> TCP) kept the previous field value (a serial path lingering in
  the TCP host field). Now the Host field keeps its value only if it fits the selected
  Type, else falls back to the remembered last target, else clears so the grey
  placeholder suggestion shows. The dialog also opens with the Type preset to the last
  connection's kind (tcp/serial/wago) so its address is shown straight away.

## [0.3.9] - 2026-06-18

### Added
- **Click any column header to sort** that table, click the same header again to flip
  ascending/descending. Works on all three tables (PGN Filter, Bus Monitor, Activity
  Log). Numeric columns (PGN, Src, Cnt, Time, line number) sort numerically; text
  columns sort case-insensitively. Sort direction is tracked per table.

## [0.3.8] - 2026-06-18

### Changed
- Select-all (`R`/`T`/`B`) now **bulk-writes** every PGN in one burst instead of one
  blocking command per PGN. The old path waited the full response window for each PGN
  (minutes for hundreds of PGNs) and wrote one Activity Log line each; the new
  `set_pgns_bulk` fires all Set-PGN frames back-to-back, drains the acks once, and logs a
  single summary line (`Bulk RX/TX N PGNs -- X enable / Y disable`). Press Activate once
  after to apply.

## [0.3.7] - 2026-06-18

### Changed
- Tab order is now **PGN Filter | Bus Monitor | Activity Log** (Bus Monitor and
  Activity Log swapped).

## [0.3.6] - 2026-06-18

### Added
- **Shift+B** selects (or, if all already on, clears) **both RX and TX** for every
  shown PGN at once -- completing the set: `b` both on one PGN, `R`/`T` all-RX/all-TX,
  `B` all-both. Acts on the filtered subset; writes run off the UI thread.

### Removed
- The hidden Space-bar TX toggle (an undocumented duplicate of `t`).

## [0.3.5] - 2026-06-18

### Changed
- Connection dialog: the Port/host **placeholder hint** now matches the selected
  Type (serial -> `/dev/ttyUSB0`, tcp -> `tcp://host:60002`, wago -> `10.0.0.202`)
  instead of always listing all three.

## [0.3.4] - 2026-06-18

### Fixed
- **Exiting the TUI no longer hangs or leaves the terminal broken.** A Textual
  worker thread doing blocking serial/SSH I/O could keep the interpreter from
  exiting (it hung joining the thread at shutdown), leaving the terminal in raw
  mode -- arrow keys then printed as `^[[A` / `^[[B` and you had to Ctrl-C twice.
  Now the terminal is fully restored on exit (mouse off, cursor on, normal cursor
  keys/keypad, `stty sane`) and the process exits hard so a stuck worker can't hang
  it. SIGTERM/SIGHUP now request a clean Textual shutdown.

## [0.3.3] - 2026-06-18

### Changed
- **Connection dialog is now type-aware and scrollable.** It shows only the fields
  relevant to the selected Type: serial -> detected ports + baud; tcp -> just host;
  WAGO -> host + SSH login. The WAGO login (username / password / iface) is stacked
  vertically so all three fields are visible (they were crammed into one row where
  only the username showed), and the dialog scrolls if taller than the terminal so
  nothing is clipped.

## [0.3.2] - 2026-06-18

### Added
- **`b` toggles both RX and TX** for the highlighted PGN at once.
- **Shift+R / Shift+T select (or, if all already on, clear) ALL** shown PGNs' RX / TX
  boxes. Acts on the current filtered subset, so filter then Shift+R/T; the writes
  to the gateway run off the UI thread. (The gateway may cap how many it accepts --
  press F5 to re-read the actual enabled set.)

### Changed
- **Connection dialog: connected gateways sort to the top.** Detected serial ports
  that report a real device (e.g. `NGX-1`) now list above the empty / `n/a` legacy
  `ttyS*` ports, and the target field is pre-filled with the first real port -- so
  the dialog opens ready to connect instead of burying the gateway at the bottom.
- TUI header now shows the **version** and **2026 (c) Karstein Kvistad**.

### Fixed
- **A SIGTERM/SIGHUP kill no longer leaves the terminal spewing mouse escape codes.**
  The TUI now traps those signals, exits cleanly, and disables mouse reporting on
  the way out (idempotent on a normal quit). If you still see leftover garbage from
  an older kill, run `reset`.

## [0.3.1] - 2026-06-17

### Fixed
- **NGX-1 Rx/Tx list readback.** `info` / `list` (and the TUI) reported 0 enabled
  PGNs against the Actisense NGX-1. The NGX ignores the bulk list query (`0x49`/`0x48`)
  that the NGT-1 answers, and replies to the Format-2 query (`0x4F`/`0x4E`) with an
  indexed parameter structure we do not decode. Added a reliable fallback: when the
  bulk query returns nothing, scan the PGN database with the per-PGN query
  (`0x47`/`0x46`), which the NGX does answer, pipelined in batches so the device
  reply latency and its `0xF2` status-frame flood are paid once per batch (a full
  Tx scan is ~15-20 s). `info` skips the moot Rx scan when the gateway is in RX_ALL.
  Verified against a real NGX-1: the 22-PGN Tx list now shows correctly.

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
