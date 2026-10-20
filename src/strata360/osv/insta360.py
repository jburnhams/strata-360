"""Insta360 (.insv) adapter: presents an Insta360 X-series recording to the rest of the pipeline exactly as an Osmo 360 .OSV looks (README 2).

A recording is TWO files, one per lens (VID_YYYYMMDD_HHMMSS_00_NNN.insv = the REAR lens, the one that sees the wearer; ..._10_NNN.insv = the FRONT lens), plus an optional low-res LRV_..._11_NNN.lrv. Each is an ordinary MP4
(one H.264 stream, 2880 x 2880 on the X3, AAC audio); the primary file (_00_) carries a proprietary trailer after the MP4 data with the camera's metadata. The pipeline's `osv` path of a clip is the primary file.

Trailer (found in the X3 sample, see docs/progress): the file ends with the 32-byte magic, then u32 trailer length and u32 version, preceded by 38 more bytes; records are read BACKWARDS from there, each being data followed by
(u16 id, u32 length). Ids used: 0x101 protobuf with device, calibration and the IMU matrix; 0x300 the IMU, 1 kHz, 20 bytes a sample (u64 microseconds, then six u16 offset-binary: accelerometer x y z, gyroscope x y z; the
gyroscope is 2000 deg/s over 32768); 0x400 per-frame exposure time (u64 microseconds, f64 seconds), whose timestamps are the camera clock the IMU shares.

What this module gives the rest of the pipeline (same shapes as the DJI readers in calib.py / telemetry.py / meta.py):
  slots(path)        the two lenses as Kannala-Brandt slots in the lens video's own pixels (the calibration is a unified-camera (Mei) model: it is converted by a fit, `_fit_kb`)
  read_frames(path)  per-frame camera clock, upright orientation quaternion and acceleration, from the gyro and accelerometer (`fuse`)
  read_exposure(path), header(path)
Body frame as DJI's: +Y the front lens, -Y the rear lens, +Z up along the stick, +X right. IMU frame -> body: x_b = z_i, y_b = y_i, z_b = -x_i (the camera is mounted square on its axes: measured by matching image rotation to gyro rotation).
"""
import functools, os, re, struct
import numpy as np
from strata360.osv.pbdump import parse

MAGIC = b'8db42d694ccc418790edff439fe026bf'
REC_EXTRA, REC_GYRO, REC_EXPOSURE, REC_AAA = 0x101, 0x300, 0x400, 0x900
GYRO_DPS_PER_LSB = 2000.0 / 32768.0
IMU_TO_BODY = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
VIDEO_LATENCY_S = 0.2336            # the camera clock at the first video frame, after the first exposure record (7 frames; 0.223 to 0.234 s on three clips, by matching image motion to the gyro)
CANVAS = 5952.0                     # the calibration is for a side-by-side canvas of two 5952-px lens images; the 2880-px video is that halved and cropped by 48 px each side (found by stitching: relative lens rotation 179.8 deg)
_NAME = re.compile(r'^(?P<kind>VID|PRO|IMG)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<lens>\d{2})_(?P<n>\d{3})\.insv$', re.I)


def is_insv(path): return str(path).lower().endswith('.insv')


def parse_name(path):
    """(date, time, number) of an Insta360 file name, or None."""
    m = _NAME.match(os.path.basename(path)); return (m['date'], m['time'], m['n'], m['lens']) if m else None


def lens_file(osv, stream):
    """The video file of one lens: stream 1 = front (_10_), stream 0 = rear (_00_, the primary file)."""
    if stream == 0: return osv
    d, b = os.path.split(osv); return os.path.join(d, re.sub(r'_00_(\d{3}\.insv)$', r'_10_\1', b, flags=re.I))


def lrv_file(osv):
    d, b = os.path.split(osv); m = _NAME.match(b)
    if not m: return None
    for name in (f"LRV_{m['date']}_{m['time']}_11_{m['n']}.lrv", f"LRV_{m['date']}_{m['time']}_11_{m['n']}.LRV"):
        if os.path.exists(os.path.join(d, name)): return os.path.join(d, name)
    return None


# ---- the trailer ---------------------------------------------------------------------------------------------------------------------------------------------------------

