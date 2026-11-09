"""Whisper through strata-models (strata360.audio.remote_whisper): when it is used, and that it answers like faster-whisper, with a fake client."""
import sys, types, wave

import numpy as np
import pytest

from strata360.audio import remote_whisper as RW


def fake_client(calls, running=True, transcribe=None):
    m = types.ModuleType('strata_models_client')
    m.available = lambda: running
    def run(role, params, app, model=None):
        calls.append((role, dict(params), app, model))
        if params.get('path', '').endswith('.wav'):
            with wave.open(params['path']) as w: calls.append(('wav', w.getframerate(), w.getnframes()))
        if params.get('detect_language_only'): return dict(language='fr', language_probability=0.7, all_language_probs={'en': 0.2, 'fr': 0.7, 'nl': 0.1})
        return transcribe or dict(language='en', language_probability=0.99, duration=11.0, segments=[dict(start=0.0, end=2.5, text=' Ask not', avg_logprob=-0.2, no_speech_prob=0.01, words=[dict(start=0.0, end=0.4, word=' Ask', probability=0.9)]), dict(start=3.0, end=4.0, text=' (pause)', avg_logprob=-1.2, no_speech_prob=0.7, words=[])])
    m.run = run
    return m


def test_used_only_when_the_service_runs_knows_the_model_and_is_not_switched_off(monkeypatch):
    calls = []; monkeypatch.delenv('STRATA360_MODELS', raising=False)
    monkeypatch.setitem(sys.modules, 'strata_models_client', fake_client(calls))
    assert RW.use_service('large-v3') and RW.use_service('small') and not RW.use_service('medium')
    monkeypatch.setenv('STRATA360_MODELS', 'local'); assert not RW.use_service('large-v3')
    monkeypatch.delenv('STRATA360_MODELS'); monkeypatch.setitem(sys.modules, 'strata_models_client', fake_client(calls, running=False)); assert not RW.use_service('large-v3')
    monkeypatch.setitem(sys.modules, 'strata_models_client', None); assert not RW.use_service('large-v3')        # not installed


def test_transcribe_a_path_and_an_array_like_faster_whisper(monkeypatch, tmp_path):
    calls = []; m = RW.ServiceWhisper('large-v3', client=fake_client(calls))
    segs, info = m.transcribe(str(tmp_path / 'a.flac'), language='en', word_timestamps=True, beam_size=5, clip_timestamps=[1.0, 9.0])
    assert info.language == 'en' and info.duration == 11.0 and segs[0].text == ' Ask not' and segs[0].words[0].word == ' Ask' and segs[1].words is None
    assert calls[0] == ('transcribe', dict(path=str(tmp_path / 'a.flac'), language='en', word_timestamps=True, beam_size=5, clip=[1.0, 9.0]), 'strata-360', 'whisper-large-v3')
    lang, p, scores = RW.ServiceWhisper('small', client=fake_client(calls)).detect_language(np.zeros(16000, np.float32))
    assert (lang, p, scores[0]) == ('fr', 0.7, ('fr', 0.7)) and calls[1][0] == 'transcribe-fast' and calls[1][1]['detect_language_only'] and calls[2] == ('wav', 16000, 16000)
    with pytest.raises(TypeError, match='hotwords'): m.transcribe('x.wav', hotwords='strata')


def test_whisper_model_falls_back_to_faster_whisper_loaded_here(monkeypatch):
    fw = types.ModuleType('faster_whisper'); made = []
    fw.WhisperModel = lambda name, device, compute_type: made.append((name, device, compute_type)) or 'local'
    monkeypatch.setitem(sys.modules, 'faster_whisper', fw)
    assert RW.whisper_model('large-v3', 'cpu', 'int8') == 'local' and made == [('large-v3', 'cpu', 'int8')]
    calls = []; monkeypatch.delenv('STRATA360_MODELS'); monkeypatch.setitem(sys.modules, 'strata_models_client', fake_client(calls))
    assert isinstance(RW.whisper_model('large-v3'), RW.ServiceWhisper)


def test_the_speech_stage_runs_unchanged_on_the_service(monkeypatch):
    """transcribe_multilingual with the service's model: language per chunk, then the chunk transcribed in it, times made clip-relative."""
    from strata360.audio import speech
    calls = []; m = RW.ServiceWhisper('large-v3', client=fake_client(calls))
    monkeypatch.setattr(speech, 'speech_chunks', lambda x16: [[1.0, 3.0]])
    segs = speech.transcribe_multilingual(np.zeros(16000 * 4, np.float32), m, allowed=['en', 'fr'], translate=False)
    assert [s['lang'] for s in segs] == ['fr', 'fr'] and segs[0]['t0'] == 1.0 and segs[0]['words'][0]['w'] == 'Ask'
    assert [c[1].get('language') for c in calls if c[0] == 'transcribe' and not c[1].get('detect_language_only')] == ['fr']
