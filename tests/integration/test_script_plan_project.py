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


def test_a_generated_clip_in_the_script_becomes_a_window_that_plays_its_file(folder, monkeypatch):
    from strata360.edit import synthetic as SY, framing as FR
    gap = dict(id='G01', t0=1_771_754_000.0, t1=1_771_754_000.0 + 7200); clip = SY.make(gap, seconds=6.0); SY.save(folder, dict(clips=[dict(clip, status='ready', file='synthetic/G01.mp4')]))
    d = draft_for(folder); d['items'].insert(2, dict(type='broll', clip='g01', seconds=30)); SD.save_draft(folder, d); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.0 for l in lines})
    p = PJ.plan_from_script(folder)['plan']; segs = p['segments']; syn = [g for g in segs if g.get('synthetic')]
    assert len(syn) == 1 and syn[0]['clip'] == 'G01' and syn[0]['synthetic'].endswith(os.path.join('synthetic', 'G01.mp4')) and syn[0]['role'] == 'broll' and syn[0]['item'] == 2 and abs(syn[0]['dur_s'] - 6.0) < 0.6
    assert [g['index'] for g in segs] == list(range(len(segs))) and abs(p['film']['length_s'] - sum(g['dur_s'] for g in segs)) < 1e-6
    assert all(abs(a['film_start_s'] + a['dur_s'] - b['film_start_s']) < 0.002 for a, b in zip(segs, segs[1:]))
    seen = []; monkeypatch.setattr(FR, 'clip_data', lambda f, c: seen.append(c) or {}); monkeypatch.setattr(FR, 'resolve_segment', lambda g, lib, data: {}); res = FR.resolve(folder, p)
    assert syn[0]['id'] not in res and 'G01' not in seen and len(res) == len(segs) - 1                                          # a generated clip has no camera to frame
    lines = json.load(open(os.path.join(folder, 'strata360', 'script2', 'lines.json')))['lines']; after = [g for g in segs if g['item'] == 3][0]; assert [l['text'] for l in lines][-1] == 'Then it got harder.' and lines[-1]['film_start_s'] >= syn[0]['film_start_s'] + syn[0]['dur_s'] - 0.002 and after['film_start_s'] >= syn[0]['film_start_s'] + syn[0]['dur_s'] - 0.002
