"""Re-sizing blocks to the measured voice-over (V4)."""
import pytest

from strata360.edit import blocks as B, vo_fit as F, vo_measure as M

MUSIC = dict(bpm=120.0, bar_beats=4, duration_s=90.0, offset_s=0.0)            # a bar is 2 s


def clip(i, usable=60.0, speech=None, q=0.6):
    cid = f'C{i:02d}'; cs = [dict(id=f'{cid}#00', clip=cid, kind='span', start_s=0.0, end_s=usable, quality=q, priority=1)]
    al = []
    for k, (a, b) in enumerate(speech or []):
        cs.append(dict(id=f'{cid}#9{k}', clip=cid, kind='speech', start_s=a - .5, end_s=b + .5, quality=q, priority=2)); al.append(dict(t0=a, t1=b, words=[dict(a0=a, a1=b, ok=True)]))
    return dict(id=cid, start_utc=f'2026-02-19T{10 + i:02d}:00:00Z', duration_s=usable + 5, candidates=cs, alignment=al)


def setup(specs, target=None, take='synth'):
    """specs: per clip {usable, speech, lines: [(seconds of speech, anchor)]} -> (plan, script, vo)."""
    clips = [clip(i, s.get('usable', 60.0), s.get('speech')) for i, s in enumerate(specs)]; plan = B.plan_blocks(clips, target or 30 * len(specs))
    lines = []; secs = []
    for i, s in enumerate(specs):
        for sec, anchor in s.get('lines', []): lines.append(dict(block=i, anchor=anchor, text=' '.join(['w'] * max(int(sec * 2.5), 1)))); secs.append(sec)
    script = dict(lines=lines)
    vo = [dict(key=key, take=take, status='ok', speech_start_s=0.1, speech_end_s=0.1 + sec) for (key, _), sec in zip(M.line_keys(script), secs)]
    return plan, script, dict(lines=vo)


def test_block_length_is_the_lines_pauses_dialogue_and_leads():
    plan, script, vo = setup([dict(speech=[(10, 14)], lines=[(3.0, 'before'), (2.0, 'before'), (4.0, 'after')])])
    f = F.fit(plan, script, vo); b = f.blocks[0]; d = plan.blocks[0].dialogue_s
    assert b.length_s == pytest.approx(0.5 + 3 + 0.4 + 2 + 0.4 + d + 0.4 + 4 + 0.5, abs=1e-3) and f.film_length_s == f.voice_over_s == pytest.approx(b.length_s)
    l = b.lines; assert l[0].start_s == pytest.approx(0.5) and l[1].start_s == pytest.approx(0.5 + 3 + 0.4)
    assert b.dialogue_start_s == pytest.approx(l[1].end_s + 0.4) and l[2].start_s == pytest.approx(b.dialogue_end_s + 0.4)


def test_every_line_lies_in_its_own_block_and_never_over_dialogue():
    plan, script, vo = setup([dict(lines=[(3, None)]), dict(speech=[(10, 14)], lines=[(2, 'before'), (2, 'after')]), dict(lines=[(5, None), (1, None)])])
    f = F.fit(plan, script, vo)
    for b in f.blocks:
        for l in b.lines:
            assert b.start_s + b.lead_in_s - 1e-6 <= l.start_s and l.end_s <= b.end_s - b.lead_out_s + 1e-6
            if b.dialogue_start_s is not None: assert l.end_s <= b.dialogue_start_s + 1e-6 or l.start_s >= b.dialogue_end_s - 1e-6
    assert [b.start_s for b in f.blocks] == pytest.approx([0, f.blocks[0].length_s, f.blocks[0].length_s + f.blocks[1].length_s])
    assert f.blocks[-1].end_s == pytest.approx(f.film_length_s)                                         # picture for every instant: the blocks tile the film


def test_a_block_is_never_shorter_than_its_minimum():
    plan, script, vo = setup([dict(lines=[]), dict(lines=[(1.0, None)])])
    f = F.fit(plan, script, vo); assert all(b.length_s >= b.min_s - 1e-9 for b in f.blocks) and f.blocks[0].length_s == pytest.approx(plan.blocks[0].min_s)


