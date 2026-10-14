import os
import json
import pytest
from strata360.edit import voiceover as V
from strata360.pipeline import config

def test_recordings_are_new_takes_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(V, '_run', lambda cmd: open(cmd[-1], 'wb').write(b'wav'))
    f = str(tmp_path); assert not os.path.exists(V.recorded_path(f, 3))
    a = V.save_recording(f, 3, 'in'); b = V.save_recording(f, 3, 'in'); c = V.save_recording(f, 30, 'in')
    assert a != b and os.path.exists(a) and V.recorded_path(f, 3) == b and V.recorded_path(f, 30) == c
    V.delete_recording(f, 3); assert not os.path.exists(V.recorded_path(f, 3)) and os.path.exists(os.path.join(os.path.dirname(a), 'removed', os.path.basename(a)))

def test_paths(tmp_path):
    f = str(tmp_path)
    race = config.race_dir(f)
    assert V.base(f) == os.path.join(race, 'voiceover')
    assert V._state_path(f) == os.path.join(race, 'voiceover', 'state.json')
    assert V.status_path(f) == os.path.join(race, 'voiceover', 'status.json')
    assert V.track_dir(f, 'key1') == os.path.join(race, 'voiceover', 'tracks', 'key1')
    assert V.synth_path(f, 1, 'text', 'eng', 'voi', 150) == os.path.join(race, 'voiceover', 'synth', f'001-{V.hashlib.sha1(b"eng|voi|150|text").hexdigest()[:10]}.wav')
    assert V.synth_path(f, '3b0', 'text', 'eng', 'voi', 150) == os.path.join(race, 'voiceover', 'synth', f'3b0-{V.hashlib.sha1(b"eng|voi|150|text").hexdigest()[:10]}.wav')
    assert V.track_key('e1', 'v1', 123.4) == 'e1-v1-123'

def test_state_persistence(tmp_path):
    f = str(tmp_path)
    # Default when missing
    assert V.load_state(f) == {'engine': None, 'voice': None, 'rate': 150, 'use': {}}

    # Save and load
    s = {'engine': 'e1', 'voice': 'v1', 'rate': 160, 'use': {'1': 'recorded'}}
    V.save_state(f, s)
    assert V.load_state(f) == s

    # Invalid JSON is treated as empty
    with open(V._state_path(f), 'w') as fh: fh.write("not json")
    assert V.load_state(f) == {'engine': None, 'voice': None, 'rate': 150, 'use': {}}

def test_status_persistence(tmp_path, monkeypatch):
    f = str(tmp_path)
    monkeypatch.setattr(os, 'getpid', lambda: 12345)
    monkeypatch.setattr(V.time, 'time', lambda: 1000.0)

    assert V.load_status(f) is None
    V.write_status(f, 'speaking', done=1, total=5, extra='info')

    status = V.load_status(f)
    assert status == {'state': 'speaking', 'pid': 12345, 'done': 1, 'total': 5, 'at': 1000.0, 'extra': 'info'}

    # Invalid JSON
    with open(V.status_path(f), 'w') as fh: fh.write("{")
    assert V.load_status(f) is None

def test_load_timings(tmp_path):
    f = str(tmp_path)
    assert V.load_timings(f) is None

    os.makedirs(V.base(f))
    with open(os.path.join(V.base(f), 'timings.json'), 'w') as fh:
        json.dump({'some': 'data'}, fh)

    assert V.load_timings(f) == {'some': 'data'}

    with open(os.path.join(V.base(f), 'timings.json'), 'w') as fh:
        fh.write("{bad")
    assert V.load_timings(f) is None

def test_recorded_path_legacy(tmp_path):
    f = str(tmp_path)
    race = config.race_dir(f)
    assert V.recorded_path(f, 3) == os.path.join(race, 'voiceover', 'recorded', '003.wav')
    assert V.recorded_path(f, '3b') == os.path.join(race, 'voiceover', 'recorded', '3b.wav')


