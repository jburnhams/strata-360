"""Per-frame telemetry from an OSV: quaternion attitude, timestamps, accel, ISO/shutter."""
import hashlib, os, struct, tempfile, numpy as np
from strata360.osv.pbdump import parse, packets


def cache_dir():
    """Where the parsed telemetry of each OSV is kept (reading it means reading the whole multi-gigabyte file from the drive: about 30 s a clip, in every stage that opens the clip). STRATA_CACHE, else ~/.cache/strata360."""
    d = os.environ.get('STRATA_CACHE') or os.path.join(os.path.expanduser('~'), '.cache', 'strata360')
    return os.path.join(d, 'telemetry') if os.access(os.path.dirname(d) or '.', os.W_OK) or os.path.isdir(d) else os.path.join(tempfile.gettempdir(), 'strata360-telemetry')


def _cached(osv, name, make):
    """The result of `make()` (a dict of numpy arrays) kept in an .npz next to nothing else: keyed by the file's path, size and modification time, so a changed file is read again."""
    try: st = os.stat(osv)
    except OSError: return make()                                                                       # not a real file (a test, a pipe): nothing to key a cache on
    key = hashlib.sha1(f'{os.path.realpath(osv)}|{st.st_size}|{st.st_mtime_ns}|{name}|1'.encode()).hexdigest()[:20]; d = cache_dir(); path = os.path.join(d, f'{key}.npz')
    try:
        with np.load(path) as z: return {k: z[k] for k in z.files}
    except (OSError, ValueError, KeyError): pass
    out = make()
    try:
        os.makedirs(d, exist_ok=True); tmp = path + f'.{os.getpid()}.tmp.npz'; np.savez(tmp, **out); os.replace(tmp, path)
    except OSError: pass
    return out

def read_frames(osv, djmd_stream=3):
    """Returns dict of arrays, one row per djmd packet (= per video frame):
       ts_us (device microseconds), quat (N,4) fields 1..4 in stored order, acc (N,3). Cached on disk (see `_cached`)."""
    return align_to_frames(_cached(osv, f'frames{djmd_stream}', lambda: _read_frames(osv, djmd_stream)))


def missing_frames(ts_us):
    """For each row, how many frames were lost before it: where the timestamps jump by more than 1.5 steps the camera dropped frames (a clip with one 180 ms and one 40 ms jump has lost 8 + 1 = 9 frames after them). All zero when the timestamps are even."""
    ts = np.asarray(ts_us, float)
    if len(ts) < 3: return np.zeros(len(ts), int)
    d = np.diff(ts); step = float(np.median(d))
    if step <= 0: return np.zeros(len(ts), int)
    lost = np.where(d > 1.5 * step, np.round(d / step) - 1, 0).astype(int)
    return np.concatenate([[0], np.cumsum(lost)])


def align_to_frames(T):
    """The orientation and acceleration of each frame, as it must be used with that frame's PICTURE. In a clip where the camera dropped frames (the timestamps jump) the rows run ahead of the pictures by exactly the number of frames lost: measured on clip 0021 of the Legends race (one jump of 180 ms and one of 40 ms near the start),
    the image motion of both lenses matched the gyro 9.0 frames (180 ms) late at 10, 25 and 45 s (correlation 0.97 to 0.99), and in clips without jumps at 0 ms. So row m is read from row m minus the frames lost before it. Clips with even timestamps are returned as they are."""
    lost = missing_frames(T['ts_us'])
    if not lost.any(): return T
    idx = np.maximum(np.arange(len(lost)) - lost, 0)
    return dict(T, quat=T['quat'][idx], acc=T['acc'][idx])


def _read_frames(osv, djmd_stream=3):
    ts, q, acc = [], [], []
    for pk in packets(osv, djmd_stream):
        fm = [v for f, w, v in parse(pk) if f == 3][0]
        d = {f: v for f, w, v in parse(fm) if w == 2}
        ts.append([v for f, w, v in parse(d[1]) if f == 2][0])
        b = {f: v for f, w, v in parse(d[2]) if w == 2}
        qq = {f: struct.unpack('<f', v)[0] for f, w, v in parse(b[9]) if w == 5}
        q.append([qq.get(i, 0.0) for i in (1, 2, 3, 4)])
        aa = {f: struct.unpack('<f', v)[0] for f, w, v in parse(b[10]) if w == 5}
        acc.append([aa.get(i, 0.0) for i in (2, 3, 4)])
    return dict(ts_us=np.array(ts, np.int64), quat=np.array(q), acc=np.array(acc))

def video_pts(osv, stream=0):
    """Presentation times (seconds, sorted) of the video frames. The first video track comes from the MP4 index (a few milliseconds; identical to the packet scan, checked on two clips); anything else, or
    a file the index reader cannot handle, from an ffprobe packet scan (reads the whole file: about 80 s for a 3 GB clip)."""
    if stream == 0:
        try:
            from strata360.osv import mp4
            return mp4.video_sample_times(osv)
        except Exception: pass
    import subprocess
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', f'v:{stream}', '-show_entries',
                                   'packet=pts_time', '-of', 'csv=p=0', osv]).split()
    return np.array(sorted(float(x) for x in out))


def read_exposure(osv):
    """Per-frame exposure (cached on disk, see `_cached`)."""
    flat = _cached(osv, 'exposure', lambda: {f'{n}__{k}': v for n, d in _read_exposure(osv).items() for k, v in d.items()})
    out = {}
    for key, v in flat.items(): n, k = key.split('__', 1); out.setdefault(n, {})[k] = v
    return out


def _read_exposure(osv):
    """Per-frame exposure of each djmd track (stream 3 and 4): ISO, shutter denominator, colour temperature.
    FrameMeta.2: field 3 = ISO (f32), field 4 = message whose varint (after a small tag) is the shutter denominator,
    field 6 = colour temperature (K)."""
    import struct
    out = {}
    for name, idx in (('djmd3', 3), ('djmd4', 4)):
        iso, shut, ct = [], [], []
        for pk in packets(osv, idx):
            fm = [v for f, w, v in parse(pk) if f == 3][0]
            b = {f: v for f, w, v in parse(fm) if w == 2}
            e = {f: v for f, w, v in parse(b[2]) if w == 2}
            iso.append(struct.unpack('<f', [v for f, w, v in parse(e[3]) if w == 5][0])[0])
            sh = parse(e[4]); den = 0
            raw = e[4]
            # e[4] = field1 length-delimited bytes: first byte is a tag (0x01), followed by a varint denominator
            inner = [v for f, w, v in sh if w == 2][0]
            i = 1; den = 0; s = 0
            while i < len(inner):
                c = inner[i]; i += 1; den |= (c & 0x7f) << s; s += 7
                if not c & 0x80: break
            shut.append(den)
            ct.append([v for f, w, v in parse(e[6])][0])
        out[name] = dict(iso=np.array(iso), shutter_den=np.array(shut), ct=np.array(ct))
    return out
