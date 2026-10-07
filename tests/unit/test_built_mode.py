"""Built mode (docs/ai-music.md G2): the built track recorded from its score, switching between it and the uploaded track, and the writer's facts when the music is made for the film."""
import json, os
import pytest
from strata360.edit import music as MU, project as PJ, script_pack as SP

SCORE = dict(version=1, source='built', file='music/built.flac', of='music/track.mp3', length_s=61.0, bpm=97.0, bars=list(range(24)), downbeats=[i * 2.5 for i in range(24)],
             levels=[0.9] * 8 + [0.15] * 8 + [0.65] * 8)


def project(tmp_path):
    f = str(tmp_path / 'trip'); os.makedirs(os.path.join(f, 'strata360', 'music')); return f, os.path.join(f, 'strata360')


def test_a_built_tracks_analysis_comes_from_its_score_with_the_mean_bar_as_the_tempo():
    a = MU.built_analysis(SCORE)
    assert a['bpm'] == pytest.approx(96.0, abs=0.01) and a['offset_s'] == 0.0 and a['usable_beats'] == 96 and a['duration_s'] == 61.0 and a['built'] is True       # a 2.5 s bar is 96 bpm
    assert a['sections'] == [(0, 32, 0.9), (32, 64, 0.15), (64, 96, 0.65)]


def test_the_score_is_only_used_for_the_file_it_describes(tmp_path):
    f, rd = project(tmp_path); json.dump(SCORE, open(os.path.join(rd, 'music', 'built.json'), 'w'))
    assert MU.built_score(rd, 'music/built.flac')['bpm'] == 97.0 and MU.built_score(rd, 'music/track.mp3') is None
    json.dump(dict(SCORE, source='original'), open(os.path.join(rd, 'music', 'built.json'), 'w')); assert MU.built_score(rd, 'music/built.flac') is None


def test_the_music_is_still_to_be_built_only_in_built_mode_until_the_built_track_is_in_use():
    s = dict(PJ.DEFAULT_SETTINGS); assert not PJ.fixed_length_free(s)
    s.update(music_mode='built', music='music/track.mp3'); assert PJ.fixed_length_free(s)
    s.update(music=PJ.BUILT, music_original='music/track.mp3'); assert not PJ.fixed_length_free(s) and PJ.original_track('x', s) == 'music/track.mp3'


def test_switching_to_the_built_track_keeps_the_uploaded_one_and_back(tmp_path, monkeypatch):
    f, rd = project(tmp_path); monkeypatch.setattr(PJ, 'propose', lambda folder: None); e = PJ.load(f); e['settings']['music'] = 'music/track.mp3'; PJ.save(f, e)
    with pytest.raises(RuntimeError, match='no built track'): PJ.use_built(f)
    open(os.path.join(rd, 'music', 'built.flac'), 'wb').write(b'x'); PJ.use_built(f); s = PJ.load(f)['settings']
    assert s['music'] == PJ.BUILT and s['music_original'] == 'music/track.mp3' and PJ.original_track(f, s) == 'music/track.mp3'
    PJ.use_built(f); assert PJ.load(f)['settings']['music_original'] == 'music/track.mp3'                                       # again: the uploaded track is not lost
    PJ.use_original(f); s = PJ.load(f)['settings']; assert s['music'] == 'music/track.mp3' and s['music_original'] is None


def test_in_built_mode_the_writer_gets_the_phrase_library_and_no_length(tmp_path, monkeypatch):
    f, rd = project(tmp_path); e = PJ.load(f); e['settings'].update(music_mode='built', music='music/track.mp3'); PJ.save(f, e)
    from strata360.edit import music_build as MB, lyrics as LY
    monkeypatch.setattr(MB, 'grid', lambda rd_, rel: dict(bpm=97.0, downbeats=[2.0 + 2.47 * i for i in range(100)], duration_s=247.0))
    monkeypatch.setattr(LY, 'view', lambda folder: dict(instrumental=False, language='en', vocal_spans=[(30.0, 40.0)], phrases=[
        dict(id='L01', t0=32.0, t1=36.0, text='no sleep till Brooklyn', doubtful=False, counts=True), dict(id='L02', t0=100.0, t1=104.0, text='no sleep till brooklyn!', doubtful=False, counts=True),
        dict(id='L03', t0=150.0, t1=152.0, text='mumble', doubtful=True, counts=False)]))
    m = SP.music_facts(f); assert m['built'] and m['length_s'] is None and m['sections'] == [] and m['bar_s'] == 2.47
    ph = m['lyrics']['phrases']; assert [p['id'] for p in ph] == ['L01', 'L02'] and ph[0]['t0'] == 30.0 and ph[0]['hook'] and ph[1]['hook']                          # from the first downbeat: 32 - 2
    text = SP.render(dict(race={}, clips=[], music=m)); assert 'BUILT FOR THE FILM' in text and 'L01 [30 s] no sleep till Brooklyn' in text and 'THE MUSIC (times are FILM seconds' not in text and 'length ' not in text.split('THE MUSIC')[1].split('\n')[2]


