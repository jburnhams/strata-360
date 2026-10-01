import pytest
import sys
from strata360.audio import speech

def test_flag_segment():
    # Empty / clean segment
    seg = {'text': 'hello world', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': [{'w': 'hello'}, {'w': 'world'}]}
    assert speech.flag_segment(seg) == []

    # Hallucination phrases
    seg = {'text': 'Thanks for watching.', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': []}
    assert 'hallucination_phrase' in speech.flag_segment(seg)

    seg = {'text': 'Sous-titres par Amara.org', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': []}
    assert 'hallucination_phrase' in speech.flag_segment(seg)

    # Low confidence
    seg = {'text': 'blurgh', 'avg_logprob': -1.2, 'no_speech': 0.1, 'words': []}
    assert 'low_confidence' in speech.flag_segment(seg)

    # Probably no speech
    seg = {'text': 'noise', 'avg_logprob': -0.5, 'no_speech': 0.7, 'words': []}
    assert 'probably_no_speech' in speech.flag_segment(seg)

    # Repetition
    # Less than 6 words: no flag
    seg = {'text': 'a a a a a', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': [{'w': 'a'}] * 5}
    assert 'repetition' not in speech.flag_segment(seg)

    # 6 words, all same
    seg = {'text': 'a a a a a a', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': [{'w': 'a'}] * 6}
    assert 'repetition' in speech.flag_segment(seg)

    # 6 words, not repeating enough (ratio <= 0.6)
    # len=6, unique=3, rep_ratio = 1 - 3/6 = 0.5
    seg = {'text': 'a b c a b c', 'avg_logprob': -0.5, 'no_speech': 0.1, 'words': [{'w': 'a'}, {'w': 'b'}, {'w': 'c'}] * 2}
    assert 'repetition' not in speech.flag_segment(seg)



def test_translate_text(monkeypatch):
    # Empty text
    assert speech.translate_text('   ', 'fr') == '   '
    # English text
    assert speech.translate_text('bonjour', 'en') == 'bonjour'

    # Mock the internal cache _MT and torch.no_grad
    from fakes import mock_torch, mock_transformers, FakeHuggingFaceTokenizer, FakeHuggingFaceModel
    mock_torch(monkeypatch)
    mock_transformers(monkeypatch)
    monkeypatch.setattr(speech, '_MT', {'fr': (FakeHuggingFaceTokenizer(), FakeHuggingFaceModel())})

    # Needs to fetch from our cache
    res = speech.translate_text('bonjour', 'fr')
    assert res == 'BONJOUR_TRANSLATED'

def test_translate_text_uncached(monkeypatch):
    from fakes import mock_torch, mock_transformers
    mock_torch(monkeypatch)
    mock_transformers(monkeypatch)

    speech._MT.clear() # force un-cached fetch
    res = speech.translate_text('bonjour uncached', 'fr')
    assert res == 'BONJOUR UNCACHED_TRANSLATED'
    assert 'fr' in speech._MT

def test_load_models_same(monkeypatch):
    import types
    fake_fw = types.ModuleType('faster_whisper')
    class FakeWhisperModel:
        def __init__(self, size, **kwargs):
            self.size = size
    fake_fw.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_fw)

    # test where translate_model is implicitly model
    m1, m2 = speech.load_models('small', translate_model='small')
    assert m1.size == 'small'
    assert m2 is m1

def test_load_models(monkeypatch):
    import types
    fake_fw = types.ModuleType('faster_whisper')
    class FakeWhisperModel:
        def __init__(self, size, **kwargs):
            self.size = size
    fake_fw.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_fw)

    # Same model
    m1, m2 = speech.load_models('small')
    assert m1.size == 'small'
    assert m2 is m1

    # Different models
    m1, m2 = speech.load_models('small', 'tiny')
    assert m1.size == 'small'
    assert m2.size == 'tiny'
    assert m1 is not m2


def test_speech_chunks(monkeypatch):
    import types
    fake_fw = types.ModuleType('faster_whisper')
    fake_vad = types.ModuleType('vad')
    class FakeVadOptions:
        def __init__(self, **kw): pass
    fake_vad.VadOptions = FakeVadOptions

    # fake get_speech_timestamps to return arbitrary chunks in samples at 16000 Hz
    def dummy_get(x, opts):
        return [
            {'start': 0, 'end': 16000},                 # 0-1s
            {'start': 16000 * 1.5, 'end': 16000 * 2.5}, # 1.5-2.5s -> gap is 0.5s <= merge_gap(0.6), so merge
            {'start': 16000 * 4, 'end': 16000 * 5},     # 4-5s -> gap is 1.5s > merge_gap, new chunk
        ]
    fake_vad.get_speech_timestamps = dummy_get
    fake_fw.vad = fake_vad
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', fake_vad)
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_fw)

    # With merge_gap=0.6, the first two chunks (0-1, 1.5-2.5) merge into 0-2.5
    chunks = speech.speech_chunks(None, max_len=18.0, merge_gap=0.6)
    assert len(chunks) == 2
    assert chunks[0] == [0.0, 2.5]
    assert chunks[1] == [4.0, 5.0]


def test_identify_language():
    class DummyModel:
        def detect_language(self, audio):
            # return lang, prob, scores
            # scores format: list of tuples
            return 'fr', 0.8, [('fr', 0.8), ('en', 0.1), ('nl', 0.05), ('it', 0.05)]

    m = DummyModel()
    best, prob, scores, raw = speech.identify_language(m, None, ['en', 'fr', 'nl'])
    assert best == 'fr'
    assert raw == 'fr'
    assert scores['fr'] == 0.8
    assert scores['en'] == 0.1
    # total allowed sum: 0.8 + 0.1 + 0.05 = 0.95. prob should be 0.8 / 0.95 = 0.842
    assert abs(prob - (0.8 / 0.95)) < 1e-3
    assert 'it' not in scores

def test_transcribe_multilingual(monkeypatch):
    import numpy as np

    # Mock speech_chunks to return a single chunk 0-2s
    monkeypatch.setattr(speech, 'speech_chunks', lambda x, **kw: [[0.0, 2.0]])

    # Mock identify_language
    monkeypatch.setattr(speech, 'identify_language', lambda m, a, allowed: ('fr', 0.9, {'fr': 0.9, 'en': 0.1}, 'fr'))

    # Mock translate_text to do a simple uppercase
    monkeypatch.setattr(speech, 'translate_text', lambda t, l: t.upper() if l != 'en' else t)

    class FakeWord:
        def __init__(self, w, s, e, p):
            self.word = w
            self.start = s
            self.end = e
            self.probability = p

    class FakeSegment:
        def __init__(self):
            self.start = 0.5
            self.end = 1.5
            self.text = "bonjour"
            self.avg_logprob = -0.1
            self.no_speech_prob = 0.05
            self.words = [FakeWord("bonjour", 0.5, 1.5, 0.95)]

    class FakeModel:
        def transcribe(self, seg, language, **kw):
            # return segs, info
            return [FakeSegment()], None

    x16 = np.zeros(16000 * 3, dtype=np.float32)
    m = FakeModel()

    out = speech.transcribe_multilingual(x16, m, translate=True, whisper_translate=False)

    assert len(out) == 1
    seg = out[0]
    assert seg['lang'] == 'fr'
    assert seg['text'] == 'bonjour'
    assert seg['text_en'] == 'BONJOUR'
    assert seg['t0'] == 0.5
    assert seg['t1'] == 1.5
    assert len(seg['words']) == 1
    assert seg['words'][0]['w'] == 'bonjour'
    assert seg['words'][0]['t0'] == 0.5
    assert seg['words'][0]['t1'] == 1.5
    assert 'flags' in seg
    assert not seg['suspect']

    # Test whisper_translate mode
    class FakeTranslateModel:
        def transcribe(self, seg, language, **kw):
            class FakeTrans:
                def __init__(self): self.text = "hello"
            return [FakeTrans()], None

    out = speech.transcribe_multilingual(x16, m, translate_model=FakeTranslateModel(), translate=True, whisper_translate=True)
    assert len(out) == 1
    assert out[0]['text_en_whisper_chunk'] == 'hello'

def test_transcribe_multilingual_empty(monkeypatch):
    import numpy as np
    x16 = np.zeros(100, dtype=np.float32) # length < 0.3 * 16000

    # Mock speech_chunks to return a single chunk 0-0.00625s
    monkeypatch.setattr(speech, 'speech_chunks', lambda x, **kw: [[0.0, 0.00625]])

    out = speech.transcribe_multilingual(x16, None)
    assert len(out) == 0

def test_transcribe_multilingual_no_text(monkeypatch):
    import numpy as np

    # Mock speech_chunks to return a single chunk 0-2s
    monkeypatch.setattr(speech, 'speech_chunks', lambda x, **kw: [[0.0, 2.0]])
    monkeypatch.setattr(speech, 'identify_language', lambda m, a, allowed: ('fr', 0.9, {'fr': 0.9, 'en': 0.1}, 'fr'))

    class FakeSegmentNoText:
        def __init__(self):
            self.start = 0.5
            self.end = 1.5
            self.text = "   " # empty text
            self.avg_logprob = -0.1
            self.no_speech_prob = 0.05
            self.words = []

    class FakeModel:
        def transcribe(self, seg, language, **kw):
            return [FakeSegmentNoText()], None

    x16 = np.zeros(16000 * 3, dtype=np.float32)
    m = FakeModel()

    out = speech.transcribe_multilingual(x16, m)
    assert len(out) == 0
