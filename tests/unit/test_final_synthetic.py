"""Generated windows in the final render (render/final.py `FinalSource`): rendered from their original sources at the film's rate and size, a point camera on a clip cut from the footage, a still never starting a whole render."""
import os

import numpy as np

from strata360.edit import pointcam as PCM, pointcam_clip as PK, synth_render as SR, synthetic as SY
from strata360.render import final as FN, progress as PG


def source(segs, fps=50.0, W=3840, H=2160, **kw): return FN.FinalSource('/f', segs, {}, W, H, fps, progress=PG.Null(), **kw)


def seg(**kw): return dict(id='w1', clip='G01', synthetic='/f/synthetic/G01.mp4', clip_start_s=0.0, **kw)


def test_a_generated_window_uses_the_clip_made_at_the_films_rate_and_size(monkeypatch):
    got = []
    monkeypatch.setattr(SY, 'load', lambda f: dict(clips=[dict(id='G01', kind='map', key='k')]))
    monkeypatch.setattr(SR, 'for_film', lambda folder, doc, fps, size, log=print: got.append((fps, size)) or '/film/G01.mp4')
    s = source([seg()]); assert s.synthetic_path(seg()) == '/film/G01.mp4' and s.synthetic_path(seg()) == '/film/G01.mp4' and got == [(50.0, (3840, 2160))]


def test_the_planners_clip_is_the_fallback_when_it_cannot_be_made(monkeypatch):
    monkeypatch.setattr(SY, 'load', lambda f: dict(clips=[dict(id='G01', kind='map', key='k')]))
    def boom(*a, **k): raise RuntimeError('no tiles')
    monkeypatch.setattr(SR, 'for_film', boom)
    assert source([seg()]).synthetic_path(seg()) == '/f/synthetic/G01.mp4'
    s = source([seg()]); s.film_synthetic = False; assert s.synthetic_path(seg()) == '/f/synthetic/G01.mp4'


def test_a_still_never_starts_a_whole_render(monkeypatch, tmp_path):
    monkeypatch.setattr(SY, 'load', lambda f: dict(clips=[dict(id='G01', kind='map', key='k')]))
    monkeypatch.setattr(SR, 'for_film', lambda *a, **k: (_ for _ in ()).throw(AssertionError('rendered')))
    s = source([seg()]); s.last_only = True
    assert s.synthetic_path(seg()) == '/f/synthetic/G01.mp4'
    made = tmp_path / 'G01.mp4'; made.write_bytes(b'x'); monkeypatch.setattr(SR, 'film_path', lambda *a: str(made))
    s = source([seg()]); s.last_only = True; assert s.synthetic_path(seg()) == str(made)                 # (the film's clip once it exists)


def test_a_point_camera_on_a_clip_becomes_a_footage_window_with_its_path(monkeypatch):
    cam = dict(id='C1', source=dict(kind='clip', clip='0021'))
    monkeypatch.setattr(PCM, 'load', lambda rd: dict(cams=[cam]))
    monkeypatch.setattr(SY, 'load', lambda f: dict(clips=[dict(id='C1', kind='pointcam', seconds=6.0)]))
    sm = dict(t=np.array([1000.0, 1006.0]))
    monkeypatch.setattr(PK, 'plan', lambda folder, c, seconds=None: dict(t0=1000.0, t1=1006.0, samples=sm, north_offset=3.0, extra=(990.0, 60.0, 'x.osv')))
    monkeypatch.setattr(PK, 'clip_path', lambda sm, t0, off: dict(ref='world', keyframes=[dict(t=0.0, yaw=0.0), dict(t=6.0, yaw=10.0)]))
    s = source([dict(id='w1', clip='C1', synthetic='x.mp4', clip_start_s=2.0)]); out = s.pointcam_footage(s.segs[0])
    assert out['clip'] == '0021' and out['synthetic'] is None and out['clip_start_s'] == 12.0 and out['utc_start'].endswith('Z')       # 10 s into the clip + 2 s into the shot
    assert [k['t'] for k in s.framing['w1']['keyframes']] == [-2.0, 4.0]


def test_a_point_camera_on_street_view_is_not_footage(monkeypatch):
    monkeypatch.setattr(PCM, 'load', lambda rd: dict(cams=[dict(id='C2', source=dict(kind='streetview', key='k'))]))
    s = source([dict(id='w1', clip='C2', synthetic='x.mp4', clip_start_s=0.0)]); assert s.pointcam_footage(s.segs[0]) is None


def test_the_film_engine_hands_the_encoder_8_bit_bgr():
    from strata360.render import preview as PV
    rgb = np.zeros((2, 2, 3), np.uint16); rgb[..., 0] = 65535; rgb[..., 2] = 257 * 10
    out = PV.to_bgr8(rgb); assert out.dtype == np.uint8 and out[0, 0].tolist() == [10, 0, 255] and out.flags['C_CONTIGUOUS']
    assert PV.to_bgr8(np.full((1, 1, 3), 7, np.uint8))[0, 0].tolist() == [7, 7, 7]
