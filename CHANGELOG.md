# Changelog

All notable changes to AcTuiSense. Format loosely follows Keep a Changelog;
versions are `MAJOR.MINOR.PATCH`.

## [Unreleased]

### Added
- Project scaffold: package layout, `pyproject.toml`, MIT license, credits.
- `actuisense.protocol` — pure, dependency-free encode/decode of the Actisense BST
  command protocol: frame builder with DLE-escaping + checksum, the full command
  opcode set, payload encoders (operating mode, Rx/Tx PGN enable, list activate,
  delete, default, EEPROM/flash commit), a streaming `FrameDecoder`, and a parser
  for Tx/Rx PGN-enable-list responses.
- Golden-vector tests built from **real bytes captured from an NGT-1** (config +
  list readback), so the codec is pinned to what the hardware accepts/emits.
- Bundled PGN database (`data/pgns.json`, 339 PGNs) derived from canboat for the
  RX/TX filter list.
