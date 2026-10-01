"""OS helpers (strata360.oslib): file lock, process liveness, termination. These run on every OS in CI."""
import os, subprocess, sys, time
from strata360 import oslib


def test_file_lock_excludes_other_processes(tmp_path):
    p = tmp_path / 'lock'
    code = ("import sys, time; from strata360 import oslib\n"
            "with open(sys.argv[1], 'a+') as f, oslib.file_lock(f):\n    print('locked', flush=True); time.sleep(1.0)\n")
    child = subprocess.Popen([sys.executable, '-c', code, str(p)], stdout=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)))
    assert child.stdout.readline().strip() == 'locked'
    t0 = time.time()
    with open(p, 'a+') as f, oslib.file_lock(f): waited = time.time() - t0
    child.wait()
    assert waited > 0.3, waited                                                  # had to wait for the child to release it


def test_file_lock_is_released_after_the_block(tmp_path):
    with open(tmp_path / 'l', 'a+') as f:
        for _ in range(3):
            with oslib.file_lock(f): pass


def test_pid_alive():
    assert oslib.pid_alive(os.getpid()) and oslib.pid_alive(str(os.getpid()))
    assert not oslib.pid_alive(None) and not oslib.pid_alive('x') and not oslib.pid_alive(0)
    p = subprocess.Popen([sys.executable, '-c', 'pass']); p.wait()
    assert not oslib.pid_alive(p.pid)


def test_kill_tree_ends_the_process():
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    assert oslib.pid_alive(p.pid)
    oslib.kill_tree(p.pid)
    p.wait(timeout=10)
    assert not oslib.pid_alive(p.pid)


def test_cli_command_runs_the_cli():
    out = subprocess.run([*oslib.cli_command(), '--help'], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and 'init' in out.stdout, out.stderr[-300:]
