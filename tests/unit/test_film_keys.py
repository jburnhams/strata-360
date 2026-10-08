"""The film's folder is named by the plan as saved, not by the plan after the glides were added: the server looks the film up by the saved plan."""
import pytest
from strata360.edit import pans as PN
from strata360.render import final as FN, preview as PV


class Stop(Exception): pass


def plan():
    return dict(segments=[dict(id='a', clip='c', clip_start_s=0.0, dur_s=2.0, film_start_s=0.0, transition=dict(type='cut')), dict(id='b', clip='c', clip_start_s=2.0, dur_s=2.0, film_start_s=2.0, transition=dict(type='cut', why='the same clip: x'))])


def test_the_preview_is_stored_under_the_saved_plans_key(tmp_path, monkeypatch):
    p = plan(); monkeypatch.setattr(PN, 'apply_pans', lambda segs, framing, enabled=None, scorer=None: ([dict(g, transition=dict(type='pan', dur_s=0.5)) for g in segs], [])); monkeypatch.setattr(PN, 'looker', lambda f: None)
    monkeypatch.setattr(PV, 'film_dir', lambda f, k: str(tmp_path / k)); monkeypatch.setattr(PV, 'build_audio', lambda *a, **k: (_ for _ in ()).throw(Stop())); monkeypatch.setattr(PV, 'proxy_of', lambda f, c: 'p.mp4')
    key = PV.plan_key('f', p)
    with pytest.raises(Stop): PV.render('f', p, {})
    assert (tmp_path / key).is_dir() and [x.name for x in tmp_path.iterdir()] == [key]


def test_the_final_film_is_stored_under_the_saved_plans_key(tmp_path, monkeypatch):
    p = plan(); monkeypatch.setattr(PN, 'apply_pans', lambda segs, framing, enabled=None, scorer=None: ([dict(g, transition=dict(type='pan', dur_s=0.5)) for g in segs], [])); monkeypatch.setattr(PN, 'looker', lambda f: None)
    monkeypatch.setattr(FN, 'final_dir', lambda f, k: str(tmp_path / k)); monkeypatch.setattr(FN, 'pieces', lambda *a, **k: (_ for _ in ()).throw(Stop())); monkeypatch.setattr(FN, 'final_key', lambda plan, size, fps, br, folder, upscale=False: 'saved' if 'why' in plan['segments'][1]['transition'] else 'pan')
    with pytest.raises(Stop): FN._render_final('f', p, {})
    assert [x.name for x in tmp_path.iterdir()] == ['saved']                                  # the key of the saved plan (its transition still has its reason), not of the one with the pan


def test_the_preview_draws_the_overlay_on_every_frame_at_the_race_time_it_shows(monkeypatch):
    import numpy as np
    seen = []
    class Ov:
        def apply(self, img, t): seen.append((round(t, 3), tuple(img[0, 0]))); out = img.copy(); out[0, 0] = (1, 2, 3); return out
    segs = [dict(id='a', clip='c', utc_start='2026-02-19T10:00:00Z', dur_s=1.0)]; src = PV.PreviewSource('f', segs, {}, 4, 4, 4, overlay=Ov())
    monkeypatch.setattr(src, '_frames', lambda k, a0, a1, y=None, p=None: (np.full((4, 4, 3), (10, 20, 30), np.uint8) for _ in range(a1 - a0)))
    out = list(src.frames(0, 25, 27)); t0 = 1771495200.0                                                      # 2026-02-19 10:00 UTC
    assert [t for t, _ in seen] == [round(t0 + 1.0, 3), round(t0 + 1.04, 3)] and seen[0][1] == (30, 20, 10)       # drawn on RGB (the frames are BGR)
    assert tuple(out[0][0, 0]) == (3, 2, 1)                                                                    # and handed back as BGR
    src.overlay = None; assert tuple(list(src.frames(0, 0, 1))[0][0, 0]) == (10, 20, 30)
