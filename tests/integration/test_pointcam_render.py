"""Point cameras with real ffmpeg: a clip's shot is cut from its proxy (the picture is where the camera should look), a street view shot from the section's pictures, and the film's clip is made once for the plan's length."""
import datetime as dt, json, os, subprocess

import cv2
import numpy as np
import pytest

from overlay_fakes import T0
from projects import make_project
from strata360 import streetview as SV
from strata360.edit import pointcam as PC, pointcam_clip as PCL, streetview_cam as CAM, synthetic as SY

M = 1 / 111_195.0
W, H = 512, 256                                  # the proxy: an equirect picture (the centre column is straight ahead, 0 degrees)


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=width,height,nb_read_frames', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip().split(','); return int(r[0]), int(r[1]), int(r[2])


def frame_at(path, i):
    cap = cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_FRAMES, i); ok, img = cap.read(); cap.release(); assert ok; return img


def redness(img): return (img[..., 2].astype(int) - img[..., 1].astype(int) - img[..., 0].astype(int) // 2)


def bar_x(img):
    """The column of the red bar in a frame as a share of the width, or None when there is none."""
    r = redness(img) > 90
    return None if r.sum() < 6 else float(np.mean(np.nonzero(r)[1])) / img.shape[1]


@pytest.fixture(params=[0.0, 30.0], ids=['heading-0', 'heading-30'])
def clip_project(tmp_path, request):
    """A project with a 6 s clip of a run due north at 3 m/s, its proxy (grey noise with a red vertical bar 90 degrees to the right of the direction of travel) and a heading of 0 or 30 degrees (the camera's heading in the proxy's frame: the point is east of the run, so the bar is that far round again)."""
    p = make_project(tmp_path, config=True); rd = p.race_dir; n = 400; t = T0 + np.arange(n); d = 3.0 * np.arange(n); nan = np.full(n, np.nan)
    track = os.path.join(rd, 'track.gpx'); os.makedirs(rd, exist_ok=True); open(track, 'w').write('<gpx/>'); np.savez_compressed(track + '.npz', t=t, lat=50.0 + d * M, lon=np.full(n, 5.0), alt=np.full(n, 100.0), speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)
    start = T0 + 20.0; iso = dt.datetime.fromtimestamp(start, dt.timezone.utc).isoformat(); p.add_clip('c1', start_utc=iso, source_frames=180, fps=30.0)
    p.write_json('clips/c1/motion.json', dict(series=dict(t=[0.0, 6.0], heading_deg=[request.param, request.param]))); cj = p.read_json('clips/c1/clip.json'); cj['source_files'] = dict(osv='x.osv'); p.write_json('clips/c1/clip.json', cj)
    rng = np.random.default_rng(3); base = cv2.GaussianBlur((rng.random((H, W)) * 120 + 60).astype(np.uint8), (0, 0), 2); img = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR); x = int(W * (0.5 + (90 + request.param) / 360)); img[:, x - 4:x + 4] = (0, 0, 255)
    out = p.path('clips', 'c1', 'proxy.mp4'); enc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', '25', '-i', '-', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
    for _ in range(150): enc.stdin.write(img.tobytes())
    enc.stdin.close(); enc.wait(); p.write_json('clips/c1/proxy.json', dict(size=[W, H], frames=[dict(proxy_frame=i, source_frame=i, t_s=i / 25.0) for i in range(150)])); return p


def make_cam(p, **kw):
    lat, lon = 50.0 + 69.0 * M, 5.0 + 10.0 * M / np.cos(np.radians(50.0))                       # 10 m to the right of the path, 69 m along (the clip covers 60 to 78 m: this is halfway)
    return PC.create(p.race_dir, dict(kind='clip', clip='c1'), lat, lon, T0 + 23.0, **kw)


