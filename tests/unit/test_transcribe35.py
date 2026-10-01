"""Batching and aligning the transcription model's text onto Whisper's words. Run: .venv/bin/python tests/test_transcribe35.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.analysis import transcribe35 as T


def draft(*segs):
    out = []
    for si, words in enumerate(segs):
        for wi, w in enumerate(words.split()): out.append((0, si, wi, w))
    return out


def test_one_for_one_swaps_and_runs_are_corrections_and_extra_or_missing_words_are_only_reported():
    d = draft('I am actually saying um okay', 'so we got forty five kilometers to go', 'and then dont it')
    fx, sk = T.align(d, "I am actually sane. Um okay so we got forty five kilometres to go and then do not it")
    f = {(x['seg'], x['word']): x for x in fx[0]}
    assert f[(0, 3)]['to'] == 'sane.' and f[(1, 5)]['to'] == 'kilometres' and f[(1, 5)]['through'] == 5                              # one word for one word
    assert f[(2, 2)]['to'] == 'do not' and all(x['through'] >= x['word'] for x in fx[0])                                     # one word for two: a correction of that word (the text goes on it)
    fx2, sk2 = T.align(draft('one two three four'), 'one two three four'); assert fx2 == {} and sk2['equal'] == 4                  # identical: nothing
    fx3, sk3 = T.align(draft('aa bb cc dd ee'), 'aa bx cy dz ee'); assert [(x['word'], x['through'], x['to']) for x in fx3[0]] == [(1, 1, 'bx'), (2, 2, 'cy'), (3, 3, 'dz')] or [(x['word'], x['through'], x['to']) for x in fx3[0]][0][0] == 1


def test_a_run_across_two_phrases_is_not_one_correction():
    fx, sk = T.align(draft('one two', 'three four'), 'one zzz four'); assert sk['cross'] == 1 and fx == {}                    # two words across two phrases became one: not one correction
    fx, sk = T.align(draft('one two', 'three four'), 'one twx thre four'); assert [(x['seg'], x['word'], x['to']) for x in fx[0]] == [(0, 1, 'twx'), (1, 0, 'thre')]        # one for one in each phrase: two corrections


def test_batches_respect_the_audio_and_size_limits_and_keep_order():
    its = [dict(chunks=[dict(a0=0.0, a1=50.0), dict(a0=60.0, a1=110.0)]) for _ in range(6)]       # 12 excerpts of 50 s (+2 s gap)
    bs = T.batches(its, max_audio_s=300); assert [len(b) for b in bs] == [5, 5, 2] and [x for b in bs for x in b] == [(i, j) for i in range(6) for j in range(2)]
    assert len(T.batches(its, max_audio_s=10 ** 6, max_bytes=2e6)) > 3                                                          # the size limit (2.2 MB a minute) also closes batches


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)


def test_a_correction_must_look_like_the_word_it_replaces_and_fillers_are_ignored():
    fx, sk = T.align(draft('so we got kilometers to go'), 'so we got ounces to go'); assert fx == {} and sk['unlike'] == 1       # an unrelated word is not a correction
    fx, sk = T.align(draft('so we got there'), 'so um we uh got there'); assert fx == {}                                         # the model writes fillers, the recogniser leaves them out
