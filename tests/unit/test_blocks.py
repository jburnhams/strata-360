import pytest

from strata360.edit import blocks as B
from strata360.edit.chrono import Settings


def cand(clip, k, a, b, kind='span', q=0.6, prio=None):
    return dict(id=f'{clip}#{k:02d}', clip=clip, kind=kind, start_s=a, end_s=b, quality=q, priority=prio or k + 1)


def clip(i, spans, speech=None, q=0.6, utc=None):
    """spans: usable [(a, b)]; speech: [(a, b)] wearer talking (a `speech` candidate each, with alignment)."""
    cid = f'C{i:02d}'; cs = [cand(cid, k, a, b, q=q) for k, (a, b) in enumerate(spans)]
    al = []
    for k, (a, b) in enumerate(speech or []):
        cs.append(cand(cid, 90 + k, a - 0.5, b + 0.5, 'speech', q)); al.append(dict(t0=a - 0.3, t1=b + 0.3, words=[dict(a0=a, a1=b, ok=True)]))
    return dict(id=cid, start_utc=utc or f'2026-02-19T{10 + i:02d}:00:00Z', duration_s=max(b for _, b in spans) + 5, candidates=cs, alignment=al)


def test_every_clip_gets_a_block_in_shooting_order():
    clips = [clip(2, [(0, 30)]), clip(0, [(0, 10)]), clip(1, [(5, 25)])]
    p = B.plan_blocks(clips, 40)
    assert [b.clip for b in p.blocks] == ['C00', 'C01', 'C02'] and [b.index for b in p.blocks] == [0, 1, 2] and p.dropped == []


def test_targets_sum_to_the_film_target():
    p = B.plan_blocks([clip(i, [(0, 20 + 10 * i)]) for i in range(5)], 47.3)
    assert sum(b.target_s for b in p.blocks) == pytest.approx(47.3, abs=1e-6) and p.target_s == pytest.approx(47.3, abs=1e-6) and p.shortfall_s == 0
    assert all(b.min_s <= b.target_s <= b.max_s for b in p.blocks)


def test_block_minimum_covers_dialogue_with_padding():
    p = B.plan_blocks([clip(0, [(0, 30)], speech=[(10.0, 14.0)])], 20)
    b = p.blocks[0]
    assert b.dialogue == [(pytest.approx(9.94), pytest.approx(14.12))]            # exact span 10..14 (alignment), 60 ms before and 120 ms after
    assert b.dialogue_s == pytest.approx(4.18) and b.min_s == pytest.approx(4.18 + B.MIN_SEG_S)


def test_speech_spans_without_alignment_use_the_candidate():
    c = clip(0, [(0, 30)], speech=[(10, 14)]); c['alignment'] = []
    assert B.speech_spans(c, c['candidates']) == [(9.5, 14.5)]


def test_speech_spans_override():
    c = clip(0, [(0, 30)], speech=[(10, 14)]); c['speech_spans'] = [(11, 12)]
    assert B.plan_blocks([c], 10).blocks[0].dialogue[0][0] == pytest.approx(10.94)


def test_unusable_clip_is_dropped_and_reported_but_a_dull_one_keeps_a_block():
    dull = clip(1, [(0, 8)], q=0.01); none = dict(id='C02', start_utc='2026-02-19T12:00:00Z', duration_s=30, candidates=[])
    p = B.plan_blocks([clip(0, [(0, 20)]), dull, none], 30)
    assert [b.clip for b in p.blocks] == ['C00', 'C01'] and p.dropped == [dict(clip='C02', reason='no usable footage')]


def test_too_small_target_drops_lowest_value_first_with_reasons():
    clips = [clip(0, [(0, 20)], q=0.9), clip(1, [(0, 20)], q=0.1), clip(2, [(0, 20)], q=0.5)]
    p = B.plan_blocks(clips, 5)                                                    # room for two minimum windows (2 s each), not three
    assert [b.clip for b in p.blocks] == ['C00', 'C02'] and [d['clip'] for d in p.dropped] == ['C01'] and 'minimum' in p.dropped[0]['reason']
    assert sum(b.target_s for b in p.blocks) == pytest.approx(5)


def test_automatic_length_grows_with_usable_footage_and_is_reproducible():
    small = B.plan_blocks([clip(0, [(0, 10)])]).target_s; big = B.plan_blocks([clip(0, [(0, 100)])]).target_s
    assert 0 < small < big < 100 and B.plan_blocks([clip(0, [(0, 100)])]).target_s == big
    p = B.plan_blocks([clip(0, [(0, 100)])]); assert p.automatic and p.requested_s is None and p.blocks[0].target_s == p.blocks[0].natural_s == pytest.approx(2 + 1.5 * 10)


def test_automatic_length_adds_dialogue_and_caps_at_footage():
    b = B.plan_blocks([clip(0, [(0, 3)])]).blocks[0]
    assert b.natural_s == pytest.approx(3.0)
    d = B.plan_blocks([clip(0, [(0, 30)], speech=[(10, 14)])]).blocks[0]
    assert d.natural_s == pytest.approx(B.natural_s(30, d.dialogue_s))


def test_not_enough_footage_reports_a_shortfall():
    p = B.plan_blocks([clip(0, [(0, 10)]), clip(1, [(0, 10)])], 60)
    assert p.target_s == pytest.approx(20) and p.shortfall_s == pytest.approx(40) and p.warnings


def test_overrides_weights_bans_and_locks():
    clips = [clip(0, [(0, 60)]), clip(1, [(0, 60)])]
    heavy = B.plan_blocks(clips, 30, Settings(clip_weight={'C01': 3.0})).blocks
    assert heavy[1].target_s > heavy[0].target_s
    banned = B.plan_blocks(clips, 30, Settings(bans_cands=frozenset({'C00#00'}))); assert [b.clip for b in banned.blocks] == ['C01'] and banned.dropped[0]['clip'] == 'C00'
    win = B.plan_blocks(clips, 30, Settings(bans_cands=frozenset({'win:C00@0.0@40.0'})))
    assert win.blocks[0].usable == [(40.0, 60)]
    lk = B.plan_blocks(clips, 30, Settings(locked=({'clip': 'C00', 'beats': 12, 'wid': 'x', 'start_s': 0, 'cand_id': 'C00#00', 'tech': 't'},)), beat_s=0.5)
    assert lk.blocks[0].min_s >= 6.0


def test_preferred_content_orders_by_priority_and_kind():
    c = clip(0, [(0, 30)], speech=[(10, 12)]); b = B.plan_blocks([c], 20).blocks[0]
    assert b.preferred[0]['kind'] == 'speech' and all(p['kind'] in B.PREFERRED_KINDS for p in b.preferred)


def test_dialogue_outside_usable_footage_is_ignored_and_empty_plan():
    c = clip(0, [(0, 5)], speech=[(20, 22)]); assert B.plan_blocks([c], 10).blocks[0].dialogue == []
    assert B.plan_blocks([], 10).blocks == [] and B.plan_blocks([], 10).warnings


def test_merge_and_subtract():
    assert B.merge([(3, 4), (0, 2), (1, 2.5)]) == [(0, 2.5), (3, 4)] and B.subtract([(0, 10)], [(2, 3), (9, 11)]) == [(0, 2), (3, 9)]
