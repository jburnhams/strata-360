import pytest
from strata360.pipeline import guard as G, resources as RS


def rows(*specs):   # (pid, ppid, cpu, rss_mb, command)
    return [(p, pp, c, m, '01:00', cmd) for p, pp, c, m, cmd in specs]


def test_check_fails_fast_and_says_what_is_using_the_machine(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False)
    monkeypatch.setattr(RS, 'mem_available_gb', lambda: 1.0); monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.1)
    monkeypatch.setattr(G, 'processes', lambda: rows((10, 1, 5.0, 4000, '/usr/bin/bigjob --x'), (11, 1, 1.0, 10, 'ffmpeg -i a')))
    with pytest.raises(G.ResourceBusy) as e: G.check('proxy render', 3.0)
    m = str(e.value); assert 'only 1.0 GB' in m and 'bigjob pid 10' in m and G.ResourceBusy.retryable and 'Wait for it to clear' in m


def test_check_counts_ffmpeg_processes_and_ignores_everything_when_switched_off(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 50.0); monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.0)
    monkeypatch.setattr(G, 'processes', lambda: rows(*[(100 + i, 1, 0.0, 50, f'ffmpeg -i x{i}') for i in range(7)]))
    with pytest.raises(G.ResourceBusy) as e: G.check('x', 1.0)
    assert '7 ffmpeg' in str(e.value) and 'pkill ffmpeg' in str(e.value)
    monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1'); G.check('x', 1.0)                         # off: no complaint


def test_popen_refuses_a_new_ffmpeg_over_the_limit_and_kills_children_when_asked(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.setenv('STRATA_MAX_FFMPEG', '1')
    monkeypatch.setattr(G, 'processes', lambda: rows((5, 1, 0.0, 10, 'ffmpeg -i a')))
    with pytest.raises(G.ResourceBusy): G.popen(['ffmpeg', '-version'])
    p = G.popen(['sleep', '30']); assert p.poll() is None
    G.kill_children(); assert p.poll() is not None                                                   # a job that ends or fails does not leave its processes running


def test_the_watchdog_stops_a_job_when_load_or_memory_or_its_own_size_goes_over(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 8.0); monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.2)
    assert G.verdict(rows=[]) is None
    monkeypatch.setattr(G, 'load_per_cpu', lambda: 3.0); assert 'overloaded' in G.verdict(rows=[])
    monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.2); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 0.3); assert 'out of memory' in G.verdict(rows=[])
    monkeypatch.setattr(RS, 'mem_available_gb', lambda: 8.0); import os
    big = rows((os.getpid(), 1, 1.0, 5000, 'python job'), (999, os.getpid(), 1.0, 1000, 'ffmpeg'))
    assert 'over its cap' in G.verdict(max_gb=4.0, rows=big) and G.verdict(max_gb=8.0, rows=big) is None


def test_heavy_runs_the_watchdog_and_cleans_up(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 50.0); monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.0); monkeypatch.setattr(G, 'processes', lambda: [])
    monkeypatch.setattr(G, 'POLL_S', 0.05); why = []; monkeypatch.setattr(G, 'verdict', lambda cap=None, **k: 'because')
    import time
    with G.heavy('job', 1.0, on_abort=why.append): p = G.popen(['sleep', '30']); time.sleep(0.4)
    assert why and why[0] == 'because' and p.poll() is not None                                      # the watchdog fired, the child is dead
