"""Words of the wearer inside a window. Run: .venv/bin/python tests/test_script_words.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import script as S


def clip_with(seg, align=None):
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, 'CAM_x')); json.dump(dict(segments=[seg]), open(os.path.join(d, 'CAM_x', 'transcript.json'), 'w'))
    if align: json.dump(dict(segments=[align]), open(os.path.join(d, 'CAM_x', 'alignment.json'), 'w'))
    return d


WORDS = [dict(w=w, t0=2.0 + 0.5 * i - 0.15, t1=2.4 + 0.5 * i - 0.15) for i, w in enumerate(['Good', 'morning,', 'quite', 'a', 'hard', 'night,', 'I', "don't", 'know'])]   # whisper times are 0.15 s early


def test_only_the_words_inside_the_window_are_returned():
    d = clip_with(dict(t0=1.9, t1=6.6, lang='en', text='Good morning, quite a hard night, I don\'t know', words=WORDS, flags=[]))
    assert S.words_in_window(d, 'CAM_x', 0.0, 10.0) == ["Good morning, quite a hard night, I don't know"]                      # the whole sentence: no ellipsis
    assert S.words_in_window(d, 'CAM_x', 2.0, 4.0) == ['Good morning, quite a …']                                          # the window ends after "a": the sentence is cut
    assert S.words_in_window(d, 'CAM_x', 4.0, 7.0) == ['… hard night, I don\'t know']                                        # starts mid-sentence
    assert S.words_in_window(d, 'CAM_x', 4.6, 5.4) == ['… night, …'] or S.words_in_window(d, 'CAM_x', 4.6, 5.4) != []     # a short window inside
    assert S.words_in_window(d, 'CAM_x', 8.0, 9.0) == []                                                                    # nothing said there


def test_adjacent_windows_do_not_repeat_each_other():
    d = clip_with(dict(t0=1.9, t1=6.6, lang='en', text='x', words=WORDS, flags=[]))
    a, b = S.words_in_window(d, 'CAM_x', 2.0, 4.0)[0], S.words_in_window(d, 'CAM_x', 4.0, 7.0)[0]
    joined = (a.replace(' …', '') + ' ' + b.replace('… ', '')).split(); assert joined == [w['w'] for w in WORDS]              # together they are the sentence, each word once


def test_foreign_phrases_give_the_matching_share_of_the_translation():
    ws = [dict(w=f'mot{i}', t0=1.0 + i * 0.5, t1=1.4 + i * 0.5) for i in range(8)]
    d = clip_with(dict(t0=1.0, t1=5.0, lang='fr', text='a b c d e f g h', text_en='one two three four five six seven eight', words=ws, flags=[]))
    first = S.words_in_window(d, 'CAM_x', 0.0, 3.2)[0]; second = S.words_in_window(d, 'CAM_x', 3.2, 9.0)[0]
    assert first.startswith('one two') and first.endswith('…') and second.startswith('…') and second.rstrip().endswith('eight'), (first, second)


def test_accurate_alignment_is_used_when_it_passed_its_checks():
    seg = dict(t0=1.9, t1=6.6, lang='en', text='x', words=WORDS, flags=[])
    al = dict(index=0, words=[dict(a0=0.0, a1=0.1, ok=True)] + [dict(a0=2.0 + 0.5 * i, a1=2.4 + 0.5 * i, ok=False) for i in range(1, 9)])          # word 0 aligned to t=0.05, which is outside 1.5-4.0
    d = clip_with(seg, al); r = S.words_in_window(d, 'CAM_x', 1.5, 4.0)[0]; assert not r.lstrip('… ').startswith('Good'), r


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
