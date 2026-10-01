"""Voice-over timing, fitting and recorded replacements with a fake speech engine (runs on any platform with ffmpeg). Run: .venv/bin/python tests/test_voiceover.py"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import voiceover as V


def fake_speak(voice, rate, text, out):                      # a tone as long as the text is: 0.1 s per word
    n = max(1, len(text.split())) * 0.1; subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency=300:duration={n}', out], check=True)


V.ENGINES['fake'] = ('Fake', lambda: True, lambda: [dict(name='Test', lang='en_GB')], fake_speak)
V.ENGINES = {'fake': V.ENGINES['fake']}


def project(lines):
    f = tempfile.mkdtemp(); rd = os.path.join(f, 'strata360'); os.makedirs(os.path.join(rd, 'scripts'))
    json.dump(dict(lines=lines), open(os.path.join(rd, 'scripts', 'script-1.json'), 'w'))
    json.dump(dict(edit=dict(plan=dict(film=dict(length_s=20.0)))), open(os.path.join(rd, 'project.json'), 'w')); return f


L = lambda seg, t, s, sec: dict(seg=seg, text=t, film_start_s=s, seconds=sec)


def test_lines_are_placed_and_fit_or_are_sped_or_flagged():
    f = project([L(0, 'one two three', 0.0, 3.0), L(1, 'a b c d e f g h i j k l', 3.0, 1.0), L(2, 'x ' * 60, 4.0, 2.0), L(3, '', 6.0, 2.0), L(4, 'end', 8.0, 2.0)])
    d = V.build(f); by = {o['seg']: o for o in d['lines']}
    assert [o['seg'] for o in d['lines']] == [0, 1, 2, 4] and by[0]['fit'] == 'ok' and abs(by[0]['film_start_s'] - 0.12) < 1e-6
    assert by[1]['fit'] in ('sped', 'over') and by[2]['fit'] == 'over' and 2 in d['over'] and by[2]['overrun_s'] > 0
    assert abs(V.duration(os.path.join(V.base(f), 'voiceover.wav')) - 20.0) < 0.05
    assert d['measured_wpm'] and abs(d['measured_wpm'] - 600) < 40


def test_a_line_may_run_into_windows_that_have_no_line():
    f = project([L(0, ' '.join('w' * 1 for _ in range(28)), 0.0, 1.0), L(1, 'next', 5.0, 2.0)])       # 2.8 s in a 1 s window, but nothing until 5.0
    d = V.build(f); assert d['lines'][0]['fit'] == 'ok' and d['lines'][0]['room_s'] > 4


def test_unchanged_lines_are_reused_and_recordings_replace_them():
    f = project([L(0, 'one two', 0.0, 3.0), L(1, 'three four five', 3.0, 3.0)]); d = V.build(f)
    p = os.path.join(V.base(f), d['lines'][0]['path']); m = os.path.getmtime(p); V.build(f); assert os.path.getmtime(p) == m
    raw = os.path.join(tempfile.mkdtemp(), 'take.wav'); subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=500:duration=1.5', raw], check=True)
    V.save_recording(f, 1, raw); d = V.build(f); o = {x['seg']: x for x in d['lines']}
    assert o[1]['source'] == 'recorded' and abs(o[1]['natural_s'] - 1.5) < 0.1 and o[0]['source'] == 'synth'
    st = V.load_state(f); st['use']['1'] = 'synth'; V.save_state(f, st); assert {x['seg']: x for x in V.build(f)['lines']}[1]['source'] == 'synth'
    V.delete_recording(f, 1); assert not os.path.exists(V.recorded_path(f, 1))


def test_an_edited_script_is_a_new_version_that_is_spoken_and_progress_is_recorded():
    f = project([L(0, 'one two three', 0.0, 3.0), L(1, 'four five', 3.0, 3.0)]); d = V.build(f); st = V.load_status(f); assert st['state'] == 'done' and st['done'] == st['total'] == 2 and not V.running(f)
    old = V.newest_script(f); name = V.save_edit(f, {'1': 'four five six seven'}); assert name and name > old and V.newest_script(f) == name and V.save_edit(f, {'1': 'four five six seven'}) is None        # unchanged: no new version
    assert os.path.exists(os.path.join(V.config.race_dir(f), 'scripts', old))                                                                     # the old one is kept
    d2 = V.build(f); assert d2['script'] == name and {x['seg']: x for x in d2['lines']}[1]['text'] == 'four five six seven'
    a = {x['seg']: x for x in d['lines']}[0]['path']; assert {x['seg']: x for x in d2['lines']}[0]['path'] == a                                    # the unchanged line was not spoken again


def test_no_engine_is_reported_clearly():
    saved = V.ENGINES; V.ENGINES = {'none': ('None', lambda: False, lambda: [], None)}
    try: V.pick({}); assert False
    except RuntimeError as e: assert 'voice model is not installed' in str(e)
    finally: V.ENGINES = saved


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
