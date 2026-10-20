"""Recordings cut short: rebuild the MP4 index of a camera file whose battery or card ran out, as a new copy (the original is never written to).

Such a file has its `ftyp` and all the media data up to the moment it stopped, but no `moov` (the index is written last), so no reader can open it. Both cameras write the media data in a strict
pattern, one sample a chunk, back to back (checked on every sample of good clips):
  * Insta360 X3 (.insv, .lrv): one H.264 frame (a single length-prefixed NAL unit), then 1 or 2 AAC frames, and again.
  * DJI Osmo 360 (.OSV): per video frame two telemetry samples (`djmd`), two debug samples (`dbgi`), each one protobuf field, then the front and the rear lens frame (HEVC, several NAL units),
    with runs of AAC frames in between.
A good clip of the same camera (the template) gives the track layout, the codec setup and the timing; this module walks the cut-short file's media data in that pattern, finds every sample's
size, and writes `original bytes + a moov built from the template's with the new sample tables`. The media data keeps its offsets, so nothing is re-encoded and nothing is moved.

The X3 writes its trailer (IMU, exposure, calibration: osv/insta360.py) after the index, so a recovered X3 file has no motion or exposure data. Its trailer is rebuilt with only the template's
camera record (model, serial, firmware, lens calibration: the same camera); insta360.py treats the missing records as "held upright, exposure unknown". A DJI file keeps its telemetry
(it is in the media data). The last few samples before the cut are dropped when they are incomplete."""
import datetime as dt, os, re, shutil, struct
import numpy as np
from strata360.osv import mp4

CONTAINERS = {'moov', 'trak', 'mdia', 'minf', 'stbl', 'edts', 'dinf'}
AAC_FIRST = 0x21                                         # every AAC frame of both cameras starts with a channel-pair element, tag 0 (0b0010000x)


# ---- reading the template --------------------------------------------------------------------------------------------------------------------------------------------------

def _tree(f, start, end):
    """[(type, bytes or children)] of the boxes in [start, end); container boxes are expanded."""
    out = []
    for typ, s, e in mp4._boxes(f, start, end):
        if typ in CONTAINERS: out.append((typ, _tree(f, s, e)))
        else: f.seek(s); out.append((typ, f.read(e - s)))
    return out


def _get(tree, *path):
    for typ, v in tree:
        if typ == path[0]: return v if len(path) == 1 else _get(v, *path[1:])
    return None


def _u32(b, o): return struct.unpack('>I', b[o:o + 4])[0]


def _kind(trak):
    """'h264', 'hevc', 'aac' or 'pb' (a protobuf metadata track: DJI djmd and dbgi)."""
    stsd = _get(trak, 'mdia', 'minf', 'stbl', 'stsd'); codec = stsd[12:16]
    return {b'avc1': 'h264', b'hvc1': 'hevc', b'hev1': 'hevc', b'mp4a': 'aac', b'djmd': 'pb', b'dbgi': 'pb'}.get(codec) or ValueError(f'track codec {codec!r} not supported')


def _samples(trak):
    """(offsets, sizes) of every sample of a template track (chunks expanded with stsc)."""
    stbl = _get(trak, 'mdia', 'minf', 'stbl'); b = _get(stbl, 'stsz'); fixed, n = _u32(b, 4), _u32(b, 8)
    sizes = np.full(n, fixed, np.int64) if fixed else np.frombuffer(b[12:12 + 4 * n], '>u4').astype(np.int64)
    co = _get(stbl, 'co64'); offs = np.frombuffer(co[8:], '>u8').astype(np.int64) if co is not None else np.frombuffer(_get(stbl, 'stco')[8:], '>u4').astype(np.int64)
    sc = _get(stbl, 'stsc'); m = _u32(sc, 4); sc = np.frombuffer(sc[8:8 + 12 * m], '>u4').reshape(-1, 3).astype(np.int64)
    out = np.empty(n, np.int64); k = 0
    for c, o in enumerate(offs):
        per = sc[np.searchsorted(sc[:, 0], c + 1, side='right') - 1, 1]
        for _ in range(per):
            if k < n: out[k] = o; o += sizes[k]; k += 1
    return out, sizes