def test_a_long_synthetic_line_is_sped_up_within_the_limit_before_anything_is_reported():
    plan, script, vo = setup([dict(usable=10.0, lines=[(10.0, None)])], target=10)                      # 10 s of speech + 1 s of leads in 10 s of footage
    f = F.fit(plan, script, vo); b = f.blocks[0]
    assert b.tempo == pytest.approx(10 / 9, abs=0.002) and b.lines[0].tempo == b.tempo and b.length_s == pytest.approx(10.0, abs=0.01) and b.overflow_s == 0 and f.problems == []


def test_overflow_beyond_the_speed_limit_names_the_line_and_the_clip_with_choices():
    plan, script, vo = setup([dict(usable=8.0, lines=[(12.0, None)])], target=8)
    f = F.fit(plan, script, vo); b = f.blocks[0]; p = f.problems[0]
    assert b.tempo == 1.25 and b.overflow_s == pytest.approx(12 / 1.25 + 1 - 8, abs=0.01) and p['kind'] == 'overflow' and p['clip'] == 'C00' and p['line'] == '000n0'
    assert p['message'].startswith('line 000n0 needs') and 'clip C00 has 8.0 s usable' in p['message'] and 'shorten the line' in p['choices'] and 'allow a hold on the last frame' in p['choices']
    assert b.lines[0].end_s <= b.end_s                                                                    # the block still holds the line (the hold is the overflow)


def test_a_recording_is_never_sped_up():
    plan, script, vo = setup([dict(usable=8.0, lines=[(12.0, None)])], target=8, take='recorded')
    f = F.fit(plan, script, vo); assert f.blocks[0].tempo == 1.0 and f.blocks[0].lines[0].tempo == 1.0 and f.blocks[0].overflow_s == pytest.approx(12 + 1 - 8, abs=0.01)


def test_only_synthetic_lines_in_a_mixed_block_are_sped_up():
    plan, script, vo = setup([dict(usable=9.0, lines=[(4.0, None), (4.0, None)])], target=9)
    vo['lines'][0]['take'] = 'recorded'; f = F.fit(plan, script, vo); a, b = f.blocks[0].lines
    assert a.tempo == 1.0 and 1.0 < b.tempo <= 1.25


def test_music_longer_than_the_voice_over_is_filled_by_growing_every_block():
    plan, script, vo = setup([dict(lines=[(10, None)]), dict(lines=[(10, None)]), dict(lines=[(10, None)])])
    base = F.fit(plan, script, vo); V = base.voice_over_s
    f = F.fit(plan, script, vo, MUSIC)
    assert f.film_length_s == pytest.approx(90.0, abs=2.0) and f.voice_over_s == V and all(b.extra_s > 0 for b in f.blocks) and f.problems == []
    assert f.music['start_s'] == 0 and f.music['cut_s'] == 0 and f.intro_s > 0 and f.outro_s > 0 and f.intro_s <= 4.0 + 1e-9
    assert f.film_length_s >= f.voice_over_s


def test_too_little_footage_fades_the_music_and_reports_a_big_loss():
    plan, script, vo = setup([dict(usable=14.0, lines=[(10, None)]), dict(usable=14.0, lines=[(10, None)])])
    f = F.fit(plan, script, vo, MUSIC)
    assert f.film_length_s == pytest.approx(28.0, abs=0.01) and f.music['cut_s'] == pytest.approx(62.0, abs=0.1) and f.music['fade_out_s'] == 2.0 and f.music['end_s'] == f.film_length_s
    assert f.problems[0]['kind'] == 'music_cut' and f.problems[0]['clips'] == ['C00', 'C01'] and 'accept the earlier fade-out' in f.problems[0]['choices']


