"""Openings and endings (edit/bookends.py): the pure parts. The window search, the spacing of candidates, the globe wrapped round a face shot, the plan segment of a candidate and the vision model's answer."""
import numpy as np
from strata360.edit import bookends as B


def test_windows_need_a_good_mean_and_no_bad_second():
    t = np.arange(0, 20.0); score = np.ones(20); score[8] = 0.2
    got = dict(B.pick_windows(t, score, 4.0, 0.8, 0.5))
    assert 0.0 in got and 3.0 in got and 4.0 not in got and 8.0 not in got and 9.0 in got               # windows 4 to 8 all contain the bad second
    assert B.pick_windows(t, score, 4.0, 0.8, 0.5, extra=lambda a, b: None) == []                        # a veto removes every window
    assert dict(B.pick_windows(t, np.full(20, 0.9), 4.0, 0.8, 0.5, extra=lambda a, b: 0.5))[0.0] == 0.45


def test_candidates_are_kept_apart_in_time():
    items = [(0.9, dict(clip='a', clip_start_s=10.0)), (0.8, dict(clip='a', clip_start_s=12.0)), (0.7, dict(clip='b', clip_start_s=12.0)), (0.6, dict(clip='a', clip_start_s=30.0))]
    got = [it['clip_start_s'] for _, it in B.spread(items, 12.0)]
    assert got == [10.0, 12.0, 30.0] and [it['clip'] for _, it in B.spread(items, 12.0)] == ['a', 'b', 'a']


FACE = dict(ref='world', subject='you', keyframes=[dict(t=0.0, yaw=40.0, pitch=2.0, fov=58.0), dict(t=1.5, yaw=42.0, pitch=2.0, fov=58.0), dict(t=3.2, yaw=41.0, pitch=1.0, fov=58.0)])


def test_an_opening_starts_as_the_planet_and_lands_on_the_face():
    p = B.globe_path(FACE, G=2.2); k = p['keyframes']
    assert k[0]['t'] == 0.0 and k[0]['pitch'] == -90.0 and k[0]['fov'] == 260.0 and k[0]['dist'] == 1.0 and k[0]['ease'] == 'smooth'
    assert k[1]['t'] == 2.2 and k[1]['fov'] == 58.0 and k[1]['dist'] == 0.0 and k[-1]['t'] == 5.4                  # the face keyframes moved 2.2 s in
    assert k[0]['yaw'] == 40.0 - B.SPIN_DEG and FACE['keyframes'][0]['t'] == 0.0                                   # (the input is not changed)


def test_an_ending_is_the_face_then_the_planet_closing():
    k = B.globe_path(FACE, G=2.2, outro=True)['keyframes']
    assert k[0]['t'] == 0.0 and k[0]['fov'] == 58.0 and k[-1]['t'] == 5.4 and k[-1]['pitch'] == -90.0 and k[-1]['fov'] == 260.0 and k[-1]['dist'] == 1.0 and k[-2]['ease'] == 'smooth'


def test_a_candidate_becomes_a_plan_segment():
    c = dict(id='intro-crowd-0', kind='crowd', where='intro', clip='CAM_1', clip_start_s=12.0, dur_s=5.0, technique='push_in', variant_seed=1000)
    g = B.segment_of(c); assert g['clip'] == 'CAM_1' and g['clip_start_s'] == 12.0 and g['dur_s'] == 5.0 and g['technique'] == 'push_in' and g['kind'] == 'best' and g['id'].endswith('intro-crowd-0')
    assert B.segment_of(dict(c, kind='globe_face', technique='selfie_close'))['kind'] == 'you'


