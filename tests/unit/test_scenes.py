"""analysis/scenes.py: the scenes stage keeps the general answers of an earlier run for the same sampling, always runs the scenery prompt, and summarises both."""
import numpy as np
import pytest
from strata360.analysis import scenes as S

LOG = dict(setting='trail', description='a trail', people=0, crowd='none', lighting='dusk', weather='fog', activity='running', mood='calm', scenic=0.4, energy=0.3, lens_problems='none', tags=['trees'])


@pytest.fixture
def fake(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(S, 'video_pts', lambda osv, k: np.arange(0, 300) / 30.0)
    monkeypatch.setattr(S.V, 'proxy_available', lambda p: True); monkeypatch.setattr(S.V, 'write_stab_views_proxy', lambda *a, **k: None)
    def vlm(py, src, tmp, out, models, prompt):
        calls.append(prompt)
        if prompt == 'scenery': return dict(model='m', seconds=1.0, items=[dict(frame=0, view=0, answer=dict(score=7, clarity=4, reason='open')), dict(frame=0, view=1, answer=dict(score=3, clarity=2, reason='fog')), dict(frame=150, view=0, answer=None)])
        return dict(model='m', seconds=2.0, items=[dict(frame=f, view=v, answer=dict(LOG)) for f, v in ((0, 0), (0, 1), (150, 0))])
    monkeypatch.setattr(S, '_vlm', vlm); return calls


def test_a_first_run_asks_both_prompts_and_summarises_the_scenery(fake, tmp_path):
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0); assert fake == ['scenery', 'log'] and r['schema'] == 2
    f, rear, bad = r['items']; assert f['scenery'] == 7.0 and f['clarity'] == 4.0 and f['scenery_why'] == 'open' and f['setting'] == 'trail' and rear['view'] == 'rear' and rear['clarity'] == 2.0
    assert bad['ok'] is True and bad['scenery'] is None and r['summary']['scenery_front'] == 7.0 and r['summary']['scenery_rear'] == 3.0 and r['summary']['clarity_front'] == 4.0


def test_an_earlier_run_for_the_same_sampling_is_not_asked_again(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); fake.clear()
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=prev); assert fake == ['scenery'] and r['items'][0]['setting'] == 'trail' and r['items'][0]['scenery'] == 7.0


def test_another_sampling_or_no_earlier_run_means_the_general_prompt_runs_again(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=10.0, previous=prev); assert fake == ['scenery', 'log']
    assert S.reusable(None, 5.0) == {} and S.reusable(dict(sample_every_s=5.0, items=[]), 5.0) == {}
