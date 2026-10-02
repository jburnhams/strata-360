"""edit/lyrics.py: where the music track is sung (from a recogniser that is rough on music), your corrections, staleness and reset. The recogniser is a fake that returns phrases."""
import json, os
import pytest
from strata360.edit import lyrics as LY
from strata360.pipeline import config


def ph(t0, t1, text, lp=-0.4, ns=0.3): return dict(t0=t0, t1=t1, text=text, avg_logprob=lp, no_speech=ns, words=[])


VERSE = [ph(100.0, 103.0, 'line one'), ph(103.5, 106.0, 'line two'), ph(106.5, 109.0, 'line three'), ph(150.0, 153.0, 'hook hook')]
CHANT = ph(193.0, 199.0, 'go to bed go to bed', lp=-0.71, ns=0.86)                 # what the recogniser invents over a quiet stretch


@pytest.fixture
def folder(tmp_path):
    f = str(tmp_path / 'trip'); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'music')); open(os.path.join(rd, 'music', 'track.mp3'), 'wb').write(b'x')
    json.dump(dict(file='music/track.mp3', sig=[1, 2]), open(os.path.join(rd, 'music.json'), 'w')); return f


def fake(phrases, **info): return lambda path: (list(phrases), dict(language='en', language_probability=0.97, duration_s=247.0, **info))


def test_confidence_falls_with_a_poor_fit_and_with_a_quiet_stretch():
    assert LY.confidence(-0.31, 0.28) > LY.confidence(-0.51, 0.76) > LY.confidence(-0.71, 0.86) and LY.confidence(0.0, 0.0) == 1.0 and LY.confidence(-0.71, 0.86) < LY.DOUBT <= LY.confidence(-0.51, 0.76)


def test_the_sung_stretches_are_the_trusted_phrases_widened_and_joined(folder):
    s = LY.build(folder, log=lambda m: None, transcriber=fake(VERSE + [CHANT])); v = LY.view(folder)
    assert s['exists'] and s['phrases'] == 5 and s['language'] == 'en' and not s['instrumental']
    assert v['vocal_spans'] == [(99.7, 109.3), (149.7, 153.3)]                                                    # the three verse lines are one stretch; the invented chant is left out
    chant = [p for p in v['phrases'] if p['text'].startswith('go to bed')][0]; assert chant['doubtful'] and not chant['counts'] and v['sung_s'] == pytest.approx(9.6 + 3.6, abs=0.05)


def test_a_track_with_almost_no_singing_is_instrumental(folder):
    s = LY.build(folder, log=lambda m: None, transcriber=fake([ph(10.0, 11.0, 'la')])); assert s['instrumental'] is True and s['phrases'] == 1
    assert LY.build(folder, log=lambda m: None, transcriber=fake([]))['instrumental'] is True


def test_corrections_change_the_spans_and_survive_finding_the_lyrics_again(folder):
    LY.build(folder, log=lambda m: None, transcriber=fake(VERSE + [CHANT]))
    assert LY.edit(folder, '150.0-153.0', deleted=True)['deleted'] is True and LY.view(folder)['vocal_spans'] == [(99.7, 109.3)]
    assert LY.edit(folder, '193.0-199.0', keep=True)['counts'] is True and (192.7, 199.3) in LY.view(folder)['vocal_spans']                   # you say the chant is real after all
    p = LY.edit(folder, '100.0-103.0', text='the true words'); assert p['text'] == 'the true words' and p['heard'] == 'line one' and p['edited'] is True
    LY.build(folder, log=lambda m: None, transcriber=fake(VERSE + [CHANT])); v = LY.view(folder); assert [p['text'] for p in v['phrases']][0] == 'the true words' and (149.7, 153.3) not in v['vocal_spans']
    assert LY.edit(folder, '100.0-103.0', text='')['edited'] is False and LY.edit(folder, '1.0-2.0', deleted=True) is None


def test_a_new_track_makes_the_record_stale_and_reset_forgets_it(folder):
    LY.build(folder, log=lambda m: None, transcriber=fake(VERSE)); assert LY.status(folder)['stale'] is False
    rd = config.race_dir(folder); json.dump(dict(file='music/track.mp3', sig=[3, 4]), open(os.path.join(rd, 'music.json'), 'w')); assert LY.status(folder)['stale'] is True
    LY.edit(folder, '100.0-103.0', deleted=True); assert LY.reset(folder) is True and not LY.status(folder)['exists'] and LY.reset(folder) is False and os.path.exists(LY.edits_path(folder))
    assert LY.reset(folder, corrections=True) is True and not os.path.exists(LY.edits_path(folder)) and LY.reset(folder, corrections=True) is False


def test_without_a_track_it_says_so(tmp_path):
    f = str(tmp_path / 'none'); os.makedirs(config.race_dir(f)); assert LY.status(f)['has_track'] is False
    with pytest.raises(RuntimeError, match='no music track'): LY.build(f, log=lambda m: None, transcriber=fake([]))
