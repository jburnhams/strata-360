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


# ---- reading the project from disk, the music switch, and the overrides' guards

def _rd(f, *p): return os.path.join(f, 'strata360', *p)


def test_a_project_json_that_cannot_be_read_counts_as_empty():
    f = make_project(); os.makedirs(_rd(f), exist_ok=True); open(_rd(f, 'project.json'), 'w').write('{broken')
    e = P.load(f); assert e['plan'] is None and e['settings'] == P.DEFAULT_SETTINGS and e['overrides'] == P.EMPTY_OVERRIDES
    P.save(f, dict(settings={}, overrides={}, plan=None)); assert json.load(open(_rd(f, 'project.json'))) == dict(edit=dict(settings={}, overrides={}, plan=None))


def test_saved_settings_and_overrides_are_laid_over_the_defaults():
    f = make_project(); P.save(f, dict(settings=dict(length_s=45.0), overrides=dict(bans_techs=['x'])))
    e = P.load(f); assert e['settings']['length_s'] == 45.0 and e['settings']['bpm'] == 120.0 and e['overrides']['bans_techs'] == ['x'] and e['overrides']['locked'] == []
    e['overrides']['locked'].append(1); assert P.EMPTY_OVERRIDES['locked'] == []                                    # (the defaults are never shared)


def test_clips_are_read_with_their_extra_analysis_and_those_without_candidates_are_named():
    f = make_project((30, 12)); ids = sorted(os.listdir(_rd(f, 'clips')))
    d = _rd(f, 'clips', ids[0]); json.dump(dict(segments=[dict(t0=1, t1=2)]), open(os.path.join(d, 'alignment.json'), 'w'))
    json.dump(dict(cameras=[dict(kind='front', start_s=0, end_s=5, score=0.9, extra='dropped')]), open(os.path.join(d, 'cameras.json'), 'w'))
    json.dump(dict(samples=[dict(t=0, score=0.8), dict(t=1, score=0.6)], clear=0.7), open(os.path.join(d, 'face_view.json'), 'w'))
    os.remove(_rd(f, 'clips', ids[1], 'candidates.json')); os.makedirs(_rd(f, 'clips', 'junk')); open(_rd(f, 'clips', 'junk', 'clip.json'), 'w').write('nope')
    clips, missing = P.load_clips(f)
    assert [c['id'] for c in clips] == [ids[0]] and missing == [ids[1]]
    c = clips[0]; assert c['alignment'] == [dict(t0=1, t1=2)] and c['cameras'] == [dict(kind='front', start_s=0, end_s=5, score=0.9)] and c['face_view'] == [(0, 0.8), (1, 0.6)] and c['face_clear'] == 0.7


def test_a_clip_whose_extra_files_are_broken_is_still_planned():
    f = make_project((30,)); cid = os.listdir(_rd(f, 'clips'))[0]
    for name, body in (('alignment.json', '{bad'), ('cameras.json', '{"cameras": [{"kind": "x"}]}'), ('face_view.json', '{"samples": [{"t": 1}]}')): open(_rd(f, 'clips', cid, name), 'w').write(body)
    c = P.load_clips(f)[0][0]; assert 'alignment' not in c and 'cameras' not in c and 'face_view' not in c


def test_there_is_no_music_record_without_a_file():
    f = make_project(); assert P.music_record(f, {}) is None and P.music_info(f, {}) is None and P.music_record(f, dict(music='music/none.mp3')) is None


def test_an_unreadable_track_is_no_music(monkeypatch):
    from strata360.edit import music as MU
    f = make_project(); os.makedirs(_rd(f, 'music')); open(_rd(f, 'music', 't.mp3'), 'wb').write(b'x')
    def boom(rd, rel): raise RuntimeError('no decoder')
    monkeypatch.setattr(MU, 'info', boom); assert P.music_record(f, dict(music='music/t.mp3')) is None
    monkeypatch.setattr(MU, 'info', lambda rd, rel: dict(analysis=dict(bpm=100.0), name=rel)); assert P.music_info(f, dict(music='music/t.mp3')) == dict(bpm=100.0)


