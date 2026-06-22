#!/usr/bin/env python3
"""
BST frame splitter / BstFt opcode hunter.

Grounded ONLY in the confirmed Actisense BST framing (canboat actisense.h +
actuisense/protocol.py), no invented semantics:

    DLE STX <command> <len> <payload...> <crc> DLE ETX
    DLE=0x10 STX=0x02 ETX=0x03 ; DLE inside the body is doubled (0x10 0x10)
    <len> = length of the UNescaped payload
    <crc> makes (command + len + sum(payload) + crc) == 0 (mod 256)

Command bytes seen so far:
    0x93 N2kMsgRecv   0x94 N2kMsgSend
    0xA0 ACmdRecv     0xA1 ACmdSend   (payload[0] = BEM opcode)

Known BEM opcodes (payload[0] when command is 0xA0/0xA1) are labelled.
ANYTHING ELSE is printed as UNKNOWN -- those are the reverse-engineering targets
(the BstFt / firmware-transfer opcodes are expected to show up here during a
Toolkit "Upgrade Firmware" capture).

Usage:
    python bst_split.py capture.bin                # raw bytes (both directions if you logged one side)
    python bst_split.py --hex capture.hex          # whitespace/comma-separated hex
    python bst_split.py tx.bin rx.bin              # label each file's direction
"""
import sys

DLE, STX, ETX = 0x10, 0x02, 0x03

BEM = {
    0x00: "REINIT_MAIN_APP", 0x01: "COMMIT_TO_EEPROM", 0x02: "COMMIT_TO_FLASH",
    0x10: "HARDWARE_INFO", 0x11: "OPERATING_MODE", 0x12: "PORT_BAUD_CFG",
    0x13: "PORT_PCODE_CFG", 0x14: "PORT_DUP_DELETE", 0x15: "TOTAL_TIME",
    0x16: "HARDWARE_BAUD",
    0x40: "SUPPORTED_PGN_LIST", 0x41: "PRODUCT_INFO_N2K", 0x42: "CAN_CONFIG",
    0x43: "CAN_INFO_FIELD1", 0x44: "CAN_INFO_FIELD2", 0x45: "CAN_INFO_FIELD3",
    0x46: "RX_PGN_ENABLE", 0x47: "TX_PGN_ENABLE", 0x48: "RX_PGN_ENABLE_LIST",
    0x49: "TX_PGN_ENABLE_LIST", 0x4A: "DELETE_PGN_ENABLE_LIST",
    0x4B: "ACTIVATE_PGN_ENABLE_LISTS", 0x4C: "DEFAULT_PGN_ENABLE_LIST",
    0x4D: "PARAMS_PGN_ENABLE_LISTS", 0x4E: "RX_PGN_ENABLE_LIST_F2",
    0x4F: "TX_PGN_ENABLE_LIST_F2",
    0xF0: "STARTUP_STATUS", 0xF1: "ERROR_REPORT", 0xF2: "SYSTEM_STATUS",
}
CMD = {0x93: "N2kMsgRecv", 0x94: "N2kMsgSend", 0xA0: "ACmdRecv", 0xA1: "ACmdSend"}


def unstuff_frames(data):
    """Yield (command, payload_bytes, crc_ok) by walking DLE STX ... DLE ETX."""
    i, n = 0, len(data)
    while i < n - 1:
        if data[i] == DLE and data[i + 1] == STX:
            j = i + 2
            body = bytearray()
            ok_end = False
            while j < n - 1:
                if data[j] == DLE:
                    if data[j + 1] == DLE:        # escaped DLE
                        body.append(DLE); j += 2; continue
                    if data[j + 1] == ETX:        # end of frame
                        ok_end = True; j += 2; break
                    break                          # malformed
                body.append(data[j]); j += 1
            if ok_end and len(body) >= 3:
                command = body[0]
                length = body[1]
                payload = bytes(body[2:2 + length])
                crc = body[2 + length] if 2 + length < len(body) else None
                crc_ok = crc is not None and (
                    (command + length + sum(payload) + crc) & 0xFF) == 0
                yield command, payload, crc_ok, length
                i = j
                continue
        i += 1


def report(data, tag=""):
    counts = {}
    unknown = []
    for command, payload, crc_ok, length in unstuff_frames(data):
        if command in (0xA0, 0xA1) and payload:
            op = payload[0]
            name = BEM.get(op)
            key = f"{CMD.get(command, hex(command))}:{name or 'UNKNOWN_'+hex(op)}"
            if name is None:
                unknown.append((command, op, payload, crc_ok))
        else:
            key = CMD.get(command, hex(command))
        counts[key] = counts.get(key, 0) + 1

    print(f"\n===== {tag or 'capture'} : frame summary =====")
    for k in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {counts[k]:6d}  {k}")

    if unknown:
        print(f"\n----- UNKNOWN BEM opcodes (RE TARGETS: candidate BstFt) -----")
        seen = {}
        for command, op, payload, crc_ok in unknown:
            seen.setdefault(op, []).append((command, payload, crc_ok))
        for op in sorted(seen):
            samples = seen[op]
            c0, p0, ok0 = samples[0]
            preview = p0[:24].hex(" ")
            print(f"  op=0x{op:02X}  x{len(samples):<5} dir={CMD.get(c0,hex(c0))} "
                  f"crc_ok={ok0} len={len(p0)}  payload[:24]={preview}")
    else:
        print("\n(no unknown BEM opcodes -- capture has no BstFt frames yet)")


def load(path, ashex):
    raw = open(path, "rb").read()
    if ashex:
        txt = raw.decode("ascii", "ignore")
        for sep in (",", ";", "\n", "\t"):
            txt = txt.replace(sep, " ")
        return bytes(int(t, 16) for t in txt.split() if t)
    return raw


def main(argv):
    ashex = "--hex" in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__); return 1
    for f in files:
        report(load(f, ashex), tag=f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
