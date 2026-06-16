# Credits & protocol provenance

AcTuiSense talks to Actisense gateways using a clean-room re-implementation of the
**Actisense BST command protocol**. The protocol opcodes, framing and byte layouts
used here are documented facts, cross-checked against these open-source projects.
No source code from them is copied into this repository.

- **canboat** — <https://github.com/canboat/canboat> (Apache-2.0). The BST framing
  (DLE/STX/ETX, escaping, checksum) and the `NGT_MSG_SEND` / startup behaviour were
  verified against `actisense-serial.c`. The bundled PGN list
  (`actuisense/data/pgns.json`) is derived from canboat's `docs/canboat.json` — PGN
  numbers, names and frame types only. canboat is © Kees Verruijt and contributors.

- **timmathews/argo** — <https://github.com/timmathews/argo> (GPL-3.0). The
  Actisense command opcode enumeration (`ACmdOperatingMode`, `ACmdTxPGNEnable`,
  `ACmdActivatePGNEnableLists`, `ACmdCommitToEEPROM`, …) was cross-checked against
  `actisense/commands.go`. © Tim Mathews.

- **aldas/go-nmea-client** — <https://github.com/aldas/go-nmea-client>. Confirmed
  the operating-mode initialise behaviour and the `ACommsCommand_SetOperatingMode`
  reference.

- **Actisense** — NGT-1 / NGW-1 are products of Active Research Ltd (Actisense).
  This project is **not affiliated with or endorsed by Actisense**. "Actisense" and
  "NGT-1" are used only to describe interoperability. The official configuration
  tool is the Windows **Actisense NMEA Reader**; AcTuiSense is an independent,
  cross-platform alternative.

Protocol opcodes and wire layouts (interface facts) are not themselves
copyrightable; this project re-expresses them in original Python.