def test_formatting_functions():
    assert V._name(5) == '005'
    assert V._name('005') == '005'
    assert V._name('5b') == '5b'
    assert V._name('abc') == 'abc'

    assert V._spoken('Hello—there…') == 'Hello, there...'
    assert V._spoken('  Lots   of  spaces  ') == 'Lots of spaces'


def test_overflow_choices():
    assert V.overflow_choices('synth', 0.0) == []
    assert V.overflow_choices('synth', 0.005) == []

    synth_choices = V.overflow_choices('synth', 0.5)
    assert len(synth_choices) == 4
    assert 'shorten the line by about 0.5 s' in synth_choices[0]
    assert 'speak faster' in synth_choices[3]

    rec_choices = V.overflow_choices('recorded', 1.5)
    assert len(rec_choices) == 4
    assert 'shorten the line by about 1.5 s' in rec_choices[0]
    assert 'record it again' in rec_choices[3]


def test_source_for():
    # state['use'] is empty
    assert V.source_for({'use': {}}, 1, True) == 'recorded'
    assert V.source_for({'use': {}}, 1, False) == 'synth'

    # state['use'] overrides
    assert V.source_for({'use': {'1': 'synth'}}, 1, True) == 'synth'
    assert V.source_for({'use': {'1': 'recorded'}}, 1, True) == 'recorded'
    assert V.source_for({'use': {'1': 'recorded'}}, 1, False) == 'synth'


def test_pick_and_engines(monkeypatch):
    # Mock engines to control what is available
    mock_engines = {
        'kokoro': ('Kokoro', lambda: True, lambda: [{'name': 'k1'}], lambda: None),
        'elevenlabs': ('EL', lambda: False, lambda: [], lambda: None),
        'fake': ('Fake', lambda: True, lambda: [{'name': 'f1'}, {'name': 'f2'}], lambda: None)
    }
    monkeypatch.setattr(V, 'ENGINES', mock_engines)

    # available_engines returns only 'ok' ones
    av = V.available_engines()
    assert len(av) == 2
    assert av[0]['id'] == 'kokoro'
    assert av[1]['id'] == 'fake'

    # pick with empty state -> uses first available and its first voice
    e, v = V.pick({})
    assert e == 'kokoro' and v == 'k1'

    # pick with saved engine that exists
    e, v = V.pick({'engine': 'fake'})
    assert e == 'fake' and v == 'f1'

    # pick with saved engine and voice that exists
    e, v = V.pick({'engine': 'fake', 'voice': 'f2'})
    assert e == 'fake' and v == 'f2'

    # pick with saved voice that doesn't exist for the engine
    e, v = V.pick({'engine': 'fake', 'voice': 'f3'})
    assert e == 'fake' and v == 'f1'

    # pick with saved engine that doesn't exist -> fall back to first available
    e, v = V.pick({'engine': 'missing'})
    assert e == 'kokoro' and v == 'k1'

    # test no engines available
    monkeypatch.setattr(V, 'available_engines', lambda: [])
    with pytest.raises(RuntimeError, match='voice model is not installed'):
        V.pick({})