def test_a_small_loss_within_the_limit_is_not_reported():
    plan, script, vo = setup([dict(usable=47.0, lines=[(10, None)]), dict(usable=40.0, lines=[(10, None)])])
    f = F.fit(plan, script, vo, dict(MUSIC, duration_s=90.0))
    assert 0 < f.music['cut_s'] <= 8.0 and f.problems == []


def test_voice_over_longer_than_the_music_puts_silence_around_it_within_limits():
    plan, script, vo = setup([dict(lines=[(30, None)]), dict(lines=[(30, None)])])
    V = F.fit(plan, script, vo).voice_over_s
    f = F.fit(plan, script, vo, dict(MUSIC, duration_s=V - 4.0))
    assert f.film_length_s == pytest.approx(V) and f.music['lead_silence_s'] + f.music['tail_silence_s'] == pytest.approx(4.0) and f.music['lead_silence_s'] <= 4 and f.music['tail_silence_s'] <= 6 and f.problems == []
    assert f.music['end_s'] == pytest.approx(f.music['start_s'] + f.music['length_s'])


def test_music_too_short_even_with_the_silences_is_reported():
    plan, script, vo = setup([dict(lines=[(30, None)]), dict(lines=[(30, None)])])
    V = F.fit(plan, script, vo).voice_over_s; f = F.fit(plan, script, vo, dict(MUSIC, duration_s=V - 16.0))
    assert f.music['lead_silence_s'] == 4.0 and f.music['tail_silence_s'] == 6.0 and f.music['unplaced_s'] == pytest.approx(6.0) and f.problems[0]['kind'] == 'music_short' and 'loop a section of the track at a bar line' in f.problems[0]['choices']


def test_the_film_is_never_shorter_than_the_voice_over():
    plan, script, vo = setup([dict(lines=[(20, None)]), dict(lines=[(20, None)])])
    for m in (10.0, 40.0, 200.0): assert F.fit(plan, script, vo, dict(MUSIC, duration_s=m)).film_length_s >= F.fit(plan, script, vo).voice_over_s - 1e-9
    assert F.fit(plan, script, vo, target_s=5).film_length_s == F.fit(plan, script, vo).voice_over_s


def test_a_target_length_without_music_spreads_the_extra_loosely():
    plan, script, vo = setup([dict(lines=[(10, None)]), dict(lines=[(10, None)])]); f = F.fit(plan, script, vo, target_s=60)
    assert f.film_length_s == pytest.approx(60.0, abs=0.01) and f.music is None and f.intro_s == 0


def test_unmeasured_lines_are_estimated_and_unknown_blocks_left_out():
    plan, script, _ = setup([dict(lines=[(5, None)])]); script['lines'].append(dict(block=9, anchor=None, text='lost'))
    f = F.fit(plan, script, None); l = f.blocks[0].lines[0]
    assert l.estimated and l.natural_speech_s == pytest.approx(len(l.text.split()) * 0.4) and any('block 9' in w for w in f.warnings) and any('estimated' in w for w in f.warnings)


def test_paragraph_gap():
    plan, script, vo = setup([dict(lines=[(2, None), (2, None)])]); a = F.fit(plan, script, vo).blocks[0].length_s
    script['lines'][0]['paragraph_after'] = True; b = F.fit(plan, script, vo).blocks[0].length_s
    assert b - a == pytest.approx(0.5)


def test_to_dict_round_trips_to_plain_data():
    import json
    plan, script, vo = setup([dict(speech=[(10, 14)], lines=[(2, 'before')])]); json.dumps(F.fit(plan, script, vo, MUSIC).to_dict())


def test_speed_already_in_the_audio_counts_against_the_limit():
    plan, script, vo = setup([dict(usable=8.0, lines=[(12.0, None)])], target=8)
    vo['lines'][0]['tempo_applied'] = 1.2; f = F.fit(plan, script, vo); l = f.blocks[0].lines[0]
    assert l.applied == 1.2 and l.tempo == pytest.approx(1.25 / 1.2, abs=1e-3) and f.blocks[0].tempo == pytest.approx(1.25, abs=1e-3) and f.problems[0]['kind'] == 'overflow'