def read_trailer(path):
    """{record id: bytes} of the trailer of a primary .insv (reads only the trailer, a few MB). ValueError when the file has none."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if size < 128: raise ValueError('too small for an Insta360 trailer')
        f.seek(size - 40); tl, ver = struct.unpack('<II', f.read(8))
        if f.read(32) != MAGIC: raise ValueError('no Insta360 trailer (the _10_ file has none: use the _00_ file)')
        if not 78 < tl < size: raise ValueError('bad trailer length')
        start = size - tl; p = size - 78; rec = {}
        while p - 6 > start:
            f.seek(p); rid, ln = struct.unpack('<HI', f.read(6))
            if ln == 0 or p - ln < start: break
            f.seek(p - ln); rec[rid] = f.read(ln); p = p - ln - 6
    return rec


@functools.lru_cache(maxsize=8)
def _extra_cached(path, size, mtime): return _extra(read_trailer(path))


def extra(path):
    """The device block (record 0x101): serial, model, firmware, lens calibration string, IMU matrix, ..."""
    st = os.stat(path); return _extra_cached(path, st.st_size, st.st_mtime_ns)


def _extra(rec):
    if REC_EXTRA not in rec: raise ValueError('no metadata record in the Insta360 trailer')
    out = dict(serial=None, model=None, firmware=None, calibration=None, imu_matrix=None)
    dec = lambda b: b.decode('ascii', 'replace')
    f60 = []
    for f, w, v in parse(rec[REC_EXTRA]):
        if f == 1 and w == 2: out['serial'] = dec(v)
        elif f == 2 and w == 2: out['model'] = dec(v)
        elif f == 3 and w == 2: out['firmware'] = dec(v)
        elif f == 54 and w == 2: out['calibration'] = dec(v)
        elif f == 60 and w == 5: f60.append(struct.unpack('<f', v)[0])
    if len(f60) == 9: out['imu_matrix'] = np.array(f60).reshape(3, 3)
    return out


# ---- lens calibration ----------------------------------------------------------------------------------------------------------------------------------------------------

def parse_calibration(s):
    """The two lens models from the calibration string `2_<lens 1>_<lens 2>_<n>` where each lens is xi, fx, fy, cx, cy, rotation (3, degrees), translation (3), k1 k2 k3, p1 p2, canvas width, height, 71.
    A unified camera (Mei) model: x = X / (Z + xi |X|), radial k1..k3 and tangential p1, p2 as OpenCV, then pixel = f x + c, in a 5952-px lens image of a side-by-side canvas (the second lens's cx is offset by 5952)."""
    p = s.split('_')
    if len(p) < 2 + 2 * 19 or p[0] != '2': raise ValueError(f'unknown Insta360 calibration: {s[:40]}')
    lens = []
    for i in range(2):
        g = [float(x) for x in p[1 + 19 * i: 1 + 19 * (i + 1)]]
        lens.append(dict(xi=g[0], fx=g[1], fy=g[2], cx=g[3] - (CANVAS if i == 1 else 0.0), cy=g[4], rot=g[5:8], trans=g[8:11], k=g[11:14], p=g[14:16]))
    return lens


def _mei_radius(L, theta):
    """Radius in canvas px of the image of a ray at angle `theta` (radians) from the optical axis."""
    x = np.sin(theta) / (np.cos(theta) + L['xi']); r2 = x * x; k1, k2, k3 = L['k']
    return L['fx'] * x * (1 + k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3)


def canvas_to_video(size):
    """(scale, offset) taking a calibration (canvas) pixel to a pixel of the lens video of `size` px: video = canvas * scale - offset. The 2880-px video is the canvas halved and cropped by 48 px each side (measured); any other size is
    assumed to be the whole canvas scaled (not checked)."""
    return (0.5, (CANVAS * 0.5 - size) / 2.0) if size <= CANVAS / 2.0 else (size / CANVAS, 0.0)


@functools.lru_cache(maxsize=32)
def lens_size(path):
    """Width in pixels of the (square) lens video of a primary .insv: 2880 on the X3."""
    import json, subprocess
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width', '-of', 'json', path])
    return int(json.loads(out)['streams'][0]['width'])


def _fit_kb(L, size=2880, theta_max_deg=110.0):
    """Kannala-Brandt terms (k1..k5 of calib.Lens) that reproduce the Mei lens's radius curve, in pixels of a lens video of `size` px: (fx, [k1..k5], cx, cy, worst error in px)."""
    s, off = canvas_to_video(size)
    th = np.radians(np.linspace(0.0, theta_max_deg, 400)); r = _mei_radius(L, th) * s
    f = float(_mei_radius(L, np.array([1e-4]))[0] / 1e-4 * s)       # central slope, px per radian
    A = np.stack([th ** (2 * (i + 1) + 1) for i in range(5)], -1); y = r / f - th
    k, *_ = np.linalg.lstsq(A, y, rcond=None); err = float(np.abs(f * (th + A @ k) - r).max())
    return f, k, L['cx'] * s - off, L['cy'] * s - off, err


def _quat_wxyz(R):
    from scipy.spatial.transform import Rotation as Rot
    x, y, z, w = Rot.from_matrix(R).as_quat(); return np.array([w, x, y, z])


# lens axes in the body frame (rows: the lens's image x, image y (down) and optical axis), from the IMU matching above and the 179.8 degree lens-to-lens rotation (stitched sample)
_R_FRONT = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
_R_REAR = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, -1.0, 0.0]])


