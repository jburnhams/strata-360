"""A narration line recorded again re-fits only its block (V6, P5-35): every window outside the block keeps its footage and technique, the cut before it stays, the cut after it moves by whole beats."""
import json, math, os

import pytest
from strata360.edit import beat_sync as BS, line_refit as LR, project as PJ, voiceover as VO
from strata360.pipeline import config

C1 = 'CAM_20260222100000_0001_D'; C2 = 'CAM_20260222100100_0002_D'; C3 = 'CAM_20260222100200_0003_D'
LEN = {C1: 120.0, C2: 120.0, C3: 120.0}; RANGE = {'t': (1.0, 8.0)}; BEAT = 0.5


def seg(i, fs, d, clip, cs, item, role, **kw):
    return dict(id=f'w{i}', index=i, film_start_s=fs, dur_s=d, beats=int(round(d / BEAT)), clip=clip, clip_start_s=cs, in_s=0.0, technique='t', item=item, role=role, utc_start='2026-02-22T10:00:10.000Z', utc_end='2026-02-22T10:00:12.000Z', **kw)


def plan(c2_after=40.0, c2_first=20.0):
    """Six shots: the runner (item 0), narration over two shots of C2 (item 1), b-roll (item 2), more narration (item 3), the runner again (item 4)."""
    return [seg(0, 0.0, 4.0, C1, 10.0, 0, 'clip'), seg(1, 4.0, 2.0, C2, c2_first, 1, 'vo'), seg(2, 6.0, 2.5, C2, c2_first + 2.0, 1, 'vo'), seg(3, 8.5, 3.0, C3, 5.0, 2, 'broll'),
            seg(4, 11.5, 3.0, C2, c2_after, 3, 'vo'), seg(5, 14.5, 2.5, C1, 30.0, 4, 'clip')]


LINES = [dict(seg='nA', text='first line', item=1, clip=C2, film_start_s=4.0, seconds=4.5, speak_s=3.8, estimated=False), dict(seg='nB', text='second line', item=3, clip=C2, film_start_s=11.5, seconds=3.0, speak_s=2.4, estimated=False)]


def window(g): return (g['id'], g['clip'], g['clip_start_s'], g['dur_s'], g['technique'])


def footage_overlaps(segs):
    for c in {g['clip'] for g in segs}:
        ws = sorted((g['clip_start_s'], g['clip_start_s'] + g['dur_s']) for g in segs if g['clip'] == c)
        if any(b[0] < a[1] - 1e-6 for a, b in zip(ws, ws[1:])): return True
    return False


def test_a_longer_take_grows_only_its_block_and_moves_the_cut_after_it():
    old = plan(); r = LR.refit(old, LINES, 'nA', 4.9, BEAT, LEN, RANGE); new = r['segments']
    assert r['beats'] == 2 and r['delta_s'] == pytest.approx(1.0)                         # 0.2 + 4.9 + 0.3 s is 11 beats; it was 9
    for i in (0, 3, 4, 5): assert window(new[i]) == window(old[i])                       # every window outside the block keeps its footage and technique
    assert new[1]['film_start_s'] == old[1]['film_start_s']                               # the cut before the block stays
    for i in (3, 4, 5): assert new[i]['film_start_s'] == pytest.approx(old[i]['film_start_s'] + 1.0)
    assert new[2]['dur_s'] == pytest.approx(3.5) and new[2]['clip_start_s'] == old[2]['clip_start_s'] and r['changed'] == ['w2']   # the last window ran on in its clip
    assert all(abs(a['film_start_s'] + a['dur_s'] - b['film_start_s']) < 1e-6 for a, b in zip(new, new[1:])) and not footage_overlaps(new)
    assert old[2]['dur_s'] == 2.5 and r['warnings'] == []                                 # (the input is not changed)


def test_the_lines_after_the_block_move_with_it_and_the_line_takes_its_new_length():
    r = LR.refit(plan(), LINES, 'nA', 4.9, BEAT, LEN, RANGE); a, b = r['lines']
    assert (a['film_start_s'], a['speak_s'], a['seconds']) == (4.0, 4.9, 5.5) and b['film_start_s'] == pytest.approx(12.5) and b['speak_s'] == 2.4


def test_a_shorter_take_shrinks_its_block_never_below_a_techniques_shortest():
    old = plan(); r = LR.refit(old, LINES, 'nA', 2.0, BEAT, LEN, RANGE); new = r['segments']             # 2.5 s is 5 beats: 4 fewer
    assert r['beats'] == -4 and r['delta_s'] == pytest.approx(-2.0)
    assert new[2]['dur_s'] == pytest.approx(1.0) and new[1]['dur_s'] == pytest.approx(1.5) and sorted(r['changed']) == ['w1', 'w2']
    for i in (0, 3, 4, 5): assert window(new[i]) == window(old[i])
    assert new[3]['film_start_s'] == pytest.approx(6.5)


