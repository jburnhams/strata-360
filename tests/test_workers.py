"""Parallel workers: claims, stale claims, state updates under a lock, clearing with dependents. Run: .venv/bin/python tests/test_workers.py"""
import json, multiprocessing as mp, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.pipeline import runner, config


def project():
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, 'strata360', 'clips', 'CAM_a_0001_D')); return d


def _claimer(folder, out):
    out.put(runner.claim(folder, 'CAM_a_0001_D', 'scenes'))


def test_only_one_process_gets_a_claim():
    f = project(); q = mp.Queue(); ps = [mp.Process(target=_claimer, args=(f, q)) for _ in range(6)]
    [p.start() for p in ps]; [p.join() for p in ps]; got = [q.get() for _ in ps]
    assert sum(got) == 1, got                                                                     # six processes race for one item: exactly one wins
    runner.release(f, 'CAM_a_0001_D', 'scenes'); assert runner.claim(f, 'CAM_a_0001_D', 'scenes')  # released: claimable again


def test_stale_claim_of_a_dead_process_is_taken_over():
    f = project(); os.makedirs(runner._claims(f)); open(os.path.join(runner._claims(f), 'CAM_a_0001_D__people'), 'w').write('999999 0')       # no such process
    assert runner.claim(f, 'CAM_a_0001_D', 'people') and open(os.path.join(runner._claims(f), 'CAM_a_0001_D__people')).read().split()[0] == str(os.getpid())


def _writer(folder, name):
    for i in range(30): runner.update_state(folder, 'CAM_a_0001_D', name, dict(status='ok', key=str(i)))


def test_concurrent_state_updates_do_not_lose_each_other():
    f = project(); ps = [mp.Process(target=_writer, args=(f, n)) for n in ('thumb', 'people', 'scenes', 'audio')]
    [p.start() for p in ps]; [p.join() for p in ps]
    st = runner.load_state(f, 'CAM_a_0001_D'); assert set(st) == {'thumb', 'people', 'scenes', 'audio'} and all(v['key'] == '29' for v in st.values()), st


def test_dependents_and_clear_items():
    assert runner.dependents('scenes')[0] == 'scenes' and 'candidates' in runner.dependents('scenes') and 'thumb_best' in runner.dependents('scenes') and 'audio' not in runner.dependents('scenes')
    f = project()
    for n in ('scenes', 'candidates', 'audio'): runner.update_state(f, 'CAM_a_0001_D', n, dict(status='ok', key='x'))
    assert runner.clear_items(f, [('CAM_a_0001_D', 'scenes'), ('CAM_a_0001_D', 'candidates'), ('CAM_a_0001_D', 'nothing')]) == 2
    assert set(runner.load_state(f, 'CAM_a_0001_D')) == {'audio'}


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
