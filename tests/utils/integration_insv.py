"""Build a tiny synthetic Insta360 X3 recording (an `.insv` pair with its metadata trailer) with ffmpeg, so integration tests need no real footage.

Layout matches what `strata360.osv.insta360` reads (docs/progress/2026-10-insta360.md):
- `VID_<date>_<time>_00_NNN.insv`: the REAR lens, H.264 full-range (`yuvj420p`) at 29.97 fps, stereo AAC, then the trailer;
- `VID_<date>_<time>_10_NNN.insv`: the FRONT lens, the same video one frame shorter (the real lens files differ by a frame), no audio, no trailer;
- optionally `LRV_<date>_<time>_11_NNN.lrv`, a 2:1 proxy (only its presence matters: it is paired, not read).

Trailer records (data, then u16 id and u32 length, read backwards; the last 40 bytes are u32 length, u32 version 3 and the 32-byte magic):
0x101 protobuf (serial, model, firmware, calibration string, IMU matrix), 0x300 IMU at 1 kHz, 0x400 exposure time a frame, 0x900 auto-exposure table (ISO).

The camera holds still and upright, then turns `TURN_DEG` about the vertical axis over the middle of the clip (gyro only: the accelerometer reads gravity throughout), so the fused orientation
has a known answer. The calibration is the X3 sample's Mei model with the focal length and centre scaled so the lens fits a `lens_px` video (`insta360.canvas_to_video` crops a small video out of
the middle of the 5952-px canvas, so the real numbers would leave a 128-px lens almost all edge).

    build_insv(folder, frames=45, name_time='20240720195607')  ->  path of the _00_ file
"""
import datetime as dt, os, struct, subprocess
import numpy as np

FPS = 30000 / 1001
MAGIC = b'8db42d694ccc418790edff439fe026bf'
CLOCK0 = 10.0                    # camera clock (s) at the first exposure record
IMU_LEAD_S = 0.5                 # IMU samples before the first exposure record and after the last
GRAVITY_LSB = 4096               # accelerometer reading of 1 g (any scale: the reader normalises by the clip's median)
ISO = 400
EXPOSURE_S = 0.004               # 1/250 s
TURN_DEG = 45.0                  # yaw turn over TURN_S, starting TURN_AT_S after the first video frame
TURN_S, TURN_AT_S = 0.5, 0.5
EARLY_EXPOSURE = 20              # exposure records start this many frames before the video
VIDEO_LATENCY_S = 0.2336         # insta360.VIDEO_LATENCY_S: the first frame is this long after the second exposure record

# The X3 sample's calibration (two Mei lenses on a 5952-px canvas, 19 numbers each, the second lens's cx offset by 5952), with fx, fy, cx, cy rewritten per lens size by `calibration`.
_LENS = [[1.948170, 4637.250, 4637.080, 2980.600, 2993.490, -0.171, -0.284, 90.064, 0.0, 0.0, 0.0, 0.42028457, 1.03285277, -3.47208929, 0.00084204, 0.00139114, 11904, 5952, 71],
         [1.948170, 4645.630, 4645.130, 8924.460, 2988.160, -0.107, -0.283, 91.229, 0.000288, -0.000136, -0.026685, 0.40457988, 1.20917737, -3.86310482, 0.00031331, 0.00040798, 11904, 5952, 71]]


def calibration(lens_px):
    """The calibration string for a lens video `lens_px` wide: the sample's lens shrunk by lens_px / 2880 about the middle of the canvas, so after `canvas_to_video` (halve, crop to the middle) it fills the frame as the
    real lens fills a 2880-px video."""
    k, mid = lens_px / 2880.0, 5952 / 2.0; out = ['2']
    for i, g in enumerate(_LENS):
        g = list(g); off = 5952.0 * i
        g[1] *= k; g[2] *= k; g[3] = mid + off + (g[3] - off - mid) * k; g[4] = mid + (g[4] - mid) * k
        out += [f'{v:.6f}' if isinstance(v, float) else str(v) for v in g]
    return '_'.join(out + ['199424'])


# ---- protobuf --------------------------------------------------------------------------------------------------------------------------------------------------------------
def _vi(n):
    out = bytearray()
    while True:
        b = n & 0x7f; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n: return bytes(out)

def _ld(f, b): return _vi(f << 3 | 2) + _vi(len(b)) + b
def _f32(f, x): return _vi(f << 3 | 5) + struct.pack('<f', x)


def extra_record(lens_px, model='Insta360 X3', serial='SYNX3001', firmware='v1.0.0'):
    imu = b''.join(_f32(60, v) for v in (1, 0, 0, 0, 1, 0, 0, 0, 1))
    return _ld(1, serial.encode()) + _ld(2, model.encode()) + _ld(3, firmware.encode()) + _ld(54, calibration(lens_px).encode()) + imu