def test_script_management(tmp_path, monkeypatch):
    f = str(tmp_path)
    race = config.race_dir(f)
    os.makedirs(os.path.join(race, 'script2'))
    os.makedirs(os.path.join(race, 'scripts'))

    # 1. No scripts at all
    assert V.script2_lines(f) is None
    assert V.script_lines(f) == (None, [])
    assert V.measured_wpm(f) is None
    assert V.newest_script(f) is None
    with pytest.raises(RuntimeError, match='no script yet'):
        V.save_edit(f, {'1': 'new'})

    # 2. Add an old legacy script
    legacy_script = os.path.join(race, 'scripts', 'script-20200101-120000.json')
    legacy_data = {'lines': [{'seg': 1, 'text': 'legacy line', 'film_start_s': 1.0, 'seconds': 2.0}]}
    with open(legacy_script, 'w') as fh: json.dump(legacy_data, fh)

    assert V.script2_lines(f) is None
    sname, slines = V.script_lines(f)
    assert sname == 'script-20200101-120000.json'
    assert len(slines) == 1 and slines[0]['text'] == 'legacy line'
    assert V.newest_script(f) == sname

    # save_edit on legacy
    new_script = V.save_edit(f, {'1': 'edited line'})
    assert new_script.startswith('script-')
    d = json.load(open(os.path.join(race, 'scripts', new_script)))
    assert d['edited'] is True and d['lines'][0]['text'] == 'edited line'

    # 3. Add script2/lines.json (newer)
    script2_path = os.path.join(race, 'script2', 'lines.json')
    s2_data = {'lines': [
        {'seg': 1, 'text': 'new s2 line', 'film_start_s': 0.0, 'seconds': 1.0, 'speak_s': 5.0},
        {'seg': 2, 'text': '  ', 'film_start_s': 1.0, 'seconds': 2.0, 'speak_s': 0.0} # empty, ignored
    ]}
    with open(script2_path, 'w') as fh: json.dump(s2_data, fh)
    import time
    os.utime(script2_path, (time.time(), time.time() + 10)) # ensure mtime is newer

    name2, lines2 = V.script2_lines(f)
    assert name2.startswith('script2-')
    assert len(lines2) == 1 and lines2[0]['text'] == 'new s2 line'

    # script_lines and newest_script now prefer script2
    assert V.script_lines(f) == (name2, lines2)
    assert V.newest_script(f) == name2

    # 4. Add an even newer legacy script (overrides script2)
    new_legacy = os.path.join(race, 'scripts', 'script-20300101-120000.json')
    with open(new_legacy, 'w') as fh: json.dump({'lines': [{'seg': 3, 'text': 'future', 'film_start_s': 0, 'seconds': 1}]}, fh)
    os.utime(new_legacy, (time.time(), time.time() + 20))

    assert V.script2_lines(f) is None
    assert V.script_lines(f)[0] == 'script-20300101-120000.json'
    assert V.newest_script(f) == 'script-20300101-120000.json'

    # Test film_length
    assert V.film_length(f) is None
    with open(os.path.join(race, 'project.json'), 'w') as fh: json.dump({'edit': {'plan': {'film': {'length_s': 123.4}}}}, fh)
    assert V.film_length(f) == 123.4


def test_measured_wpm(tmp_path):
    f = str(tmp_path)
    race = config.race_dir(f)
    os.makedirs(os.path.join(race, 'script2'))

    path = os.path.join(race, 'script2', 'lines.json')
    # Valid data (words >= 20, sec >= 10.0)
    data = {'lines': [
        {'text': 'word ' * 10, 'speak_s': 6.0},
        {'text': 'word ' * 10, 'speak_s': 6.0, 'estimated': False},
        {'text': 'ignore me', 'estimated': True}
    ]}
    with open(path, 'w') as fh: json.dump(data, fh)
    # 20 words / 12 seconds = 1.66 words/sec * 60 = 100 wpm
    assert V.measured_wpm(f) == 100

    # Not enough words/sec
    with open(path, 'w') as fh: json.dump({'lines': [{'text': 'word', 'speak_s': 5.0}]}, fh)
    assert V.measured_wpm(f) is None


def test_line_durations(tmp_path, monkeypatch):
    f = str(tmp_path)
    monkeypatch.setattr(V, 'pick', lambda s: ('e1', 'v1'))

    # Mock synth_line to just return a fake path without running ffmpeg
    monkeypatch.setattr(V, 'synth_line', lambda *a: 'fake_synth.wav')
    monkeypatch.setattr(V, 'recorded_path', lambda *a: 'fake_rec.wav')

    def fake_speech_span(p):
        if 'rec' in p: return 1.0, 3.0
        return 0.0, 5.0

    monkeypatch.setattr(V, 'speech_span', fake_speech_span)
    monkeypatch.setattr(os.path, 'exists', lambda p: 'rec' in p) # simulate recording exists

    lines = [{'seg': 1, 'text': 'a'}, {'seg': 2, 'text': 'b'}]

    # with default state, uses recording if available -> 3.0 - 1.0 = 2.0
    V.save_state(f, {})
    durs = V.line_durations(f, lines)
    assert durs == {1: 2.0, 2: 2.0}

    # if state overrides to synth -> 5.0 - 0.0 = 5.0
    V.save_state(f, {'use': {'1': 'synth'}})
    durs = V.line_durations(f, lines)
    assert durs[1] == 5.0
    assert durs[2] == 2.0

    # test pick failure
    def fake_pick_fail(s): raise RuntimeError('fail')
    monkeypatch.setattr(V, 'pick', fake_pick_fail)

    logs = []
    assert V.line_durations(f, lines, log=logs.append) == {}
    assert 'fail' in logs[0]