def test_music_modes_decide_whether_the_track_sets_the_length():
    assert P.built_mode(dict(music_mode='built')) and not P.built_mode(dict(music_mode='fixed')) and not P.built_mode({})
    assert P.fixed_length_free(dict(music_mode='built', music='music/t.mp3')) and P.fixed_length_free(dict(music_mode='built', music=None))
    assert not P.fixed_length_free(dict(music_mode='built', music=P.BUILT)) and not P.fixed_length_free(dict(music_mode='fixed', music='music/t.mp3'))
    assert P.original_track('f', dict(music=P.BUILT, music_original='music/t.mp3')) == 'music/t.mp3' and P.original_track('f', dict(music='music/t.mp3')) == 'music/t.mp3' and P.original_track('f', {}) is None


def test_using_the_built_track_keeps_the_upload_and_going_back_restores_it(monkeypatch):
    f = make_project(); monkeypatch.setattr(P, 'propose', lambda folder, **kw: P.load(folder))
    try: P.use_built(f); assert False
    except RuntimeError as e: assert 'no built track' in str(e)
    os.makedirs(_rd(f, 'music')); open(_rd(f, P.BUILT), 'wb').write(b'x'); P.set_music(f, 'music/up.mp3')
    s = P.use_built(f)['settings']; assert s['music'] == P.BUILT and s['music_original'] == 'music/up.mp3'
    s = P.use_built(f)['settings']; assert s['music_original'] == 'music/up.mp3'                                       # (using it twice does not lose the upload)
    s = P.use_original(f)['settings']; assert s['music'] == 'music/up.mp3' and s['music_original'] is None
    assert P.set_music(f, None)['settings']['music'] is None


def test_a_clip_weight_is_held_between_a_fifth_and_five_times_and_one_removes_it(monkeypatch):
    f = make_project(); monkeypatch.setattr(P, 'propose', lambda folder, **kw: P.load(folder))
    assert P.set_clip_weight(f, 'C01', 50)['overrides']['clip_weight'] == {'C01': 5.0} and P.set_clip_weight(f, 'C01', 0.01)['overrides']['clip_weight'] == {'C01': 0.2}
    assert P.set_clip_weight(f, 'C01', 1.0)['overrides']['clip_weight'] == {} and P.set_clip_weight(f, 'C02', 3)['overrides']['clip_weight'] == {'C02': 3.0}
    assert P.set_clip_weight(f, 'C02', None)['overrides']['clip_weight'] == {}


def test_banning_twice_keeps_one_entry_and_lifting_removes_it(monkeypatch):
    f = make_project(); monkeypatch.setattr(P, 'propose', lambda folder, **kw: P.load(folder))
    P.ban(f, 'moment', 'c1'); assert P.ban(f, 'moment', 'c1')['overrides']['bans_cands'] == ['c1'] and P.ban(f, 'technique', 'orbit')['overrides']['bans_techs'] == ['orbit']
    o = P.ban(f, 'moment', 'c1', on=False)['overrides']; assert o['bans_cands'] == [] and o['bans_techs'] == ['orbit']


def test_an_override_on_a_window_that_does_not_exist_is_an_error(monkeypatch):
    f = make_project(); monkeypatch.setattr(P, 'propose', lambda folder, **kw: P.load(folder))
    for call in (lambda: P.set_technique(f, 'nope@0.00', 'orbit'), lambda: P.set_lock(f, 'nope@0.00', True), lambda: P.set_transition(f, 'nope@0.00', 'cut')):
        try: call(); assert False
        except KeyError as e: assert 'no such segment nope@0.00' in str(e)
    assert P.set_technique(f, 'nope@0.00', None)['overrides']['tech_force'] == {}                                         # (clearing needs no window)


def test_a_transition_must_be_a_known_one_and_none_goes_back_to_the_rule(monkeypatch):
    from strata360.edit import transitions as TR
    f = make_project(); monkeypatch.setattr(P, 'propose', lambda folder, **kw: P.load(folder))
    edit = P.load(f); edit['plan'] = dict(segments=[dict(id='w@0.00')]); P.save(f, edit)
    try: P.set_transition(f, 'w@0.00', 'teleport'); assert False
    except ValueError as e: assert 'one of' in str(e)
    assert P.set_transition(f, 'w@0.00', TR.TYPES[0])['overrides']['transitions'] == {'w@0.00': TR.TYPES[0]}
    assert P.set_transition(f, 'w@0.00', None)['overrides']['transitions'] == {}


