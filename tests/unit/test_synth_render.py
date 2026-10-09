import os

import pytest

from strata360.edit import synth_render as SR
from strata360.pipeline import config


@pytest.fixture
def rd(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'race_dir', lambda f: str(tmp_path))
    return tmp_path


def doc(kind='map', **kw): return dict(id='G01', kind=kind, key='abc123', fps=30.0, seconds=4.0, t0='2026-02-19T10:00:00Z', t1='2026-02-19T11:00:00Z', **kw)


def test_the_film_copy_is_named_by_clip_key_rate_and_size(rd):
    p = SR.film_path('f', doc(), 50.0, (3840, 2160))
    assert p == os.path.join(str(rd), 'synthetic', 'film', 'G01-abc123-50fps-3840x2160.mp4')
    assert SR.film_path('f', doc(), 29.97, (1920, 1080)) != SR.film_path('f', doc(), 30.0, (1920, 1080))


def test_the_clip_is_rendered_once_at_the_films_rate_and_size(rd, monkeypatch):
    calls = []
    def render(folder, d, out, fps=None, size=None, log=print, crf=14):
        calls.append((d['id'], fps, size)); open(out, 'wb').write(b'x'); return True
    monkeypatch.setattr(SR, 'render', render)
    a = SR.for_film('f', doc(), 50.0, (3840, 2160)); b = SR.for_film('f', doc(), 50.0, (3840, 2160))
    assert a == b and os.path.exists(a) and calls == [('G01', 50.0, (3840, 2160))]
    SR.for_film('f', doc(), 25.0, (3840, 2160)); assert len(calls) == 2                       # another rate is another render
    assert not [n for n in os.listdir(os.path.dirname(a)) if n.endswith('.part.mp4')]


def test_a_kind_cut_from_footage_is_not_rendered_here(rd, monkeypatch):
    monkeypatch.setattr(SR, 'render', lambda *a, **k: False)
    assert SR.for_film('f', doc('pointcam'), 50.0, (1920, 1080)) is None and not os.path.exists(os.path.dirname(SR.film_path('f', doc(), 50.0, (1920, 1080))) + '/G01-abc123-50fps-1920x1080.mp4')


def test_an_unknown_kind_is_refused(rd):
    with pytest.raises(ValueError):
        SR.render('f', doc('hologram'), str(rd / 'x.mp4'))


def test_the_map_clip_is_built_at_the_films_rate_and_size(rd, monkeypatch):
    seen = {}
    import strata360.overlay.mapclip as MC
    class Fake:
        def __init__(self, series, t0, t1, seconds, fps, size, **k): seen.update(fps=fps, size=size, seconds=seconds); self.W, self.H = size
    monkeypatch.setattr(MC, 'MapClip', Fake)
    import strata360.gps.track as TR, strata360.overlay.series as SE, strata360.overlay.tiles as TI
    monkeypatch.setattr(config, 'load', lambda f: {}); monkeypatch.setattr(config, 'track_path', lambda f, c: 'x.fit'); monkeypatch.setattr(TR, 'load', lambda p: {}); monkeypatch.setattr(SE, 'Series', lambda t: t); monkeypatch.setattr(TI, 'Tiles', lambda s: s)
    mc = SR.gap_clip('f', doc(), 50.0, (3840, 2160))
    assert seen == dict(fps=50.0, size=(3840, 2160), seconds=4.0) and (mc.W, mc.H) == (3840, 2160)
