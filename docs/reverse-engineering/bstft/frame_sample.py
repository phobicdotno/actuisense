import sys, collections
DLE, STX, ETX = 0x10, 0x02, 0x03
CMD = {0x93: "N2kRecv", 0x94: "N2kSend", 0xA0: "ACmdRecv", 0xA1: "ACmdSend",
       0xA9: "MDT", 0xC1: "FT"}

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
cnt = collections.Counter(); first = {}; lens = collections.defaultdict(collections.Counter)
for body in frames(d):
    cmd = body[0]; cnt[cmd] += 1; lens[cmd][len(body)] += 1
    if cmd not in first: first[cmd] = body
print("file bytes:", len(d), " frames:", sum(cnt.values()))
for cmd, c in cnt.most_common():
    nm = CMD.get(cmd, "?UNKNOWN?")
    s = first[cmd]
    common_len = lens[cmd].most_common(1)[0]
    print(f"cmd=0x{cmd:02X} {nm:10s} count={c:6d} mode_len={common_len[0]}(x{common_len[1]}) first48={s[:48].hex(' ')}")