# Measured correction of the front lens against the nominal 180-degree flip, from 32 stitched frames of the X3 sample (feature matches in the lens overlap, then refined against the seam edge match with a held-out half:
# edge disagreement at the seam fell by about a fifth, and 30 of 32 frames improved). A rotation vector in degrees (body frame) and a focal scale. Calibration is per camera, so this is applied to the X3 only.
FRONT_ROTVEC_DEG = (0.609, 0.991, 0.121)
FRONT_FOCAL_SCALE = 1.004


def _front_rotation(model):
    """The front lens's body-to-lens rotation, corrected for the X3's measured alignment (other models: nominal)."""
    if not (model or '').startswith('Insta360 X3'): return _R_FRONT
    from scipy.spatial.transform import Rotation as Rot
    return _R_FRONT @ Rot.from_rotvec(np.radians(FRONT_ROTVEC_DEG)).as_matrix().T


def slots(path):
    """{1: rear lens, 2: front lens} in calib.read_slots' shape: fx fy (1, 2), cx cy (3, 4), k1..k4 (5..8), k5 (15), extrinsic quaternion 'q' (body -> lens), and an empty selfie-stick occlusion polygon."""
    x = extra(path); lens = parse_calibration(x['calibration']); out = {}; x3 = (x['model'] or '').startswith('Insta360 X3'); size = lens_size(path)
    for slot, L, R in ((1, lens[0], _R_REAR), (2, lens[1], _front_rotation(x['model']))):
        f, k, cx, cy, _ = _fit_kb(L, size)
        if slot == 2 and x3: f *= FRONT_FOCAL_SCALE
        out[slot] = {1: f, 2: f, 3: cx, 4: cy, 5: k[0], 6: k[1], 7: k[2], 8: k[3], 15: k[4], 10: size, 11: size, 'q': _quat_wxyz(R),
                     'poly_x': np.zeros(0), 'poly_y': np.zeros(0)}
    return out


# ---- motion --------------------------------------------------------------------------------------------------------------------------------------------------------------

