"""Word-by-word transcript corrections: model and user layers, timing kept, stale edits. Run: .venv/bin/python tests/test_transcript_edits.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
from strata360.analysis import transcript_edits as TE, transcript_fix as TF


def clip_dir():
    d = tempfile.mkdtemp(); ws = lambda *a: [dict(w=w, t0=i * 0.5, t1=i * 0.5 + 0.4, p=0.5) for i, w in enumerate(a)]
    json.dump(dict(segments=[dict(t0=1.0, t1=3.0, lang='en', text='He has been audio there.', text_en='He has been audio there.', words=ws('He', 'has', 'been', 'audio', 'there.')),
                             dict(t0=5.0, t1=6.0, lang='fr', text='Bonjour tout', text_en='Hello all', words=ws('Bonjour', 'tout'))]), open(os.path.join(d, 'transcript.json'), 'w')); return d


def test_model_and_user_layers_with_timing_kept():
    d = clip_dir(); n = TE.set_gemini(d, [dict(seg=0, word=3, **{'from': 'audio', 'to': 'out', 'why': 'made no sense'}), dict(seg=0, word=1, **{'from': 'WRONG', 'to': 'x'})], model='m'); assert n == 1     # a 'from' that does not match is dropped
    tr = TE.load_effective(d); s = tr['segments'][0]; assert s['text'] == 'He has been out there.' and s['text_en'] == s['text'] and s['edited']
    w = s['words'][3]; assert w['w'] == 'out' and w['edit']['orig'] == 'audio' and w['edit']['src'] == 'gemini' and w['edit']['why'] == 'made no sense' and (w['t0'], w['t1']) == (1.5, 1.9)      # same timing
    TE.set_user(d, 0, 3, 'in'); s = TE.load_effective(d)['segments'][0]; assert s['words'][3]['w'] == 'in' and s['words'][3]['edit']['src'] == 'user' and s['words'][3]['edit']['gemini_text'] == 'out'
    TE.set_user(d, 0, 3, 'audio'); assert TE.load_effective(d)['segments'][0]['words'][3]['w'] == 'audio'                                  # the user restored the original and overruled the model
    TE.clear_user(d, 0, 3); assert TE.load_effective(d)['segments'][0]['words'][3]['w'] == 'out'                                           # their entry dropped: the model's shows again
    assert json.load(open(os.path.join(d, 'transcript.json')))['segments'][0]['words'][3]['w'] == 'audio'                                  # the recogniser's output is never changed


def test_rerun_replaces_model_edits_keeps_user_edits_and_foreign_translation_is_left_alone():
    d = clip_dir(); TE.set_gemini(d, [dict(seg=0, word=3, to='out')]); TE.set_user(d, 0, 1, 'had'); n = TE.set_gemini(d, [dict(seg=0, word=4, to='there,')]); assert n == 1
    s = TE.load_effective(d)['segments'][0]; assert [w['w'] for w in s['words']] == ['He', 'had', 'been', 'audio', 'there,']                  # model fix 3 gone, user fix kept, new model fix in
    TE.set_user(d, 1, 0, 'Bonsoir'); f = TE.load_effective(d)['segments'][1]; assert f['text'] == 'Bonsoir tout' and f['text_en'] == 'Hello all'     # a translation is not word-aligned: left as it was


def test_stale_edits_are_ignored_when_the_transcript_changes():
    d = clip_dir(); TE.set_user(d, 0, 3, 'out'); tr = json.load(open(os.path.join(d, 'transcript.json'))); tr['segments'][0]['words'][3]['w'] = 'something'; json.dump(tr, open(os.path.join(d, 'transcript.json'), 'w'))
    out, stale = TE.apply(tr, TE.load(d)); assert stale == ['0:3'] and out['segments'][0]['words'][3]['w'] == 'something'


def test_the_model_run_stores_suggestions_per_clip():
    from strata360.edit import script as SC
    from strata360.pipeline import config
    f = tempfile.mkdtemp(); rd = config.race_dir(f); d = os.path.join(rd, 'clips', 'C1'); os.makedirs(d); src = clip_dir(); open(os.path.join(d, 'transcript.json'), 'w').write(open(os.path.join(src, 'transcript.json')).read())
    json.dump(dict(library=f, llm=dict(provider='vertex', model='m')), open(os.path.join(rd, 'race.json'), 'w'))
    seen = []; SC.run_llm = lambda msgs, **kw: (seen.append(msgs[-1]['content']), dict(text='', parsed=dict(fixes=[dict(clip=1, seg=0, word=3, **{'from': 'audio', 'to': 'out', 'why': 'x'})])))[1]
    r = TF.run(f, log=lambda *a: None); assert r == {'C1': 1} and len(seen) == 1 and '3:audio(0.50)' in seen[0] and 'Clip 1 (C1)' in seen[0]; assert TE.load_effective(d)['segments'][0]['words'][3]['w'] == 'out'


def words_at(*items):
    return [dict(w=w, t0=t0, t1=t1) for w, t0, t1 in items]


def test_long_phrases_split_only_at_sentence_ends_and_every_part_is_over_five_seconds():
    w = words_at(('One', 0, 1), ('two.', 1, 6.5), ('Three', 7, 8), ('four.', 8, 13), ('Five', 13.5, 14), ('six', 14, 16))                                     # 16 s: sentence ends after 6.5 s and 13 s
    assert TE.split_points(w) == [(0, 2), (2, 4), (4, 6)] or TE.split_points(w) == [(0, 2), (2, 6)]                                                          # never a part of 5 s or less
    for a, b in TE.split_points(w): assert w[b - 1]['t1'] - w[a]['t0'] > 5.0
    assert TE.split_points(words_at(('a', 0, 4), ('b.', 4, 9.9))) == [(0, 2)]                                                                                # 9.9 s: left whole
    assert TE.split_points(words_at(('a', 0, 3), ('b.', 3, 4), ('c', 4.2, 12))) == [(0, 3)]                                                                  # the only sentence end leaves 4 s before it: no split
    assert TE.split_points(words_at(('a', 0, 6), ('b', 6, 12))) == [(0, 2)]                                                                                  # no sentence end at all: no split
    assert TE.split_points(words_at(('a', 0, 2.5), ('b.', 2.5, 6), ('c', 6.5, 9), ('d.', 9, 14))) == [(0, 2), (2, 4)]                                         # 14 s: a 6 s part and an 7.5 s part


def test_parts_carry_play_ranges_and_absolute_word_numbers_and_foreign_phrases_stay_whole():
    seg = dict(t0=0.0, t1=16.0, lang='en', text='x', text_en='x', words=words_at(('One', 0, 1), ('two.', 1, 6.5), ('Three', 7, 8), ('four', 8, 16))); ps = TE.parts(seg)
    assert len(ps) == 2 and [w['i'] for w in ps[1]['words']] == [2, 3] and ps[1]['play0'] == 6.9 and ps[1]['play1'] == 16.3
    fr = dict(seg, lang='fr', text='bonjour', text_en='hello'); assert len(TE.parts(fr)) == 1


def seg_words(t0, text):
    out = []; t = t0
    for w in text.split(): out.append(dict(w=w, t0=round(t, 2), t1=round(t + 0.4, 2), p=0.5)); t += 0.5
    return dict(t0=t0, t1=t, lang='en', text=text, text_en=text, words=out)


def test_excerpts_are_speech_only_cut_at_natural_pauses_with_the_limits_given_and_one_to_two_minutes_by_default():
    # phrases of 5 s every 5.5 s for 150 s (continuous speech), then a 10 s silence, then 12 s more
    segs = [seg_words(i * 5.5, 'one two three four five six seven eight nine ten.' if i % 3 == 2 else 'one two three four five six seven eight nine ten') for i in range(27)]
    last = segs[-1]['t1']; segs += [seg_words(last + 10, 'after the silence we carry on talking for a while longer. yes indeed it is so')]
    for s in segs: s['t1'] = s['words'][-1]['t1']
    ch = TF.chunks(dict(segments=segs), 400.0, min_s=30.0, max_s=60.0)
    d = TF.chunks(dict(segments=segs), 400.0); assert all(c['t1'] - c['t0'] <= 120.0 + 1e-6 for c in d) and d[0]['t1'] - d[0]['t0'] >= 60.0 and len(d) < len(ch)             # the default: 60-120 s a request
    assert len(ch) >= 4 and all(c['t1'] - c['t0'] <= 60.0 + 1e-6 for c in ch) and ch[-1]['t0'] > last + 9 and sum(len(c['segs']) for c in ch) == len(segs)           # the silence is not sent; nothing lost
    assert all(c['a1'] - c['a0'] <= 61.1 for c in ch) and all(abs((c['t0'] - c['a0']) - 0.5) < 1e-6 or c['a0'] == 0 for c in ch)                                    # half a second of padding
    assert all(c['t1'] - c['t0'] >= 30.0 for c in ch[:-2]), [(c['t0'], c['t1']) for c in ch]                                                                    # pieces are 30-60 s (the last of a stretch may be shorter)
    assert TF.chunks(dict(segments=[]), 10) == [] and len(TF.chunks(dict(segments=[seg_words(0, 'a b c')]), 10)) == 1


def test_only_fixes_most_checks_agree_on_are_kept():
    f = lambda w, to, th=None, why='x': dict(seg=0, word=w, to=to, why=why, **({'through': th} if th is not None else {}))
    runs = [[f(1, 'sane.'), f(5, 'socks')], [f(1, 'sane.'), f(7, 'x')], [f(1, 'sane.'), f(5, 'socks'), f(2, 'a b', 3)]]
    got = TF.vote(runs); assert [(g['word'], g['to'], g['votes']) for g in got] == [(1, 'sane.', 3), (5, 'socks', 2)] and '3 of 3' in got[0]['why']
    assert TF.vote([[f(1, 'a')], [f(1, 'b')]]) == []                                                                                                              # no agreement: nothing
    both = TF.vote([[f(1, 'x y', 2)], [f(1, 'x y', 2)], [f(2, 'z')], [f(2, 'z')]], 2); assert [(g['word'], g['through']) for g in both] == [(1, 2)]            # overlapping runs of words: one wins


def test_a_run_of_words_becomes_one_correction_and_the_rest_are_hidden_with_timing_kept():
    d = clip_dir(); n = TE.set_gemini(d, [dict(seg=0, word=2, through=3, to='been out', why='misheard')]); assert n == 1
    s = TE.load_effective(d)['segments'][0]; assert [w['w'] for w in s['words']] == ['He', 'has', 'been out', '', 'there.'] and s['text'] == 'He has been out there.'
    assert [(w['t0'], w['t1']) for w in s['words']] == [(0.0, 0.4), (0.5, 0.9), (1.0, 1.4), (1.5, 1.9), (2.0, 2.4)] and s['words'][3]['edit']['orig'] == 'audio'          # every word keeps its own timing


def _fx(w, to='x', th=None): return dict(seg=0, word=w, to=to, **({'through': th} if th is not None else {}))


def test_decide_accepts_fixes_most_checks_agree_on_and_keeps_partial_support_undecided():
    calls = [('a', [_fx(1, 'sane'), _fx(5, 'maybe')]), ('b', [_fx(1, 'sane')]), ('c', [_fx(1, 'sane'), _fx(5, 'maybe'), _fx(9, 'once')]), ('d', [_fx(1, 'sane')]), ('e', [_fx(1, 'sane')]), ('f', [])]
    acc, und, tally = TF.decide(calls); assert acc == [(0, 1, 1, 'sane')] and tally[(0, 1, 1, 'sane')]['votes'] == 5 and len(tally[(0, 1, 1, 'sane')]['models']) == 5
    assert und == [(0, 5, 5, 'maybe')]                                                                  # 2 of 6: some support, not enough yet
    assert (0, 9, 9, 'once') not in und                                                                 # 1 of 6: too little support to keep waiting for


def test_the_ensemble_stops_when_settled_spreads_over_models_and_replays_from_the_cache():
    import random
    pool = ['gemini:m1', 'gemini:m2', 'gemini:m3']; seen = []; tr = dict(segments=[seg_words(0, 'a b c d e f g h')]); ch = dict(segs=[0], a0=0.0, a1=5.0)
    def fake(folder, clip, tr, ch, au, ctx, provider='x', model=None, thinking='low', run=0, cache_dir=None, log=None):
        seen.append((model, run)); return [_fx(1, 'sane')] + ([_fx(4, 'noise%d' % (len(seen) % 5))] if len(seen) % 2 else []), dict(cached=False)                # one stable fix, one that keeps changing
    old = TF.check_chunk; TF.check_chunk = fake; TF._DOWN.clear()
    try:
        r = TF.ensemble_excerpt('f', 'c', tr, ch, 'au', '', None, pool, min_calls=6, max_calls=18, patience=3, log=lambda *a: None)
    finally: TF.check_chunk = old
    assert r['stopped'] == 'settled' and 6 <= r['calls'] <= 12 and [(a['word'], a['to']) for a in r['accepted']] == [(1, 'sane')], r
    assert max(r['models'].values()) - min(r['models'].values()) <= 1 and set(r['models']) == set(pool)                       # an even mixture of the models
    assert all((m.split(':')[1], k) in seen for m, n in r['models'].items() for k in range(n)) and len({s for s in seen}) == len(seen)       # each model's k-th ask is a separate cacheable call


def test_the_ensemble_stops_at_the_cap_when_answers_never_settle_and_skips_models_that_are_down():
    pool = ['gemini:ok', 'gemini:busy', 'gemini:gone']; tr = dict(segments=[seg_words(0, 'a b c d e f g h')]); ch = dict(segs=[0], a0=0.0, a1=5.0); n = [0]
    class Busy(Exception): retryable = True
    class Gone(Exception): retryable = False
    def fake(folder, clip, tr, ch, au, ctx, provider='x', model=None, thinking='low', run=0, cache_dir=None, log=None):
        if model == 'busy': raise Busy('HTTP 429 quota')
        if model == 'gone': raise Gone('HTTP 404 no longer available')
        n[0] += 1; return ([_fx(1, 'q')] if n[0] % 5 in (1, 2) else []), dict(cached=False)                                   # a fix in 40% of the checks: never accepted, never dropped: it does not settle
    old = TF.check_chunk; TF.check_chunk = fake; TF._DOWN.clear()
    try: r = TF.ensemble_excerpt('f', 'c', tr, ch, 'au', '', None, pool, min_calls=4, max_calls=9, log=lambda *a: None)
    finally: TF.check_chunk = old
    assert r['stopped'] == 'max_calls' and r['calls'] == 9 and r['models'] == {'gemini:ok': 9} and r['accepted'] == [] and r['undecided']
    TF._DOWN.clear(); n[0] = 0; old = TF.check_chunk; TF.check_chunk = lambda *a, **k: ([], dict(cached=False))
    try: r2 = TF.ensemble_excerpt('f', 'c', tr, ch, 'au', '', None, ['gemini:ok'], min_calls=4, max_calls=9, log=lambda *a: None)
    finally: TF.check_chunk = old
    assert r2['stopped'] == 'settled' and r2['calls'] == 4 and r2['accepted'] == []                                       # nothing to fix, consistently: settled at once


def test_when_every_model_is_busy_the_stage_is_asked_to_retry_and_what_was_done_counts_as_progress():
    from strata360.pipeline.retry import RetryLater
    pool = ['gemini:a', 'gemini:b']; tr = dict(segments=[seg_words(0, 'a b c d')]); ch = dict(segs=[0], a0=0.0, a1=5.0); n = [0]
    class Busy(Exception): retryable = True
    def fake(folder, clip, tr, ch, au, ctx, provider='x', model=None, thinking='low', run=0, cache_dir=None, log=None):
        n[0] += 1
        if n[0] > 2: raise Busy('503')
        return [_fx(1, 'q')], dict(cached=False)
    old = TF.check_chunk; TF.check_chunk = fake; TF._DOWN.clear()
    try: TF.ensemble_excerpt('f', 'c', tr, ch, 'au', '', None, pool, min_calls=6, log=lambda *a: None); assert False
    except RetryLater as e: assert e.progress and 'done and kept' in str(e)
    finally: TF.check_chunk = old; TF._DOWN.clear()


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
