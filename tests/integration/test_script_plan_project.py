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


C = 'CAM_20260222113000_0003_D'


@pytest.fixture
def gap_folder(make_project):
    """Clips 0001 and 0002 a minute apart, 0003 an hour and a half later, and a race track over all of it: one gap (G01) between 0002 and 0003."""
    import numpy as np
    pr = make_project(config=True)
    pr.add_clip(A, start_utc='2026-02-22T10:01:00+00:00', source_frames=1800, fps=30.0, candidates=dict(candidates=[cand(A, 0, 0, 60), cand(A, 1, 20, 36, 'speech', 1.0)], unusable=[]),
                transcript=dict(segments=[dict(t0=20.0, t1=22.0, text='we are fine', text_en='we are fine', lang='en', words=words('we', 'are', 'fine', t=20.0))]))
    pr.add_clip(B, start_utc='2026-02-22T10:02:00+00:00', source_frames=900, fps=30.0, candidates=dict(candidates=[cand(B, 0, 0, 30)], unusable=[]))
    pr.add_clip(C, start_utc='2026-02-22T11:30:00+00:00', source_frames=900, fps=30.0, candidates=dict(candidates=[cand(C, 0, 0, 30)], unusable=[]))
    n = 720; t0 = 1_771_754_400.0 - 3600; d = 3.0 * 10.0 * np.arange(n); nan = np.full(n, np.nan); tp = os.path.join(pr.race_dir, 'track.gpx'); open(tp, 'w').write('<gpx/>')
    np.savez_compressed(tp + '.npz', t=t0 + 10.0 * np.arange(n), lat=50.0 + d * 5.4e-6, lon=5.0 + d * 1.119e-5, alt=100 + np.arange(n) * 0.2, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)
    return pr.folder


def gap_draft(kind='flyover', seconds=14):
    d = draft_for(None); d['items'] = d['items'][:3] + [dict(type='gap', clip='g01', kind=kind, seconds=seconds, why='the quiet hour', anchor=dict(film_s=20, why='the chorus')), dict(type='broll', clip='0003', seconds=4.0)]; return d


def test_a_gap_item_plans_its_clip_with_the_planners_kind_and_becomes_a_window_that_waits_to_be_rendered(gap_folder, monkeypatch):
    from strata360.edit import synthetic as SY
    SD.save_draft(gap_folder, gap_draft()); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.0 for l in lines}); log = []
    p = PJ.plan_from_script(gap_folder, log=log.append)['plan']; segs = p['segments']; syn = [g for g in segs if g.get('synthetic')]
    c = SY.load(gap_folder)['clips']; assert len(c) == 1 and c[0]['id'] == 'G01' and c[0]['kind'] == 'map' and c[0]['by'] == 'planner' and c[0]['seconds'] == 14.0 and c[0]['status'] == 'planned' and not any('approval' in l for l in log)          # the draft asked for a flyover: the planner chose (a short, flat gap is a map)
    assert len(syn) == 1 and syn[0]['clip'] == 'G01' and syn[0]['role'] == 'broll' and syn[0]['item'] == 3 and syn[0]['synthetic'].endswith(os.path.join('synthetic', 'G01.mp4')) and abs(syn[0]['dur_s'] - 14.0) < 0.6
    assert any('G01' in w and 'not rendered yet' in w and 'approve' not in w for w in p['warnings'])
    assert [g['index'] for g in segs] == list(range(len(segs))) and all(abs(a['film_start_s'] + a['dur_s'] - b['film_start_s']) < 0.002 for a, b in zip(segs, segs[1:])) and abs(p['film']['length_s'] - sum(g['dur_s'] for g in segs)) < 1e-6


