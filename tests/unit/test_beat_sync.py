"""Cuts on the music's real beats (V5): every cut on a beat of a drifting track unless a rule forbids it, the runner's words and the narration's lead-in kept, footage never shown twice, the music's start chosen."""
import math

import pytest
from strata360.edit import beat_sync as BS, project as PJ

C1 = 'CAM_20260222100000_0001_D'; C2 = 'CAM_20260222100100_0002_D'; C3 = 'CAM_20260222100200_0003_D'
LEN = {C1: 120.0, C2: 120.0, C3: 120.0}


def seg(fs, d, clip=C1, cs=None, role='broll', tech='t', item=None, **kw):
    return dict(film_start_s=fs, dur_s=d, clip=clip, clip_start_s=fs + 10.0 if cs is None else cs, in_s=0.0, role=role, technique=tech, item=item, utc_start='2026-02-22T10:00:10.000Z', **kw)


def drifting(n=80, wobble=0.03, phase=0.0):
    """A track at 120 bpm whose beats wander up to `wobble` s from the grid; every fourth beat a bar line."""
    b = [phase + 0.5 * i + wobble * math.sin(i / 5.0) for i in range(n)]; return b, b[::4]


def clip_time(g, t): return g['clip_start_s'] + (t - g['film_start_s'])


def run(segs, beats, downs, seek=0.0, lines=(), **kw): return BS.sync(segs, beats, downs, seek, lines, clip_len=LEN, **kw)


def shots():
    return [seg(0.0, 2.0, C1, item=0), seg(2.0, 2.5, C2, cs=40.0, item=1), seg(4.5, 2.5, C2, cs=42.5, item=1), seg(7.0, 3.0, C3, cs=5.0, item=2), seg(10.0, 2.0, C1, cs=60.0, item=3)]


def test_every_cut_lands_on_a_real_beat_of_a_drifting_track_and_every_frame_keeps_its_film_time():
    b, d = drifting(); segs = shots(); out, rep = run(segs, b, d)
    assert rep['off_beat'] == [] and rep['on_bar'] + rep['on_beat'] == len(segs)
    film_beats = [x - rep['seek_s'] for x in b]
    for g in out[1:] + [dict(film_start_s=rep['length_s'])]: assert min(abs(g['film_start_s'] - x) for x in film_beats) < 1e-3          # (the end too)
    for old, new in zip(segs, out):                                                                                             # a frame inside both versions of a shot shows the same moment of its clip
        t = max(old['film_start_s'], new['film_start_s']) + 0.05; assert clip_time(new, t) == pytest.approx(clip_time(old, t), abs=1e-6)
    assert all(abs(a['film_start_s'] + a['dur_s'] - b['film_start_s']) < 1e-6 for a, b in zip(out, out[1:]))                    # still end to end


def test_the_music_start_is_chosen_so_cuts_on_a_steady_grid_need_not_move():
    b = [0.037 + 0.5 * i for i in range(60)]; out, rep = run(shots(), b, b[::4])
    assert rep['shift_s'] == pytest.approx(0.037, abs=0.003) and rep['seek_s'] == pytest.approx(0.037, abs=0.003) and rep['moved_max_ms'] <= 3.0 and rep['delay_s'] == 0.0


def test_music_that_must_start_after_the_film_does_is_delayed():
    b = [0.5 * i - 0.04 for i in range(1, 60)]; _, rep = run(shots(), b, b[::4])
    assert rep['delay_s'] == pytest.approx(0.04, abs=0.003) and rep['seek_s'] == 0.0


