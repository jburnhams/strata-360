"""Per-frame telemetry from an OSV: quaternion attitude, timestamps, accel, ISO/shutter."""
import struct, numpy as np
from strata360.osv.pbdump import parse, packets

def read_frames(osv, djmd_stream=3):
    """Returns dict of arrays, one row per djmd packet (= per video frame):
       ts_us (device microseconds), quat (N,4) fields 1..4 in stored order, acc (N,3)."""
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
    import subprocess
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', f'v:{stream}', '-show_entries',
                                   'packet=pts_time', '-of', 'csv=p=0', osv]).split()
    return np.array(sorted(float(x) for x in out))


def read_exposure(osv):
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
