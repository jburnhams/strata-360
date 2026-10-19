"""The cold open (edit/cold_open.py): the project's own range, windows that keep whole lines, the choice of the best moment, the files the film reads and the `coldopen` command."""
import argparse, json

import numpy as np
import pytest

from strata360.edit import cold_open as CO


def test_values_are_ranked_in_the_projects_own_range():
    a, b = CO.fit_range([[0.1, 0.2, np.nan], [0.3, 0.2]])
    assert a.tolist() == [0.0, pytest.approx(1 / 3), 0.0] and b.tolist() == [1.0, pytest.approx(1 / 3)]       # ties take the lowest of their ranks; NaN is the bottom
    assert [x.tolist() for x in CO.fit_range([[0.4, 0.4], [0.4]])] == [[0.5, 0.5], [0.5]]                    # nothing to tell apart: the middle
    assert CO.fit_range([]) == []


def test_a_window_grows_to_take_whole_lines():
    lines = [(4.0, 7.0, None), (9.5, 12.0, None)]
    assert CO.whole_lines(5.0, 11.0, lines, 30.0) == (3.75, 12.25)                                          # both edges were inside a line
    assert CO.whole_lines(0.0, 3.0, lines, 30.0) == (0.0, 3.0)                                              # nothing said across an edge: unchanged
    assert CO.whole_lines(5.0, 11.0, lines, 30.0, max_s=8.0) is None                                        # too long once grown
    assert CO.whole_lines(10.0, 13.0, lines, 12.0) is None                                                  # would run off the clip
    assert CO.whole_lines(6.0, 8.0, [(4.0, 7.0, None), (3.0, 4.5, None)], 30.0) == (2.75, 8.0)              # a line taken in can reach into another


def sig(clip, pos, n=60, excite=None, **kw):
    t = np.arange(n) + 0.5; base = dict(clip=clip, pos=pos, dur=float(n), t=t, excite=np.zeros(n) if excite is None else excite, energy=np.full(n, 0.3), scenery=np.full(n, 0.5), you=np.zeros(n), steady=np.full(n, 0.8), people=np.zeros(n), usable=np.ones(n, bool), lines=[])
    base.update(kw); return base


def loud(n, a, b, v=0.9):
    x = np.zeros(n); x[a:b] = v; return x


def test_the_loudest_moment_late_in_the_race_wins():
    cs = CO.candidates([sig('A', 0.0, excite=loud(60, 10, 16, 1.0)), sig('B', 0.5), sig('C', 1.0, excite=loud(60, 40, 46))])
    best = cs[0]; assert best['clip'] == 'C' and 37.0 <= best['clip_start_s'] <= 40.0 and best['dur_s'] == CO.COLD_S and best['id'] == 'cold-0' and best['variant_seed'] == 2000
    assert 'A' not in {c['clip'] for c in cs}                                                                # the start of the race is where the story begins anyway
    assert best['parts']['excite'] >= 0.6 and 'excite' in best['why'] and '100% of the way' in best['why'] and best['technique'] == 'push_in' and best['speech'] is False
    assert [c['score'] for c in cs] == sorted((c['score'] for c in cs), reverse=True)


def test_early_clips_are_used_when_there_is_nothing_else():
    cs = CO.candidates([sig('A', 0.0, excite=loud(60, 10, 16))]); assert cs and cs[0]['clip'] == 'A'
    assert CO.candidates([]) == [] and CO.candidates([sig('A', 0.5, n=0)]) == []


def test_unusable_shaky_and_never_use_footage_is_left_out():
    n = 60; ex = loud(n, 20, 26, 1.0)
    unusable = np.ones(n, bool); unusable[22] = False
    covers = lambda c, x: c['clip_start_s'] <= x < c['clip_start_s'] + c['dur_s']
    got = CO.candidates([sig('A', 1.0, excite=ex, usable=unusable)], per=10, per_clip=10, gap=0.5); assert got and not any(covers(c, 22.5) for c in got)
    shaky = np.full(n, 0.8); shaky[23] = 0.05
    got = CO.candidates([sig('A', 1.0, excite=ex, steady=shaky)], per=10, per_clip=10, gap=0.5); assert got and not any(covers(c, 23.5) for c in got)
    got = CO.candidates([sig('A', 1.0, excite=ex, lines=[(21.0, 23.0, 'never')])], per=10, per_clip=10, gap=0.5)
    assert got and all(c['clip_start_s'] + c['dur_s'] <= 21.0 or c['clip_start_s'] >= 23.0 for c in got)


