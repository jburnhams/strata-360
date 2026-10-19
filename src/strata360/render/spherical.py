"""Spherical video metadata: marks an MP4 as a monoscopic equirectangular 360 video, so YouTube, VLC and headset players show it as a sphere you can look round, not as a flat 2:1 picture.

Both versions of Google's Spherical Video spec are written into the video track (what Google's own spatial-media injector writes):
  V1  a `uuid` box (ffcc8263-f855-4a93-8814-587a02521fdd) in the `trak`, holding the GSpherical XML        (YouTube, older players)
  V2  `st3d` (mono) and `sv3d` (svhd + proj: prhd + equi) boxes in the video sample entry (`hvc1`, `avc1`)   (ffmpeg reads these: ffprobe shows "Spherical Mapping")

ffmpeg 6 has no command-line option that writes them, so the boxes are added here. Only the `moov` box (a few hundred KB) is rebuilt: when it is the last box of the file it is rewritten in place,
otherwise (a `+faststart` file, moov before the media) the file is copied once and the chunk offsets (`stco`/`co64`) are moved by the moov's growth."""
import os, struct, uuid

V1_UUID = uuid.UUID('ffcc8263-f855-4a93-8814-587a02521fdd').bytes
CONTAINERS = {'moov', 'trak', 'mdia', 'minf', 'stbl', 'edts', 'dinf', 'udta', 'sv3d', 'proj'}
PREAMBLE = {'stsd': 8}                                                           # bytes before the children: stsd has version, flags and entry count
SAMPLE_ENTRIES = {'hvc1', 'hev1', 'avc1', 'avc3'}
SAMPLE_ENTRY_HEADER = 78                                                         # a visual sample entry's fixed fields before its child boxes (ISO 14496-12 8.5.2)
SOFTWARE = 'Strata 360'


def v1_xml(software=SOFTWARE):
    return ('<?xml version="1.0"?><rdf:SphericalVideo xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/">'
            '<GSpherical:Spherical>true</GSpherical:Spherical><GSpherical:Stitched>true</GSpherical:Stitched>'
            f'<GSpherical:StitchingSoftware>{software}</GSpherical:StitchingSoftware><GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType></rdf:SphericalVideo>').encode()


def box(typ, payload=b''): return struct.pack('>I4s', 8 + len(payload), typ.encode('latin1')) + payload


def full_box(typ, payload=b'', version=0, flags=0): return box(typ, struct.pack('>I', (version << 24) | flags) + payload)


def v2_boxes(software=SOFTWARE):
    """st3d (monoscopic) and sv3d (equirectangular, no crop, no rotation)."""
    st3d = full_box('st3d', b'\x00')
    svhd = full_box('svhd', software.encode() + b'\x00'); prhd = full_box('prhd', struct.pack('>iii', 0, 0, 0)); equi = full_box('equi', struct.pack('>IIII', 0, 0, 0, 0))
    return st3d + box('sv3d', svhd + box('proj', prhd + equi))


class Box:
    """One box of the tree: `kids` for containers (their own bytes before the children kept in `head`), `data` for the rest."""
    def __init__(self, typ, head=b'', kids=None, data=b''): self.typ, self.head, self.kids, self.data = typ, head, kids, data

    def to_bytes(self):
        body = self.head + b''.join(k.to_bytes() for k in self.kids) if self.kids is not None else self.data
        return box(self.typ, body)

    def find(self, typ): return [k for k in (self.kids or []) if k.typ == typ]


def parse(buf, path=()):
    """The boxes in `buf` as a tree; only the containers on the way to the sample entries are opened."""
    out = []; pos = 0
    while pos + 8 <= len(buf):
        size, typ = struct.unpack('>I4s', buf[pos:pos + 8]); typ = typ.decode('latin1'); hdr = 8
        if size == 1: size = struct.unpack('>Q', buf[pos + 8:pos + 16])[0]; hdr = 16
        elif size == 0: size = len(buf) - pos
        if size < hdr or pos + size > len(buf): raise ValueError(f'a broken {typ!r} box in the moov')
        body = buf[pos + hdr:pos + size]
        if typ in CONTAINERS or typ in PREAMBLE or (typ in SAMPLE_ENTRIES and 'stsd' in path):
            n = PREAMBLE.get(typ, SAMPLE_ENTRY_HEADER if typ in SAMPLE_ENTRIES else 0); out.append(Box(typ, body[:n], parse(body[n:], path + (typ,))))
        else: out.append(Box(typ, data=body))
        pos += size
    return out


