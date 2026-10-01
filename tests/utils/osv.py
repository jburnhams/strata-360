import struct

def build_varint(n):
    out = bytearray()
    while True:
        c = n & 0x7f
        n >>= 7
        if n:
            out.append(c | 0x80)
        else:
            out.append(c)
            break
    return bytes(out)

def encode_field(f, w, v):
    k = (f << 3) | w
    out = bytearray(build_varint(k))
    if w == 0:
        out.extend(build_varint(v))
    elif w == 1:
        out.extend(struct.pack('<d', v))
    elif w == 5:
        out.extend(struct.pack('<f', v))
    elif w == 2:
        out.extend(build_varint(len(v)))
        out.extend(v)
    return bytes(out)
