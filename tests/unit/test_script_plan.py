"""The film's plan from the script: windows in script order, dialogue held whole, narration timed by the voice, whole beats, free footage first."""
import pytest
from strata360.edit import script_plan as SPL, chrono as CH, optimise as O, techniques as TQ

LIB = TQ.load()
BPM = 120.0; BEAT = 60.0 / BPM          # 0.5 s


def feats(speech=0.0): return dict(steady=0.8, clear_nadir=0.8, open_ground=0.6, canopy=0.4, subject=0.6, speech=speech, protagonist=0.5, low_obstruction=0.8, resolution=0.8)


def cand(clip, k, a, b, kind='span', q=0.6, speech=0.0):
    return dict(id=f'{clip}#{k}', clip=clip, start_s=a, end_s=b, quality=q, energy=0.5, min_dur=1.0, max_dur=b - a, kind=kind, features=feats(speech))


def clip(n, dur, cands):
    cid = f'CAM_2026022210{n:02d}00_{n:04d}_D'; return dict(id=cid, start_utc=f'2026-02-22T10:{n:02d}:00Z', duration_s=dur, candidates=[dict(c, id=c['id'].replace('X', cid), clip=cid) for c in cands], unusable=[])


def pc(c, lines=()):
    return dict(label=c['id'][-6:-2], clip=c['id'], duration_s=c['duration_s'], usable_s=sum(x['end_s'] - x['start_s'] for x in c['candidates']), usable=[], scene={}, note='', lines=[dict(id=i, t0=a, t1=b, text='x', words=1, lang='en', mark=None) for i, a, b in lines], speech_s=0, speech_words=0)


# clip 0001: 60 s of footage with the runner talking from 20 s to 36 s; clip 0002: 30 s, nothing said
C1 = clip(1, 60.0, [cand('X', 0, 0, 60), cand('X', 1, 20, 36, 'speech', 0.7, 1.0)]); C2 = clip(2, 30.0, [cand('X', 0, 0, 30)])
PACK = dict(race={}, clips=[pc(C1, [('0001.00', 20.5, 25.0), ('0001.01', 26.0, 35.0)]), pc(C2)])
MUSIC = O.Music(bpm=BPM, beats=1, bar_beats=4)
def item(t, clipno, **kw): return dict(type=t, clip=f'{clipno:04d}', **kw)
DRAFT = dict(wpm=150, items=[item('vo', 1, text='A short line to say.'), item('clip', 1, lines=['0001.00', '0001.01']), item('broll', 2, seconds=4.0), item('vo', 2, text='One more thing to say about the day.')])
VOICE = {0: 3.0, 3: 5.2}


def run(draft=DRAFT, voice=VOICE, clips=(C1, C2), pack=PACK):
    return SPL.build(draft, pack, list(clips), LIB, MUSIC, voice, st=CH.Settings(seed=1))


def test_the_plan_follows_the_script_in_order_and_every_window_is_whole_beats():
    r = run(); segs = r['segs']; assert r['roles'][0] == 'vo' and 'clip' in r['roles'] and r['roles'][-1] == 'vo'
    assert [r['piece_of'][i] for i in range(len(segs))] == sorted(r['piece_of'])                                       # pieces in script order
    assert all(abs(s.beats * BEAT - s.dur_s) < 1e-9 and s.beats >= 1 for s in segs) and sum(s.beats for s in segs) == r['beats']
    assert [s.cand.clip[-6:-2] for s in segs][0] == '0001' and segs[-1].cand.clip[-6:-2] == '0002'


def test_dialogue_is_one_window_that_holds_the_whole_padded_span_and_only_dialogue_techniques_are_used():
    r = run()
    segs = [s for s, role in zip(r['segs'], r['roles']) if role == 'clip']; assert len(segs) == 1
    s = segs[0]; a, b = s.clip_start_s, s.clip_start_s + s.dur_s
    assert a <= 20.5 - 0.06 + 1e-6 and b >= 35.0 + 0.12 - 1e-6 and s.tech.dialogue_ok and s.parts['speech']


def test_narration_gets_a_window_as_long_as_the_voice_needs_and_its_line_starts_with_it():
    r = run(); lines = {l['item']: l for l in r['lines']}
    assert set(lines) == {0, 3} and lines[0]['speak_s'] == 3.0 and lines[0]['seconds'] >= 3.0 + SPL.LEAD_S + SPL.TAIL_S - 1e-9 and lines[3]['seconds'] >= 5.2 + 0.5 - 1e-9
    starts = {}; pos = 0
    for sg, k in zip(r['segs'], r['piece_of']): starts.setdefault(r['pieces'][k]['n'], pos * BEAT); pos += sg.beats                 # film time of the first window of each script item
    assert abs(lines[0]['film_start_s'] - starts[0]) < 1e-6 and abs(lines[3]['film_start_s'] - starts[3]) < 1e-6 and starts[3] > starts[0]