def test_the_preview_of_a_clip_looks_at_the_point_as_the_runner_passes_it(clip_project, monkeypatch):
    p = clip_project; cam = make_cam(p, before_m=40, after_m=40, smooth_s=0.0); out = str(p.path('pointcams', 'C1.mp4')); logs = []; r = PCL.render_preview(p.folder, cam, out, log=logs.append)
    w, h, n = probe(out); assert (w, h) == (960, 540) and r['fps'] == 25.0 and abs(n - 150) <= 2 and not os.path.exists(out + '.part.mp4') and any('rendering' in l for l in logs) and 'aimed at the point' in logs[-1]
    ahead = bar_x(frame_at(out, 3)); mid = bar_x(frame_at(out, n // 2))
    assert mid is not None and abs(mid - 0.5) < 0.12                                           # at the closest approach the point is 90 degrees to the right: the camera looks there and the bar is in the middle
    assert ahead is None or abs(ahead - 0.5) > 0.2                                              # early on, the point is nearly ahead: the bar (at 90 degrees) is off to one side or out of the view


def test_the_clip_for_the_film_is_made_once_for_the_plans_length(clip_project, monkeypatch):
    p = clip_project; cam = make_cam(p, before_m=40, after_m=40, use='must'); monkeypatch.setattr(PCL, 'CLIP_SIZE', (320, 180)); logs = []
    (c,) = PCL.sync(p.folder, [dict(clip='C1', seconds=3.0)], logs.append); path = p.path('synthetic', 'C1.mp4'); w, h, n = probe(path)
    assert (w, h) == (320, 180) and abs(n - 75) <= 2 and c['kind'] == 'pointcam' and c['status'] == 'ready' and c['seconds'] == 3.0 and c['file'] == os.path.join('synthetic', 'C1.mp4') and SY.load(p.folder)['clips'][0]['id'] == 'C1'
    assert abs((dt.datetime.fromisoformat(c['t1'].replace('Z', '+00:00')) - dt.datetime.fromisoformat(c['t0'].replace('Z', '+00:00'))).total_seconds() - 3.0) < 0.6          # a 3 s shot is the 3 s round the closest approach
    mid = bar_x(frame_at(path, n // 2)); assert mid is not None and abs(mid - 0.5) < 0.12
    before = os.path.getmtime(path); PCL.sync(p.folder, [dict(clip='C1', seconds=3.0)]); assert os.path.getmtime(path) == before


def test_a_clip_without_a_proxy_is_explained(clip_project):
    p = clip_project; cam = make_cam(p); os.remove(p.path('clips', 'c1', 'proxy.mp4'))
    with pytest.raises(RuntimeError, match='has no proxy yet'): PCL.render_preview(p.folder, cam, str(p.path('pointcams', 'x.mp4')))


def test_the_job_renders_the_preview_and_a_second_call_finishes_at_once(clip_project, cli):
    p = clip_project; cam = make_cam(p); out = PCL.preview_path(p.folder, cam); r = cli('pointcam-video', p.folder, 'C1'); assert f'done: {out}' in r.out and os.path.exists(out) and 'rendering' in r.out
    t = os.path.getmtime(out); cli('pointcam-video', p.folder, 'C1'); assert os.path.getmtime(out) == t
    assert cli('pointcam-video', p.folder, 'C9', check=False).code != 0


def streetview_section(tmp_path, n=12):
    """A 360 Mapillary section of n textured pictures along a meridian 6 m apart, saved where the camera looks for them."""
    rd = str(tmp_path); items = []; meta = {}; sec = dict(id='M1', provider='mapillary', stretch='R1', kind='360', km0=1.0, km1=1.0 + 6 * (n - 1) / 1000.0, length_m=6 * (n - 1), frames=n, spacing_m=6.0, years=[2024], camera='x', size=[720, 360], seq='s1', angles=None, items=items)
    os.makedirs(CAM.src_dir(rd, sec), exist_ok=True); rng = np.random.default_rng(1); base = cv2.cvtColor(cv2.GaussianBlur((rng.random((360, 720)) * 255).astype(np.uint8), (0, 0), 3), cv2.COLOR_GRAY2BGR)
    for i in range(n):
        it = dict(id=f'x{i}', km=1.0 + 6 * i / 1000.0, lat=50.0 + 6 * i / 111320.0, lon=5.0, a=None, b=0, c=0.0); items.append(it); cv2.imwrite(CAM.src_path(rd, sec, it['id']), np.roll(base, 3 * i, axis=1))
        meta[it['id']] = dict(computed_rotation=cv2.Rodrigues(np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float))[0].ravel().tolist(), computed_geometry=dict(coordinates=[5.0, 50.0 + 6 * i / 111320.0]), compass_angle=0.0)
    json.dump(meta, open(CAM.meta_path(rd, sec), 'w')); return rd, sec


def test_a_street_view_shot_is_rendered_to_the_wanted_length_and_size(tmp_path):
    rd, sec = streetview_section(tmp_path); out = str(tmp_path / 'o.mp4'); N = 30; idx = np.linspace(0, 10.5, N); yaw = np.linspace(20, 160, N); r = CAM.render_point(rd, sec, idx, yaw, np.full(N, -2.0), np.full(N, 70.0), out, size=(160, 90), encode_size=(320, 180))
    w, h, n = probe(out); assert (w, h) == (320, 180) and n == N and r == dict(frames=N, fps=30) and not os.path.exists(out + '.part.mp4')
    assert not np.array_equal(frame_at(out, 0), frame_at(out, N - 1))                                                                      # (it looks somewhere else at the end)
