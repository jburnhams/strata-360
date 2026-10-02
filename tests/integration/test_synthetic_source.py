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