def test_words_marked_must_use_lift_a_moment_and_are_kept_whole():
    plain = CO.candidates([sig('A', 1.0, excite=loud(60, 5, 11)), sig('B', 1.0, lines=[(33.0, 37.5, None)])], per=10)
    cs = CO.candidates([sig('A', 1.0, excite=loud(60, 5, 11)), sig('B', 1.0, lines=[(33.0, 37.5, 'must')])], per=10)
    top = lambda cs: max((c for c in cs if c['clip'] == 'B'), key=lambda c: c['score'])
    best = top(cs); assert best['score'] > top(plain)['score'] + 0.1 and best['parts']['must'] and best['speech'] and 'must use' in best['why'] and not top(plain)['parts']['must']
    assert best['clip_start_s'] <= 33.0 and best['clip_start_s'] + best['dur_s'] >= 37.5                     # a line is never cut
    assert CO.segment_of(best)['speech'] is True


def test_candidates_are_spread_out():
    cs = CO.candidates([sig('A', 1.0, excite=loud(60, 5, 55)), sig('B', 0.9, excite=loud(60, 5, 55))], per=5)
    by = {}
    for c in cs: by.setdefault(c['clip'], []).append(c['clip_start_s'])
    assert len(cs) == 4 and all(len(v) == CO.PER_CLIP and abs(v[0] - v[1]) >= CO.GAP_S for v in by.values())


def test_the_camera_move_follows_what_is_there():
    you = np.ones(60); assert CO.candidates([sig('A', 1.0, you=you)])[0]['technique'] == 'selfie_close'
    c = CO.candidates([sig('A', 1.0, excite=loud(60, 30, 40), people=np.full(60, 4.0))])[0]; assert c['technique'] == 'pan_reveal' and c['view'] == 'ahead'
    g = CO.segment_of(dict(c, view='you')); assert g['kind'] == 'you' and g['role'] == 'cold_open' and g['film_start_s'] == 0.0 and g['id'] == f"A@cold.{c['id']}" and g['speech'] is False


# ---- a project on disk: the signals read from the clip folders, the file the film reads and the command

def motion(n):
    return dict(duration_s=float(n), series=dict(t=[float(i) for i in range(n)], shake_dps=[4.0] * n, ang_speed_dps=[20.0] * n, acc_energy=[0.3] * n))


def events(n, a, b, v=0.9):
    return dict(windows=[dict(t0=float(s), t1=float(s + 6), cats=dict(cheering=v if a <= s < b else 0.05)) for s in range(0, n - 5, 3)])


def build(make_project, n=60):
    p = make_project('race', config=True)
    for i, (cid, ev) in enumerate((('CAM_0001_D', None), ('CAM_0002_D', events(n, 30, 36)), ('CAM_0003_D', events(n, 9, 15, 0.3)))):
        files = dict(motion=motion(n), candidates=dict(spans=[dict(start_s=0.0, end_s=float(n))]))
        if ev: files['audio_events'] = ev
        p.add_clip(cid, start_utc=f'2026-02-21T1{i}:00:00+00:00', source_frames=n * 30, **files)
    p.write_json('clips/CAM_0002_D/transcript.json', dict(segments=[dict(t0=33.5, t1=36.0, text='we made it', lang='en', words=[])]))
    return p


def test_signals_are_read_from_the_clip_folders(make_project):
    p = build(make_project); s = CO.signals(p.folder)
    assert [x['clip'] for x in s] == ['CAM_0001_D', 'CAM_0002_D', 'CAM_0003_D'] and [x['pos'] for x in s] == [0.0, 0.5, 1.0]
    b = s[1]; assert b['dur'] == 60.0 and b['usable'].all() and b['excite'][32] > 0.4 and b['excite'][5] == pytest.approx(0.05) and not s[0]['excite'].any()
    assert len(b['lines']) == 1 and b['lines'][0][2] is None and b['lines'][0][1] > 35.0


def test_a_clip_that_cannot_be_read_has_no_signals(tmp_path):
    assert CO.clip_signals(str(tmp_path), 'X', 0.5) is None