def _video_traks(moov):
    for t in moov.find('trak'):
        for md in t.find('mdia'):
            hd = md.find('hdlr')
            if hd and hd[0].data[8:12] == b'vide': yield t, md


def _shift_offsets(moov, delta):
    """Move every chunk offset of every track by `delta` bytes (the media moved because the moov before it grew)."""
    for t in moov.find('trak'):
        for md in t.find('mdia'):
            for mi in md.find('minf'):
                for st in mi.find('stbl'):
                    for b in st.kids:
                        if b.typ not in ('stco', 'co64'): continue
                        n = struct.unpack('>I', b.data[4:8])[0]; fmt, w = ('>I', 4) if b.typ == 'stco' else ('>Q', 8)
                        vals = [struct.unpack(fmt, b.data[8 + i * w:8 + (i + 1) * w])[0] + delta for i in range(n)]
                        if b.typ == 'stco' and vals and max(vals) >= 2 ** 32: raise ValueError('the chunk offsets no longer fit in 32 bits')
                        b.data = b.data[:8] + b''.join(struct.pack(fmt, v) for v in vals)


def mark(moov, software=SOFTWARE):
    """Add the V1 and V2 boxes to the video track(s) of the parsed `moov` (any earlier ones are replaced). Returns the number of video tracks marked."""
    n = 0
    for t, md in _video_traks(moov):
        t.kids = [k for k in t.kids if not (k.typ == 'uuid' and k.data[:16] == V1_UUID)] + [Box('uuid', data=V1_UUID + v1_xml(software))]
        for mi in md.find('minf'):
            for st in mi.find('stbl'):
                for sd in st.find('stsd'):
                    for se in sd.kids:
                        if se.typ in SAMPLE_ENTRIES: se.kids = [k for k in se.kids if k.typ not in ('st3d', 'sv3d')] + parse(v2_boxes(software))
        n += 1
    return n


def _top(f, size):
    """[(type, start, size)] of the file's top-level boxes."""
    out = []; pos = 0
    while pos + 8 <= size:
        f.seek(pos); hdr = f.read(16); n, typ = struct.unpack('>I4s', hdr[:8])
        if n == 1: n = struct.unpack('>Q', hdr[8:16])[0]
        elif n == 0: n = size - pos
        if n < 8: raise ValueError('not an MP4 file')
        out.append((typ.decode('latin1'), pos, n)); pos += n
    return out


def inject(path, software=SOFTWARE):
    """Mark the MP4 at `path` as a 360 video (equirectangular, mono), in place. Returns `path`."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        top = _top(f, size); mv = next(((s, n) for t, s, n in top if t == 'moov'), None)
        if mv is None: raise ValueError(f'{path}: no moov box')
        f.seek(mv[0]); raw = f.read(mv[1])
    moov = parse(raw)[0]
    if not mark(moov, software): raise ValueError(f'{path}: no video track')
    later = any(s > mv[0] for _, s, _ in top)                                    # media after the moov: it moves by the moov's growth
    if not later:
        new = moov.to_bytes()
        with open(path, 'r+b') as f: f.seek(mv[0]); f.write(new); f.truncate()
        return path
    grow = len(moov.to_bytes()) - mv[1]; _shift_offsets(moov, grow); new = moov.to_bytes(); tmp = path + '.360.part'
    with open(path, 'rb') as src, open(tmp, 'wb') as dst:
        for typ, s, n in top:
            if typ == 'moov': dst.write(new); continue
            src.seek(s); left = n
            while left:
                chunk = src.read(min(left, 64 << 20))
                if not chunk: raise ValueError(f'{path}: the file is shorter than its boxes say')
                dst.write(chunk); left -= len(chunk)
    os.replace(tmp, path); return path


def is_marked(path):
    """True when the video track carries the V2 `sv3d` box (what `inject` writes)."""
    with open(path, 'rb') as f:
        top = _top(f, os.path.getsize(path)); mv = next(((s, n) for t, s, n in top if t == 'moov'), None)
        if mv is None: return False
        f.seek(mv[0]); moov = parse(f.read(mv[1]))[0]
    for _, md in _video_traks(moov):
        for mi in md.find('minf'):
            for st in mi.find('stbl'):
                for sd in st.find('stsd'):
                    if any(k.typ == 'sv3d' for se in sd.kids if se.kids for k in se.kids): return True
    return False

