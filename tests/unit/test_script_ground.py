"""Narration grounding: quotes must be in the material, numbers too, 'km to go' must match the clip, and claims from the runner's words need those words next to them."""
from strata360.edit import script_ground as G, script_pack as SP


def L(i, t0, t1, text): return dict(id=i, t0=t0, t1=t1, text=text, words=len(text.split()), lang='en')


PACK = dict(race=dict(note='I lost the plot.', details='d', track='t', km_total=100.0), clips=[
    dict(label='0001', clip='A', duration_s=30, usable_s=30, usable=[(0, 30)], scene={}, note='', km=20.0, track='km 20.0 of 100', lines=[L('0001.00', 1, 3, 'We are doing fine so far.')], speech_s=2, speech_words=5),
    dict(label='0002', clip='B', duration_s=20, usable_s=20, usable=[(0, 20)], scene={}, note='', km=90.0, track='km 90.0 of 100', lines=[L('0002.00', 2, 5, 'I keep seeing things that are not there.')], speech_s=3, speech_words=8)])
TEXT = SP.render(PACK)


def vo(clip, text, *basis): return dict(type='vo', clip=clip, text=text, basis=list(basis))
def clip(c, a, b): return dict(type='clip', clip=c, **{'from': a, 'to': b})
def chk(*items): return G.check(dict(items=list(items)), PACK, TEXT)


def test_spelled_out_numbers_are_understood():
    assert G.numbers_in('a hundred and eleven of us, forty-two hours, 350 km, three hundred and fifty') == [350.0, 111.0, 42.0, 350.0]


def test_a_grounded_narration_passes():
    assert chk(vo('0001', 'Twenty kilometres in.', 'km 20.0 of 100')) == []


def test_missing_basis_an_invented_basis_and_a_made_up_number_are_reported_but_a_paraphrase_is_fine():
    p = ' | '.join(chk(vo('0001', 'Nothing here.'), vo('0001', 'It rained all day.', 'the rain never stopped'), vo('0001', 'Fifty-five of us quit.', 'km 20.0 of 100')))
    assert 'has no basis' in p and 'does not seem to come from the material' in p and 'the number 55 is not in the material' in p
    assert chk(vo('0001', 'Twenty kilometres in.', 'km 20.0 of 100, the first fifth')) == [] and chk(vo('0001', 'Twenty kilometres in.', 'clip 0001: km 20.0 of the 100 km')) == []          # a paraphrase of the material passes


def test_km_to_go_must_match_the_clips_own_distance():
    assert chk(vo('0002', 'Only ten kilometres to go.', 'km 90.0 of 100')) == []                       # 100 - 90 = 10
    assert 'says 10 km to go but clip 0001' in ' '.join(chk(vo('0001', 'Only ten kilometres to go.', 'km 20.0 of 100')))


def test_a_claim_from_the_runners_words_needs_those_words_next_to_it():
    ok = chk(vo('0002', 'By then I was seeing things.', '0002.00'), clip('0002', '0002.00', '0002.00')); assert ok == []
    far = chk(vo('0002', 'By then I was seeing things.', 'I keep seeing things that are not there'), clip('0001', '0001.00', '0001.00'), vo('0001', 'Filler one.', 'km 20.0 of 100'), vo('0001', 'Filler two.', 'km 20.0 of 100'), clip('0002', '0002.00', '0002.00'))
    assert any("rests on the runner's line 0002.00" in x for x in far)                                  # the clip item is four items away: too far from the claim
    near = chk(vo('0002', 'Seeing things.', '0002.00'), vo('0002', 'Filler.', 'km 90.0 of 100'), clip('0002', '0002.00', '0002.00')); assert near == []        # two items after: fine
    assert any("rests on the runner's line 0002.00" in x for x in chk(vo('0002', 'Seeing things.', '0002.00')))   # no clip item at all
