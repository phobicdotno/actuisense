# BstFt — Actisense BST File Transfer (NGX-1 firmware update)

Reverse-engineered 2026-06-22 from a successful NGX-1 firmware update (3.032 → 3.068),
captured by **Actisense Toolkit's own "Enable Logging"** feature — which writes a fully
annotated `*-bstft.log` to `Documents\Actisense\Toolkit\Logs\`. No serial sniffer or
virtual-port tunnel is needed; just enable Toolkit logging before *Change Firmware*.

Files here:
- `bstft-transfer-v3.068.log` — the raw Toolkit capture (1.8 MB, 21 479 lines).
- `frames.txt` — representative frame of each type, extracted from the log.
- `bst_split.py` — BST frame splitter / opcode hunter (decodes raw byte captures).

## What is transferred

The **whole `.zip`** (`NGX-1-Release-v3.068.1986.zip`, 2 101 402 bytes) is streamed to the
device — *not* the inner `.actp`. The device unwraps and decrypts the (encrypted) `.actp`
internally. Mode logged as `Local (direct BST), Target address 0`.

## Framing

BstFt rides standard Actisense **BST framing** (`DLE STX … DLE ETX`, DLE-stuffing, the
`(cmd+len+sum(payload)+crc) mod 256 == 0` checksum) but uses **dedicated top-level command
bytes**, *not* the `0xA1/0xA0` BEM command space:

| Cmd  | Meaning                  |
|------|--------------------------|
| `0xA9` | MDT control response (subtype `0x00`=Start, `0x01`=End) |
| `0xC1` | FT flow/ack (subtype `0x01`=ACK, `0x10`=XON, `0x11`=XOFF) |

The TX **data** frames (the bulk `.zip` chunks) are **not** logged individually by Toolkit
(only the control frames + RX ACKs), so the exact data-frame command byte/framing is the one
remaining unknown — a raw byte sniff (e.g. HHD Serial Analyzer) would fill it in.

## Sequence

1. **TX `MDT_START`** `[54]`
   `00 00 44 00 …00… C8 9A 10 20 00 00 20 00 02 11 00 <filename ASCII>`
   - `0x44` type byte; `0xC8`=200 window/chunk size; **fileSize LE32** `9A 10 20 00` = `0x0020109A` = 2 101 402; params `0x0020`/`0x1102`; then the filename.
2. **RX `0xA9` BST MDT Start** `[14]` `A9 0C 00 01 <8-byte N2K NAME>`
   - subtype `0x00`=Start, status `0x01`=OK, NAME `3B 00 2E E7 04 00 00 00` (model `0x3B`=59, serial `0x04E72E`=321326).
3. **Data plane** — raw `.zip` bytes in ~200-byte windows, sliding-window flow control:
   - **RX `0xC1` FT ACK** `C1 0C 01 00 00 <ackIndex LE32> 01 00 00 00 00` — `ackIndex` = bytes acknowledged.
   - **RX `0xC1` FT XOFF** (subtype `0x11`) — device buffer full, pause (≈ every 64 600 B).
   - **RX `0xC1` FT XON** (subtype `0x10`) — resume.
4. **TX `MDT_END`** `[22]` `01 …00… 9A 10 20 00 41 06 34 C2`
   - finalize flag `0x01` + **fileSize LE32** + **CRC32 LE32** `41 06 34 C2` = `0xC2340641`.
5. **RX `0xA9` BST MDT End** `A9 0C 01 01 <NAME>` — subtype `0x01`=End, status `0x01`=OK.
6. Toolkit summary: `COMPLETE bytes=2101402 elapsed=478.421s CRC=0xC2340641`.

**Integrity:** CRC32 = `0xC2340641` over the full 2 101 402-byte `.zip`, verified by the
device at `MDT_END`. Transfer took ~478 s (~8 min) at 115200 baud in **Convert** mode.

## Prerequisite (hard-won)

Toolkit only lists/updates the NGX-1 when it is in **Convert** mode. The NGX-1-USB
auto-flips to **Transfer** mode on fresh USB enumeration / when a PC app connects; in
Transfer mode *Change Firmware* stays greyed. Power-cycle (USB **and** N2K) to return to
Convert, then go straight to Toolkit. A network/virtual-COM tunnel cannot hold Convert mode
(latency + auto-baud breaks enumeration) — capture must be local/native.

## Toward a Toolkit-free push in actuisense

The control plane is now known (MDT_START/END framing, `0xA9`/`0xC1` responses, CRC32,
windowed flow control). Remaining: the `MDT_DATA` frame format (one HHD raw capture).