def test_narration_and_b_roll_keep_off_the_dialogue_the_script_plays():
    r = run(); dlg = (20.5 - 0.06, 35.0 + 0.12)
    for s, role in zip(r['segs'], r['roles']):
        if role != 'clip' and s.cand.clip[-6:-2] == '0001': assert s.clip_start_s + s.dur_s <= dlg[0] + 0.5 or s.clip_start_s >= dlg[1] - 0.5


def test_a_clip_with_too_little_footage_is_still_planned_with_a_warning():
    small = clip(1, 12.0, [cand('X', 0, 0, 12)]); pack = dict(race={}, clips=[pc(small), pc(C2)])
    draft = dict(wpm=150, items=[item('broll', 1, seconds=8.0), item('broll', 1, seconds=8.0), item('broll', 2, seconds=3.0)])
    r = SPL.build(draft, pack, [small, C2], LIB, MUSIC, {}, st=CH.Settings(seed=1))
    assert sum(1 for role in r['roles'] if role == 'broll') >= 3 and any('not enough free footage' in w for w in r['warnings'])


def test_long_dialogue_is_split_into_contiguous_windows_of_at_most_twenty_seconds():
    long_c = clip(1, 80.0, [cand('X', 0, 0, 80), cand('X', 1, 5, 50, 'speech', 0.7, 1.0)]); pack = dict(race={}, clips=[pc(long_c, [('0001.00', 6.0, 46.0)])])
    r = SPL.build(dict(wpm=150, items=[item('clip', 1, lines=['0001.00'])]), pack, [long_c], LIB, MUSIC, {}, st=CH.Settings(seed=1))
    segs = r['segs']; assert len(segs) >= 3 and all(s.dur_s <= 20.0 + 1e-9 for s in segs)
    assert all(abs((a.clip_start_s + a.dur_s) - b.clip_start_s) < 0.51 for a, b in zip(segs, segs[1:]))


def test_items_for_unknown_clips_are_skipped_and_an_empty_script_is_refused():
    d = dict(wpm=150, items=[item('broll', 9, seconds=4.0), item('broll', 2, seconds=4.0)]); r = SPL.build(d, PACK, [C1, C2], LIB, MUSIC, {}, st=CH.Settings(seed=1))
    assert any('no clip 0009' in w for w in r['warnings']) and len(r['segs']) >= 1
    with pytest.raises(O.Infeasible): SPL.build(dict(wpm=150, items=[item('broll', 9, seconds=4.0)]), PACK, [C1, C2], LIB, MUSIC, {}, st=CH.Settings(seed=1))


def test_missing_voice_lengths_are_estimated_from_the_words():
    r = run(voice={}); l = {x['item']: x for x in r['lines']}; assert l[0]['estimated'] is True and abs(l[0]['speak_s'] - 5 * 60 / 150) < 1e-6


def test_a_narration_line_keeps_its_name_while_its_words_do_not_change():
    assert SPL.seg_id('A', 'Hello there.') == SPL.seg_id('A', ' Hello there. ') and SPL.seg_id('A', 'Hello there.') != SPL.seg_id('B', 'Hello there.') and SPL.seg_id('A', 'Hello.') != SPL.seg_id('A', 'Bye.')


def test_the_same_seed_gives_the_same_plan():
    a, b = run(), run(); assert [(s.cand.id, s.clip_start_s, s.beats, s.tech.id) for s in a['segs']] == [(s.cand.id, s.clip_start_s, s.beats, s.tech.id) for s in b['segs']]


def test_a_window_is_never_shorter_than_the_voice_needs_even_just_under_the_longest_window():
    for speak in (7.3, 7.6, 7.9, 12.0):                                                             # whole beats, the 8 s limit and the lead and tail must not clip the narration
        r = run(voice={0: speak, 3: 2.0}); l = {x['item']: x for x in r['lines']}[0]
        assert l['seconds'] >= speak + SPL.LEAD_S + SPL.TAIL_S - 1e-9, (speak, l['seconds'])
        assert all(s.dur_s <= 8.0 + 1e-9 for s, role in zip(r['segs'], r['roles']) if role == 'vo')


def test_dialogue_just_under_twenty_seconds_still_fits_a_dialogue_technique():
    c = clip(1, 80.0, [cand('X', 0, 0, 80), cand('X', 1, 5, 60, 'speech', 0.7, 1.0)]); pack = dict(race={}, clips=[pc(c, [('0001.00', 6.0, 25.85)])])        # 19.85 + pads = 20.03 s: 41 beats of 0.5 s would be 20.5 s
    r = SPL.build(dict(wpm=150, items=[item('clip', 1, lines=['0001.00'])]), pack, [c], LIB, MUSIC, {}, st=CH.Settings(seed=1)); assert all(s.tech.dialogue_ok and s.dur_s <= 20.0 + 1e-9 for s in r['segs'])