# ---- the camera clock: exposure, auto-exposure and IMU records ---------------------------------------------------------------------------------------------------------
def first_frame_clock():
    """Camera clock (s) at the first video frame (what `insta360.device_start` should find)."""
    return CLOCK0 + 1 / FPS + VIDEO_LATENCY_S


def exposure_record(frames):
    n = frames + EARLY_EXPOSURE + 5
    return b''.join(struct.pack('<Qd', round((CLOCK0 + i / FPS) * 1e6), EXPOSURE_S) for i in range(n))


def aaa_record(frames):
    """48-byte entries every 4 frames after a header entry: u32 ms, f32 target EV, f32 exposure ms, u32 stats, u32 packed luma stats (ISO = 100 * (bits >> 19) >> 6), seven unused words."""
    bits = (ISO * 64 // 100) << 19
    rows = [struct.pack('<IffII7I', 0, 0.0, 0.0, 0, 0, *[0] * 7)]
    rows += [struct.pack('<IffII7I', round((CLOCK0 + i / FPS) * 1000), 0.0, EXPOSURE_S * 1000, 0, bits, *[0] * 7) for i in range(0, frames + EARLY_EXPOSURE + 5, 4)]
    return b''.join(rows)


def imu_record(frames):
    """1 kHz samples: u64 microseconds, then accelerometer x y z and gyroscope x y z as offset-binary u16. Upright: gravity along -x of the IMU; a yaw turn (about body z = -x of the IMU) of TURN_DEG."""
    t0, t1 = CLOCK0 - IMU_LEAD_S, CLOCK0 + (frames + EARLY_EXPOSURE + 5) / FPS + IMU_LEAD_S
    t = np.arange(round(t0 * 1000), round(t1 * 1000)) / 1000.0
    turn = (t >= first_frame_clock() + TURN_AT_S) & (t < first_frame_clock() + TURN_AT_S + TURN_S)
    gx = np.where(turn, -(TURN_DEG / TURN_S) / (2000.0 / 32768.0), 0.0)                                 # rate about body z = -(rate about IMU x)
    raw = np.zeros((len(t), 6)); raw[:, 0] = -GRAVITY_LSB; raw[:, 3] = gx
    rows = np.zeros(len(t), dtype=[('t', '<u8'), ('v', '<u2', 6)])
    rows['t'] = np.round(t * 1e6).astype(np.uint64); rows['v'] = np.round(raw + 32768).astype(np.uint16)
    return rows.tobytes()


def trailer(frames, lens_px, model='Insta360 X3'):
    """The trailer bytes: records (data, u16 id, u32 length) then 32 bytes of padding, u32 trailer length, u32 version and the magic."""
    body = b''
    for rid, d in ((0x101, extra_record(lens_px, model)), (0x300, imu_record(frames)), (0x400, exposure_record(frames)), (0x900, aaa_record(frames))):
        body += d + struct.pack('<HI', rid, len(d))
    return body + b'\0' * 32 + struct.pack('<II', len(body) + 72, 3) + MAGIC


# ---- the files -------------------------------------------------------------------------------------------------------------------------------------------------------------
def names(name_time='20240720195607', number=1):
    d, t = name_time[:8], name_time[8:]
    return f'VID_{d}_{t}_00_{number:03d}.insv', f'VID_{d}_{t}_10_{number:03d}.insv', f'LRV_{d}_{t}_11_{number:03d}.lrv'


def _encode(out, pattern, frames, size, creation, audio):
    src = ['-f', 'lavfi', '-i', f'{pattern}=size={size}:rate=30000/1001']
    if audio: src += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={frames / FPS + 0.1}:sample_rate=48000']
    maps = ['-map', '0:v'] + (['-map', '1:a', '-c:a', 'aac', '-ac', '2'] if audio else [])
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *src, *maps, '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuvj420p', '-color_range', 'pc',
                    '-shortest', '-metadata', f'creation_time={creation}', '-f', 'mp4', out], check=True)


def build_insv(folder, frames=45, name_time='20240720195607', number=1, lens_px=128, lrv=True, model='Insta360 X3'):
    """Write the pair (and an LRV proxy) into `folder`; returns the path of the primary (_00_, rear) file. The container's creation_time is 10 s before the file name, as on the camera."""
    os.makedirs(folder, exist_ok=True); rear, front, proxy = (os.path.join(folder, n) for n in names(name_time, number))
    creation = (dt.datetime.strptime(name_time, '%Y%m%d%H%M%S') - dt.timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _encode(rear, 'testsrc2', frames, f'{lens_px}x{lens_px}', creation, audio=True)
    _encode(front, 'smptebars', frames - 1, f'{lens_px}x{lens_px}', creation, audio=False)
    if lrv: _encode(proxy, 'testsrc', frames, '128x64', creation, audio=True)
    with open(rear, 'ab') as f: f.write(trailer(frames, lens_px, model))
    return rear
