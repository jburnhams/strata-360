import sys
import pytest
from strata360.pipeline import guard as G, resources as RS


@pytest.fixture(autouse=True)
def calm_machine(monkeypatch):
    """The verdict also reads the real machine's memory pressure, swap and size: pin them, or a test fails whenever the machine that runs it has swap in use."""
    monkeypatch.setattr(G, 'pressure_level', lambda: 1); monkeypatch.setattr(G, 'swap_used_gb', lambda: 0.0); monkeypatch.setattr(RS, 'mem_total_gb', lambda: 16.0)


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
    monkeypatch.setattr(G, 'processes', lambda: rows(*[(100 + i, 1, 0.0, 50, f'ffmpeg -i x{i}') for i in range(9)]))
    with pytest.raises(G.ResourceBusy) as e: G.check('x', 1.0)
    assert '9 ffmpeg' in str(e.value) and 'pkill ffmpeg' in str(e.value)
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


def test_memory_pressure_and_swap_stop_a_job_and_block_a_start(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 8.0); monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.1)
    monkeypatch.setattr(G, 'processes', lambda: []); monkeypatch.setattr(G, 'pressure_level', lambda: 2); monkeypatch.setattr(G, 'swap_used_gb', lambda: 0.0)
    assert 'memory pressure' in G.verdict(rows=[])
    with pytest.raises(G.ResourceBusy) as e: G.check('x', 1.0)
    assert 'memory pressure' in str(e.value)
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 16.0); monkeypatch.setattr(G, 'pressure_level', lambda: 1); monkeypatch.setattr(G, 'swap_used_gb', lambda: 5.0); assert 'swap is filling up' in G.verdict(rows=[])
    with pytest.raises(G.ResourceBusy): G.check('x', 1.0)
    monkeypatch.setattr(G, 'swap_used_gb', lambda: 0.0); assert G.verdict(rows=[]) is None


@pytest.mark.skipif(sys.platform == 'win32', reason='needs ps')
def test_kill_tree_and_panic_stop_leftovers_but_not_the_server(monkeypatch):
    import subprocess, sys, time
    a = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); b = subprocess.Popen(['sleep', '60'])
    try:
        assert a.pid in G.descendants() and b.pid in G.descendants()
        G.kill_tree(); time.sleep(0.3); assert a.poll() is not None and b.poll() is not None
    finally:
        for p in (a, b):
            if p.poll() is None: p.kill()
    rows_ = [(900, 1, 0.0, 10, '1:00', '.venv/bin/python -m strata360 serve --port 8360'), (901, 1, 0.0, 10, '1:00', 'ffmpeg -i x'), (902, 1, 0.0, 10, '1:00', '/bin/ls')]
    monkeypatch.setattr(G, 'processes', lambda: rows_); killed = []; monkeypatch.setattr(G.os, 'kill', lambda pid, sig: killed.append(pid))
    assert G.panic() == [901] and killed == [901]                                                    # ffmpeg goes; the server and unrelated processes stay


def test_the_swap_limits_are_shares_of_the_machines_memory(monkeypatch):
    for k in ('STRATA_START_SWAP_PCT', 'STRATA_KILL_SWAP_PCT', 'STRATA_KILL_SWAP_GB'): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 16.0); assert G.swap_limit_gb('start') == pytest.approx(4.0) and G.swap_limit_gb('kill') == pytest.approx(4.8)
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 64.0); assert G.swap_limit_gb('start') == pytest.approx(16.0)                                    # the same share on a bigger machine
    monkeypatch.setenv('STRATA_START_SWAP_PCT', '10'); assert G.swap_limit_gb('start') == pytest.approx(6.4)
    monkeypatch.setenv('STRATA_KILL_SWAP_GB', '5'); assert G.swap_limit_gb('kill') == 5.0


def test_a_start_is_blocked_only_above_the_start_share(monkeypatch):
    monkeypatch.delenv('STRATA_NO_RESOURCE_LIMITS', raising=False); monkeypatch.delenv('STRATA_START_SWAP_PCT', raising=False); monkeypatch.setattr(RS, 'mem_total_gb', lambda: 16.0); monkeypatch.setattr(RS, 'mem_available_gb', lambda: 8.0)
    monkeypatch.setattr(G, 'load_per_cpu', lambda: 0.1); monkeypatch.setattr(G, 'processes', lambda: []); monkeypatch.setattr(G, 'pressure_level', lambda: 1); monkeypatch.setattr(G, 'swap_used_gb', lambda: 3.5)
    G.check('x', 1.0)                                                                                                                                  # 3.5 GB of 16 GB is under 25 percent
    monkeypatch.setattr(G, 'swap_used_gb', lambda: 4.4)
    with pytest.raises(G.ResourceBusy, match=r'limit 4\.0 GB, 25% of memory'): G.check('x', 1.0)


def test_the_machines_memory_is_read_in_gb():
    assert RS.mem_total_gb() > 1.0
