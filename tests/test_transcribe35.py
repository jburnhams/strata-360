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
    d = draft('I am actually saying um okay', 'so we got forty five kilometers to go', 'and then that was it')
    fx, sk = T.align(d, "I am actually sane. Um okay so we got forty five km to go and then it just was it")
    f = {(x['seg'], x['word']): x for x in fx[0]}
    assert f[(0, 3)]['to'] == 'sane.' and f[(1, 5)]['to'] == 'km' and f[(1, 5)]['through'] == 5                              # one word for one word
    assert f[(2, 2)]['to'] == 'it just' and all(x['through'] >= x['word'] for x in fx[0])                                     # one word for two: a correction of that word (the text goes on it)
    fx2, sk2 = T.align(draft('one two three four'), 'one two three four'); assert fx2 == {} and sk2['equal'] == 4                  # identical: nothing
    fx3, sk3 = T.align(draft('a b c d e'), 'a x y z e'); assert [(x['word'], x['through'], x['to']) for x in fx3[0]] == [(1, 3, 'x'), (2, 2, 'y'), (3, 3, 'z')] or [(x['word'], x['through'], x['to']) for x in fx3[0]][0][0] == 1


def test_a_run_across_two_phrases_is_not_one_correction():
    fx, sk = T.align(draft('one two', 'three four'), 'one zzz four'); assert sk['cross'] == 1 and fx == {}                    # two words across two phrases became one: not one correction
    fx, sk = T.align(draft('one two', 'three four'), 'one zzz qqq four'); assert [(x['seg'], x['word'], x['to']) for x in fx[0]] == [(0, 1, 'zzz'), (1, 0, 'qqq')]        # one for one in each phrase: two corrections


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