def test_a_take_with_the_same_number_of_beats_changes_no_window():
    old = plan(); r = LR.refit(old, LINES, 'nA', 3.9, BEAT, LEN, RANGE)
    assert r['beats'] == 0 and r['delta_s'] == 0 and r['changed'] == [] and [window(g) for g in r['segments']] == [window(g) for g in old]
    assert r['lines'][0]['speak_s'] == 3.9


def test_the_block_grows_only_as_far_as_its_free_footage_and_says_so():
    old = plan(c2_after=5.0, c2_first=0.0); r = LR.refit(old, LINES, 'nA', 4.9, BEAT, LEN, RANGE); new = r['segments']   # the C2 footage after the block is in item 3's shot from 5 s
    assert r['beats'] == 1 and r['delta_s'] == pytest.approx(0.5) and not footage_overlaps(new)
    assert len(r['warnings']) == 1 and 'item 2: the new take needs 5.5 s' in r['warnings'][0] and 'record it again shorter' in r['warnings'][0]


def test_a_window_that_cannot_run_on_starts_earlier_in_its_clip():
    old = plan(); old[2]['clip_start_s'] = 60.0; old[4]['clip_start_s'] = 62.5; r = LR.refit(old, LINES, 'nA', 4.9, BEAT, LEN, RANGE); g = r['segments'][2]
    assert (g['clip_start_s'], g['dur_s'], g['film_start_s']) == (59.0, 3.5, 6.0) and g['utc_start'] == '2026-02-22T10:00:09.000Z' and not footage_overlaps(r['segments'])


def test_with_a_beat_grid_the_blocks_end_lands_on_a_real_beat_and_later_cuts_off_it_are_reported():
    beats = [0.5 * i + 0.03 * math.sin(i / 3.0) for i in range(80)]; grid = BS.Grid(beats, beats[::4]); old = plan()
    r = LR.refit(old, LINES, 'nA', 4.9, BEAT, LEN, RANGE, grid=grid, seek=0.0); new = r['segments']
    end = new[3]['film_start_s']; assert min(abs(end - b) for b in beats) < 1e-4 and r['beats'] == 2
    for i in (0, 3, 4, 5): assert window(new[i]) == window(old[i])
    off = LR.off_beat(new, new[-1]['film_start_s'] + new[-1]['dur_s'], grid, 0.0, [dict(cut=1, film_s=4.0, off_ms=12.0, why='the words in clip 0001 end there')], r['last'] + 1, 'moved')
    assert off[0] == dict(cut=1, film_s=4.0, off_ms=12.0, why='the words in clip 0001 end there')                            # a cut before the block keeps its entry
    assert all(o['cut'] > 3 and o['why'] == 'moved' and o['off_ms'] >= 1.0 for o in off[1:]) and 3 not in [o['cut'] for o in off]


def test_narration_over_a_generated_clip_cannot_be_refitted_here():
    old = plan(); old[1]['synthetic'] = 'synthetic/film/G3.mp4'; assert LR.refit(old, LINES, 'nA', 4.9, BEAT, LEN, RANGE) is None


def test_an_unknown_line_is_an_error():
    with pytest.raises(KeyError, match='nZ'): LR.refit(plan(), LINES, 'nZ', 4.0, BEAT, LEN, RANGE)


@pytest.fixture
def script_project(tmp_path, monkeypatch):
    f = str(tmp_path); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'script2'))
    edit = PJ.load(f); edit['plan'] = dict(source='script', script='draft-1', film=dict(length_s=17.0, beats=34, bpm=120.0, bar_beats=4), segments=plan(), warnings=['keep me'])
    PJ.save(f, edit); json.dump(dict(draft='draft-1', lines=LINES), open(os.path.join(rd, VO.SCRIPT2_LINES), 'w'))
    monkeypatch.setattr(PJ, 'load_clips', lambda folder: ([dict(id=c, duration_s=v) for c, v in LEN.items()], []))
    return f


def test_refit_project_saves_the_refitted_plan_and_lines(script_project, monkeypatch):
    monkeypatch.setattr(LR, 'measure', lambda folder, seg, text: 4.9)
    r = LR.refit_project(script_project, 'nA', log=lambda *_: None)
    assert r['mode'] == 'refit' and r['item'] == 1 and r['delta_s'] == pytest.approx(1.0)
    p = PJ.load(script_project)['plan']; assert p['film']['length_s'] == 18.0 and p['film']['beats'] == 36 and p['refit']['seg'] == 'nA' and p['warnings'] == ['keep me']
    assert [window(g) for g in p['segments']][3:] == [window(g) for g in plan()][3:]
    d = json.load(open(os.path.join(config.race_dir(script_project), VO.SCRIPT2_LINES))); assert d['lines'][0]['speak_s'] == 4.9 and d['lines'][1]['film_start_s'] == 12.5 and d['draft'] == 'draft-1'


