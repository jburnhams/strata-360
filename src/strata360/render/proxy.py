"""Canonical analysis proxy: ONE file per clip for every visual analysis step.

Upright (horizon-locked, world-locked) equirectangular, rendered from the full-resolution lens streams with the same
calibration, stabilisation, lens weights and linear-light blending as the final renderer (spike/render4k.py).

  * upright: detectors and vision models see people the right way up; heading is the camera-independent world datum
  * equirect 3840 x 1920 (about 10.7 px/deg; the source has about 21 px/deg): enough for people at range; faces are
    re-cropped from the full-resolution lens frames when needed
  * 12.5 fps by default (every 4th source frame; --every 2 gives 25 fps). Exact source timestamps are kept in the sidecar.
  * HEVC 8-bit (hvc1), BT.709 tagged. Default: VideoToolbox at 80 Mbit/s requested (about 100 Mbit/s delivered at 25 fps); --encoder x265
    --crf 24 is about 1.4x more efficient per bit but roughly 10x slower. The proxy is for detection, tracking and coarse vision only:
    anything that needs fine detail (faces, bibs, kit) must be re-cropped from the full-resolution lens streams, not from this file.
  * sidecar <name>.json: per proxy frame the source frame index and clip-relative time, plus the stabilisation used, so
    any analysis result can be mapped back to source time, UTC (clip.json start_utc + t_s) and to the camera-body frame

Lower-resolution copies for cheap tasks (exposure statistics, motion, shot detection) are derived on the fly from this file
with ffmpeg's scale filter; there is no second proxy.

Usage: python make_proxy.py CAM.OSV proxy.mp4 [--size 3840x1920] [--every 2] [--frames N]
"""
import argparse, json, os, subprocess, sys, time
import numpy as np, cv2
from strata360.render import flat as r4
from strata360.osv.telemetry import read_frames, video_pts


class EquirectRenderer(r4.Renderer):
    """Same calibration, weights and blending as the flat renderer, but the output is the upright equirect sphere."""
    def __init__(self, osv, W=3840, H=1920, interp='linear', grid=8):
        super().__init__(osv, W, H, 90.0, interp, grid)
        xs = np.linspace(0, W, self.gw); ys = np.linspace(0, H, self.gh); X, Y = np.meshgrid(xs, ys)
        lon = (X / W - 0.5) * 2 * np.pi; lat = (0.5 - Y / H) * np.pi                       # Standard layout, centre column = +Y
        self.dE = np.stack([np.sin(lon) * np.cos(lat), np.cos(lon) * np.cos(lat), np.sin(lat)], -1).reshape(-1, 3)

    def maps(self, M, _unused, roll=0.0):
        d = np.einsum('nj,ij->ni', self.dE, M)                                          # d_body = M d_E
        out = []
        for L in (self.master, self.slave):
            uu, vv, th = L.project(d)
            out.append((uu.reshape(self.gh, self.gw), vv.reshape(self.gh, self.gw), np.degrees(th).reshape(self.gh, self.gw)))
        return out


def decoder(osv, stream, every):
    cmd = ['ffmpeg', '-v', 'error', '-hwaccel', 'videotoolbox', '-i', osv, '-map', f'0:v:{stream}', '-fps_mode', 'passthrough',
           '-vf', f"select='not(mod(n\\,{every}))'", '-pix_fmt', 'rgb48le', '-f', 'rawvideo', '-']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=r4.LS * r4.LS * r4.BYTES * 2)


def make_proxy(osv, out, size='3840x1920', every=4, bitrate='80M', encoder='vt', crf=24, frames_limit=0, progress=None):
    """encoder 'h264' (the pipeline default): H.264 from VideoToolbox with the clip's audio, one file for analysis AND the browser player; 'vt' HEVC / 'x265' for archival proxies."""
    """Render the canonical analysis proxy and its JSON sidecar (next to `out`, .json). Returns the sidecar dict."""
    W, H = map(int, size.split('x')); t0 = time.time()
    R = EquirectRenderer(osv, W, H)
    tel = read_frames(osv); pts = video_pts(osv, 0); n_src = len(pts)
    idx = list(range(0, n_src, every))
    if frames_limit: idx = idx[:frames_limit]
    nominal_fps = 50.0 / every
    dm, ds = decoder(osv, 1, every), decoder(osv, 0, every)
    venc = (['-c:v', 'h264_videotoolbox', '-profile:v', 'high', '-b:v', bitrate] if encoder == 'h264' else ['-c:v', 'hevc_videotoolbox', '-profile:v', 'main', '-b:v', bitrate] if encoder == 'vt' else ['-c:v', 'libx265', '-preset', 'medium', '-x265-params', f'crf={crf}:log-level=error'])
    final = out; out = out + '.video.mp4' if encoder == 'h264' else out
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', f'{W}x{H}', '-r', str(nominal_fps), '-i', '-',
                            '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p'] + venc +
                           (['-movflags', '+faststart'] if encoder == 'h264' else ['-tag:v', 'hvc1', '-bsf:v', 'hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0']) +
                           ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', out], stdin=subprocess.PIPE)
    frames = []
    for j, k in enumerate(idx):
        cm = r4.read_frame(dm); cs = r4.read_frame(ds)
        if cm is None or cs is None: break
        img = R.render(cm, cs, R.stab_matrix(tel['quat'][k]), None)
        enc.stdin.write(np.ascontiguousarray(img).tobytes())
        frames.append(dict(proxy_frame=j, source_frame=int(k), t_s=round(float(pts[k] - pts[0]), 4)))
        if progress and j % 25 == 0: progress(j, len(idx))
    enc.stdin.close(); enc.wait(); dm.kill(); ds.kill()
    if encoder == 'h264':                                                                            # add the clip's audio (AAC) and finish: one file for the detectors and the player
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', out, '-i', osv, '-map', '0:v', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k', '-shortest', '-movflags', '+faststart', final], check=True)
        os.remove(out); out = final
    side = dict(schema_version=1, tool='strata360.make_proxy', source_file=os.path.basename(osv), proxy_file=os.path.basename(out),
                projection='equirectangular', layout='standard: centre column = world +Y (DJI upright yaw datum), lon increases right, lat up',
                frame='upright / world-locked: rotation applied per frame = B^T R(q)^T P^T (see progress.md); quaternion = telemetry row of source_frame',
                size=[W, H], nominal_fps=nominal_fps, every_n_source_frames=every, codec=('h264_videotoolbox %s + aac' % bitrate) if encoder == 'h264' else ('hevc_videotoolbox %s' % bitrate) if encoder == 'vt' else ('x265 crf %d' % crf),
                profile='main 8-bit hvc1, bt709 tv', seconds=round(time.time() - t0, 1),
                time_note='t_s is clip-relative seconds from the source frame pts (authoritative; the mp4 timestamps are nominal and drift by up to '
                          '0.06 s around dropped source frames). UTC = clip.json start_utc + t_s.', frames=frames)
    with open(os.path.splitext(out)[0] + '.json', 'w') as fh: json.dump(side, fh)
    return side


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('osv'); ap.add_argument('out')
    ap.add_argument('--size', default='3840x1920'); ap.add_argument('--every', type=int, default=4)
    ap.add_argument('--encoder', choices=['vt', 'x265'], default='vt'); ap.add_argument('--crf', type=int, default=24)
    ap.add_argument('--frames', type=int, default=0); ap.add_argument('--bitrate', default='80M')
    a = ap.parse_args()
    side = make_proxy(a.osv, a.out, a.size, a.every, a.bitrate, a.encoder, a.crf, a.frames, lambda j, n: print(f'  proxy frame {j}/{n}', flush=True))
    print(f"done: {len(side['frames'])} proxy frames in {side['seconds']} s; {os.path.getsize(a.out) / 1e6:.1f} MB")


