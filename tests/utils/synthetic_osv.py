"""Build a tiny synthetic DJI-style `.OSV` with ffmpeg, so integration tests need no real footage (which is gitignored).

Layout matches what `strata360.osv` expects: streams 0 and 1 are HEVC lens videos, stream 2 is stereo AAC, streams 3 and 4 are `djmd`
protobuf data tracks (device header + calibration slots in the first packet of stream 3, per-frame meta after). The data tracks are
appended to the ffmpeg-made MP4 as hand-written `trak` boxes (ffmpeg cannot mux arbitrary binary tracks).

    build_osv(path, frames=60, drop=(30, 31), name_time='20260221120007')
"""
import os, struct, subprocess

FPS = 50


# ---- protobuf writers -----------------------------------------------------------------------------------------------------------
def _vi(n):
    out = bytearray()
    while True:
        b = n & 0x7f; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n: return bytes(out)

def _key(f, w): return _vi(f << 3 | w)
def ld(f, b): return _key(f, 2) + _vi(len(b)) + b
def f32(f, x): return _key(f, 5) + struct.pack('<f', x)
def vint(f, n): return _key(f, 0) + _vi(n)


def _slot(i):
    """One 264-byte PanoDewarpParams slot: fx, fy, cx, cy, k1..k4, size, k5, occlusion polygons, extrinsic quaternion; padded to 264."""
    ident = i < 16                                                  # the real sample has 16 populated slots out of 24
    body = b''.join([f32(1, 1000.0 if ident else 0.0), f32(2, 1000.0 if ident else 0.0), f32(3, 960.0), f32(4, 960.0)]
                    + [f32(5 + k, 0.0) for k in range(4)] + [f32(15, 0.0), f32(10, 1920.0), f32(11, 1920.0)])
    body += ld(22, struct.pack('<14f', *([0.0] * 14))) + ld(23, struct.pack('<14f', *([0.0] * 14)))
    body += ld(28, b''.join(f32(j + 1, v) for j, v in enumerate((1.0, 0.0, 0.0, 0.0))))
    return _pad_slot(body)


def _pad_slot(body):
    # Pad with an unknown length-delimited field so the slot parses cleanly and is exactly 264 bytes.
    need = 264 - len(body)
    for n in range(need):                                           # length field is 1 byte for n < 128, 2 bytes beyond
        if len(_key(40, 2)) + len(_vi(n)) + n == need: return body + ld(40, b'\0' * n)
    raise AssertionError(need)


def header_packet(device='Osmo 360', serial='SYN0001', firmware='1.0.0', proto='dvtm_oq101.proto', colour_mode=0):
    h = ld(1, proto.encode()) + ld(5, serial.encode()) + ld(6, firmware.encode()) + ld(10, device.encode())
    dev = ld(1, h)
    stream = vint(4, colour_mode) + ld(6, b''.join(ld(1 + i % 24, _slot(i)) for i in range(24)))
    return ld(1, dev) + ld(2, stream) + frame_packet(0)


def frame_packet(i):
    """FrameMeta (field 3): .1 timestamp, .2 exposure block (3 ISO, 4 shutter = tag byte + varint denominator, 6 colour temp, 9 quaternion, 10 accel)."""
    ts = ld(1, vint(2, 20000 * i))
    quat = ld(9, b''.join(f32(j + 1, v) for j, v in enumerate((1.0, 0.0, 0.0, 0.0))))
    acc = ld(10, b''.join(f32(j + 2, 0.0) for j in range(3)))
    exp = ld(3, f32(1, 100.0)) + ld(4, ld(1, b'\x01' + _vi(500))) + ld(6, vint(1, 5500)) + quat + acc
    return ld(3, ts + ld(2, exp))


# ---- MP4 box writer for the extra data tracks -----------------------------------------------------------------------------------
def _box(typ, payload=b''): return struct.pack('>I4s', 8 + len(payload), typ) + payload
def _full(typ, payload, ver=0, flags=0): return _box(typ, struct.pack('>I', ver << 24 | flags) + payload)