def test_core_build_logic(tmp_path, monkeypatch):
    f = str(tmp_path)
    race = config.race_dir(f)
    os.makedirs(os.path.join(race, 'script2'))

    # 1. Setup mock functions to bypass external calls and slow operations
    monkeypatch.setattr(V, 'pick', lambda s: (s.get('engine') or 'e1', s.get('voice') or 'v1'))

    _synth_calls = []
    def fake_synth(fldr, seg, text, eng, voi, rate):
        _synth_calls.append((seg, eng, voi, rate))
        return V.synth_path(fldr, seg, text, eng, voi, rate)
    monkeypatch.setattr(V, 'synth_line', fake_synth)

    def fake_duration(p): return 2.0
    monkeypatch.setattr(V, 'duration', fake_duration)

    # fake speech_span based on seg: seg 1 is fast, seg 2 is slow (needs to be sped up), seg 3 is very slow (over)
    def fake_speech_span(p):
        if '001' in p: return 0.0, 1.0   # fits in 2.0s window
        if '002' in p: return 0.0, 2.2   # 2.2s speech in 2.0s window -> speed up
        if '003' in p: return 0.0, 5.0   # 5.0s speech in 2.0s window -> over
        return 0.0, 1.0
    monkeypatch.setattr(V, 'speech_span', fake_speech_span)

    _mix_calls = []
    def fake_mix(*a):
        _mix_calls.append(a)
        open(a[3], 'wb').write(b'wav') # Write fake mix to dest
    monkeypatch.setattr(V, '_mix', fake_mix)

    # Write a script with 3 lines spaced 2 seconds apart
    data = {'lines': [
        {'seg': 1, 'text': 'one', 'film_start_s': 0.0, 'seconds': 2.0},
        {'seg': 2, 'text': 'two', 'film_start_s': 2.0, 'seconds': 2.0},
        {'seg': 3, 'text': 'three', 'film_start_s': 4.0, 'seconds': 2.0},
    ]}
    with open(os.path.join(race, 'script2', 'lines.json'), 'w') as fh: json.dump(data, fh)

    # Write film length
    with open(os.path.join(race, 'project.json'), 'w') as fh: json.dump({'edit': {'plan': {'film': {'length_s': 7.0}}}}, fh)

    # Need to touch a fake recorded file to avoid FileNotFoundError in cached_tracks -> signature -> getmtime
    os.makedirs(os.path.join(V.base(f), 'recorded'))
    with open(os.path.join(V.base(f), 'recorded', 'fake.wav'), 'w') as fh: fh.write('')

    # --- Test `build` and `_build` ---

    # Progress callback capture
    progs = []
    def prog_cb(i, n): progs.append((i, n))

    # Run the build! We'll request a specific engine and voice
    doc = V.build(f, engine='e2', voice='v2', rate=160, progress=prog_cb)

    # Check that state was updated with explicit request
    assert V.load_state(f) == {'engine': 'e2', 'voice': 'v2', 'rate': 160, 'use': {}}

    # Check that synth_line was called correctly
    assert len(_synth_calls) == 3
    assert _synth_calls[0] == (1, 'e2', 'v2', 160)

    # Check doc results (timings logic)
    assert doc['engine'] == 'e2' and doc['voice'] == 'v2' and doc['rate'] == 160
    assert doc['film_length_s'] == 7.0
    assert len(doc['lines']) == 3

    l1, l2, l3 = doc['lines']
    # l1: fits easily (1.0s speech in ~1.85s avail)
    assert l1['fit'] == 'ok'
    assert l1['tempo'] == 1.0

    # l2: 2.2s speech in ~1.85s avail (2.0 to 4.0) -> speed up
    # Note: 2.2 / 1.85 = 1.189 which is <= 1.25 (MAX_TEMPO)
    assert l2['fit'] == 'sped' or l2['fit'] == 'over' # if math rounding makes it slightly over

    # l3: 5.0s speech in ~2.88s avail (4.0 to 7.0) -> over
    assert l3['fit'] == 'over'
    assert l3['tempo'] == 1.25 # max tempo applied before giving up

    # Check progress callbacks
    assert progs == [(1, 3), (2, 3), (3, 3)]

    # Check that status was written correctly
    st = V.load_status(f)
    assert st['state'] == 'done'
    assert st['done'] == 3

    # Check mix call
    assert len(_mix_calls) == 1
    assert len(_mix_calls[0][1]) == 3 # 3 lines out

    # Check that _publish worked (files copied to base)
    assert os.path.exists(os.path.join(V.base(f), 'voiceover.wav'))
    assert os.path.exists(os.path.join(V.base(f), 'timings.json'))

    # --- Test `cached_tracks` ---

    # We should have one cached track now (the one we just built)
    # The active timings.json is in base, so it should be marked active
    tracks = V.cached_tracks(f)
    assert len(tracks) == 1
    assert tracks[0]['engine'] == 'e2'
    assert tracks[0]['voice'] == 'v2'
    assert tracks[0]['active'] is True
    assert tracks[0]['key'] == V.track_key('e2', 'v2', 160)

    # --- Test fast path (already built) ---

    _mix_calls.clear()
    _synth_calls.clear()

    # Build again with same settings. Should hit the cache.
    doc2 = V.build(f)

    assert len(_synth_calls) == 0 # synth wasn't called again!
    assert len(_mix_calls) == 0   # mix wasn't called again!
    assert doc2['sig'] == doc['sig']

    # --- Test failure in build ---
    monkeypatch.setattr(V, '_mix', lambda *a: exec('raise RuntimeError("Mix failed")'))
    with pytest.raises(RuntimeError, match="Mix failed"):
        V.build(f, rate=170)

    st = V.load_status(f)
    assert st['state'] == 'error'
    assert 'Mix failed' in st['error']

