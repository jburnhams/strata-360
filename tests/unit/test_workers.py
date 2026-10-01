"""Parallel workers: claims, stale claims, state updates under a lock, clearing with dependents. Run: .venv/bin/python tests/test_workers.py"""
import json, multiprocessing as mp, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
from strata360.pipeline import runner, config


def project():
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, 'strata360', 'clips', 'CAM_a_0001_D')); return d


def _claimer(folder, out):
    out.put(runner.claim(folder, 'CAM_a_0001_D', 'scenes')); time.sleep(1.5)                    # a real worker stays alive while it holds a claim (a claim of a dead process is stale by design)


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


def test_track_stages_pause_without_a_track_and_reset_when_it_or_the_clock_changes():
    from strata360.pipeline import clips as clipmod
    f = project(); cfg = dict(config.DEFAULTS); cfg['stages'] = ['ingest', 'places']; cfg['camera_clock'] = dict(utc_offset_hours=0.0, offset_seconds=370.0, verified=True); st = runner.STAGES['places']
    c = clipmod.Clip(id='CAM_a_0001_D', osv='x.OSV', fingerprint='abc'); state = dict(ingest=dict(status='ok', key='k'))
    done, key, blocked = runner._cached(f, st, c, cfg, state, '/nonexistent'); assert not done and 'race_track' in blocked            # no track: paused (not failed)
    open(os.path.join(f, 'strata360', 'track.fit'), 'wb').write(b'a' * 5000)
    done, k1, blocked = runner._cached(f, st, c, cfg, state, '/nonexistent'); assert not blocked and k1                              # a track: runnable
    open(os.path.join(f, 'strata360', 'track.fit'), 'wb').write(b'b' * 5000); _, k2, _ = runner._cached(f, st, c, cfg, state, '/nonexistent'); assert k2 != k1   # a different track: new key, so it is redone
    cfg['camera_clock']['offset_seconds'] = 380.0; _, k3, _ = runner._cached(f, st, c, cfg, state, '/nonexistent'); assert k3 != k2                                # the clip-to-track alignment moved: redone
    cfg['camera_clock']['offset_seconds'] = 370.0; _, k4, _ = runner._cached(f, st, c, cfg, state, '/nonexistent'); assert k4 == k2                                # back to the same alignment: same key


def test_soft_dependency_holds_back_new_work_but_never_invalidates_finished_work():
    from strata360.pipeline import clips as clipmod
    f = project(); cfg = dict(config.DEFAULTS); cfg['stages'] = ['ingest', 'proxy', 'people']; st = runner.STAGES['people']; assert 'proxy' in st.soft_deps and 'proxy' not in st.deps
    c = clipmod.Clip(id='CAM_a_0001_D', osv='x.OSV', fingerprint='abc'); d = os.path.join(f, 'strata360', 'clips', 'CAM_a_0001_D')
    state = dict(ingest=dict(status='ok', key='k'))
    done, key, blocked = runner._cached(f, st, c, cfg, state, d); assert not done and blocked == ['proxy']                    # a new item waits for the proxy
    state['people'] = dict(status='ok', key=key)
    for o in st.outputs: open(os.path.join(d, o), 'w').write('x')
    done2, key2, blocked2 = runner._cached(f, st, c, cfg, state, d); assert done2 and key2 == key and not blocked2               # the same item, finished before the proxy existed: still valid, key unchanged
    state['proxy'] = dict(status='ok', key='p'); done3, key3, blocked3 = runner._cached(f, st, c, cfg, state, d); assert done3 and key3 == key


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