def test_planning_again_keeps_a_rendered_clip_and_one_you_made_but_a_new_length_plans_it_again(gap_folder, monkeypatch):
    from strata360.edit import synthetic as SY
    monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.0 for l in lines}); SD.save_draft(gap_folder, gap_draft()); PJ.plan_from_script(gap_folder)
    doc = SY.load(gap_folder); doc['clips'][0]['status'] = 'ready'; doc['clips'][0]['file'] = 'synthetic/G01.mp4'; SY.save(gap_folder, doc)
    PJ.plan_from_script(gap_folder); c = SY.load(gap_folder)['clips'][0]; assert c['status'] == 'ready'                                                    # the same kind and length: left alone
    SD.save_draft(gap_folder, gap_draft(seconds=20)); PJ.plan_from_script(gap_folder); c = SY.load(gap_folder)['clips'][0]; assert c['seconds'] == 20.0 and c['status'] == 'planned' and c['kind'] == 'map'          # a new length: planned again, in the kept kind
    SY.upsert(gap_folder, SY.make(dict(id='G01', t0=1_771_754_000.0, t1=1_771_754_000.0 + 7200), seconds=20.0, kind='flyover', by='user'))
    PJ.plan_from_script(gap_folder); c = SY.load(gap_folder)['clips'][0]; assert c['kind'] == 'flyover' and c['by'] == 'user'                          # one you made by hand keeps its kind whatever the planner would choose


def test_a_rendered_generated_clip_is_not_a_warning_and_its_file_is_played(gap_folder, monkeypatch):
    from strata360.edit import synthetic as SY
    monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.0 for l in lines}); SD.save_draft(gap_folder, gap_draft(kind='map')); PJ.plan_from_script(gap_folder)
    rd = os.path.join(gap_folder, 'strata360'); os.makedirs(os.path.join(rd, 'synthetic'), exist_ok=True); open(os.path.join(rd, 'synthetic', 'G01.mp4'), 'wb').write(b'x')
    doc = SY.load(gap_folder); doc['clips'][0].update(status='ready', file='synthetic/G01.mp4'); SY.save(gap_folder, doc)
    assert not any('not rendered yet' in w for w in PJ.plan_from_script(gap_folder)['plan']['warnings'])


def test_narration_over_a_gap_plans_a_clip_as_long_as_the_voice_needs_and_b_roll_keeps_the_planned_kind(gap_folder, monkeypatch):
    from strata360.edit import synthetic as SY, script_plan as SPL
    d = draft_for(None); d['items'] = d['items'][:3] + [dict(type='vo', clip='G01', text='A long stretch of night, one step after another, and nothing else.'), dict(type='broll', clip='0003', seconds=4.0)]
    SD.save_draft(gap_folder, d); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 9.0 for l in lines}); log = []
    p = PJ.plan_from_script(gap_folder, log=log.append)['plan']; c = SY.load(gap_folder)['clips']; need = SPL.LEAD_S + 9.0 + SPL.TAIL_S
    assert len(c) == 1 and c[0]['kind'] == 'map' and c[0]['seconds'] >= need - 0.01 and c[0]['approved'] is True and any('planned map clip G01' in l for l in log)                       # no gap item, but the narration needs picture
    syn = [g for g in p['segments'] if g.get('synthetic')]; assert len(syn) == 1 and syn[0]['role'] == 'vo' and abs(syn[0]['dur_s'] - c[0]['seconds']) < 0.6                              # the window is as long as the clip: no held last frame
    SY.upsert(gap_folder, SY.make(dict(id='G01', t0=1_771_754_000.0, t1=1_771_754_000.0 + 7200), seconds=20.0, kind='flyover', by='user'))
    PJ.plan_from_script(gap_folder); c = SY.load(gap_folder)['clips'][0]; assert c['kind'] == 'flyover' and c['seconds'] == 20.0                                                         # long enough and of another kind: left as it is
    d['items'][3] = dict(type='broll', clip='G01', seconds=12.0); SD.save_draft(gap_folder, d); PJ.plan_from_script(gap_folder); c = SY.load(gap_folder)['clips'][0]; assert c['kind'] == 'flyover' and c['seconds'] == 12.0       # b-roll: its own length, in the planned kind
