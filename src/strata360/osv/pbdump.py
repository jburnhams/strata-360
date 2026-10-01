"""Schema-less protobuf dumper for DJI djmd samples (no protoc available).

Strict wire-format parsing: a length-delimited field is shown as a nested message only if it
parses completely and cleanly; otherwise as a string, packed floats/doubles, or hex bytes.
Usage: python pbdump.py <file.osv> <stream_index> <packet_index> [max_depth]
"""
import struct, subprocess, sys

def varint(b, i):
    r = s = 0
    while True:
        if i >= len(b): raise ValueError("eof")
        c = b[i]; i += 1; r |= (c & 0x7f) << s; s += 7
        if not c & 0x80: return r, i
        if s > 70: raise ValueError("varint")

def parse(b):
    i, out = 0, []
    while i < len(b):
        k, i = varint(b, i); f, w = k >> 3, k & 7
        if f == 0 or f > 4000: raise ValueError("field")
        if w == 0: v, i = varint(b, i)
        elif w == 1:
            if i + 8 > len(b): raise ValueError("trunc")
            v = b[i:i+8]; i += 8
        elif w == 5:
            if i + 4 > len(b): raise ValueError("trunc")
            v = b[i:i+4]; i += 4
        elif w == 2:
            l, i = varint(b, i)
            if i + l > len(b): raise ValueError("trunc")
            v = b[i:i+l]; i += l
        else: raise ValueError("wire")
        out.append((f, w, v))
    return out

def try_msg(v):
    if len(v) < 2: return None
    try: return parse(v)
    except Exception: return None

def show(b, ind=0, maxd=8, lines=None):
    lines = lines if lines is not None else []
    pad = "  " * ind
    for f, w, v in parse(b):
        if w == 0: lines.append(f"{pad}{f}: {v}")
        elif w == 5: lines.append(f"{pad}{f}: f32 {struct.unpack('<f', v)[0]:.6g}  (i32 {struct.unpack('<i', v)[0]})")
        elif w == 1: lines.append(f"{pad}{f}: f64 {struct.unpack('<d', v)[0]:.10g}")
        else:
            sub = try_msg(v) if ind < maxd else None
            printable = all(32 <= c < 127 for c in v) and len(v) > 0
            if printable and len(v) >= 3: lines.append(f"{pad}{f}: {v.decode()!r}")
            elif sub is not None and len(sub) > 0:
                lines.append(f"{pad}{f}: msg({len(v)})"); show(v, ind + 1, maxd, lines)
            elif len(v) % 8 == 0 and len(v) >= 16 and all(abs(x) < 1e7 for x in struct.unpack(f'<{len(v)//8}d', v)):
                lines.append(f"{pad}{f}: packed f64[{len(v)//8}] " + " ".join(f"{x:.8g}" for x in struct.unpack(f'<{len(v)//8}d', v)[:24]))
            elif len(v) % 4 == 0 and len(v) >= 8 and all(abs(x) < 1e7 for x in struct.unpack(f'<{len(v)//4}f', v)):
                lines.append(f"{pad}{f}: packed f32[{len(v)//4}] " + " ".join(f"{x:.6g}" for x in struct.unpack(f'<{len(v)//4}f', v)[:24]))
            else: lines.append(f"{pad}{f}: bytes({len(v)}) {v[:24].hex()}")
    return lines

def first_packet(path, idx):
    """Bytes of the first packet of stream `idx` only (reads the start of the file, not the whole track)."""
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-map', f'0:{idx}', '-c', 'copy', '-frames:d', '1', '-f', 'data', '-'])


def packets(path, idx):
    sizes = [int(x) for x in subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', str(idx), '-show_entries', 'packet=size', '-of', 'csv=p=0', path]).split()]
    data = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', path, '-map', f'0:{idx}', '-c', 'copy', '-f', 'data', '-'])
    off = 0
    for s in sizes:
        yield data[off:off+s]; off += s

if __name__ == '__main__':
    path, idx, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    maxd = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    for k, p in enumerate(packets(path, idx)):
        if k == n:
            print("\n".join(show(p, 0, maxd))); break
