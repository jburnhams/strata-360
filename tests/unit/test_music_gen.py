"""audio/music_gen (G3) with a fake backend and fake file I/O: captions, what a take's key depends on, the ACE-Step parameters for each way of making a section, the take cache, and the error when ACE-Step is not installed."""
import json, os
import numpy as np
import pytest
from strata360.audio import music_gen as MG

STYLE = 'rap rock, distorted guitar riff, live drums'


def section(**kw):
    return dict(dict(first=8, end=16, level=0.65, source='generate', strength=0.65, repaint=True, key='abc'), **kw)


def test_the_caption_names_the_style_and_the_level():
    assert MG.caption(STYLE, 0.15).startswith(STYLE + ', sparse') and 'full band' in MG.caption(STYLE + ',', 0.9) and MG.caption(STYLE, 0.4).endswith('instrumental, no vocals')


def test_a_take_key_follows_what_it_sounds_like():
    k = lambda **kw: MG.spec(section(**kw.pop('sec', {})), 2.47, 97, 'F major', kw.pop('style', STYLE), kw.pop('ctx', [1, 2, 3]))['key']
    assert k() == k() and k(style='jazz') != k() and k(ctx=[1, 2, 4]) != k() and k(sec=dict(strength=0.3)) != k()
    s = MG.spec(section(), 2.47, 97, 'F major', STYLE, []); assert s['mode'] == 'repaint' and s['keyscale'] == 'F major'
    assert MG.spec(section(repaint=False), 2.47, 97, 'F major', STYLE, [])['mode'] == 'cover' and MG.spec(section(repaint=False, strength=0.0), 2.47, 97, 'F major', STYLE, [])['mode'] == 'text'


def test_the_ace_step_parameters_for_each_way():
    sp = lambda **kw: MG.spec(section(**kw), 2.47, 96.9, 'F major', STYLE, [])
    r = MG.params(sp(), 'src.wav', 'ref.wav', 59.4, 19.8, 39.6)
    assert r['task_type'] == 'repaint' and r['repainting_start'] == 19.8 and r['repainting_end'] == 39.6 and r['duration'] == 59.4 and r['reference_audio'] == 'ref.wav' and r['bpm'] == 97 and r['repaint_mode'] == 'conservative' and r['chunk_mask_mode'] == 'explicit'
    c = MG.params(sp(repaint=False, strength=0.5), 'src.wav', 'ref.wav', 19.8); assert c['task_type'] == 'cover' and c['audio_cover_strength'] == 0.5 and c['cover_noise_strength'] == 0.3
    t = MG.params(sp(repaint=False, strength=0.0), 'src.wav', 'ref.wav', 19.8); assert t['task_type'] == 'text2music' and 'reference_audio' not in t and 'src_audio' not in t


def fake_io():
    store = {}
    def write(p, x, sr): store[p] = np.array(x); open(p, 'wb').write(b'x')
    return write, lambda p: (store[p], 100), store


def test_takes_are_made_once_and_kept(tmp_path):
    write, read, store = fake_io(); calls = []
    def backend(jobs, log):
        calls.append(jobs)
        for j in jobs: write(j['out'], np.full((1000, 2), j['seed'] + 1.0), 100)
        return dict(device='cpu', load_s=1.0, jobs=[dict(out=j['out'], ok=True, seconds=2.0, peak_gb=1.0) for j in jobs])
    gen = MG.Generator(str(tmp_path), 100, backend, log=lambda m: None, write=write, read=read)
    rp = MG.spec(section(), 2.0, 120, 'C major', STYLE, [0]); cv = MG.spec(section(repaint=False, first=20, end=24), 2.0, 120, 'C major', STYLE, [0])
    items = [(rp, dict(src=np.zeros((1000, 2)), r0=2.0, r1=6.0, ref=np.zeros((10, 2)))), (cv, dict(src=np.zeros((800, 2)), ref=None))]
    out = gen(items, [0, 3])
    assert out[0].shape == (1000, 2) and out[1][0, 0] == 4.0 and len(calls) == 1 and len(calls[0]) == 2 and calls[0][0]['params']['repainting_end'] == 6.0      # a repaint comes back whole: music_fit judges its bars in context and cuts them
    assert calls[0][0]['params']['src_audio'].endswith('src.wav') and calls[0][0]['params']['reference_audio'].endswith('ref.wav') and 'reference_audio' not in calls[0][1]['params']
    assert gen(items, [0, 3])[1][0, 0] == 4.0 and len(calls) == 1 and gen.runs[0]['load_s'] == 1.0                                         # cached: nothing made again
    gen.note(rp, 0, dict(action='as is')); assert [t['seed'] for t in gen.takes(rp['key'])] == [0] and gen.takes('nothing') == []
    assert json.load(open(os.path.join(gen.dir(rp['key']), 'spec.json')))['caption'] == rp['caption']


def test_a_failed_take_is_none(tmp_path):
    write, read, _ = fake_io(); gen = MG.Generator(str(tmp_path), 100, lambda jobs, log: dict(jobs=[dict(out=j['out'], ok=False, error='out of memory') for j in jobs]), log=lambda m: None, write=write, read=read)
    s = MG.spec(section(repaint=False), 2.0, 120, 'C major', STYLE, []); assert gen([(s, dict(src=np.zeros((10, 2)), ref=None))], [0]) == [None]


def test_without_ace_step_the_error_says_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATA_ACESTEP_ROOT', str(tmp_path)); monkeypatch.delenv('STRATA_ACESTEP_PYTHON', raising=False)
    assert not MG.available()
    with pytest.raises(RuntimeError, match='not installed'): MG.acestep([])