def syn_pack(): return dict(race={}, clips=PACK['clips'] + [dict(label='G03', clip='G03', duration_s=6.0, usable_s=6.0, usable=[], scene={}, note='', lines=[], synthetic=True)])


def test_a_generated_clip_takes_its_whole_length_between_the_footage_windows_and_shifts_what_follows():
    d = dict(wpm=150, items=[item('broll', 1, seconds=4.0), dict(type='broll', clip='G03', seconds=99), item('broll', 2, seconds=4.0)])
    r = run(d, {}, pack=syn_pack()); syn = r['synthetic']; assert len(syn) == 1 and syn[0]['clip'] == 'G03' and syn[0]['beats'] == 12 and syn[0]['role'] == 'broll' and syn[0]['item'] == 1
    first = [s for s, k in zip(r['segs'], r['piece_of']) if k == 0]; last = [s for s, k in zip(r['segs'], r['piece_of']) if k == 2]
    assert syn[0]['start_beat'] == sum(s.beats for s in first) and last[0].start == syn[0]['start_beat'] + 12 and r['beats'] == sum(s.beats for s in r['segs']) + 12


def test_narration_over_a_generated_clip_is_placed_with_it_and_longer_narration_stretches_it():
    d = dict(wpm=150, items=[dict(type='vo', clip='G03', text='Some words over the map.'), item('broll', 2, seconds=2.0)])
    r = run(d, {0: 9.0}, pack=syn_pack()); s = r['synthetic'][0]; assert s['beats'] * BEAT >= 9.0 + SPL.LEAD_S + SPL.TAIL_S - 1e-9 and s['start_beat'] == 0
    assert r['lines'][0]['item'] == 0 and r['lines'][0]['film_start_s'] == 0.0 and r['lines'][0]['seconds'] == s['beats'] * BEAT


def test_a_script_of_only_generated_clips_has_no_footage_windows_and_still_plans():
    r = run(dict(wpm=150, items=[dict(type='broll', clip='G03')]), {}, pack=syn_pack()); assert r['segs'] == [] and r['beats'] == 12 and r['synthetic'][0]['start_beat'] == 0


def test_a_generated_clip_has_no_words_so_a_dialogue_item_on_it_is_skipped():
    r = run(dict(wpm=150, items=[dict(type='clip', clip='G03', lines=['x']), item('broll', 2, seconds=4.0)]), {}, pack=syn_pack()); assert r['synthetic'] == [] and any('G03' in w for w in r['warnings'])


def test_narration_longer_than_the_clips_footage_gets_the_missing_time_held_with_the_choices_named():
    tiny = clip(3, 6.0, [cand('X', 0, 0, 3.0)]); pack = dict(race={}, clips=PACK['clips'] + [pc(tiny)])
    d = dict(wpm=150, items=[dict(type='vo', clip='0003', text='A long line over a very short clip.')])
    r = SPL.build(d, pack, [C1, C2, tiny], LIB, MUSIC, {0: 6.0}, st=CH.Settings(seed=1)); need = 6.0 + SPL.LEAD_S + SPL.TAIL_S
    assert sum(s.dur_s for s in r['segs']) >= need - 1e-6 and any('narration needs' in w and 'shorten the line' in w and 'last frame is held' in w for w in r['warnings'])


# ---- the director's anchors and the music's singing

def anchored(items): return dict(wpm=150, items=items)


def test_an_anchored_item_is_moved_to_the_nearest_bar_by_stretching_the_b_roll_before_it():
    d = anchored([dict(type='broll', clip='0001', seconds=4.0), dict(type='broll', clip='0002', seconds=4.0, anchor=dict(film_s=8.9, why='the chorus'))])             # bars are 2 s: 8.9 s is nearest the bar at 8 s
    r = run(d, {}); a = r['anchors'][0]; assert a['item'] == 2 and a['target_s'] == 8.0 and a['moved_s'] == 4.0 and a['left_s'] == 0.0 and a['start_s'] == 8.0 and not any('anchored' in w for w in r['warnings'])
    assert r['pieces'][0]['seconds'] == 8.0 and sum(s.beats for s, k in zip(r['segs'], r['piece_of']) if k == 0) * BEAT == 8.0


def test_an_anchor_that_needs_more_than_the_b_roll_can_give_is_reported_not_forced():
    r = run(anchored([dict(type='broll', clip='0001', seconds=4.0), dict(type='broll', clip='0002', seconds=4.0, anchor=dict(film_s=40, why='x'))]), {})
    a = r['anchors'][0]; assert a['left_s'] > 0 and a['start_s'] < 40 and any('anchored at 40 s' in w and 'no b-roll before it to stretch' in w for w in r['warnings'])
    only_voice = run(anchored([dict(type='vo', clip='0001', text='one two three'), dict(type='broll', clip='0002', seconds=4.0, anchor=dict(film_s=20, why='x'))]), {0: 2.0})
    assert only_voice['anchors'][0]['moved_s'] == 0.0 and any('no b-roll before it' in w for w in only_voice['warnings'])                                        # the voice's length is not ours to change