def test_a_cut_before_the_runners_words_only_moves_away_from_them_and_is_reported_when_it_cannot_reach_a_beat():
    segs = [seg(0.0, 2.0, C1, item=0), seg(2.0, 3.0, C2, cs=40.0, role='clip', item=1, speech=True, voice_span=[0.0, 2.6]), seg(5.0, 2.0, C3, cs=5.0, item=2)]
    late = [0.0, 0.5, 1.0, 1.5, 2.03, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]                     # the beat is 30 ms after the cut: moving there would cut 30 ms off the words
    out, rep = run(segs, late, late[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[1]['film_start_s'] <= 2.0 + 1e-9 and len(rep['off_beat']) == 1
    o = rep['off_beat'][0]; assert o['cut'] == 1 and o['off_ms'] == pytest.approx(30.0, abs=0.5) and 'words in clip 0002 start there' in o['why']
    words = (2.0, 2.0 + 2.6); assert out[1]['film_start_s'] <= words[0] and out[1]['film_start_s'] + out[1]['dur_s'] >= words[1] - 1e-9
    early = [x - 0.06 if abs(x - 2.03) < 1e-9 else x for x in late]                                              # a beat 30 ms BEFORE the cut: moving outwards is fine
    out, rep = run(segs, early, early[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[1]['film_start_s'] == pytest.approx(1.97) and out[1]['voice_span'][0] == pytest.approx(0.03) and rep['off_beat'] == []


def test_a_cut_after_the_runners_words_never_moves_into_them():
    segs = [seg(0.0, 3.0, C2, cs=40.0, role='clip', item=0, voice_span=[0.2, 3.0]), seg(3.0, 2.0, C3, cs=5.0, item=1), seg(5.0, 2.0, C1, cs=80.0, item=2)]
    b = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 2.96, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]; out, rep = run(segs, b, b[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[0]['dur_s'] >= 3.0 - 1e-9 and rep['off_beat'][0]['cut'] == 1 and 'end there' in rep['off_beat'][0]['why']


def test_a_cut_before_a_narration_line_keeps_its_lead_in():
    b = [0.0, 0.5, 1.0, 1.5, 2.04, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]; segs = [seg(0.0, 2.0, C1, item=0), seg(2.0, 3.0, C2, cs=40.0, role='vo', item=1), seg(5.0, 2.0, C3, cs=5.0, item=2)]
    out, rep = run(segs, b, b[::4], lines=[(2.12, 4.5, 'A line about the climb')], settings=BS.SyncSettings(shift_beats=0.0, lead_s=0.12))
    assert out[1]['film_start_s'] <= 2.0 + 1e-9 and 'keeps its lead-in' in rep['off_beat'][0]['why'] and 'A line about the climb' in rep['off_beat'][0]['why']
    out, rep = run(segs, b, b[::4], lines=[(2.2, 4.5, 'x')], settings=BS.SyncSettings(shift_beats=0.0, lead_s=0.12))                # with room for the lead-in the cut goes onto the beat
    assert out[1]['film_start_s'] == pytest.approx(2.04) and rep['off_beat'] == []


def test_footage_another_shot_shows_is_never_shown_again():
    segs = [seg(0.0, 2.0, C1, cs=10.0, item=0), seg(2.0, 2.0, C2, cs=40.0, item=1), seg(4.0, 2.0, C1, cs=12.0, item=2), seg(6.0, 2.0, C3, cs=5.0, item=3)]
    b = [0.0, 0.5, 1.0, 1.5, 2.04, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]; out, rep = run(segs, b, b[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[0]['clip_start_s'] + out[0]['dur_s'] <= 12.0 + 1e-9 and 'in another shot' in rep['off_beat'][0]['why']


def test_two_shots_of_one_clip_back_to_back_share_the_cut_freely():
    segs = [seg(0.0, 2.0, C1, cs=10.0, item=0), seg(2.0, 2.0, C1, cs=12.0, item=0), seg(4.0, 2.0, C3, cs=5.0, item=1)]
    b = [0.0, 0.5, 1.0, 1.5, 2.04, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5]; out, rep = run(segs, b, b[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[1]['film_start_s'] == pytest.approx(2.04) and out[0]['clip_start_s'] + out[0]['dur_s'] == pytest.approx(out[1]['clip_start_s']) and rep['off_beat'] == []


def test_the_film_never_ends_before_the_last_narration():
    segs = [seg(0.0, 6.0, C1, item=0), seg(6.0, 6.0, C2, cs=40.0, role='vo', item=1)]
    b = [0.5 * i for i in range(24)] + [11.8, 12.24, 12.7]; b = sorted(set(round(x, 3) for x in b if not 11.9 < x < 12.2))
    out, rep = run(segs, b, b[::4], lines=[(6.12, 11.9, 'the last line')], settings=BS.SyncSettings(shift_beats=0.0, end_pad_s=0.3))
    assert rep['length_s'] >= 11.9 + 0.3 - 1e-9 and rep['length_s'] == pytest.approx(12.24)


def test_a_generated_clip_plays_at_most_a_little_faster_or_slower_and_keeps_its_own_start_and_race_time():
    segs = [seg(0.0, 2.0, C1, item=0), dict(seg(2.0, 1.0, 'G03', cs=0.0, item=1), synthetic='/x/G03.mp4', utc_start='2026-02-22T03:00:00.000Z', utc_end='2026-02-22T04:00:00.000Z'), seg(3.0, 2.0, C3, cs=5.0, item=2)]
    b = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.2, 3.5, 4.0, 4.5, 5.0, 5.5]; out, rep = run(segs, b, b[::4], settings=BS.SyncSettings(shift_beats=0.0, stretch=0.08))
    g = out[1]; assert g['dur_s'] <= 1.08 + 1e-9 and g['clip_start_s'] == 0.0 and g['utc_start'] == '2026-02-22T03:00:00.000Z' and g['utc_end'] == '2026-02-22T04:00:00.000Z'
    assert any(o['cut'] == 2 for o in rep['off_beat'])


def test_a_shot_does_not_get_further_from_its_techniques_length():
    segs = [seg(0.0, 2.0, C1, item=0, tech='short'), seg(2.0, 2.0, C2, cs=40.0, item=1), seg(4.0, 2.0, C3, cs=5.0, item=2)]
    b = [0.0, 0.5, 1.0, 1.5, 1.96, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]; out, rep = run(segs, b, b[::4], dur_range={'short': (2.0, 4.0)}, settings=BS.SyncSettings(shift_beats=0.0))
    assert out[0]['dur_s'] >= 2.0 - 1e-9 and any(o['cut'] == 1 and 'lengths' in o['why'] for o in rep['off_beat'])


def test_the_same_plan_and_track_give_the_same_cuts():
    b, d = drifting(wobble=0.04); assert run(shots(), b, d) == run(shots(), b, d)


def test_cuts_after_the_music_ends_stay_where_they_are():
    b = [0.5 * i for i in range(10)]; out, rep = run(shots(), b, b[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert rep['after_music'] >= 2 and out[-1]['film_start_s'] == 10.0


def test_a_built_tracks_beats_come_from_its_bar_lines():
    assert BS.from_downbeats([0.0, 2.0, 4.2], 4) == [0.0, 0.5, 1.0, 1.5, 2.0, 2.55, 3.1, 3.65, 4.2, 4.75, 5.3, 5.85, 6.4]


def test_the_project_step_records_why_the_beats_are_missing_and_keeps_the_plan(monkeypatch):
    segs = shots(); warn = []
    def broken(*a): raise RuntimeError('the track is too short')
    monkeypatch.setattr(PJ, 'beat_list', broken)
    out, rep = PJ.beat_sync('f', {}, dict(offset_s=0.0), segs, [], [], {}, warn); assert out is segs and rep is None and 'too short' in warn[0]
    b, d = drifting(); monkeypatch.setattr(PJ, 'beat_list', lambda *a: dict(beats=b, downbeats=d))
    out, rep = PJ.beat_sync('f', {}, dict(offset_s=0.0), segs, [dict(film_start_s=2.0, speak_s=1.5, text='x')], [dict(id=c, duration_s=120.0) for c in LEN], {}, warn)
    assert rep['cuts'] == len(segs) and 'warnings' not in rep and out[0]['film_start_s'] == 0.0
    assert PJ.beat_sync('f', {}, None, segs, [], [], {}, warn) == (segs, None)


def test_a_cut_inside_one_continuous_talking_run_moves_freely_because_the_sound_plays_through_it():
    segs = [seg(0.0, 2.0, C1, item=0), seg(2.0, 3.0, C2, cs=40.0, role='clip', item=1, voice_span=[0.0, 3.0]), seg(5.0, 3.0, C2, cs=43.0, role='clip', item=1, voice_span=[0.0, 2.8]), seg(8.0, 2.0, C3, cs=5.0, item=2)]
    b = [0.5 * i for i in range(10)] + [5.04] + [0.5 * i for i in range(11, 24)]; out, rep = run(segs, b, b[::4], settings=BS.SyncSettings(shift_beats=0.0))
    assert out[2]['film_start_s'] == pytest.approx(5.04) and out[1]['clip_start_s'] + out[1]['dur_s'] == pytest.approx(out[2]['clip_start_s']) and not any(o['cut'] == 2 for o in rep['off_beat'])
