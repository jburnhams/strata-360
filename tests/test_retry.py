"""Retrying stage items: counts per stage, waiting between tries, non-retryable errors, progress that does not use a retry, and the health shown in the app. Run: .venv/bin/python tests/test_retry.py"""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.pipeline import runner, config, retry, stages

retry.BASE_WAIT_S = 0.05; retry.MAX_WAIT_S = 0.2
CALLS = []


def project(stage_name):
    f = tempfile.mkdtemp(); open(os.path.join(f, 'CAM_20260101000000_0001_D.OSV'), 'wb').write(b'x' * 100); rd = config.race_dir(f); os.makedirs(rd)
    cfg = dict(library=f, stages=[stage_name], resources=dict(busy_load_fraction=1000, reserve_gb=0.0)); json.dump(cfg, open(os.path.join(rd, 'race.json'), 'w')); return f


def fake(name, behaviour, retries=2):
    CALLS.clear()
    def fn(ctx):
        CALLS.append(1); b = behaviour(len(CALLS))
        if b: raise b
        open(ctx.path('out.txt'), 'w').write('ok')
    stages.STAGES[name] = stages.Stage(name, 1, fn, (), (), ('out.txt',), False, 'fake', (), retries, False)
    if name not in stages.ORDER: stages.ORDER.append(name)


def state(f, name): return runner.load_state(f, 'CAM_20260101000000_0001_D').get(name, {})


def test_every_stage_retries_twice_except_the_paid_transcript_check():
    assert stages.STAGES['transcript_check'].retries == 100 and all(s.retries == 2 for n, s in stages.STAGES.items() if n not in ('transcript_check',) and not n.startswith('t_'))


def test_a_flaky_item_is_tried_again_and_succeeds():
    fake('t_flaky', lambda n: RuntimeError('boom') if n < 3 else None); f = project('t_flaky'); runner.work(f, ['t_flaky'], log=lambda *a: None)
    assert len(CALLS) == 3 and state(f, 't_flaky')['status'] == 'ok'                                          # failed twice, the third try worked


def test_after_its_retries_the_item_fails_with_the_tries_recorded():
    fake('t_always', lambda n: RuntimeError('nope')); f = project('t_always'); runner.work(f, ['t_always'], log=lambda *a: None); s = state(f, 't_always')
    assert len(CALLS) == 3 and s['status'] == 'failed' and s['attempts'] == 3 and 'nope' in s['error']      # 1 try + 2 retries


def test_an_error_that_is_not_worth_retrying_fails_at_once():
    class Rejected(Exception): retryable = False
    fake('t_fatal', lambda n: Rejected('key rejected')); f = project('t_fatal'); runner.work(f, ['t_fatal'], log=lambda *a: None); assert len(CALLS) == 1 and state(f, 't_fatal')['status'] == 'failed'


def test_an_attempt_that_made_progress_does_not_use_up_a_retry():
    fake('t_slow', lambda n: retry.RetryLater('busy', progress=True) if n < 6 else None); f = project('t_slow'); runner.work(f, ['t_slow'], log=lambda *a: None)
    assert len(CALLS) == 6 and state(f, 't_slow')['status'] == 'ok'                                          # five slow-progress attempts, only 2 retries allowed: still done


def test_next_state_rules_and_backoff():
    k, e = retry.next_state(None, 'x', True, False, 2, now=100.0); assert k == 'retry' and e['attempts'] == 1 and retry.backoff_s(1) <= e['wait_s'] <= retry.backoff_s(1) * 1.2 + 0.1 and abs(e['next_try_at'] - 100.0 - e['wait_s']) < 0.1
    k, e = retry.next_state(e, 'x', True, False, 2, now=110.0); assert k == 'retry' and e['attempts'] == 2 and e['first_failure_at'] == 100.0
    k, e = retry.next_state(e, 'x', True, False, 2, now=120.0); assert k == 'failed' and e['attempts'] == 3
    assert retry.next_state(None, 'x', False, False, 100)[0] == 'failed' and retry.backoff_s(1) < retry.backoff_s(3) <= retry.MAX_WAIT_S
    retry.BASE_WAIT_S, retry.MAX_WAIT_S = 15.0, 600.0; assert [retry.backoff_s(n) for n in (1, 2, 3, 4, 5, 6, 7, 8)] == [15, 30, 60, 120, 240, 480, 600, 600]; retry.BASE_WAIT_S, retry.MAX_WAIT_S = 0.05, 0.2       # doubles each time, capped


def test_health_counts_items_failing_now_and_time_since_the_last_success():
    fake('t_health', lambda n: None, retries=100); f = project('t_health'); now = time.time(); import datetime as dt
    runner.update_state(f, 'CAM_20260101000000_0001_D', 't_health', dict(status='retry', attempts=3, retries=100, last_error='HTTP 503 high demand', wait_s=120, next_try_at=now + 60, last_attempt_at=now))
    h = runner.stage_health(f)['t_health']; assert h['retrying'] == 1 and h['attempts'] == 3 and h['retries'] == 100 and 50 <= h['next_try_in_s'] <= 60 and h['sleep_s'] == 120 and '503' in h['last_error'] and h['last_success_ago_s'] is None
    runner.update_state(f, 'CAM_20260101000000_0001_D', 't_other', dict(status='ok', at=(dt.datetime.now() - dt.timedelta(seconds=300)).isoformat(timespec='seconds')))
    stages.STAGES['t_other'] = stages.Stage('t_other', 1, lambda c: None, (), (), (), False, '', (), 2, False)
    h2 = runner.stage_health(f); assert 't_other' not in h2                                                      # a stage with nothing failing is not listed


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for fn in fns:
        try: fn(); print('ok  ', fn.__name__)
        except Exception as e: bad += 1; print('FAIL', fn.__name__, repr(e)[:300])
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
