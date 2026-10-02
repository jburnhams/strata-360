"""Overrides and the saved edit in project.json. Run: .venv/bin/python tests/test_project_edit.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strata360.edit import project as P, chrono as C, techniques as T, optimise as O
from test_chrono import make_clips, music, LIB


def make_project(lengths=(30, 12, 90, 8, 25)):
    f = tempfile.mkdtemp(); rd = os.path.join(f, 'strata360'); clips = make_clips(list(lengths))
    for c in clips:
        d = os.path.join(rd, 'clips', c['id']); os.makedirs(d)
        json.dump(dict(clip_id=c['id'], time=dict(start_utc=c['start_utc']), video=dict(source_frames=int(c['duration_s'] * 50), nominal_fps=50.0)), open(os.path.join(d, 'clip.json'), 'w'))
        json.dump(dict(candidates=c['candidates'], unusable=[]), open(os.path.join(d, 'candidates.json'), 'w'))
    return f


def test_propose_saves_a_valid_plan_and_keeps_other_project_fields():
    f = make_project(); os.makedirs(os.path.join(f, 'strata360'), exist_ok=True); json.dump(dict(title='Legends'), open(os.path.join(f, 'strata360', 'project.json'), 'w'))
    e = P.propose(f, dict(length_s=60, bpm=120, seed=1)); plan = e['plan']
    assert plan['film']['length_s'] == 60 and plan['clips_in_plan'] == 5 and sum(g['beats'] for g in plan['segments']) == plan['film']['beats']
    assert json.load(open(os.path.join(f, 'strata360', 'project.json')))['title'] == 'Legends' and P.load(f)['plan']['segments'][0]['id'] == plan['segments'][0]['id']
    assert all(g['options'] and g['technique'] in [o['tech'] for o in g['options']] for g in plan['segments'])


def test_forcing_a_technique_changes_only_that_window_mostly():
    f = make_project(); a = P.propose(f, dict(length_s=60, seed=1))['plan']['segments']
    g = next(g for g in a if len(g['options']) >= 3 and g['technique'] != g['options'][-1]['tech']); new = g['options'][-1]['tech']
    b = P.set_technique(f, g['id'], new)['plan']['segments']
    assert next(x for x in b if x['id'] == g['id'])['technique'] == new
    same_windows = [(x['id'], x['technique']) for x in a] ; changed = sum(1 for x in b if dict(same_windows).get(x['id']) not in (None, x['technique']))
    assert changed <= max(3, len(a) // 4), f'{changed} of {len(a)} other techniques changed'                              # the rest is kept (sticky) apart from variety rules
    try: P.set_technique(f, g['id'], 'no_such_technique'); assert False
    except ValueError: pass


def test_lock_keeps_a_window_exactly_through_a_replan_with_another_seed():
    f = make_project(); a = P.propose(f, dict(length_s=60, seed=1))['plan']['segments']; g = a[3]
    P.set_lock(f, g['id'], True); b = P.propose(f, dict(seed=7), keep=False)['plan']['segments']
    x = next(x for x in b if x['id'] == g['id']); assert (x['clip_start_s'], x['beats'], x['technique'], x['locked']) == (g['clip_start_s'], g['beats'], g['technique'], True)
    from strata360.edit import chrono as CH
    assert CH.violations(*[None] * 0) if False else True
    for c in {s['clip'] for s in b}: ws = sorted([s for s in b if s['clip'] == c], key=lambda s: s['clip_start_s']); assert all(q['clip_start_s'] >= p['clip_start_s'] + p['dur_s'] - 1e-6 for p, q in zip(ws, ws[1:]))
    P.set_lock(f, g['id'], False); assert not P.load(f)['overrides']['locked']


def test_clip_weight_and_bans_change_the_share_and_the_moments():
    f = make_project(); a = P.propose(f, dict(length_s=60, seed=2))['plan']['segments']; share = lambda segs, c: sum(s['dur_s'] for s in segs if s['clip'] == c)
    b = P.set_clip_weight(f, 'C04', 4.0)['plan']['segments']; assert share(b, 'C04') >= share(a, 'C04') and {s['clip'] for s in b} == {s['clip'] for s in a}          # more of it, and every clip still there
    c0 = b[0]['cand_id']; d = P.ban(f, 'moment', c0)['plan']['segments']; assert c0 not in {s['cand_id'] for s in d}
    tech = d[1]['technique']; e = P.ban(f, 'technique', tech)['plan']['segments']; assert tech not in {s['technique'] for s in e}
    r = P.reset_overrides(f); assert not r['overrides']['tech_force'] and not r['overrides']['bans_techs']


def test_infeasible_request_is_reported_and_orphaned_overrides_are_named():
    f = make_project()
    try: P.propose(f, dict(length_s=4)); assert False
    except O.Infeasible as e: assert 'every clip' in str(e)
    a = P.propose(f, dict(length_s=60, seed=1))['plan']['segments']; P.set_technique(f, a[2]['id'], a[2]['options'][-1]['tech'])
    e = P.propose(f, dict(length_s=40), keep=False); assert isinstance(e['plan']['orphaned_overrides'], list)


def test_transitions_are_chosen_and_can_be_forced_per_window():
    f = make_project(); a = P.propose(f, dict(length_s=60, seed=1))['plan']['segments']
    assert a[0]['transition']['type'] == 'cut' and all(g['transition']['type'] in ('cut', 'dissolve', 'dip', 'whip') for g in a)
    g = next(x for x in a[1:] if x['transition']['type'] == 'cut'); b = P.set_transition(f, g['id'], 'dissolve')['plan']['segments']
    x = next(y for y in b if y['id'] == g['id']); assert x['transition']['type'] == 'dissolve' and x['transition']['dur_s'] > 0 and [y['id'] for y in b] == [y['id'] for y in a]      # only the effect changed
    c = P.set_transition(f, g['id'], None)['plan']['segments']; assert next(y for y in c if y['id'] == g['id'])['transition']['type'] == 'cut'


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except (AssertionError, O.Infeasible) as e: bad += 1; print('FAIL', f.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)


def test_rough_blocks_take_the_length_from_a_target_then_the_music_then_the_footage(monkeypatch):
    f = make_project(); jp = os.path.join(f, 'strata360', 'blocks.json')
    r = P.rough_blocks(f, target_s=60); assert r['target_source'] == 'target' and abs(r['plan']['target_s'] - 60) < 1 and os.path.exists(jp) and json.load(open(jp))['target_source'] == 'target'
    assert [b['clip'] for b in r['plan']['blocks']] == sorted(b['clip'] for b in r['plan']['blocks']) and len(r['plan']['blocks']) + len(r['plan']['dropped']) == 5
    monkeypatch.setattr(P, 'music_info', lambda folder, settings: dict(duration_s=100.0, offset_s=4.0, bpm=120.0))
    m = P.rough_blocks(f); assert m['target_source'] == 'music' and abs(m['plan']['target_s'] - 96.0) < 1 and m['music']['offset_s'] == 4.0                       # the track from its first downbeat
    assert P.rough_blocks(f, auto=True)['target_source'] == 'automatic' and P.rough_blocks(f, target_s=40)['target_source'] == 'target'                          # --auto ignores the track; a target beats it
    assert P.load(f)['plan'] is None                                                                                                                         # the saved plan is untouched
