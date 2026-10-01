"""Resource guards: extra workers only with lots of free memory, lowest priority, heavy stages one at a time. Run: .venv/bin/python tests/test_resources.py"""
import os, subprocess, sys, tempfile
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
from strata360.pipeline import resources as R, runner, config


def test_extra_workers_need_plenty_of_free_memory_and_an_idle_machine():
    R.mem_available_gb = lambda: 30.0; R.busy = lambda cfg=None: False
    assert R.may_start_extra_worker(0)[0] and R.may_start_extra_worker(1)[0] and not R.may_start_extra_worker(2)[0]                # first always; a second with 30 GB free; not beyond the limit of 2
    R.mem_available_gb = lambda: 6.0; ok, why = R.may_start_extra_worker(1); assert not ok and 'free' in why and R.may_start_extra_worker(0)[0]
    R.mem_available_gb = lambda: 30.0; R.busy = lambda cfg=None: True; ok, why = R.may_start_extra_worker(1); assert not ok and 'busy' in why
    cfg = dict(resources=dict(max_workers=1)); R.busy = lambda cfg=None: False; assert not R.may_start_extra_worker(1, cfg)[0]      # configurable


def test_a_worker_waits_for_memory_and_load_before_starting_an_item():
    seen = []; R.time.sleep = lambda s: seen.append(s)
    R.busy = lambda cfg=None: False; mem = iter([2.0, 2.0, 20.0]); R.mem_available_gb = lambda: next(mem)
    assert R.wait_for_headroom('scenes', None, None, lambda m: None) and len(seen) == 2                                              # scenes needs about 9 GB: waited twice, then went
    R.mem_available_gb = lambda: 20.0; loads = iter([True, False]); R.busy = lambda cfg=None: next(loads); seen.clear()
    assert R.wait_for_headroom('proxy', None, None, lambda m: None) and len(seen) == 1
    R.mem_available_gb = lambda: 0.5; assert not R.wait_for_headroom('proxy', None, None, lambda m: None, max_wait=-1)             # gives up when told to


def test_heavy_stages_have_a_concurrency_cap_and_light_ones_do_not():
    assert R.STAGE_MAX_CONCURRENT['scenes'] == 1 and R.STAGE_MAX_CONCURRENT['proxy'] == 1 and R.STAGE_MAX_CONCURRENT['people'] == 1 and 'places' not in R.STAGE_MAX_CONCURRENT
    f = tempfile.mkdtemp(); os.makedirs(os.path.join(f, 'strata360'))
    assert runner._stage_count(f, 'scenes') == 0 and runner.claim(f, 'A', 'scenes') and runner._stage_count(f, 'scenes') == 1
    assert runner.claim(f, 'B', 'scenes')                                                                                            # claims themselves do not enforce the cap (the worker loop does)


@pytest.mark.skipif(sys.platform == 'win32', reason='nice values do not exist on Windows (oslib.lower_priority uses a priority class; see test_oslib)')
def test_low_priority_really_lowers_the_niceness():
    code = "import sys; sys.path.insert(0, %r); import os; from strata360.pipeline import resources as R; R.low_priority(); print(os.nice(0), os.environ['OMP_NUM_THREADS'])" % os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src')
    out = subprocess.run([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True).stdout.split(); assert out[1] == '2', out
    if sys.platform == 'darwin': assert int(out[0]) > 0, out                    # macOS also moves the process to the background task class, which reports a lower niceness (9 on the CI runners)
    else: assert out[0] == '19', out


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
