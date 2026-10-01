"""Minimal MP4 index reader: frame timestamps straight from the sample tables in the `moov` box, without reading the (multi-gigabyte) media data.

ffprobe's packet listing demuxes the whole file, which on a slow external drive is minutes per race. The sample tables are a few hundred KB."""
import struct
import numpy as np


def _boxes(f, start, end):
    pos = start
    while pos + 8 <= end:
        f.seek(pos); hdr = f.read(16); size, typ = struct.unpack('>I4s', hdr[:8]); hdr_len = 8
        if size == 1: size = struct.unpack('>Q', hdr[8:16])[0]; hdr_len = 16
        elif size == 0: size = end - pos
        if size < hdr_len: return
        yield typ.decode('latin1'), pos + hdr_len, pos + size
        pos += size


def _find(f, start, end, path):
    """First box at `path` (list of 4-char types) inside [start, end)."""
    for typ, s, e in _boxes(f, start, end):
        if typ == path[0]: return (s, e) if len(path) == 1 else _find(f, s, e, path[1:])
    return None


def _u32(b, o): return struct.unpack('>I', b[o:o + 4])[0]


def video_sample_times(path):
    """Presentation times (seconds, sorted) of every sample in the first video track, from mdhd, stts and ctts."""
    import os
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        moov = _find(f, 0, size, ['moov'])
        if moov is None: raise ValueError('no moov box')
        for typ, s, e in _boxes(f, *moov):
            if typ != 'trak': continue
            hdlr = _find(f, s, e, ['mdia', 'hdlr'])
            if hdlr is None: continue
            f.seek(hdlr[0] + 8)
            if f.read(4) != b'vide': continue
            mdhd = _find(f, s, e, ['mdia', 'mdhd']); f.seek(mdhd[0]); body = f.read(mdhd[1] - mdhd[0])
            timescale = _u32(body, 12 if body[0] == 0 else 20)
            stbl = _find(f, s, e, ['mdia', 'minf', 'stbl'])
            stts = _find(f, *stbl, ['stts']); f.seek(stts[0]); b = f.read(stts[1] - stts[0]); n = _u32(b, 4)
            ent = np.frombuffer(b[8:8 + 8 * n], dtype='>u4').reshape(-1, 2)
            deltas = np.repeat(ent[:, 1].astype(np.int64), ent[:, 0])
            dts = np.concatenate([[0], np.cumsum(deltas)[:-1]]) if len(deltas) else np.zeros(0, np.int64)
            pts = dts.copy(); ctts = _find(f, *stbl, ['ctts'])
            if ctts:                                                    # composition offsets (B-frames): version 1 offsets are signed
                f.seek(ctts[0]); b = f.read(ctts[1] - ctts[0]); ver = b[0]; n = _u32(b, 4)
                ent = np.frombuffer(b[8:8 + 8 * n], dtype='>u4').reshape(-1, 2)
                off = np.repeat(ent[:, 1].astype(np.int64), ent[:, 0])
                if ver == 1: off = np.where(off >= 2 ** 31, off - 2 ** 32, off)
                if len(off) >= len(dts): pts = dts + off[:len(dts)]
            return np.sort(pts.astype(np.float64) / timescale)
    raise ValueError('no video track')