def test_the_rough_plan_and_the_planner_ignore_the_tracks_length_while_the_music_is_to_be_built():
    s = dict(PJ.DEFAULT_SETTINGS, music_mode='built', music='music/track.mp3', length_s=200.0); mus = dict(bpm=120.0, bar_beats=4, usable_beats=100, duration_s=50.0, offset_s=0.0, sections=[(0, 100, 0.5)])
    music, _ = PJ._planner(dict(settings=s, overrides=PJ.load.__globals__['EMPTY_OVERRIDES']), None, None, mus); assert music.beats == 400                      # 200 s of 120 bpm, not the track's 100 beats
    s2 = dict(s, music_mode='fixed'); music2, _ = PJ._planner(dict(settings=s2, overrides=PJ.load.__globals__['EMPTY_OVERRIDES']), None, None, mus); assert music2.beats == 100


def test_the_scripts_sing_items_become_pins_for_the_build(tmp_path, monkeypatch):
    from strata360.edit import music_studio as MS, script_draft as SD, lyrics as LY
    f, rd = project(tmp_path); g = dict(downbeats=[2.0 + 2.5 * i for i in range(60)])                                   # bars of 2.5 s from 2 s
    ph = [dict(id='L01', t0=32.0, t1=40.5, text='x', doubtful=False, counts=True), dict(id='L02', t0=100.0, t1=101.0, text='y', doubtful=True, counts=False), dict(id='L03', t0=148.0, t1=150.0, text='z', doubtful=False, counts=True)]
    monkeypatch.setattr(LY, 'view', lambda folder: dict(phrases=ph)); items = [dict(type='broll', clip='0001', seconds=5), dict(type='sing', clip='0002', phrase='L01'), dict(type='sing', clip='0002', phrase='L02'), dict(type='sing', clip='0003', phrase='L03')]
    monkeypatch.setattr(SD, 'load_draft', lambda folder, name=None: dict(items=items))
    e = PJ.load(f); e['plan'] = dict(source='script', script='d.json', segments=[dict(item=1, film_start_s=45.2), dict(item=2, film_start_s=80.0), dict(item=3, film_start_s=130.0)]); PJ.save(f, e)
    pins, notes = MS.sing_pins(f, g, 2.5, 80)
    assert pins == [(18, 11, 6)]                                                                                         # bar 12 holds 32 s (2 + 2.5 * 12): one bar of lead-in from source bar 11, bars 12 to 15 hold the phrase, one of lead-out; the item is at 45.2 s: film bar 18
    assert any('L02' in n and 'not a trusted' in n for n in notes) and any('L03' in n and 'does not fit' in n for n in notes) and len(pins) == 1                                  # L03 sits in the track's last bars: its lead-out would run past the end


def test_music_build_passes_the_score_settings_and_prints_each_generated_piece(tmp_path, monkeypatch, capsys):
    import argparse
    from strata360 import cli
    from strata360.pipeline import config
    from strata360.edit import music_build as MB, lyrics as LY
    f, rd = project(tmp_path); open(os.path.join(rd, 'music', 'track.mp3'), 'wb').write(b'x'); seen = {}
    monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1')                                                                   # (the build is faked: the machine's load and free memory are not what this test is about)
    monkeypatch.setattr(config, 'race_dir', lambda name: rd); monkeypatch.setattr(PJ, 'music_record', lambda folder, s: dict(file='music/track.mp3')); monkeypatch.setattr(LY, 'view', lambda folder: None)
    monkeypatch.setattr(MB, 'grid', lambda rd_, rel: dict(downbeats=[2.0 * i for i in range(30)]))
    json.dump(dict(style='rap rock'), open(os.path.join(rd, 'music', 'built.json'), 'w'))
    def build(rd_, rel, length, **kw):
        seen.update(kw); return dict(file='music/built.flac', length_s=length, bpm=120.0, key={}, worst_join=0.1, stray_vocal_db=None, windows=[], partial_windows=[], fidelity=kw['fidelity'], share_original=0.5, check=dict(ok=True),
                                     generated=[dict(first=4, end=12, mode='repaint', seed=1), dict(first=20, end=24, kept_original=True, why='no take kept time with the grid')])
    monkeypatch.setattr(MB, 'build', build)
    a = argparse.Namespace(name=f, length_s=60.0, track=None, vocals=None, preset='flat', levels=None, no_sing=True, use=False, fidelity=0.5, pin=['8=generate'], style=None, take=['abc=3'], no_generate=False)
    cli.cmd_music_build(a); out = capsys.readouterr().out
    assert seen['fidelity'] == 0.5 and seen['section_pins'] == {8: 'generate'} and seen['takes'] == {'abc': 3} and seen['style'] == 'rap rock' and callable(seen['generator'])           # the style is remembered from the last build
    assert 'bars 5 to 12: generated (repaint, take 1)' in out and "bars 21 to 24: the track's own bars: no take kept time" in out
    with pytest.raises(SystemExit, match='--pin'): cli.cmd_music_build(argparse.Namespace(**dict(vars(a), pin=['8=loud'])))
    cli.cmd_music_build(argparse.Namespace(**dict(vars(a), no_generate=True, style='funk'))); assert seen['generator'] is None and seen['style'] == 'funk'