def read_imu(path):
    """(t_s, gyro (N, 3) rad/s, accel (N, 3) raw LSB), in the IMU's own axes and the camera clock (seconds)."""
    rec = read_trailer(path)
    if REC_GYRO not in rec: raise ValueError('no IMU record')
    a = np.frombuffer(rec[REC_GYRO], np.uint8); a = a[:len(a) // 20 * 20].reshape(-1, 20)
    ts = a[:, :8].copy().view('<u8').ravel().astype(np.float64) / 1e6
    raw = a[:, 8:].copy().view('<u2').reshape(-1, 6).astype(np.float64) - 32768.0
    keep = ts > np.maximum.accumulate(np.r_[-np.inf, ts[:-1]])                                         # now and then a few ms of samples are written twice (the clock steps back 14 ms): keep only samples later than all before them
    ts, raw = ts[keep], raw[keep]
    return ts, np.radians(raw[:, 3:] * GYRO_DPS_PER_LSB), raw[:, :3]


def read_exposure_records(path):
    """(camera-clock seconds (N,), exposure time seconds (N,)): one record a frame."""
    rec = read_trailer(path)
    if REC_EXPOSURE not in rec: raise ValueError('no exposure record')
    d = np.frombuffer(rec[REC_EXPOSURE], np.uint8); d = d[:len(d) // 16 * 16].reshape(-1, 16)
    return d[:, :8].copy().view('<u8').ravel().astype(np.float64) / 1e6, d[:, 8:].copy().view('<f8').ravel()


def read_aaa(path):
    """(camera-clock seconds, ISO) of the auto-exposure table (record 0x900: 48-byte entries about every 4 frames; u32 ms timestamp, f32 target EV, f32 exposure ms, u32 stats, u32 packed luma stats whose top 13 bits give the
    ISO as `100 * (bits >> 19) >> 6`; layout from Gyroflow's telemetry-parser, checked here: ISO about 3100 at dusk with the shutter at its limit, 110 to 350 by day). The first entry is a header and is skipped."""
    rec = read_trailer(path)
    if REC_AAA not in rec: raise ValueError('no auto-exposure record')
    a = np.frombuffer(rec[REC_AAA], np.uint8); a = a[:len(a) // 48 * 48].reshape(-1, 48).astype(np.int64); a = a[a.any(1)][1:]
    ts = (a[:, 0] | a[:, 1] << 8 | a[:, 2] << 16 | a[:, 3] << 24) / 1000.0
    ls = a[:, 16] | a[:, 17] << 8 | a[:, 18] << 16 | a[:, 19] << 24
    return ts, ((100 * ((ls & 0xFFF80000) >> 19)) >> 6).astype(np.float64)


def has_motion(path):
    """Does the trailer hold the IMU? A recording rebuilt after it was cut short (osv/recover.py) has only the camera record."""
    return REC_GYRO in read_trailer(path)


NO_EXPOSURE_ISO, NO_EXPOSURE_SHUTTER_DEN = 100.0, 100      # what a rebuilt recording, which has no exposure record, reports (clip.json says so in its notes)


def device_start(path):
    """Camera clock (seconds) at the first video frame (0 when the exposure record is missing)."""
    try: ets, _ = read_exposure_records(path)
    except ValueError: return 0.0
    return float((ets[1] if len(ets) > 1 else ets[0]) + VIDEO_LATENCY_S)


IMU_GAP_S = 0.05      # a block longer than this is a hole in the IMU record (56 of 881 X3 clips lose 0.2 to 1 s about a second into the video)
RELEVEL_BLOCKS = 40   # after a hole, 'up' is measured again from the next 40 blocks (0.2 s) of accelerometer


def fuse(dt, w, a, kp=0.8, block=5):
    """Upright orientation from the gyroscope (rad/s, body axes) and accelerometer (any scale, body axes): Mahony filter, body-to-world quaternions (w, x, y, z), world Z up and yaw starting at 0 (it drifts with the
    gyro's bias, which has no reference: only the clip's median bias is removed). The accelerometer pulls the 'up' direction back where its length is near gravity (kp per second); running shakes pass through the gate.
    Across a hole in the record (a block longer than IMU_GAP_S) the rotation is unknown: the orientation is held rather than spinning on at the last rate, and 'up' is re-levelled from the accelerometer after it
    (the shortest turn, so the heading is kept)."""
    n = len(dt) // block * block
    if n < block: return np.tile([1.0, 0.0, 0.0, 0.0], (len(dt), 1))
    dtb = dt[:n].reshape(-1, block).sum(1); wb = w[:n].reshape(-1, block, 3).mean(1); ab = a[:n].reshape(-1, block, 3).mean(1)
    mag = np.linalg.norm(ab, axis=1); g0 = float(np.median(mag[mag > 0])) if (mag > 0).any() else 1.0
    gate = np.exp(-(((mag / max(g0, 1e-9)) - 1.0) / 0.2) ** 2); an = ab / np.maximum(mag, 1e-9)[:, None]
    up0 = an[:min(len(an), 200)].mean(0); up0 /= max(np.linalg.norm(up0), 1e-9)                         # start level: the shortest turn that takes the measured 'up' to world Z
    ax = np.cross(up0, [0.0, 0.0, 1.0]); s = np.linalg.norm(ax); ang = np.arctan2(s, up0[2])
    ax = ax / s if s > 1e-9 else np.array([1.0, 0.0, 0.0])
    qw, qx, qy, qz = float(np.cos(ang / 2)), *(float(np.sin(ang / 2)) * ax)
    out = np.empty((len(dtb), 4)); wl = wb.tolist(); al = an.tolist(); gl = gate.tolist(); dl = dtb.tolist()
    for i in range(len(dl)):
        ux, uy, uz = al[i]; vx = 2 * (qx * qz - qw * qy); vy = 2 * (qy * qz + qw * qx); vz = qw * qw - qx * qx - qy * qy + qz * qz
        if dl[i] > IMU_GAP_S:
            u = an[i:i + RELEVEL_BLOCKS].mean(0); u /= max(np.linalg.norm(u), 1e-9); c = np.cross(u, [vx, vy, vz]); s = np.linalg.norm(c); ang = np.arctan2(s, float(np.dot(u, [vx, vy, vz])))
            if s > 1e-9:                                                                               # q <- q * c, c turning the measured up onto the predicted one, so world Z seen from the body is the measured up
                cw, (cx, cy, cz) = np.cos(ang / 2), np.sin(ang / 2) * c / s
                qw, qx, qy, qz = qw * cw - qx * cx - qy * cy - qz * cz, qw * cx + qx * cw + qy * cz - qz * cy, qw * cy - qx * cz + qy * cw + qz * cx, qw * cz + qx * cy - qy * cx + qz * cw
            out[i] = (qw, qx, qy, qz); continue
        k = kp * gl[i]; wx = wl[i][0] + k * (uy * vz - uz * vy); wy = wl[i][1] + k * (uz * vx - ux * vz); wz = wl[i][2] + k * (ux * vy - uy * vx)
        h = 0.5 * dl[i]; dx, dy, dz = wx * h, wy * h, wz * h
        nw = qw - qx * dx - qy * dy - qz * dz; nx = qw * dx + qx + qy * dz - qz * dy; ny = qw * dy - qx * dz + qy + qz * dx; nz = qw * dz + qx * dy - qy * dx + qz
        r = (nw * nw + nx * nx + ny * ny + nz * nz) ** -0.5; qw, qx, qy, qz = nw * r, nx * r, ny * r, nz * r
        out[i] = (qw, qx, qy, qz)
    return out, dtb, g0


def frames_from_imu(path, pts):
    """Telemetry rows for video frames at presentation times `pts` (seconds): dict(ts_us, quat (N, 4) w x y z, acc (N, 3) m/s^2)."""
    from scipy.spatial.transform import Rotation as Rot, Slerp
    pts = np.asarray(pts, float); pts = pts - pts[0]
    if not has_motion(path):                                                                           # rebuilt recording: no IMU; held upright, facing the start direction
        n = len(pts); return dict(ts_us=np.round(pts * 1e6).astype(np.int64), quat=np.tile([1.0, 0.0, 0.0, 0.0], (n, 1)), acc=np.tile([0.0, 0.0, 9.80665], (n, 1)))
    t, gyro, acc = read_imu(path)
    wb = gyro @ IMU_TO_BODY.T; ab = acc @ IMU_TO_BODY.T; bias = np.median(wb, 0)
    dt = np.gradient(t); q, dtb, g0 = fuse(dt, wb - bias, ab); block = 5; n = len(dtb) * block
    tb = t[:n].reshape(-1, block).mean(1)                                                              # block mid times
    T = device_start(path) + pts; T = np.clip(T, tb[0], tb[-1])
    R = Rot.from_quat(q[:, [1, 2, 3, 0]]); quat = Slerp(tb, R)(T).as_quat()[:, [3, 0, 1, 2]]
    quat *= np.where(quat[:, :1] < 0, -1.0, 1.0)                                                       # w >= 0: one sign for a rotation
    a_ms2 = np.stack([np.interp(T, t, ab[:, i]) for i in range(3)], -1) * (9.80665 / g0)
    return dict(ts_us=np.round((device_start(path) + pts) * 1e6).astype(np.int64), quat=quat, acc=a_ms2)


def exposure_frames(path, pts):
    """Per-frame exposure like the DJI reader's: ISO from the auto-exposure table (100 where there is none), shutter denominator, colour temperature (not recorded: 0), one entry a frame (both lenses share it)."""
    pts = np.asarray(pts, float)
    try: ets, ex = read_exposure_records(path)
    except ValueError:                                                                                 # rebuilt recording: no exposure record
        d = dict(iso=np.full(len(pts), NO_EXPOSURE_ISO), shutter_den=np.full(len(pts), NO_EXPOSURE_SHUTTER_DEN, np.int64), ct=np.zeros(len(pts), np.int64))
        return {'djmd3': d, 'djmd4': {k_: v.copy() for k_, v in d.items()}}
    T = device_start(path) + (pts - pts[0])
    k = np.clip(np.searchsorted(ets, T), 0, len(ets) - 1); e = ex[k]
    iso = np.full(len(pts), 100.0)
    try:
        ts, v = read_aaa(path)
        if len(ts): iso = v[np.clip(np.searchsorted(ts, T, side='right') - 1, 0, len(ts) - 1)]              # the last entry at or before each frame
    except ValueError: pass
    d = dict(iso=iso, shutter_den=np.maximum(np.round(1.0 / np.maximum(e, 1e-6)), 1).astype(np.int64), ct=np.zeros(len(pts), np.int64))
    return {'djmd3': d, 'djmd4': {k_: v.copy() for k_, v in d.items()}}


def header(path):
    """Device, firmware, serial and calibration facts, in meta.header's shape (the colour mode is the camera's own 'vivid' profile, Rec.709 transfer: 'normal')."""
    x = extra(path); n = 0
    try: n = len(parse_calibration(x['calibration']))
    except Exception: pass
    return dict(device=x['model'], firmware=x['firmware'], serial=x['serial'], proto='insta360-trailer-v3', colour_mode='normal', colour_mode_raw=0, calibration_slots=n)
