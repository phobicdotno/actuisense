import sys
DLE, STX, ETX = 0x10, 0x02, 0x03
def frames(d):
    i, n = 0, len(d)
    while i < n - 1:
        if d[i] == DLE and d[i + 1] == STX:
            j = i + 2; body = bytearray(); ok = False
            while j < n - 1:
                if d[j] == DLE:
                    if d[j + 1] == DLE: body.append(DLE); j += 2; continue
                    if d[j + 1] == ETX: ok = True; j += 2; break
                    break
                body.append(d[j]); j += 1
            if ok and len(body) >= 2:
                yield bytes(body); i = j; continue
        i += 1
d = open(sys.argv[1], "rb").read()
k = 0
for body in frames(d):
    if body[0] == 0xC1 and len(body) > 50:   # DATA frame (len 0xD0)
        # body: C1 D0 <subtype> <offset...> <data...> crc
        print(f"#{k} bodylen={len(body)} cmd_len_sub={body[:3].hex(' ')} next8={body[3:11].hex(' ')} data4={body[11:15].hex(' ')}")
        k += 1
        if k >= 8: break