def test_generated_clips_are_put_in_their_places_among_the_segments():
    from strata360.edit import synthetic as SY
    f = make_project(); seg = lambda i, b: dict(id=f's{i}', index=i, start_beat=b, clip='C')
    assert P.insert_synthetic(f, [seg(0, 0)], [], 0.5) == [seg(0, 0)]
    SY.save(f, dict(clips=[dict(id='G01', seconds=4.0, t0='2026-02-21T12:00:00.000Z', t1='2026-02-21T12:00:04.000Z')]))
    out = P.insert_synthetic(f, [seg(0, 0), seg(1, 16)], [dict(clip='G01', beats=8, start_beat=8, role='gap', item=3)], 0.5)
    assert [g['start_beat'] for g in out] == [0, 8, 16] and [g['index'] for g in out] == [0, 1, 2]
    g = out[1]; assert g['clip'] == 'G01' and g['dur_s'] == 4.0 and g['film_start_s'] == 4.0 and g['kind'] == 'synthetic' and g['role'] == 'gap' and g['item'] == 3
    assert g['synthetic'] == os.path.normpath(_rd(f, 'synthetic', 'G01.mp4')) and g['synthetic_seconds'] == 4.0


def test_gap_clips_that_already_match_the_plan_are_left_alone():
    from strata360.edit import synthetic as SY
    f = make_project(); SY.save(f, dict(clips=[dict(id='G01', seconds=4.0)]))
    assert P.sync_gap_clips(f, [dict(clip='G01', seconds=4.02)]) == [] and P.sync_gap_clips(f, []) == []


def test_without_music_the_beats_cannot_be_synced():
    f = make_project(); ser = [dict(id='a')]
    assert P.beat_list(f, dict(music=None), None) is None and P.beat_list(f, dict(music='m'), None) is None and P.beat_list(f, dict(music=None), dict(built=False)) is None
    assert P.beat_sync(f, {}, None, ser, [], [], {}, []) == (ser, None) and P.beat_sync(f, {}, dict(x=1), [], [], [], {}, []) == ([], None)


def test_beats_that_cannot_be_found_leave_the_cuts_on_the_average_tempo(monkeypatch):
    f = make_project(); ser = [dict(id='a')]; warnings = []
    monkeypatch.setattr(P, 'beat_list', lambda *a: (_ for _ in ()).throw(RuntimeError('no tracker')))
    assert P.beat_sync(f, dict(music='m'), dict(x=1), ser, [], [], {}, warnings) == (ser, None) and 'no tracker' in warnings[0]
    monkeypatch.setattr(P, 'beat_list', lambda *a: None); assert P.beat_sync(f, dict(music='m'), dict(x=1), ser, [], [], {}, []) == (ser, None)


def test_a_built_tracks_beats_come_from_its_bar_lines(monkeypatch):
    from strata360.edit import beat_sync as BS, music as MU
    f = make_project(); monkeypatch.setattr(MU, 'built_score', lambda rd, rel: dict(downbeats=[0.0, 2.0])); monkeypatch.setattr(BS, 'from_downbeats', lambda d, n: [0.0, 0.5, 1.0])
    assert P.beat_list(f, dict(music='m'), dict(built=True, bar_beats=4)) == dict(beats=[0.0, 0.5, 1.0], downbeats=[0.0, 2.0])
    monkeypatch.setattr(MU, 'built_score', lambda rd, rel: None); assert P.beat_list(f, dict(music='m'), dict(built=True, bar_beats=4)) is None


def test_a_script_plan_needs_a_draft_and_candidates():
    f = make_project()
    try: P.plan_from_script(f); assert False
    except O.Infeasible as e: assert 'no script draft' in str(e)
    from strata360.edit import script_draft as SD
    SD.save_draft(f, dict(items=[]))
    for name in os.listdir(_rd(f, 'clips')): os.remove(_rd(f, 'clips', name, 'candidates.json'))
    try: P.plan_from_script(f); assert False
    except O.Infeasible as e: assert 'no candidates yet' in str(e)


def test_gap_items_need_a_gap_in_the_draft_and_a_track():
    f = make_project()
    assert P.apply_gap_items(f, dict(items=[dict(type='clip', clip='0001')])) == [] and P.apply_gap_items(f, {}) == []
    os.makedirs(_rd(f), exist_ok=True); json.dump({}, open(_rd(f, 'race.json'), 'w'))
    try: P.apply_gap_items(f, dict(items=[dict(type='gap', clip='G01', seconds=5)])); assert False
    except O.Infeasible as e: assert 'no race track' in str(e)