def test_the_models_answer_is_read_even_with_a_trailing_comma():
    cs = [dict(id='a', dur_s=5.0), dict(id='b', dur_s=5.0)]

    class Server:
        def ask(self, prompt, images, max_tokens): return 'Here: {"scores": [{"i": 0, "score": 6, "why": "ok"}, {"i": 1, "score": 9, "why": "great"},], "best": 1}'
    scores, best = B.rank(cs, ['x.jpg', 'y.jpg'], 'intro', 'crowd', Server())
    assert best == 'b' and scores['b'] == dict(vlm_score=9.0, vlm_why='great') and scores['a']['vlm_score'] == 6.0


# ---- the paths of the whole sequence, the candidates found in a project, and the files the film reads

def test_an_opening_sequence_runs_planet_wide_pan_then_face():
    k = B.sequence_path(FACE, G=2.0, P=3.2, sweep=270.0)['keyframes']
    assert len(k) == 7 and k[0]['pitch'] == -90.0 and k[0]['fov'] == 260.0 and k[0]['yaw'] == 40.0 - 270.0 - B.SPIN_DEG
    assert k[1]['t'] == 2.0 and k[1]['yaw'] == 40.0 - 270.0 and k[1]['fov'] == 95.0                          # the pan starts wide, a full sweep from the face
    assert k[4]['t'] == 5.2 and k[4]['yaw'] == 40.0 and k[4]['fov'] == 58.0                                  # and ends on the face's own view
    assert k[-1]['t'] == 8.4 and [x['t'] for x in k] == sorted(x['t'] for x in k)


def test_an_ending_sequence_is_the_same_run_backwards():
    p = B.sequence_path(FACE, outro=True); k = p['keyframes']
    assert len(k) == 7 and k[0]['t'] == 0.0 and k[0]['fov'] == 58.0 and k[-1]['t'] == 8.4 and k[-1]['pitch'] == -90.0 and k[-1]['fov'] == 260.0
    assert p['why'].startswith('your face')


def test_the_sign_turns_the_globe_the_other_way():
    up = B.globe_path(FACE, sign=1.0)['keyframes'][0]['yaw']; down = B.globe_path(FACE, sign=-1.0)['keyframes'][0]['yaw']
    assert up == 40.0 - B.SPIN_DEG and down == 40.0 + B.SPIN_DEG


def _scenes(people, n=11):
    return dict(items=[dict(ok=True, t_s=2.0 * i, view='front', people=people, crowd='many' if people > 8 else 'few', scenery=6, clarity=4, setting='start_finish') for i in range(n)])


def _faces(n=21, score=1.0): return dict(samples=[dict(t=float(i), score=score) for i in range(n)])


def _motion(dur=60.0): return dict(duration_s=dur, series=dict(t=[float(i) for i in range(int(dur))], shake_dps=[5.0] * int(dur)))


FIRST, LAST = 'CAM_20260221120007_0001_D', 'CAM_20260225120007_0001_D'


def _race(make_project, dur=60.0, faces=None, people=12):
    """Five clips a day apart: the first and last have a face and a crowd, the three between nothing."""
    p = make_project(clips=())
    for i in range(5):
        edge = i in (0, 4)
        p.add_clip(f'CAM_2026022{i + 1}120007_0001_D', start_utc=f'2026-02-2{i + 1}T12:00:07+00:00',
                   **(dict(face_view=faces or _faces(), motion=_motion(dur), scenes=_scenes(people)) if edge else {}))
    return p


def test_openings_come_from_the_start_of_the_race_and_endings_from_its_end(make_project):
    cs = B.candidates(_race(make_project).folder)
    assert {c['kind'] for c in cs['intro']} == {'globe_face', 'sequence', 'crowd'} and {c['kind'] for c in cs['outro']} == {'globe_face', 'sequence', 'crowd'}
    assert {c['clip'] for c in cs['intro']} == {FIRST} and {c['clip'] for c in cs['outro']} == {LAST}
    assert all(c['id'].startswith(f"{c['where']}-{c['kind']}-") and c['where'] == w for w in cs for c in cs[w])