def test_refit_project_does_nothing_without_a_script_plan_or_the_line(script_project, monkeypatch):
    monkeypatch.setattr(LR, 'measure', lambda folder, seg, text: 4.9)
    assert LR.refit_project(script_project, 'nZ')['mode'] == 'none'
    monkeypatch.setattr(LR, 'measure', lambda folder, seg, text: None); assert LR.refit_project(script_project, 'nA')['reason'] == 'no voice to measure the line with'
    e = PJ.load(script_project); e['plan']['source'] = 'beats'; PJ.save(script_project, e); assert LR.refit_project(script_project, 'nA')['mode'] == 'none'


def test_refit_project_plans_again_when_the_line_is_over_a_generated_clip(script_project, monkeypatch):
    e = PJ.load(script_project); e['plan']['segments'][1]['synthetic'] = 'x.mp4'; PJ.save(script_project, e); calls = []
    monkeypatch.setattr(LR, 'measure', lambda folder, seg, text: 4.9); monkeypatch.setattr(PJ, 'plan_from_script', lambda folder, name, log: calls.append(name))
    assert LR.refit_project(script_project, 'nA', log=lambda *_: None)['mode'] == 'replan' and calls == ['draft-1']


def test_measure_uses_the_recording_when_it_is_the_take_in_use(tmp_path, monkeypatch):
    f = str(tmp_path); rec = tmp_path / 'take.wav'; rec.write_bytes(b'x')
    monkeypatch.setattr(VO, 'recorded_path', lambda folder, seg: str(rec)); monkeypatch.setattr(VO, 'speech_span', lambda p: (0.25, 3.75))
    assert LR.measure(f, 'nA', 'first line') == 3.5
    monkeypatch.setattr(VO, 'recorded_path', lambda folder, seg: str(tmp_path / 'none.wav')); monkeypatch.setattr(VO, 'line_durations', lambda folder, lines, log: {'nA': 2.0})
    assert LR.measure(f, 'nA', 'first line') == 2.0


def test_the_timeline_draws_each_line_where_its_speech_starts_and_the_plans_own_beats_without_music(script_project):
    t = LR.timeline(script_project)
    assert [(l['seg'], l['item'], l['start_s'], l['speak_s'], l['room_s'], l['source'], l['has_recording']) for l in t['lines']] == [('nA', 1, 4.12, 3.8, 4.5, 'synth', False), ('nB', 3, 11.62, 2.4, 3.0, 'synth', False)]
    assert t['synced'] is False and t['beats'][:3] == [0.0, 0.5, 1.0] and t['beats'][-1] == 17.0 and t['bars'][:2] == [0.0, 2.0] and t['length_s'] == 17.0


def test_the_timeline_takes_the_built_lengths_and_the_real_beats_when_the_plan_was_synced(script_project, monkeypatch):
    e = PJ.load(script_project); e['plan']['beat_sync'] = dict(seek_s=0.0, delay_s=0.25, off_beat=[]); PJ.save(script_project, e)
    monkeypatch.setattr(VO, 'load_timings', lambda folder: dict(script='script2-x', lines=[dict(seg='nA', played_s=4.4, fit='over', overrun_s=0.3)]))
    monkeypatch.setattr(VO, 'newest_script', lambda folder: 'script2-x')
    monkeypatch.setattr(PJ, 'music_info', lambda folder, settings: dict(bar_beats=4)); monkeypatch.setattr(PJ, 'beat_list', lambda folder, settings, mus: dict(beats=[0.0, 0.5, 1.0, 1.5, 2.0], downbeats=[0.0, 2.0]))
    t = LR.timeline(script_project)
    assert t['lines'][0]['speak_s'] == 4.4 and t['lines'][0]['fit'] == 'over' and t['lines'][0]['overrun_s'] == 0.3 and t['lines'][1]['fit'] is None
    assert t['synced'] is True and t['beats'] == [0.25, 0.75, 1.25, 1.75, 2.25] and t['bars'] == [0.25, 2.25]          # the music starts 0.25 s into the film


def test_the_timeline_is_empty_without_a_plan(tmp_path): assert LR.timeline(str(tmp_path)) == dict(lines=[], beats=[], bars=[], synced=False, length_s=0.0)
