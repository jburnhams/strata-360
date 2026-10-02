"""A script draft becomes the project's plan: saved in project.json, narration lines for the voice-over, and the voice-over builder reads them."""
import json, os
import pytest
from strata360.edit import project as PJ, script_draft as SD, voiceover as VO

A, B = 'CAM_20260222100100_0001_D', 'CAM_20260222100200_0002_D'


def feats(speech=0.0): return dict(steady=0.8, clear_nadir=0.8, open_ground=0.6, canopy=0.4, subject=0.6, speech=speech, protagonist=0.5, low_obstruction=0.8, resolution=0.8)
def cand(cid, k, a, b, kind='span', speech=0.0): return dict(id=f'{cid}#{k}', clip=cid, kind=kind, view='ahead', start_s=a, end_s=b, quality=0.7, energy=0.5, min_dur=1.0, max_dur=b - a, features=feats(speech), start_utc='2026-02-22T10:01:00Z', end_utc='2026-02-22T10:01:30Z')
def words(*ws, t=0.0): return [dict(w=w, t0=round(t + 0.4 * i, 2), t1=round(t + 0.4 * i + 0.3, 2), p=0.9) for i, w in enumerate(ws)]


@pytest.fixture
def folder(make_project):
    pr = make_project(config=True)
    pr.add_clip(A, start_utc='2026-02-22T10:01:00+00:00', source_frames=1800, fps=30.0, candidates=dict(candidates=[cand(A, 0, 0, 60), cand(A, 1, 20, 36, 'speech', 1.0)], unusable=[]),
                transcript=dict(segments=[dict(t0=20.0, t1=22.0, text='we are fine', text_en='we are fine', lang='en', words=words('we', 'are', 'fine', t=20.0))]))
    pr.add_clip(B, start_utc='2026-02-22T10:02:00+00:00', source_frames=900, fps=30.0, candidates=dict(candidates=[cand(B, 0, 0, 30)], unusable=[]))
    return pr.folder


def draft_for(folder):
    return dict(title='T', wpm=150, target_s=40, items=[dict(type='vo', clip='0001', text='It was a long morning.'), dict(type='clip', clip='0001', **{'from': '0001.00', 'to': '0001.00'}, lines=['0001.00']),
                                                         dict(type='broll', clip='0002', seconds=4.0), dict(type='vo', clip='0002', text='Then it got harder.')], skipped=[])


def test_the_draft_becomes_the_plan_with_roles_and_the_narration_lines(folder, monkeypatch):
    SD.save_draft(folder, draft_for(folder)); seen = {}
    def durations(f, lines, log=print): seen['lines'] = [l['text'] for l in lines]; return {l['seg']: 2.5 for l in lines}
    monkeypatch.setattr(VO, 'line_durations', durations)
    edit = PJ.plan_from_script(folder); p = edit['plan']
    assert p['source'] == 'script' and seen['lines'] == ['It was a long morning.', 'Then it got harder.']
    segs = p['segments']; assert [g['role'] for g in segs][0] == 'vo' and 'clip' in {g['role'] for g in segs} and {g['item'] for g in segs} == {0, 1, 2, 3}
    assert abs(p['film']['length_s'] - sum(g['dur_s'] for g in segs)) < 1e-6 and [g['film_start_s'] for g in segs] == sorted(g['film_start_s'] for g in segs)
    assert all(g['dur_s'] >= 2.0 - 1e-9 for g in segs) and all(abs(g['beats'] * 60.0 / p['film']['bpm'] - g['dur_s']) < 0.002 for g in segs)
    saved = json.load(open(os.path.join(folder, 'strata360', 'project.json')))['edit']['plan']; assert saved['source'] == 'script' and len(saved['segments']) == len(segs)
    lines = json.load(open(os.path.join(folder, 'strata360', 'script2', 'lines.json')))['lines']; assert [l['text'] for l in lines] == ['It was a long morning.', 'Then it got harder.'] and lines[0]['film_start_s'] == 0.0 and lines[1]['film_start_s'] > lines[0]['film_start_s']


def test_the_voice_over_builder_speaks_the_script_plans_lines_not_an_older_script(folder, monkeypatch):
    SD.save_draft(folder, draft_for(folder)); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.0 for l in lines}); PJ.plan_from_script(folder)
    name, lines = VO.script_lines(folder); assert name.startswith('script2-') and [l['text'] for l in lines] == ['It was a long morning.', 'Then it got harder.'] and VO.newest_script(folder) == name
    legacy = os.path.join(folder, 'strata360', 'scripts'); os.makedirs(legacy, exist_ok=True); p = os.path.join(legacy, 'script-20990101-000000.json'); json.dump(dict(lines=[dict(seg=1, text='old', film_start_s=0, seconds=3)]), open(p, 'w'))
    os.utime(p, (4102444800, 4102444800)); assert VO.script_lines(folder)[1][0]['text'] == 'old'                                      # a newer beat-planner script wins again


def test_no_draft_and_no_candidates_are_refused_with_the_reason(make_project):
    from strata360.edit import optimise as O
    pr = make_project(config=True)
    with pytest.raises(O.Infeasible, match='no script draft'): PJ.plan_from_script(pr.folder)
    SD.save_draft(pr.folder, dict(items=[]))
    with pytest.raises(O.Infeasible, match='candidates'): PJ.plan_from_script(pr.folder)