def test_a_later_anchor_does_not_undo_an_earlier_one():
    d = anchored([dict(type='broll', clip='0001', seconds=4.0), dict(type='broll', clip='0002', seconds=4.0, anchor=dict(film_s=8, why='a')), dict(type='broll', clip='0001', seconds=4.0), dict(type='broll', clip='0002', seconds=4.0, anchor=dict(film_s=20, why='b'))])
    r = run(d, {}); starts = {a['item']: a['start_s'] for a in r['anchors']}; assert starts == {2: 8.0, 4: 20.0}


def test_narration_over_singing_is_found_and_recorded_in_the_plan_without_a_warning():
    lines = [dict(text='over the verse', film_start_s=10.0, speak_s=6.0), dict(text='in the quiet', film_start_s=40.0, speak_s=5.0), dict(text='a bit of overlap', film_start_s=29.0, speak_s=5.0)]
    got = SPL.over_singing(lines, [[8.0, 20.0], [30.0, 31.0]]); assert [g['text'] for g in got] == ['over the verse'] and got[0]['sung_s'] == 6.0                          # one second of five is under the share
    pack = dict(PACK, music=dict(lyrics=dict(vocal_spans=[[0.0, 60.0]]))); r = SPL.build(DRAFT, pack, [C1, C2], LIB, MUSIC, VOICE, st=CH.Settings(seed=1)); assert r['over_singing'] and not any('singing' in w for w in r['warnings'])                         # recorded in the plan, not a warning: narration over singing is normal


# ---- fitting the film to the music

def pieces_of(*secs): return [dict(kind='broll', seconds=x, n=i) for i, x in enumerate(secs)]


def test_b_roll_is_shortened_evenly_to_bring_the_film_to_the_musics_length():
    ps = pieces_of(10.0, 10.0, 10.0) + [dict(kind='vo', seconds=10.0, n=3)]; f = SPL.fit_pass(ps, MUSIC, 30.0)                                       # 40 s of pieces, the music has 30 s
    assert f['before_s'] == 40.0 and abs(f['after_s'] - 30.0) <= 1.0 and [p['seconds'] for p in ps[:3]] == pytest.approx([ps[0]['seconds']] * 3, abs=0.51) and ps[3]['seconds'] == 10.0 and all(p['seconds'] >= 2.0 for p in ps)


def test_b_roll_is_never_shortened_below_two_seconds_and_what_cannot_be_absorbed_is_left():
    ps = pieces_of(3.0, 3.0) + [dict(kind='clip', seconds=30.0, n=2)]; f = SPL.fit_pass(ps, MUSIC, 20.0)
    assert [p['seconds'] for p in ps[:2]] == [2.0, 2.0] and f['after_s'] == 34.0                                                                      # 4 s of b-roll is all there was to give


def test_a_short_film_gets_longer_b_roll_and_a_film_within_a_bar_is_left_alone():
    ps = pieces_of(4.0, 4.0); f = SPL.fit_pass(ps, MUSIC, 14.0); assert f['after_s'] > 8.0 and f['after_s'] <= 14.0 + 1.0 and all(p['seconds'] <= 10.0 for p in ps)
    ps = pieces_of(4.0, 4.0); f = SPL.fit_pass(ps, MUSIC, 9.0); assert f['after_s'] == 8.0 and [p['seconds'] for p in ps] == [4.0, 4.0]                  # a bar is 2 s


def test_the_plan_reports_a_film_that_is_too_long_for_the_music_when_the_b_roll_cannot_absorb_it():
    d = anchored([dict(type='broll', clip='0001', seconds=3.0), dict(type='clip', clip='0001', lines=['0001.00', '0001.01']), dict(type='vo', clip='0002', text='one two three four five six seven eight nine')])
    r = SPL.build(d, PACK, [C1, C2], LIB, MUSIC, {2: 5.0}, st=CH.Settings(seed=1), target_s=10.0)
    assert r['fit']['target_s'] == 10.0 and r['fit']['over_s'] > 2.0 and any('longer than the music' in w and 'shorten narration' in w for w in r['warnings'])
    ok = SPL.build(anchored([dict(type='broll', clip='0001', seconds=20.0)]), PACK, [C1, C2], LIB, MUSIC, {}, st=CH.Settings(seed=1), target_s=10.0); assert ok['fit']['final_s'] <= 11.0 and not any('than the music' in w for w in ok['warnings'])
