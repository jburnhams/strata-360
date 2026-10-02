"""Measuring the spoken voice-over (V3): speech extent, word times, status, reuse; on synthetic tone 'speech' and a scripted aligner (no model)."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from strata360.edit import vo_measure as M, voiceover as V

SR = 16000


def burst(n_words, per_word=0.4): return int(n_words * per_word * SR)


def make_wav(path, parts):
    """parts: ('s', seconds) silence or ('w', n_words) 'speech' (a 300 Hz tone, 0.4 s per word); returns the truth [(start, end)] of every speech part."""
    x = []; t = 0.0; truth = []
    for kind, v in parts:
        n = int(v * SR) if kind == 's' else burst(v)
        x.append(np.zeros(n) if kind == 's' else 0.3 * np.sin(2 * np.pi * 300 * np.arange(n) / SR))
        if kind == 'w': truth.append((t, t + n / SR))
        t += n / SR
    wavfile.write(str(path), SR, (np.concatenate(x) * 32767).astype(np.int16)); return truth


def even_aligner(score=0.9):
    """Spreads the words evenly over the active part of the audio (what a perfect aligner gives for tone 'speech' of constant pace)."""
    def al(x16, words):
        idx = np.where(np.abs(x16) > 0.01)[0]
        if not len(idx): return [None] * len(words)
        a, b = idx[0] / 16000, idx[-1] / 16000; w = (b - a) / len(words)
        return [(a + i * w, a + (i + 1) * w, score) for i in range(len(words))]
    return al


def test_speech_runs_find_the_bursts_and_close_short_gaps(tmp_path):
    truth = make_wav(tmp_path / 'a.wav', [('s', 0.5), ('w', 3), ('s', 0.1), ('w', 2), ('s', 1.0), ('w', 2), ('s', 0.3)])
    x, sr = M.read_audio(tmp_path / 'a.wav'); runs = M.speech_runs(x, sr)
    assert len(runs) == 2 and runs[0][0] == pytest.approx(0.5, abs=0.05) and runs[0][1] == pytest.approx(truth[1][1], abs=0.05) and runs[1][0] == pytest.approx(truth[2][0], abs=0.05)


def test_silence_has_no_runs(tmp_path):
    wavfile.write(str(tmp_path / 's.wav'), SR, np.zeros(SR, np.int16)); x, sr = M.read_audio(tmp_path / 's.wav')
    assert M.speech_runs(x, sr) == [] and M.measure_take(tmp_path / 's.wav', 'hello', even_aligner())['status'] == 'silent'


def test_measure_take_reports_length_edges_words_and_loudness(tmp_path):
    make_wav(tmp_path / 't.wav', [('s', 0.6), ('w', 5), ('s', 0.9)])
    m = M.measure_take(tmp_path / 't.wav', 'one two three four five', even_aligner())
    assert m['natural_s'] == pytest.approx(3.5, abs=0.01) and m['speech_start_s'] == pytest.approx(0.6, abs=0.05) and m['speech_end_s'] == pytest.approx(2.6, abs=0.05)
    assert m['lead_s'] == pytest.approx(0.6, abs=0.05) and m['trail_s'] == pytest.approx(0.9, abs=0.05) and m['status'] == 'ok' and m['aligned'] == 1.0
    assert [w['w'] for w in m['words']] == ['one', 'two', 'three', 'four', 'five'] and m['words'][0]['t0'] == pytest.approx(0.6, abs=0.05) and m['words'][-1]['t1'] == pytest.approx(2.6, abs=0.05)
    assert all(a['t1'] <= b['t0'] + 1e-6 for a, b in zip(m['words'], m['words'][1:]))
    assert m['loudness_db'] == pytest.approx(20 * np.log10(0.3 / np.sqrt(2)), abs=0.5)


@pytest.mark.parametrize('text,parts,aligner,status', [
    ('a b c d e f g h i j k l', [('w', 3)], even_aligner(), 'short'),                    # 12 words, 1.2 s of speech: words are missing
    ('a b', [('w', 12)], even_aligner(), 'long'),                                        # 2 words, 4.8 s: extra or repeated words
    ('a b c', [('w', 3)], even_aligner(0.05), 'mismatch'),                                # the aligner cannot place them
    ('a b c', [('w', 3)], lambda x, w: [None] * len(w), 'mismatch'),                      # none alignable
])
def test_status(tmp_path, text, parts, aligner, status):
    make_wav(tmp_path / 't.wav', parts); assert M.measure_take(tmp_path / 't.wav', text, aligner)['status'] == status


def test_recording_of_several_lines_splits_within_50_ms(tmp_path):
    lines = [dict(key='a', text='one two three'), dict(key='b', text='four five'), dict(key='c', text='six seven eight nine')]
    truth = make_wav(tmp_path / 'r.wav', [('s', 0.7), ('w', 3), ('s', 1.2), ('w', 2), ('s', 0.8), ('w', 4), ('s', 0.5)])

    def al(x16, words):                                                                                  # a good aligner with a 30 ms error at every word start (times are relative to the excerpt, which starts 0.3 s before the speech: 0.4 s)
        out = []
        for (a, b), n in zip(truth, (3, 2, 4)):
            w = (b - a) / n
            for k in range(n): out.append((a - 0.4 + k * w + 0.03, a - 0.4 + (k + 1) * w, 0.9))
        return out
    r = M.measure_recording(tmp_path / 'r.wav', lines, al)
    for l, (a, b) in zip(lines, truth):
        m = r[l['key']]; assert m['status'] == 'ok' and m['speech_start_s'] == pytest.approx(a, abs=0.05) and m['speech_end_s'] == pytest.approx(b, abs=0.05)
    assert r['a']['pause_before_s'] is None and r['b']['pause_before_s'] == pytest.approx(1.2, abs=0.1) and r['c']['pause_before_s'] == pytest.approx(0.8, abs=0.1)


def test_a_missing_line_in_a_recording_is_reported(tmp_path):
    lines = [dict(key='a', text='one two'), dict(key='b', text='three four'), dict(key='c', text='five six')]
    make_wav(tmp_path / 'r.wav', [('w', 2), ('s', 1.0), ('w', 2)])                                      # the middle line was never read

    def al(x16, words): return [(0.0, 0.4, .9), (0.4, 0.8, .9), None, None, (1.8, 2.2, .9), (2.2, 2.6, .9)]
    r = M.measure_recording(tmp_path / 'r.wav', lines, al)
    assert r['b']['status'] == 'missing' and r['a']['status'] == 'ok' and r['c']['status'] == 'ok'


def test_a_repeated_line_is_reported_long(tmp_path):
    lines = [dict(key='a', text='one two')]; make_wav(tmp_path / 'r.wav', [('w', 2), ('s', 0.4), ('w', 2), ('s', 0.4), ('w', 2), ('s', 0.4), ('w', 2)])
    r = M.measure_recording(tmp_path / 'r.wav', lines, lambda x, w: [(0.0, 0.4, .9), (7.0, 7.4, .9)])
    assert r['a']['status'] == 'long'


def test_line_keys_are_stable_and_ordered():
    doc = dict(lines=[dict(block=3, anchor='before', text='x'), dict(block=3, anchor='before', text='y'), dict(block=3, anchor='after', text='z'), dict(block=4, anchor=None, text='w')])
    assert [k for k, _ in M.line_keys(doc)] == ['003b0', '003b1', '003a0', '004n0']


# ---- vo.json -----------------------------------------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def proj(project, monkeypatch):
    monkeypatch.setattr(V, 'ENGINES', {'fake': ('Fake', lambda: True, lambda: [dict(name='Test', lang='en_GB')], lambda *a: None)})
    return project


def script(*texts): return dict(title='T', lines=[dict(block=i, anchor=None, text=t) for i, t in enumerate(texts)])


def test_vo_json_is_written_and_unchanged_lines_are_not_measured_again(proj, tmp_path):
    n = {'calls': 0}; al0 = even_aligner()
    def al(x, w): n['calls'] += 1; return al0(x, w)
    files = {}
    def resolve(key, text):
        p = tmp_path / f'{key}.wav'
        if key not in files: make_wav(p, [('s', 0.2), ('w', len(text.split())), ('s', 0.3)]); files[key] = p
        return 'synth', str(files[key])
    d = M.measure_script(proj.folder, script('one two', 'three four five', ''), al, resolve)
    assert [l['key'] for l in d['lines']] == ['000n0', '001n0'] and n['calls'] == 2 and d['problems'] == [] and d['total_speech_s'] == pytest.approx(0.8 + 1.2, abs=0.15)
    assert json.load(open(M.vo_path(proj.folder)))['lines'][1]['natural_s'] == pytest.approx(1.7, abs=0.01) and M.load(proj.folder)['lines'][0]['block'] == 0
    M.measure_script(proj.folder, script('one two', 'three four five'), al, resolve); assert n['calls'] == 2                  # nothing changed
    make_wav(files['001n0'], [('w', 3), ('s', 1.0)]); import os; os.utime(files['001n0'], (1e9, 1e9))                             # a new take of line 1 only
    d = M.measure_script(proj.folder, script('one two', 'three four five'), al, resolve); assert n['calls'] == 3 and d['lines'][1]['trail_s'] == pytest.approx(1.0, abs=0.05)
    d = M.measure_script(proj.folder, script('one two', 'three four five six'), al, resolve); assert n['calls'] == 4                 # the text changed


def test_a_line_without_audio_is_missing(proj):
    d = M.measure_script(proj.folder, script('hello there'), even_aligner(), lambda k, t: ('recorded', None))
    assert d['lines'][0]['status'] == 'missing' and d['problems'] == [dict(key='000n0', status='missing')]


def test_load_without_a_file(proj): assert M.load(proj.folder) is None


def test_overflow_choices_name_what_can_be_done_and_are_empty_when_it_fits():
    from strata360.edit import voiceover as V
    assert V.overflow_choices('synth', 0.0) == [] and V.overflow_choices('recorded', 0.004) == []
    s = V.overflow_choices('synth', 2.0); r = V.overflow_choices('recorded', 2.0)
    assert 'about 2.0 s' in s[0] and any('faster' in c for c in s) and not any('faster' in c for c in r) and any('record it again' in c for c in r)
