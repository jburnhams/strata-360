"""Word-by-word transcript corrections: model and user layers, timing kept, stale edits. Run: .venv/bin/python tests/test_transcript_edits.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
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
    seen = []; SC.run_llm = lambda msgs, **kw: (seen.append(msgs[-1]['content']), dict(text='', parsed=dict(fixes=[dict(seg=0, word=3, **{'from': 'audio', 'to': 'out', 'why': 'x'})])))[1]
    r = TF.run(f, log=lambda *a: None); assert r == {'C1': 1} and '3:audio(0.50)' in seen[0] and 'Clip C1' in seen[0]; assert TE.load_effective(d)['segments'][0]['words'][3]['w'] == 'out'


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