def test_candidates_are_best_first_and_a_kind_is_capped(make_project):
    cs = B.candidates(_race(make_project).folder, per=2)
    for w in cs:
        assert [c['score'] for c in cs[w]] == sorted((c['score'] for c in cs[w]), reverse=True)
        for kind in B.KINDS: assert sum(1 for c in cs[w] if c['kind'] == kind) <= 2
    crowd = [c for c in cs['intro'] if c['kind'] == 'crowd']; assert crowd and {c['technique'] for c in crowd} <= {'push_in', 'pan_reveal'}
    assert all(c['view'] == 'you' for c in cs['intro'] if c['kind'] != 'crowd') and all(c['view'] == 'ahead' for c in crowd)


def test_a_clip_too_short_for_the_globe_gives_no_globe_or_sequence(make_project):
    cs = B.candidates(_race(make_project, dur=5.0).folder)
    assert not [c for w in cs for c in cs[w] if c['kind'] in ('globe_face', 'sequence')]
    assert all(c['clip_start_s'] + c['dur_s'] <= 5.0 + 1e-9 for w in cs for c in cs[w] if c['kind'] == 'crowd')    # a crowd shot is pulled back to fit


def test_a_face_that_is_never_clear_gives_no_globe_shot(make_project):
    cs = B.candidates(_race(make_project, faces=_faces(score=0.3)).folder)
    assert not [c for w in cs for c in cs[w] if c['kind'] in ('globe_face', 'sequence')] and [c for c in cs['intro'] if c['kind'] == 'crowd']


def test_a_sparse_crowd_is_not_a_crowd(make_project):
    p = make_project(clips=()); p.add_clip(FIRST, scenes=_scenes(2), motion=_motion())
    assert B.candidates(p.folder) == {'intro': [], 'outro': []}


def test_clips_without_a_readable_clip_json_are_left_out(make_project):
    import os
    p = make_project(clips=()); p.add_clip(FIRST); broken = p.clip_dir('CAM_BROKEN'); os.makedirs(broken)
    open(os.path.join(broken, 'clip.json'), 'w').write('{not json')
    assert [c for c, _ in B._race_clips(p.folder)] == [FIRST]


def test_the_title_words_are_the_project_name_and_the_dates(make_project):
    p = make_project('ultra-trip', config=True, clips=())
    p.add_clip(FIRST, start_utc='2026-02-21T12:00:07+00:00'); p.add_clip('CAM_20260224120007_0001_D', start_utc='2026-02-24T12:00:07+00:00')
    assert B.default_lines(p.folder) == [dict(role='title', text='Ultra Trip'), dict(role='meta', text='21 to 24 February 2026')]
    p.add_clip('CAM_20260302120007_0001_D', start_utc='2026-03-02T12:00:07+00:00')
    assert B.default_lines(p.folder)[1]['text'] == '21 February to 2 March 2026'


def test_a_project_without_clips_has_only_a_title(make_project):
    import os
    p = make_project('solo_run', config={'name': 'my_run'}, clips=()); os.makedirs(p.path('clips'))
    assert B.default_lines(p.folder) == [dict(role='title', text='My Run')]


def _bookends_json(p, chosen):
    cand = lambda cid, kind, where: dict(id=cid, kind=kind, where=where)
    p.write_json('bookends/bookends.json', dict(candidates=dict(intro=[cand('intro-sequence-0', 'sequence', 'intro'), cand('intro-crowd-0', 'crowd', 'intro')], outro=[cand('outro-crowd-0', 'crowd', 'outro')]), chosen=chosen))