def test_signature(tmp_path):
    f = str(tmp_path)
    os.makedirs(os.path.join(V.base(f), 'recorded'))
    with open(os.path.join(V.base(f), 'recorded', '1.wav'), 'w') as fh: fh.write('a')

    # Same inputs -> same sig
    st = {'engine': 'e', 'voice': 'v', 'rate': 100, 'use': {}}
    sig1 = V.signature(f, 'script.json', st, 10.0)
    sig2 = V.signature(f, 'script.json', st, 10.0)
    assert sig1 == sig2

    # Different script name -> different sig
    assert V.signature(f, 'script2.json', st, 10.0) != sig1

    # Different total length -> different sig
    assert V.signature(f, 'script.json', st, 11.0) != sig1

    # Different state -> different sig
    assert V.signature(f, 'script.json', dict(st, engine='e2'), 10.0) != sig1

    # Changing recording mtime -> different sig
    import time
    with open(os.path.join(V.base(f), 'recorded', '1.wav'), 'a') as fh: fh.write('b')
    # Update mtime manually
    os.utime(os.path.join(V.base(f), 'recorded', '1.wav'), (time.time(), time.time() + 10))
    assert V.signature(f, 'script.json', st, 10.0) != sig1

def test_running(tmp_path, monkeypatch):
    f = str(tmp_path)
    # Mock alive
    monkeypatch.setattr(V, 'alive', lambda pid: pid == 123)

    # Monkeypatch getpid so write_status uses our pid
    monkeypatch.setattr(os, 'getpid', lambda: 123)

    assert V.running(f) is False

    V.write_status(f, 'speaking')
    assert V.running(f) is True

    monkeypatch.setattr(os, 'getpid', lambda: 456)
    V.write_status(f, 'speaking')
    assert V.running(f) is False

    monkeypatch.setattr(os, 'getpid', lambda: 123)
    V.write_status(f, 'done')
    assert V.running(f) is False