def _varint(b, i):
    v = s = 0
    while True:
        if i >= len(b): raise IndexError
        c = int(b[i]); v |= (c & 127) << s; i += 1; s += 7
        if c < 128: return v, i


def _pb_fields(b, i, n):
    """End of `n` protobuf fields starting at i, or None when they are not valid."""
    try:
        for _ in range(n):
            tag, i = _varint(b, i); wt = tag & 7
            if tag >> 3 == 0: return None
            if wt == 0: _, i = _varint(b, i)
            elif wt == 2: ln, i = _varint(b, i); i += ln
            elif wt == 1: i += 8
            elif wt == 5: i += 4
            else: return None
    except IndexError: return None
    return i if i <= len(b) else None


def _pb_count(f, o, z):
    """How many top-level protobuf fields a template sample has."""
    f.seek(o); b = f.read(z); i = n = 0
    while i < z:
        e = _pb_fields(b, i, 1)
        if e is None: return None
        i, n = e, n + 1
    return n


def _asc(stsd):
    """The AAC AudioSpecificConfig from an mp4a sample description's esds (descriptor tag 5)."""
    i = stsd.find(b'esds') + 8
    while i < len(stsd):
        tag = stsd[i]; i += 1; ln = 0
        while True:
            c = stsd[i]; i += 1; ln = ln << 7 | (c & 127)
            if c < 128: break
        if tag == 5: return bytes(stsd[i:i + ln])
        if tag == 3: i += 3
        elif tag == 4: i += 13
        else: i += ln
    return None


class AacCheck:
    """Does a byte range decode as exactly one AAC frame? A cut too early runs out of bits before the END element; two frames together decode as 2048 samples. Needs PyAV (installed with
    faster-whisper); without it every range passes and the split relies on frame sizes alone."""

    def __init__(self, asc):
        self.cc = None
        try:
            import av; av.logging.set_level(av.logging.FATAL)
            self.av = av; self.cc = av.CodecContext.create('aac', 'r'); self.cc.extradata = asc
        except Exception: pass

    def __call__(self, data):
        if self.cc is None: return True
        try: return [f.samples for f in self.cc.decode(self.av.Packet(bytes(data)))] == [1024]
        except Exception: return False