def _trak(track_id, samples, times_ms, data_offset, timescale=1000):
    n = len(samples)
    deltas = [times_ms[i + 1] - times_ms[i] for i in range(n - 1)] + [20]
    dur = sum(deltas)
    tkhd = _full(b'tkhd', struct.pack('>IIIII', 0, 0, track_id, 0, dur) + b'\0' * 8 + struct.pack('>hhhh', 0, 0, 0, 0)
                 + struct.pack('>9I', 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000) + struct.pack('>II', 0, 0), flags=3)
    mdhd = _full(b'mdhd', struct.pack('>IIII', 0, 0, timescale, dur) + struct.pack('>HH', 0x55c4, 0))
    hdlr = _full(b'hdlr', struct.pack('>I4s', 0, b'meta') + b'\0' * 12 + b'djmd\0')
    stsd = _full(b'stsd', struct.pack('>I', 1) + _box(b'djmd', b'\0' * 6 + struct.pack('>H', 1)))
    stts = _full(b'stts', struct.pack('>I', n) + b''.join(struct.pack('>II', 1, d) for d in deltas))
    stsc = _full(b'stsc', struct.pack('>IIII', 1, 1, n, 1))
    stsz = _full(b'stsz', struct.pack('>II', 0, n) + b''.join(struct.pack('>I', len(s)) for s in samples))
    stco = _full(b'stco', struct.pack('>II', 1, data_offset))
    stbl = _box(b'stbl', stsd + stts + stsc + stsz + stco)
    minf = _box(b'minf', _full(b'nmhd', b'') + _box(b'dinf', _full(b'dref', struct.pack('>I', 1) + _full(b'url ', b'', flags=1))) + stbl)
    return _box(b'trak', tkhd + _box(b'mdia', mdhd + hdlr + minf))


def _top_level(data):
    i, out = 0, []
    while i < len(data):
        size, typ = struct.unpack('>I4s', data[i:i + 8])
        if size == 0: size = len(data) - i
        out.append((typ, data[i:i + size])); i += size
    return out


def _inject_data_tracks(mp4_path, tracks):
    data = open(mp4_path, 'rb').read(); boxes = _top_level(data)
    types = [t for t, _ in boxes]
    assert types.index(b'mdat') < types.index(b'moov'), 'moov must follow mdat (do not use faststart)'
    head = b''.join(b for t, b in boxes if t not in (b'moov',))
    moov = next(b for t, b in boxes if t == b'moov')
    payloads = [b''.join(s) for s, _ in tracks]
    mdat = _box(b'mdat', b''.join(payloads))
    base = len(head) + 8; traks = b''; first_id = 10
    for k, (samples, times) in enumerate(tracks):
        traks += _trak(first_id + k, samples, times, base + sum(len(p) for p in payloads[:k]))
    new_moov = _box(b'moov', moov[8:] + traks)
    open(mp4_path, 'wb').write(head + mdat + new_moov)


def build_osv(path, frames=60, drop=(30, 31), name_time='20260221120007', creation_time=None, lens_px=128):
    """Write the synthetic OSV. `drop` frame numbers are removed from both lens streams (and their djmd packets) to make timing gaps."""
    creation_time = creation_time or f'{name_time[:4]}-{name_time[4:6]}-{name_time[6:8]}T{name_time[8:10]}:{name_time[10:12]}:{name_time[12:14]}Z'
    keep = [i for i in range(frames) if i not in drop]
    sel = '+'.join(f'eq(n\\,{i})' for i in drop) or '0'
    vf = f"select='not({sel})',format=yuv420p10le"
    tmp = path + '.tmp.mp4'
    src = lambda c: ['-f', 'lavfi', '-i', f'{c}=size={lens_px}x{lens_px}:rate={FPS}']
    cmd = ['ffmpeg', '-y', '-v', 'error', *src('testsrc2'), *src('smptebars'), '-f', 'lavfi', '-i', f'sine=frequency=440:duration={frames / FPS}:sample_rate=48000',
           '-filter_complex', f"[0:v]{vf}[a];[1:v]{vf}[b]", '-map', '[a]', '-map', '[b]', '-map', '2:a',
           '-c:v', 'libx265', '-preset', 'ultrafast', '-x265-params', 'log-level=error:bframes=0:keyint=25',
           '-fps_mode', 'passthrough', '-c:a', 'aac', '-ac', '2', '-t', f'{frames / FPS}', '-metadata', f'creation_time={creation_time}', '-f', 'mp4', tmp]
    subprocess.run(cmd, check=True)
    times = [round(i * 1000 / FPS) for i in keep]
    pk3 = [header_packet()] + [frame_packet(i) for i in keep[1:]]
    pk4 = [frame_packet(i) for i in keep]
    _inject_data_tracks(tmp, [(pk3, times), (pk4, times)])
    os.replace(tmp, path)
    return path