if __name__ == '__main__':
    main()


def make_preview(osv, out, size='2048x1024', bitrate='6M', progress=None, frames_limit=0):
    """Browser preview for the GUI player: the same upright, world-locked equirect as the proxy but at 25 fps (every 2nd source frame), H.264 8-bit (plays in every browser, seeks well)
    with the clip's audio (AAC). The GUI viewer projects it on a sphere (drag to pan, wheel to zoom) and can follow the runner's heading. Sidecar `<name>.json` has the per-frame source times."""
    W, H = map(int, size.split('x')); t0 = time.time(); every = 2
    R = EquirectRenderer(osv, W, H); tel = read_frames(osv); pts = video_pts(osv, 0); idx = list(range(0, len(pts), every))
    if frames_limit: idx = idx[:frames_limit]
    dm, ds = decoder(osv, 1, every), decoder(osv, 0, every); tmp = out + '.video.mp4'
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', f'{W}x{H}', '-r', '25', '-i', '-',
                            '-vf', 'scale=in_range=full:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p', '-c:v', 'h264_videotoolbox', '-b:v', bitrate,
                            '-profile:v', 'high', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    frames = []
    for j, k in enumerate(idx):
        cm = r4.read_frame(dm); cs = r4.read_frame(ds)
        if cm is None or cs is None: break
        enc.stdin.write(np.ascontiguousarray(R.render(cm, cs, R.stab_matrix(tel['quat'][k]), None)).tobytes()); frames.append(round(float(pts[k] - pts[0]), 3))
        if progress and j % 50 == 0: progress(j, len(idx))
    enc.stdin.close(); enc.wait(); dm.kill(); ds.kill()
    dur = len(frames) / 25.0
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-ss', '0', '-t', f'{dur:.3f}', '-i', osv, '-map', '0:v', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k', '-shortest', '-movflags', '+faststart', out], check=True)
    os.remove(tmp)
    side = dict(schema_version=1, projection='equirectangular', layout='centre column = world +Y (heading datum), lon increases right', size=[W, H], fps=25, frame_times_s=frames, seconds=round(time.time() - t0, 1),
                note='upright and world-locked; the viewer adds the runner heading (motion.json) to follow their direction; frame_times_s are source clip times (the mp4 is nominal 25 fps)')
    json.dump(side, open(os.path.splitext(out)[0] + '.json', 'w')); return side


def make_preview_from_proxy(proxy_path, osv, out, size='2048x1024', bitrate='6M'):
    """The browser preview derived from the clip's proxy: rescale to 2048x1024, H.264 (plays in every browser), the clip's audio as AAC. Takes seconds, not a second render."""
    t0 = time.time(); side = json.load(open(os.path.splitext(proxy_path)[0] + '.json')); W, H = size.split('x')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', proxy_path, '-i', osv, '-map', '0:v', '-map', '1:a:0?', '-vf', f'scale={W}:{H}:flags=area,format=yuv420p', '-c:v', 'h264_videotoolbox', '-b:v', bitrate,
                    '-profile:v', 'high', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', '-c:a', 'aac', '-b:a', '96k', '-shortest', '-movflags', '+faststart', out], check=True)
    fps = 50.0 / side['every_n_source_frames']
    info = dict(schema_version=1, projection='equirectangular', layout='centre column = world +Y (heading datum), lon increases right', size=[int(W), int(H)], fps=fps, from_proxy=os.path.basename(proxy_path),
                frame_times_s=[f['t_s'] for f in side['frames']], seconds=round(time.time() - t0, 1), note='upright and world-locked; the viewer adds the runner heading (motion.json) to follow their direction')
    json.dump(info, open(os.path.splitext(out)[0] + '.json', 'w')); return info