class Template:
    """What a good clip of the same camera tells about the layout: per track its kind, the field counts of its metadata samples, the order the non-audio tracks repeat in, the audio frame sizes."""

    def __init__(self, path):
        self.path = path; size = os.path.getsize(path)
        with open(path, 'rb') as f:
            m = mp4._find(f, 0, size, ['moov'])
            if m is None: raise ValueError(f'{path}: no index, so it cannot be a template')
            self.moov = _tree(f, *m)
            self.traks = [v for t, v in self.moov if t == 'trak']; self.kinds = [_kind(t) for t in self.traks]
            for k in self.kinds:
                if isinstance(k, Exception): raise k
            samples = [_samples(t) for t in self.traks]
            ev = sorted((int(o), i, int(z)) for i, (offs, szs) in enumerate(samples) for o, z in zip(offs, szs))
            cyc = []
            for _, i, _ in ev:
                if self.kinds[i] == 'aac': continue
                if i in cyc: break
                cyc.append(i)
            self.cycle = cyc                                                                                 # e.g. [0] for the X3, [3, 4, 5, 6, 0, 1] for the DJI
            self.first = ev[0][0]
            self.fields, self.sig = {}, {}
            for i, k in enumerate(self.kinds):
                if k == 'pb':
                    offs, szs = samples[i]; self.fields[i] = (_pb_count(f, int(offs[0]), int(szs[0])), _pb_count(f, int(offs[1]), int(szs[1])))
                    f.seek(int(offs[0])); first = f.read(1)[0]; f.seek(int(offs[1])); self.sig[i] = (first, f.read(1)[0])       # the first byte (field tag) of the first and of the later samples
            self.size_range = {i: (int(z.min()) // 4, int(z.max()) * 3) for i, (_, z) in enumerate(samples)}
            self.pb_range = {i: ((int(z[0]) // 2, int(z[0]) * 2), (int(z[1:].min() * 0.8), int(z[1:].max() * 1.25) + 8)) for i, (_, z) in enumerate(samples) if self.kinds[i] == 'pb'}   # first, later samples: telemetry varies little
            a = [i for i, k in enumerate(self.kinds) if k == 'aac']; self.audio = a[0] if a else None; self.audio_rule = None
            if self.audio is not None:
                ao, szs = samples[self.audio]; self.audio_range = (int(szs.min() * 0.5), int(szs.max() * 2)); self.audio_typical = float(np.median(szs))
                f.seek(int(ao[1])); self.audio_sig = f.read(1)[0]; self.asc = _asc(_get(self.traks[self.audio], 'mdia', 'minf', 'stbl', 'stsd'))
                vo = samples[cyc[0]][0]; r = (self._delta(cyc[0]) / self._timescale(cyc[0])) / (self._delta(self.audio) / self._timescale(self.audio))
                before = np.searchsorted(np.sort(ao), vo); k = np.arange(len(vo)); lo, hi = (before - k * r).max(), (before + 1 - k * r).min()
                if lo < hi: self.audio_rule = (r, (lo + hi) / 2)                                             # X3: the AAC frames before video frame k are floor(k r + c), on every clip checked
            self.hdr = {t: v for t, v in self.moov if t != 'trak'}

    def _timescale(self, i): m = _get(self.traks[i], 'mdia', 'mdhd'); return _u32(m, 20 if m[0] == 1 else 12)

    def _delta(self, i): return _u32(_get(self.traks[i], 'mdia', 'minf', 'stbl', 'stts'), 12)


# ---- walking the media data --------------------------------------------------------------------------------------------------------------------------------------------------

def _nal_type(kind, hdr): return (hdr >> 1) & 63 if kind == 'hevc' else hdr & 31


def _new_picture(kind, b, i):
    """Does the NAL unit at b[i] (after its 4-byte length) start a new picture? H.264: a slice whose first_mb_in_slice is 0, or SPS/PPS/AUD/SEI; HEVC: a slice with
    first_slice_segment_in_pic_flag set, or VPS/SPS/PPS/AUD/prefix SEI."""
    t = _nal_type(kind, b[i])
    if kind == 'hevc': return t in (32, 33, 34, 35, 39) or (t < 32 and b[i + 2] >> 7 == 1)
    return t in (6, 7, 8, 9) or (t in (1, 5) and b[i + 1] >> 7 == 1)


def _valid_nal(kind, b, i, end):
    """A plausible NAL unit at b[i:] (4-byte length, then its header): (end, type) or None."""
    if i + 6 > end or b[i] != 0: return None
    ln = _u32(b, i); h = b[i + 4]
    if ln < 2 or i + 4 + ln > end or h >> 7: return None
    t = _nal_type(kind, h)
    if kind == 'hevc' and (t > 40 or b[i + 5] not in (1, 2)): return None                             # nuh_layer_id 0, temporal id 0 or 1
    if kind == 'h264' and t not in (1, 5, 6, 7, 8, 9): return None
    return i + 4 + ln, t


def _video(kind, b, i, end):
    """End of the video sample starting at b[i] and whether it is a key frame, or None. A sample is the NAL units up to the next new picture or the next non-video byte."""
    first = _valid_nal(kind, b, i, end)
    if first is None or not _new_picture(kind, b, i + 4): return None
    j, t = first; key = t == 5 if kind == 'h264' else 16 <= t <= 21; seen_slice = (t < 32) if kind == 'hevc' else t in (1, 5)
    while True:
        nxt = _valid_nal(kind, b, j, end) if j < end else None
        if nxt is None: return j, key
        if seen_slice and _new_picture(kind, b, j + 4): return j, key
        j, t = nxt
        if kind == 'hevc': key |= 16 <= t <= 21; seen_slice |= t < 32
        else: key |= t == 5; seen_slice |= t in (1, 5)


class Walker:
    def __init__(self, tpl, b, base):
        self.t, self.b, self.base = tpl, b, base                                                          # b: the media bytes from file offset `base`
        self.samples = {i: [] for i in range(len(tpl.kinds))}; self.keys = {i: [] for i in range(len(tpl.kinds))}
        self.aac = AacCheck(tpl.asc) if tpl.audio is not None else None; self._ok = {}

    def sample(self, track, i, end, first):
        """End of a sample of `track` starting at b[i] (and its key flag), or None."""
        k = self.t.kinds[track]; lo, hi = self.t.size_range[track]
        if k == 'pb':
            if self.b[i] != self.t.sig[track][0 if first else 1]: return None
            e = _pb_fields(self.b, i, self.t.fields[track][0 if first else 1]); plo, phi = self.t.pb_range[track][0 if first else 1]
            return (e, False) if e is not None and e <= end and plo <= e - i <= phi else None
        r = _video(k, self.b, i, end)
        return r if r is not None and lo <= r[0] - i <= hi else None

    def starts(self, pos, track, first, end, depth=2):
        """Is `pos` the start of a `track` sample followed by `depth - 1` more samples of the cycle? (guards against a match inside audio data)"""
        r = self.sample(track, pos, end, first)
        if r is None: return False
        if depth <= 1 or r[0] >= end: return True
        c = self.t.cycle; nt = c[(c.index(track) + 1) % len(c)]
        if self.t.audio is not None and self.b[r[0]] == self.t.audio_sig and self.audio_run(r[0], nt, first and c.index(nt) > 0, end, depth - 1) is not None: return True
        return self.starts(r[0], nt, first and c.index(nt) > 0, end, depth - 1)

    def audio_run(self, pos, track, first, end, depth=3):
        """[(start, end)] of the AAC frames from pos up to the next `track` sample (found by scanning), or None."""
        if depth <= 1: return [(pos, pos)]
        lo, hi = self.t.audio_range; j = pos + lo; want = None
        if self.t.audio_rule and track == self.t.cycle[0]:
            r, c = self.t.audio_rule; k = len(self.samples[track]); want = int(np.floor(k * r + c)) - len(self.samples[self.t.audio])
        while j < min(end, pos + hi * 8):
            if (self.b[j] == 0 or self.t.kinds[track] == 'pb') and self.starts(j, track, first, end, max(depth - 1, 4 if self.t.kinds[track] == 'pb' else 2)):
                cut = self._split(pos, j, want)
                if cut is not None: return cut
            j += 1
        return None

    def _split(self, s, e, want=None):
        """Cut [s, e) into AAC frames. A frame starts with the template's first byte and has a size in the template's range; with `want` (the X3's timing rule) exactly that many frames,
        otherwise the cut whose frame sizes are closest to the template's typical size (DJI audio is nearly constant bit rate)."""
        lo, hi = self.t.audio_range; b = self.b; typ = self.t.audio_typical
        if want is not None and want < 1: return None
        cand = [s] + [k for k in range(s + 1, e) if b[k] == self.t.audio_sig] + [e]
        best = {(s, 0): (0.0, None)}                                                                     # (start, frames so far) -> (cost, previous key)
        for k in cand[:-1]:
            for key in [x for x in best if x[0] == k]:
                for n in cand:
                    if n <= k or not lo <= n - k <= hi or not self.frame_ok(k, n): continue
                    nk = (n, key[1] + 1); cost = best[key][0] + abs(np.log((n - k) / typ))
                    if want is not None and nk[1] > want: continue
                    if nk not in best or cost < best[nk][0]: best[nk] = (cost, key)
        ends = [x for x in best if x[0] == e and (want is None or x[1] == want)]
        if not ends: return None
        key = min(ends, key=lambda x: best[x][0]); out = []
        while key[0] != s: prev = best[key][1]; out.append((prev[0], key[0])); key = prev
        return out[::-1]

    def frame_ok(self, k, n):
        if (k, n) not in self._ok: self._ok[(k, n)] = self.aac(self.b[k:n])
        return self._ok[(k, n)]

    def run(self):
        c = self.t.cycle; pos = 0; end = len(self.b); n = 0; ci = 0
        while pos < end:
            track = c[ci]; first = n == 0
            if self.t.audio is not None and not self.starts(pos, track, first, end):                    # audio (its first frame may not start like the rest: an encoder's priming frame)
                run = self.audio_run(pos, track, first, end)
                if run is None: break
                self.samples[self.t.audio] += run; pos = run[-1][1]; continue
            r = self.sample(track, pos, end, first)
            if r is None: break
            self.samples[track].append((pos, r[0])); self.keys[track].append(r[1]); pos = r[0]
            ci = (ci + 1) % len(c); n += ci == 0
        whole = min(len(self.samples[t]) for t in c)                                                      # complete cycles only: every track the same number of frames
        for t in c: self.samples[t] = self.samples[t][:whole]; self.keys[t] = self.keys[t][:whole]
        if self.t.audio is not None:
            last = self.samples[c[-1]][-1][1] if whole else 0
            self.samples[self.t.audio] = [s for s in self.samples[self.t.audio] if s[1] <= last]
        return {t: [(a + self.base, z - a) for a, z in v] for t, v in self.samples.items()}, self.keys


# ---- writing the new index ------------------------------------------------------------------------------------------------------------------------------------------------

def _box(typ, body): return struct.pack('>I4s', 8 + len(body), typ.encode('latin1')) + body


def _ser(tree): return b''.join(_box(t, _ser(v) if isinstance(v, list) else v) for t, v in tree)


def _full(version_flags, body): return version_flags + body


def _stbl(old, samples, keys, delta):
    """A new sample table: the template's description, one sample a chunk at the found offsets, a constant duration, key frames when the template had them."""
    n = len(samples); offs = np.array([o for o, _ in samples], '>u8'); sizes = np.array([z for _, z in samples], '>u4')
    out = [('stsd', _get(old, 'stsd')), ('stts', b'\0' * 4 + struct.pack('>III', 1, n, delta)), ('stsc', b'\0' * 4 + struct.pack('>IIII', 1, 1, 1, 1)),
           ('stsz', b'\0' * 4 + struct.pack('>II', 0, n) + sizes.tobytes()), ('co64', b'\0' * 4 + struct.pack('>I', n) + offs.tobytes())]
    if _get(old, 'stss') is not None:
        ks = np.flatnonzero(keys) + 1; out.insert(2, ('stss', b'\0' * 4 + struct.pack('>I', len(ks)) + ks.astype('>u4').tobytes()))
    return out


def _set_duration(b, version_at, field_v0, field_v1, value):
    """Replace a duration field in an mvhd/tkhd/mdhd body (version 0: 32-bit, 1: 64-bit)."""
    b = bytearray(b)
    if b[version_at] == 1: b[field_v1:field_v1 + 8] = struct.pack('>Q', value)
    else: b[field_v0:field_v0 + 4] = struct.pack('>I', min(value, 0xffffffff))
    return bytes(b)


MAC_EPOCH = 2082844800      # seconds from 1904-01-01 (MP4 times) to 1970-01-01
DROP = {'udta', 'meta'}     # the template's own user data (DJI: its clip id, a thumbnail, settings): not this recording's, so left out


def _set_times(b, when):
    """Creation and modification time of an mvhd/tkhd/mdhd body (`when`: POSIX seconds; None keeps the template's)."""
    if when is None: return b
    b = bytearray(b); t = int(when) + MAC_EPOCH
    if b[0] == 1: b[4:20] = struct.pack('>QQ', t, t)
    else: b[4:12] = struct.pack('>II', t, t)
    return bytes(b)


def build_moov(tpl, samples, keys, when=None):
    """The template's moov with this recording's sample tables, durations and (`when`, POSIX seconds) creation time."""
    mvhd = tpl.hdr['mvhd']; mts = _u32(mvhd, 20 if mvhd[0] == 1 else 12); traks = []; longest = 0
    for i, trak in enumerate(tpl.traks):
        mdia = _get(trak, 'mdia'); mdhd = _get(mdia, 'mdhd'); ts = _u32(mdhd, 20 if mdhd[0] == 1 else 12)
        stts = _get(mdia, 'minf', 'stbl', 'stts'); delta = _u32(stts, 12)
        dur = len(samples[i]) * delta; mdur = dur * mts // ts; longest = max(longest, mdur)
        stbl = _stbl(_get(mdia, 'minf', 'stbl'), samples[i], np.array(keys.get(i) or [False] * len(samples[i]), bool), delta)
        minf = [(t, stbl if t == 'stbl' else v) for t, v in _get(mdia, 'minf')]
        mdia = [(t, _set_times(_set_duration(v, 0, 16, 24, dur), when) if t == 'mdhd' else minf if t == 'minf' else v) for t, v in mdia]
        new = []
        for t, v in trak:
            if t in DROP: continue
            if t == 'tkhd': v = _set_times(_set_duration(v, 0, 20, 28, mdur), when)
            elif t == 'mdia': v = mdia
            elif t == 'edts': v = [(et, _elst(ev, mdur) if et == 'elst' else ev) for et, ev in v]
            new.append((t, v))
        traks.append(('trak', new))
    out = []; ti = iter(traks)
    for t, v in tpl.moov:
        if t == 'trak': out.append(next(ti))
        elif t == 'mvhd': out.append((t, _set_times(_set_duration(v, 0, 16, 24, longest), when)))
        elif t not in DROP: out.append((t, v))
    return _box('moov', _ser(out))


def _elst(b, mdur):
    """The template's edit list with its last segment's duration set to the new track length (an initial empty edit, if any, is kept)."""
    b = bytearray(b); v, n = b[0], _u32(b, 4); w = 20 if v == 1 else 12; o = 8 + (n - 1) * w
    if v == 1: b[o:o + 8] = struct.pack('>Q', mdur)
    else: b[o:o + 4] = struct.pack('>I', min(mdur, 0xffffffff))
    return bytes(b)


def x3_trailer(template_rear):
    """A trailer with only the template's camera record (0x101: model, serial, firmware, lens calibration), in the layout insta360.read_trailer expects."""
    from strata360.osv import insta360
    rec = insta360.read_trailer(template_rear)[insta360.REC_EXTRA]
    body = rec + struct.pack('<HI', insta360.REC_EXTRA, len(rec))
    return body + b'\0' * 32 + struct.pack('<II', len(body) + 72, 3) + insta360.MAGIC


def media_start(path):
    """Offset just after the 8-byte mdat header. (A cut-short X3 file's mdat has size 0 and its 64-bit size, 8 more bytes, unwritten: the template's first sample offset says where the media starts.)"""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        for typ, s, e in mp4._boxes(f, 0, size):
            if typ == 'mdat': return s
    raise ValueError(f'{path}: no media data')


def mdat_header(path):
    """Offset of the mdat header when its size is 0 (unfinished: the X3 leaves it so, with its 64-bit size unwritten), else None."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        for typ, s, e in mp4._boxes(f, 0, size):
            if typ == 'mdat':
                f.seek(s - 8); return s - 8 if struct.unpack('>I', f.read(4))[0] == 0 else None
    return None


def blank_boxes(path):
    """Offsets of top-level boxes whose type is four zero bytes (space reserved by the camera and never written)."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f: return [s - 8 for typ, s, e in mp4._boxes(f, 0, size) if typ == '\0\0\0\0']


def recover(src, template, dest, trailer=None, when=None):
    """Write `dest` = the bytes of `src` + a new moov (+ `trailer`); `when` (POSIX seconds) is written as its creation time. `src` is only read. Returns a summary dict."""
    tpl = Template(template); start = media_start(src); size = os.path.getsize(src)
    start = max(start, tpl.first)                                                                       # the first sample is at a fixed offset for a camera (X3 48, DJI 4096)
    b = np.memmap(src, np.uint8, 'r', offset=start, shape=(size - start,))
    samples, keys = Walker(tpl, b, start).run(); del b
    n = {i: len(v) for i, v in samples.items()}
    if not n[tpl.cycle[0]]: raise ValueError(f'{src}: no complete frame found')
    moov = build_moov(tpl, samples, keys, when)
    os.makedirs(os.path.dirname(dest), exist_ok=True); tmp = dest + '.part'
    with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
        shutil.copyfileobj(fi, fo, 64 << 20); fo.write(moov)
        if trailer: fo.write(trailer)
        for h in blank_boxes(src): fo.seek(h); fo.write(struct.pack('>I4s', size - h, b'free'))                                    # the DJI reserves the space for its moov as a box with no type: readers stop there
        h = mdat_header(src)
        if h is not None:
            fo.seek(h)
            if start >= h + 16: fo.write(struct.pack('>I4sQ', 1, b'mdat', size - h))
            elif size - h < 1 << 32: fo.write(struct.pack('>I4s', size - h, b'mdat'))
            else: raise ValueError(f'{src}: the media data is over 4 GB and has no room for a 64-bit size')           # an X3 mdat says "to the end of the file" (size 0), which would swallow the new moov: give the copy its real size
    os.replace(tmp, dest)
    used = max(o + z for v in samples.values() for o, z in v)
    return dict(src=src, dest=dest, template=template, samples=n, kinds=tpl.kinds, dropped_bytes=size - used)


# ---- a whole footage folder -----------------------------------------------------------------------------------------------------------------------------------------------

RECOVERED = 'recovered'      # <library>/strata360/recovered/: the rebuilt copies, under their original names (discovery uses them in place of the originals)
_X3 = re.compile(r'^(?P<kind>VID|LRV)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<lens>\d{2})_(?P<n>\d{3})\.(?P<ext>insv|lrv)$', re.I)
_DJI = re.compile(r'^CAM_(?P<date>\d{8})(?P<time>\d{6})_\d+_\w\.(?P<ext>osv|lrf)$', re.I)


def recovered_dir(library): return os.path.join(library, 'strata360', RECOVERED)


def _name_time(fn):
    m = _X3.match(fn) or _DJI.match(fn)
    return dt.datetime.strptime(m['date'] + m['time'], '%Y%m%d%H%M%S').replace(tzinfo=dt.timezone.utc) if m else None


def _role(fn):
    """What a file is, so a template of the same kind is found: ('x3', '00' | '10' | '11') or ('dji', 'osv' | 'lrf'), else None."""
    m = _X3.match(fn)
    if m: return ('x3', m['lens'])
    m = _DJI.match(fn)
    return ('dji', m['ext'].lower()) if m else None


def cut_short_files(library):
    """Camera files under `library` (not its strata360 folder) that were cut short."""
    out = []
    for root, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if d != 'strata360']
        out += [os.path.join(root, fn) for fn in sorted(files) if _role(fn) and mp4.cut_short(os.path.join(root, fn))]
    return out


def template_for(path):
    """The good file of the same kind in the same folder recorded nearest in time (same camera settings, most likely), or None. An X3 rear lens file also needs its trailer."""
    from strata360.osv import insta360
    d, fn = os.path.split(path); role, t = _role(fn), _name_time(fn); best = None
    for other in os.listdir(d):
        if other == fn or _role(other) != role: continue
        p = os.path.join(d, other)
        if mp4.cut_short(p): continue
        with open(p, 'rb') as f:
            if mp4._find(f, 0, os.path.getsize(p), ['moov']) is None: continue
        if role == ('x3', '00'):
            try: insta360.read_trailer(p)
            except ValueError: continue
        gap = abs((_name_time(other) - t).total_seconds())
        if best is None or gap < best[0]: best = (gap, p)
    return best and best[1]


def recover_library(library, log=print):
    """Rebuild every cut-short camera file under `library` into <library>/strata360/recovered/ (originals are only read). Returns [summary dicts]; a file already rebuilt is skipped."""
    out = []; dest_dir = recovered_dir(library)
    for src in cut_short_files(library):
        fn = os.path.basename(src); dest = os.path.join(dest_dir, fn)
        if os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(src): log(f'{fn}: already rebuilt'); continue
        tpl = template_for(src)
        if tpl is None: log(f'{fn}: no good recording of the same kind in its folder to learn the layout from; skipped'); out.append(dict(src=src, error='no template')); continue
        trailer = x3_trailer(tpl) if _role(fn) == ('x3', '00') else None
        log(f'{fn}: rebuilding the index (template {os.path.basename(tpl)}) ...')
        try: r = recover(src, tpl, dest, trailer=trailer, when=_name_time(fn).timestamp())
        except Exception as e: log(f'{fn}: failed: {e}'); out.append(dict(src=src, error=str(e))); continue
        n = r['samples']; tr = Template(tpl); v = n[tr.cycle[-1]]; fps = tr._timescale(tr.cycle[-1]) / tr._delta(tr.cycle[-1])
        log(f'{fn}: {v} frames ({v / fps:.1f} s) recovered, {r["dropped_bytes"]} bytes after the last whole frame left out'); out.append(r)
    return out
