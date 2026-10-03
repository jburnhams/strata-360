"""render/synthetic.py: frames of a generated clip for the film: picked at the film's rate, scaled, the first frame held before the start and the last after the end; the preview and final sources use it."""
import subprocess
import numpy as np
import pytest
from strata360.render import synthetic as SYN


@pytest.fixture(scope='module')
def video(tmp_path_factory):
    """2 s at 10 fps whose frame i is the grey level 20 * i (+ 10)."""
    p = str(tmp_path_factory.mktemp('syn') / 'v.mp4'); n = 20; W, H = 64, 36
    raw = b''.join(np.full((H, W, 3), 10 + 11 * i, np.uint8).tobytes() for i in range(n))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', '10', '-i', '-', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', p], input=raw, check=True); return p


def grey(img): return float(img.mean())


def test_frames_are_picked_at_the_film_rate_and_scaled(video):
    out = list(SYN.frames(video, 0.0, 0, 20, 10.0, 32, 18)); assert len(out) == 20 and out[0].shape == (18, 32, 3) and out[0].dtype == np.uint8
    g = [grey(f) for f in out]; assert all(b > a for a, b in zip(g, g[1:])) and g[0] < 30 and g[19] > 190


def test_a_window_starts_where_it_is_asked_to(video):
    out = list(SYN.frames(video, 1.0, 0, 5, 10.0, 32, 18)); assert abs(grey(out[0]) - (10 + 11 * 10)) < 10


def test_the_first_frame_is_held_before_the_video_and_the_last_after_it(video):
    out = list(SYN.frames(video, -0.5, 0, 8, 10.0, 32, 18)); assert all(abs(grey(f) - grey(out[0])) < 1 for f in out[:5]) and grey(out[7]) > grey(out[0])
    end = list(SYN.frames(video, 1.5, 0, 12, 10.0, 32, 18)); assert abs(grey(end[-1]) - grey(end[-4])) < 1 and len(end) == 12


def test_handles_before_the_window_come_from_the_video(video):
    out = list(SYN.frames(video, 1.0, -3, 2, 10.0, 32, 18)); assert len(out) == 5 and grey(out[0]) < grey(out[4])


def test_final_pictures_are_16_bit_and_preview_ones_bgr(video):
    f = next(SYN.frames(video, 0.0, 0, 1, 10.0, 32, 18, 'rgb', np.uint16)); assert f.dtype == np.uint16 and f.max() > 255 * 8
    img = np.zeros((36, 64, 3), np.uint8); img[..., 0] = 255                                                   # pure red, in rgb order
    import subprocess as sp
    p = video.replace('v.mp4', 'red.mp4'); sp.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '64x36', '-r', '10', '-i', '-', '-c:v', 'libx264', '-crf', '8', '-pix_fmt', 'yuv444p', p], input=img.tobytes() * 5, check=True)
    rgb = next(SYN.frames(p, 0.0, 0, 1, 10.0, 64, 36, 'rgb')); bgr = next(SYN.frames(p, 0.0, 0, 1, 10.0, 64, 36, 'bgr'))
    assert rgb[18, 32, 0] > 200 > rgb[18, 32, 2] and bgr[18, 32, 2] > 200 > bgr[18, 32, 0]


def test_a_clip_not_rendered_yet_shows_a_card_so_the_film_still_plays(tmp_path):
    out = list(SYN.frames(str(tmp_path / 'G01.mp4'), 0.0, 0, 5, 10.0, 64, 36)); assert len(out) == 5 and out[0].shape == (36, 64, 3) and out[0].dtype == np.uint8 and out[0].max() > 100                      # grey with a line of text
    w = next(SYN.frames(str(tmp_path / 'G01.mp4'), 0.0, 0, 1, 10.0, 64, 36, 'rgb', np.uint16)); assert w.dtype == np.uint16 and w.max() > 255 * 100


def test_a_synthetic_clip_keeps_its_approval_when_planned_again_with_the_same_key(tmp_path, monkeypatch):
    from strata360.edit import synthetic as SY
    gap = dict(id='G01', t0=1_771_754_000.0, t1=1_771_754_000.0 + 3600); monkeypatch.setattr(SY, 'load', lambda f: doc); monkeypatch.setattr(SY, 'save', lambda f, d: d.update(saved=True)); doc = dict(clips=[dict(SY.make(gap, seconds=8, kind='flyover', approved=False), approved=True, status='ready')])
    again = SY.upsert('x', SY.make(gap, seconds=8, kind='flyover', approved=False)); assert again['approved'] is True and again['status'] == 'ready'


def test_the_race_time_of_a_frame_follows_the_clip_and_holds_at_its_end():
    sg = dict(utc_start='2026-02-22T10:00:00Z', utc_end='2026-02-22T12:00:00Z', synthetic_seconds=10.0, clip_start_s=0.0, dur_s=12.0); t0 = 1_771_754_400.0
    assert SYN.race_time(sg, 0, 10.0) == t0 and SYN.race_time(sg, 50, 10.0) == pytest.approx(t0 + 3600) and SYN.race_time(sg, 100, 10.0) == pytest.approx(t0 + 7200) and SYN.race_time(sg, 115, 10.0) == pytest.approx(t0 + 7200)   # a longer window holds the last moment
    assert SYN.race_time(dict(sg, clip_start_s=2.0), 0, 10.0) == pytest.approx(t0 + 1440) and SYN.race_time(dict(sg, synthetic_seconds=None, dur_s=20.0), 100, 10.0) == pytest.approx(t0 + 3600)


def test_the_film_puts_its_own_overlay_on_a_generated_clip_at_the_race_time_each_frame_shows(video):
    from strata360.render import final as FI
    seen = []
    class Overlay:
        def apply(self, img, t): seen.append(t); img[0, 0] = 65535; return img
    sg = dict(clip='G01', synthetic=video, utc_start='2026-02-22T10:00:00Z', utc_end='2026-02-22T12:00:00Z', synthetic_seconds=2.0, clip_start_s=0.0, dur_s=2.0, id='G01@0.00')
    src = FI.FinalSource('x', [sg], {}, 32, 18, 10.0, overlay=Overlay()); out = list(src.frames(0, 0, 20)); t0 = 1_771_754_400.0
    assert len(out) == 20 and out[0].dtype == np.uint16 and all(f[0, 0, 0] == 65535 for f in out) and seen[0] == t0 and seen[-1] == pytest.approx(t0 + 7200 * 19 / 20) and seen == sorted(seen)
    assert list(FI.FinalSource('x', [sg], {}, 32, 18, 10.0, overlay=None).frames(0, 0, 3))[0][0, 0, 0] != 65535                                                                       # without an overlay: the picture as it is