def test_without_candidates_usable_comes_from_the_picture(make_project):
    p = make_project('race', config=True); p.add_clip('CAM_0001_D', source_frames=600, motion=motion(20))
    s = CO.signals(p.folder); assert len(s) == 1 and s[0]['usable'].all()


def test_run_chooses_the_best_and_the_film_reads_it(make_project, monkeypatch):
    p = build(make_project); doc = CO.run(p.folder, log=lambda *a: None)
    best = doc['candidates'][0]; assert doc['chosen'] == best['id'] and doc['by'] == 'score' and best['clip'] == 'CAM_0002_D'
    assert best['clip_start_s'] + best['dur_s'] >= 36.0 and best['speech']                                    # 'we made it' is kept whole
    assert p.read_json('cold_open/cold_open.json')['chosen'] == best['id'] and CO.for_film(p.folder) == best
    monkeypatch.setenv('STRATA_COLD_OPEN', '0'); assert CO.for_film(p.folder) is None


def test_your_choice_is_kept_when_it_is_found_again(make_project):
    p = build(make_project); doc = CO.run(p.folder, log=lambda *a: None); other = doc['candidates'][1]
    assert CO.choose(p.folder, other['id'])['by'] == 'you'
    again = CO.run(p.folder, log=lambda *a: None); assert again['chosen'] == other['id'] and again['by'] == 'you' and CO.for_film(p.folder)['clip_start_s'] == other['clip_start_s']
    CO.choose(p.folder, 'none'); assert CO.for_film(p.folder) is None and CO.run(p.folder, log=lambda *a: None)['chosen'] == 'none'
    with pytest.raises(ValueError, match='no candidate cold-99'): CO.choose(p.folder, 'cold-99')


def test_a_choice_that_is_gone_falls_back_to_the_best(make_project):
    p = build(make_project); CO.run(p.folder, log=lambda *a: None); doc = p.read_json('cold_open/cold_open.json')
    doc.update(chosen='cold-x', by='you'); doc['candidates'].append(dict(id='cold-x', clip='gone', clip_start_s=1.0)); p.write_json('cold_open/cold_open.json', doc)
    again = CO.run(p.folder, log=lambda *a: None); assert again['chosen'] == again['candidates'][0]['id'] and again['by'] == 'score'


def test_nothing_to_choose_from(make_project):
    p = make_project('race', config=True)
    with pytest.raises(ValueError, match='run `strata360 coldopen'): CO.choose(p.folder, 'cold-0')
    assert CO.for_film(p.folder) is None
    doc = CO.run(p.folder, log=lambda *a: None); assert doc['candidates'] == [] and doc['chosen'] is None and CO.for_film(p.folder) is None


def test_previews_are_rendered_on_request_and_a_failure_is_recorded(make_project, monkeypatch):
    p = build(make_project); calls = []

    def fake(folder, c, d, lib=None):
        calls.append(c['id'])
        if c['id'] == 'cold-1': raise RuntimeError('no proxy')
        return f'{d}/{c["id"]}.mp4', f'{d}/{c["id"]}.jpg'
    monkeypatch.setattr(CO, 'render_preview', fake); logs = []
    doc = CO.run(p.folder, render=True, log=logs.append); cs = {c['id']: c for c in doc['candidates']}
    assert calls == list(cs) and cs['cold-0']['video'] == 'cold-0.mp4' and cs['cold-0']['picture'] == 'cold-0.jpg' and cs['cold-1']['error'] == 'RuntimeError: no proxy' and logs


def test_the_command_lists_and_picks(make_project, capsys):
    from strata360 import cli
    p = build(make_project); cli.cmd_coldopen(argparse.Namespace(name=p.folder, per=3, pick=None, render=False)); out = capsys.readouterr().out
    assert out.count('cold-') >= 3 and '* cold-0' in out and 'chosen: cold-0' in out and out.strip().endswith('cold_open.json')
    cli.cmd_coldopen(argparse.Namespace(name=p.folder, per=3, pick='cold-1', render=False)); assert 'chosen: cold-1 (yours)' in capsys.readouterr().out
    with pytest.raises(SystemExit, match='no candidate'): cli.cmd_coldopen(argparse.Namespace(name=p.folder, per=3, pick='zzz', render=False))
    assert json.load(open(p.path('cold_open', 'cold_open.json')))['chosen'] == 'cold-1'
