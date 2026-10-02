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
    monkeypatch.setattr(FN, 'final_dir', lambda f, k: str(tmp_path / k)); monkeypatch.setattr(FN, 'pieces', lambda *a, **k: (_ for _ in ()).throw(Stop())); monkeypatch.setattr(FN, 'final_key', lambda plan, size, fps, br, folder: 'saved' if 'why' in plan['segments'][1]['transition'] else 'pan')
    with pytest.raises(Stop): FN._render_final('f', p, {})
    assert [x.name for x in tmp_path.iterdir()] == ['saved']                                  # the key of the saved plan (its transition still has its reason), not of the one with the pan
