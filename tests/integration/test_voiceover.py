"""Voice-over timing, fitting and recorded replacements with a fake speech engine (the `fake_engine` fixture: runs on any platform with ffmpeg, no TTS model)."""
import json, os
import pytest
from library import duration, make_tone


def L(seg, text, start, seconds): return dict(seg=seg, text=text, film_start_s=start, seconds=seconds)


@pytest.fixture
def speech(tmp_path, fake_engine):
    """`speech(lines)` -> a project folder whose newest script holds `lines` and whose film is 20 s long; the module is `fake_engine`."""
    def make(lines):
        f = str(tmp_path / 'proj'); rd = os.path.join(f, 'strata360'); os.makedirs(os.path.join(rd, 'scripts'), exist_ok=True)
        json.dump(dict(lines=lines), open(os.path.join(rd, 'scripts', 'script-1.json'), 'w'))
        json.dump(dict(edit=dict(plan=dict(film=dict(length_s=20.0)))), open(os.path.join(rd, 'project.json'), 'w')); return f
    return make


def by_seg(d): return {o['seg']: o for o in d['lines']}


class TestFitting:
    def test_lines_are_placed_and_fit_or_are_sped_or_flagged(self, speech, fake_engine):
        V = fake_engine; f = speech([L(0, 'one two three', 0.0, 3.0), L(1, 'a b c d e f g h i j k l', 3.0, 1.0), L(2, 'x ' * 60, 4.0, 2.0), L(3, '', 6.0, 2.0), L(4, 'end', 8.0, 2.0)])
        d = V.build(f); by = by_seg(d)
        assert [o['seg'] for o in d['lines']] == [0, 1, 2, 4]                                  # an empty line is not spoken
        assert by[0]['fit'] == 'ok' and by[0]['film_start_s'] == pytest.approx(0.12)
        assert by[1]['fit'] in ('sped', 'over') and by[2]['fit'] == 'over' and 2 in d['over'] and by[2]['overrun_s'] > 0
        assert duration(os.path.join(V.base(f), 'voiceover.wav')) == pytest.approx(20.0, abs=0.05)         # the track is as long as the film
        assert d['measured_wpm'] == pytest.approx(600, abs=40)

    def test_a_line_may_run_into_windows_that_have_no_line(self, speech, fake_engine):
        f = speech([L(0, ' '.join('w' * 1 for _ in range(28)), 0.0, 1.0), L(1, 'next', 5.0, 2.0)])       # 2.8 s in a 1 s window, but nothing until 5.0
        d = fake_engine.build(f); assert d['lines'][0]['fit'] == 'ok' and d['lines'][0]['room_s'] > 4


class TestReuseAndRecordings:
    def test_an_unchanged_line_is_not_spoken_again(self, speech, fake_engine):
        V = fake_engine; f = speech([L(0, 'one two', 0.0, 3.0), L(1, 'three four five', 3.0, 3.0)]); d = V.build(f)
        p = os.path.join(V.base(f), d['lines'][0]['path']); m = os.path.getmtime(p); V.build(f)
        assert os.path.getmtime(p) == m

    def test_a_recording_replaces_the_synthetic_line_until_the_user_switches_back(self, speech, fake_engine, tmp_path):
        V = fake_engine; f = speech([L(0, 'one two', 0.0, 3.0), L(1, 'three four five', 3.0, 3.0)]); V.build(f)
        V.save_recording(f, 1, make_tone(tmp_path / 'take.wav', 1.5, 500)); o = by_seg(V.build(f))
        assert o[1]['source'] == 'recorded' and o[1]['natural_s'] == pytest.approx(1.5, abs=0.1) and o[0]['source'] == 'synth'
        st = V.load_state(f); st['use']['1'] = 'synth'; V.save_state(f, st)
        assert by_seg(V.build(f))[1]['source'] == 'synth'

    def test_a_recording_can_be_deleted(self, speech, fake_engine, tmp_path):
        V = fake_engine; f = speech([L(0, 'one two', 0.0, 3.0)]); V.save_recording(f, 0, make_tone(tmp_path / 'take.wav', 1.0))
        assert os.path.exists(V.recorded_path(f, 0)); V.delete_recording(f, 0); assert not os.path.exists(V.recorded_path(f, 0))


class TestScriptVersions:
    def test_an_edited_script_is_a_new_version_that_is_spoken_and_progress_is_recorded(self, speech, fake_engine):
        V = fake_engine; f = speech([L(0, 'one two three', 0.0, 3.0), L(1, 'four five', 3.0, 3.0)]); d = V.build(f)
        st = V.load_status(f); assert st['state'] == 'done' and st['done'] == st['total'] == 2 and not V.running(f)
        old = V.newest_script(f); name = V.save_edit(f, {'1': 'four five six seven'})
        assert name and name > old and V.newest_script(f) == name
        assert V.save_edit(f, {'1': 'four five six seven'}) is None                                    # unchanged: no new version
        assert os.path.exists(os.path.join(V.config.race_dir(f), 'scripts', old))                       # the old one is kept
        d2 = V.build(f); assert d2['script'] == name and by_seg(d2)[1]['text'] == 'four five six seven'
        assert by_seg(d2)[0]['path'] == by_seg(d)[0]['path']                                            # the unchanged line was not spoken again