def test_the_film_gets_the_best_chosen_kind_with_its_title(make_project, monkeypatch):
    p = make_project(config=True); monkeypatch.delenv('STRATA_BOOKENDS', raising=False)
    _bookends_json(p, {'intro-crowd': 'intro-crowd-0', 'intro-sequence': 'intro-sequence-0', 'outro-crowd': 'outro-crowd-0'}); p.write_json('bookends/intro-sequence-0.title.json', dict(spec={'elements': []}))
    got = B.for_film(p.folder)
    assert [(g['where'], g['c']['id']) for g in got] == [('intro', 'intro-sequence-0'), ('outro', 'outro-crowd-0')]          # sequence beats crowd
    assert got[0]['spec'] == {'elements': []} and got[1]['spec'] is None                                                   # no title designed for the ending yet
    assert [g['where'] for g in B.for_film(p.folder, where=('outro',))] == ['outro']


def test_no_bookends_file_or_the_switch_off_means_none(make_project, monkeypatch):
    p = make_project(config=True); monkeypatch.delenv('STRATA_BOOKENDS', raising=False); assert B.for_film(p.folder) == []
    _bookends_json(p, {'intro-crowd': 'intro-crowd-0'}); assert len(B.for_film(p.folder)) == 1
    monkeypatch.setenv('STRATA_BOOKENDS', '0'); assert B.for_film(p.folder) == []


def test_a_chosen_id_that_is_not_a_candidate_is_ignored(make_project, monkeypatch):
    p = make_project(config=True); monkeypatch.delenv('STRATA_BOOKENDS', raising=False); _bookends_json(p, {'intro-crowd': 'gone'}); assert B.for_film(p.folder) == []


def test_glob_first_takes_the_first_by_name(tmp_path):
    (tmp_path / 'mmproj-b.gguf').write_text('x'); (tmp_path / 'mmproj-a.gguf').write_text('x')
    assert B.glob_first(str(tmp_path), 'mmproj*.gguf') == str(tmp_path / 'mmproj-a.gguf') and B.glob_first(str(tmp_path), 'none*') is None


class _Ask:
    def __init__(self, text): self.text, self.prompt = text, None
    def ask(self, prompt, images, max_tokens): self.prompt = prompt; return self.text


def test_the_models_answer_may_be_junk_and_out_of_range_indexes_are_dropped():
    cs = [dict(id='a', dur_s=5.0), dict(id='b', dur_s=5.0)]
    assert B.rank(cs, ['x', 'y'], 'outro', 'sequence', _Ask('no json here')) == ({}, None)
    scores, best = B.rank(cs, ['x', 'y'], 'outro', 'globe_face', _Ask('{"scores": [{"i": 7, "score": 9}, {"i": 0, "score": 4}], "best": 9}'))
    assert list(scores) == ['a'] and best is None
    assert B.parse('{"a": 1,}') == {'a': 1} and B.parse('{broken') is None


def test_the_prompt_names_the_kind_of_shot_and_the_count():
    srv = _Ask('{}'); B.rank([dict(id='a', dur_s=7.4), dict(id='b', dur_s=7.4)], ['x', 'y'], 'outro', 'sequence', srv)
    assert 'ending' in srv.prompt and '7-second' in srv.prompt and 'Candidates: 2' in srv.prompt and 'little planet' in srv.prompt


def test_steadiness_is_the_mean_shake_in_the_window_and_neutral_where_there_is_none():
    tm = np.arange(0.0, 10.0); shake = np.array([0.0] * 5 + [45.0] * 5)
    assert B._steadiness(tm, shake, 0, 4) == 1.0 and B._steadiness(tm, shake, 5, 9) == 0.0 and B._steadiness(tm, shake, 3, 6) == 0.5
    assert B._steadiness(tm, shake, 20, 25) == 0.5 and B._steadiness(np.array([]), np.array([]), 0, 5) == 0.5      # no reading in the window: neither steady nor shaky
    assert B._steadiness(tm, np.where(tm == 0, np.nan, 0.0), 0, 2) == 1.0                                            # a missing second is skipped, not counted


def test_a_window_past_the_end_of_the_motion_series_gives_no_warning(make_project, recwarn):
    B.candidates(_race(make_project, dur=5.0).folder)
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]
