"""The user's pins on the whole-race script: tagging, the prompt section and checking a reply."""
from strata360.edit import script_pins as PN, script_pack as SP


def L(i, t0, t1, text='x y z'): return dict(id=i, t0=t0, t1=t1, text=text, words=3, lang='en')


PACK = dict(race=dict(note='n', details='d', track='t'), clips=[
    dict(label='0001', clip='A', duration_s=30, usable_s=30, usable=[(0, 30)], scene={}, note='', lines=[L('0001.00', 1, 3), L('0001.01', 4, 6), L('0001.02', 7, 9)], speech_s=6, speech_words=9),
    dict(label='0002', clip='B', duration_s=20, usable_s=20, usable=[(0, 20)], scene={}, note='', lines=[L('0002.00', 2, 5)], speech_s=3, speech_words=3)])


def script(*items): return dict(items=list(items))
def vo(clip, text): return dict(type='vo', clip=clip, text=text)
def clip(c, a, b): return dict(type='clip', clip=c, **{'from': a, 'to': b})


def test_ranges_expand_within_one_clip_and_exclude_beats_include():
    assert PN.expand('0001.00..0001.01', PACK) == ['0001.00', '0001.01'] and PN.expand('0002.00', PACK) == ['0002.00'] and PN.expand('9999.00', PACK) == []
    assert PN.marks(dict(include=['0001.00..0001.02'], exclude=['0001.01']), PACK) == {'0001.00': 'must', '0001.01': 'never', '0001.02': 'must'}


def test_the_pack_text_tags_the_fixed_lines():
    t = SP.render(PACK, marks=PN.marks(dict(include=['0001.00'], exclude=['0002.00']), PACK)); assert '[0001.00] 1.0-3.0 s (2.0 s): x y z   <<< MUST INCLUDE' in t and '<<< DO NOT USE' in t and '[0001.01]' in t


def test_the_prompt_section_lists_every_kind_of_pin_and_the_time_they_take():
    pins = dict(include=['0001.00..0001.01'], exclude=['0002.00'], vo=[dict(id='v1', text='one two three four five six', mode='clip', clip='0001'), dict(id='v2', text='ordered text', mode='ordered'), dict(id='v3', text='free text', mode='anywhere')])
    s = PN.render_constraints(pins, PACK, 100, 120)
    assert 'MUST INCLUDE' in s and 'DO NOT USE' in s and '[v1] (at about the moment of clip 0001: inside it, or in the item just before or after it if there is not room)' in s and 'keep the order' in s and 'no order' in s and 'of the 100 s target' in s
    assert PN.render_constraints({}, PACK, 100, 120) == '' and PN.render_constraints(dict(include=[]), PACK, 100, 120) == ''
    cs, vs = PN.seconds_summary(pins, PACK, 120); assert abs(cs - (6 - 1 + 0.18)) < 0.05 and vs > 0            # lines 00 and 01 are one run: 1.0 to 6.0 s plus the pad


def test_a_script_that_follows_the_pins_has_no_problems():
    pins = dict(include=['0001.00'], exclude=['0001.02'], vo=[dict(id='v1', text='Hello there, friend.', mode='clip', clip='0001'), dict(id='v2', text='second piece', mode='ordered'), dict(id='v3', text='anywhere piece', mode='anywhere')])
    ok = script(vo('0001', 'Well. Hello there, friend! And more.'), clip('0001', '0001.00', '0001.01'), vo('0002', 'second piece'), clip('0002', '0002.00', '0002.00'), vo('0002', 'anywhere piece'))
    assert PN.check(ok, PACK, pins) == []


def test_every_way_of_breaking_a_pin_is_reported():
    pins = dict(include=['0001.00', '0002.00'], exclude=['0001.02'], vo=[dict(id='v1', text='anchored text', mode='clip', clip='0001'), dict(id='v2', text='first piece', mode='ordered'), dict(id='v3', text='later piece', mode='ordered'), dict(id='v4', text='gone', mode='anywhere')])
    bad = script(vo('0002', 'anchored text'), vo('0002', 'later piece'), vo('0002', 'first piece'), clip('0001', '0001.01', '0001.02'))
    p = ' | '.join(PN.check(bad, PACK, pins))
    assert 'MUST INCLUDE line 0001.00' in p and 'MUST INCLUDE line 0002.00' in p and 'DO NOT USE line 0001.02' in p and 'belongs at the moment of clip 0001' in p and 'further away' in p
    assert '[v2] must come before [v3]' in p and '[v4] is missing' in p                           # v3 is spoken before v2, and v4 never appears


def test_reworded_narration_does_not_count():
    pins = dict(vo=[dict(id='v1', text='I had put the spare watch on the other wrist', mode='anywhere')])
    assert PN.check(script(vo('0001', 'I put the spare watch on my other wrist')), PACK, pins) and PN.check(script(vo('0001', 'Then, I had put the spare watch on the other wrist, and it was worse')), PACK, pins) == []


def test_narration_pinned_to_a_clip_may_spill_into_the_item_before_or_after_it():
    pins = dict(vo=[dict(id='v1', text='anchored text', mode='clip', clip='0001')])
    assert PN.check(script(clip('0001', '0001.01', '0001.02'), vo('0002', 'anchored text')), PACK, pins) == []                    # in the next item
    assert PN.check(script(vo('0002', 'anchored text'), clip('0001', '0001.01', '0001.02')), PACK, pins) == []                    # in the one before
    assert PN.check(script(clip('0001', '0001.01', '0001.02'), vo('0001', 'anchored text')), PACK, pins) == []                    # inside it
    far = ' | '.join(PN.check(script(vo('0002', 'anchored text'), vo('0002', 'x y'), vo('0002', 'x z'), clip('0001', '0001.01', '0001.02')), PACK, pins)); assert 'further away' in far