class TestVoices:
    def test_each_voice_keeps_its_own_track_so_swapping_is_instant_and_a_newer_choice_is_not_lost(self, speech, fake_engine):
        V = fake_engine; f = speech([L(0, 'one two three', 0.0, 3.0), L(1, 'four five', 3.0, 3.0)])
        V.build(f, voice='Test'); ta = os.path.join(V.track_dir(f, V.track_key('fake', 'Test', 150)), 'voiceover.wav'); m = os.path.getmtime(ta)
        b = V.build(f, voice='Other')
        assert b['voice'] == 'Other' and V.load_timings(f)['voice'] == 'Other' and {c['voice'] for c in V.cached_tracks(f)} == {'Test', 'Other'}
        assert [c['voice'] for c in V.cached_tracks(f) if c['active']] == ['Other']
        a2 = V.build(f, voice='Test'); assert os.path.getmtime(ta) == m and a2['voice'] == 'Test' and V.load_timings(f)['voice'] == 'Test'      # back to the first: just switched
        assert V.load_state(f)['voice'] == 'Test'                                                      # the job never writes a voice back over the user's choice
        V.save_edit(f, {'1': 'four five six'}); assert V.cached_tracks(f) == []                        # a new script makes every old track stale
        V.build(f, voice='Other'); assert [c['voice'] for c in V.cached_tracks(f)] == ['Other']

    def test_no_engine_is_reported_clearly(self, monkeypatch, fake_engine):
        monkeypatch.setattr(fake_engine, 'ENGINES', {'none': ('None', lambda: False, lambda: [], None)})
        with pytest.raises(RuntimeError, match='voice model is not installed'): fake_engine.pick({})


class TestMeasure:
    def test_block_script_lines_are_spoken_at_natural_length_and_measured(self, speech, fake_engine, tmp_path):
        from strata360.edit import vo_measure as M
        V = fake_engine; f = speech([]); doc = dict(title='T', lines=[dict(block=0, anchor=None, text='one two three'), dict(block=1, anchor='before', text='four five six seven eight'), dict(block=1, anchor='after', text='')])
        def al(x, w): n = len(w); return [(i * 0.1, (i + 1) * 0.1, 0.9) for i in range(n)]
        d = M.measure_script(f, doc, al)
        assert [l['key'] for l in d['lines']] == ['000n0', '001b0'] and [l['take'] for l in d['lines']] == ['synth', 'synth'] and {l['status'] for l in d['lines']} == {'short'}       # the tone voice reads 600 words a minute: far faster than a person, so the words-missing check fires
        assert d['lines'][0]['natural_s'] == pytest.approx(0.3, abs=0.05) and d['lines'][1]['natural_s'] == pytest.approx(0.5, abs=0.05)            # 0.1 s a word: no tempo change
        V.save_recording(f, '000n0', make_tone(tmp_path / 'take.wav', 1.2, 500)); d = M.measure_script(f, doc, lambda x, w: [(i * 0.4, (i + 1) * 0.4, 0.9) for i in range(len(w))])
        assert d['lines'][0]['take'] == 'recorded' and d['lines'][0]['natural_s'] == pytest.approx(1.2, abs=0.1) and os.path.exists(M.vo_path(f))


class TestFitRespeak:
    def test_a_line_too_long_for_its_footage_is_spoken_again_faster_and_then_fits(self, speech, monkeypatch, tmp_path):
        from strata360.edit import blocks as B, vo_fit as F, vo_measure as M, voiceover as V
        def speak(voice, rate, text, out): make_tone(out, len(text.split()) * 0.4 * 150.0 / rate, hz=300)         # a voice whose pace follows the requested words a minute
        monkeypatch.setattr(V, 'ENGINES', {'fake': ('Fake', lambda: True, lambda: [dict(name='Test', lang='en_GB')], speak)})
        f = speech([]); clips = [dict(id='C00', start_utc='2026-02-19T10:00:00Z', duration_s=15.0, candidates=[dict(id='C00#00', clip='C00', kind='span', start_s=0.0, end_s=10.0, quality=0.6, priority=1)])]
        plan = B.plan_blocks(clips, 10.0); script = dict(title='T', lines=[dict(block=0, anchor=None, text=' '.join(['w'] * 25))])           # 10 s of speech in 10 s of footage, plus 1 s of leads
        al = lambda x, w: [(i * 0.4, (i + 1) * 0.4, 0.9) for i in range(len(w))]
        fit = F.fit_project(f, plan, script, aligner=al); b = fit.blocks[0]; l = b.lines[0]
        assert b.tempo == pytest.approx(10 / 9, abs=0.002) and l.applied == pytest.approx(b.tempo) and l.tempo == 1.0 and b.overflow_s == 0 and fit.problems == []
        assert l.end_s - l.start_s == pytest.approx(10 / b.tempo, abs=0.15) and b.length_s <= 10.0 + 1e-6
        assert M.load(f)['lines'][0]['tempo_applied'] == pytest.approx(b.tempo, abs=0.002)
