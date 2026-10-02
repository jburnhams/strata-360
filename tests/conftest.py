"""Shared pytest configuration. Tests under tests/integration get the `integration` marker automatically."""
import os, shutil, socket, pytest
from strata360.pipeline import guard


def pytest_collection_modifyitems(items):
    for item in items:
        if os.sep + 'integration' + os.sep in str(item.fspath): item.add_marker(pytest.mark.integration)


@pytest.fixture(scope='session')
def synthetic_osv(tmp_path_factory):
    """A tiny synthetic OSV (see tests/utils/synthetic_osv.py) built once per session; skipped if ffmpeg/libx265 is missing."""
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')): pytest.skip('ffmpeg/ffprobe not installed')
    from synthetic_osv import build_osv
    d = tmp_path_factory.mktemp('osv'); path = str(d / 'CAM_20260221120007_0019_D.OSV')
    try: build_osv(path, frames=60, drop=(30, 31))
    except Exception as e: pytest.skip(f'cannot build the synthetic clip: {e}')
    return path


# ---- hermetic by default: every suite ----

@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """~ points into the test's tmp dir, so nothing reads or writes the developer's real ~/.strata360 (server state, secrets, keys)."""
    base = tmp_path_factory.mktemp('env'); home = base / 'home'; home.mkdir()      # outside the test's own tmp_path: tests browse that as a root
    monkeypatch.setenv('HOME', str(home)); monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('STRATA_RACES', str(base / 'races'))
    for k in ('ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'): monkeypatch.delenv(k, raising=False)
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A unit test that tries to open an outbound connection fails at once (loopback and unix sockets are fine). Use `fake_urlopen` to script HTTP."""
    real = socket.socket.connect
    def guarded(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in ('127.0.0.1', '::1', 'localhost'): raise AssertionError(f'unit tests must not use the network (tried {address!r})')
        return real(self, address, *a, **kw)
    monkeypatch.setattr(socket.socket, 'connect', guarded)


@pytest.fixture(autouse=True)
def restore_globals():
    """Several tests were written as standalone scripts and replace module globals directly (time.sleep, urlopen, resource probes, env vars).
    Put everything back after each test so the suite can run in one process and in any order."""
    import sys, time, urllib.request
    sleep, urlopen, env = time.sleep, urllib.request.urlopen, dict(os.environ)
    res = sys.modules.get('strata360.pipeline.resources'); saved = {k: getattr(res, k) for k in ('mem_available_gb', 'busy') if hasattr(res, k)} if res else {}
    yield
    time.sleep, urllib.request.urlopen = sleep, urlopen
    os.environ.clear(); os.environ.update(env)
    res = sys.modules.get('strata360.pipeline.resources')
    if res:
        for k, v in saved.items(): setattr(res, k, v)


# ---- shared fixtures: scripted outside world and on-disk projects (helpers live in tests/utils) ----

@pytest.fixture
def fake_urlopen(monkeypatch):
    """Script `urllib.request.urlopen`: `fake_urlopen.reply({...}, http_error(429))`, then assert on `fake_urlopen.calls` (url, method, headers, parsed JSON body). Unexpected calls fail."""
    import urllib.request
    from fakes import FakeUrlopen
    f = FakeUrlopen(); monkeypatch.setattr(urllib.request, 'urlopen', f); return f


@pytest.fixture
def fake_popen(monkeypatch):
    """Replace `subprocess.Popen` everywhere: nothing starts; `fake_popen.instances` lists the commands (`.cmd`) and kwargs (`.kw`) it was asked to run."""
    import subprocess
    from fakes import FakePopen
    FakePopen.instances = []; monkeypatch.setattr(subprocess, 'Popen', FakePopen); return FakePopen


@pytest.fixture
def fake_run(monkeypatch):
    """Replace `subprocess.run` / `check_output`: record the command lines in `.calls`; set `.returns['ffprobe'] = b'...'` (substring of the command line) for output, `.code = 1` to fail."""
    import subprocess
    from fakes import FakeRun
    f = FakeRun(); monkeypatch.setattr(subprocess, 'run', f); monkeypatch.setattr(subprocess, 'check_output', f.check_output); return f


@pytest.fixture
def no_sleep(monkeypatch):
    """time.sleep returns at once and records the delays: `no_sleep.delays`."""
    import time
    class S(list):
        def __call__(self, s): self.append(s)
    s = S(); s.delays = s; monkeypatch.setattr(time, 'sleep', s); return s


@pytest.fixture
def make_project(tmp_path):
    """`make_project(name='trip', config=True, clips=[...])` -> Project (folder, race_dir, add_clip, write_json). See tests/utils/projects.py."""
    from projects import make_project as mk
    return lambda name='trip', **kw: mk(tmp_path, name, **kw)


@pytest.fixture
def project(make_project):
    """A ready project with race.json and one clip."""
    from projects import CLIP_ID
    return make_project(config=True, clips=[CLIP_ID])


@pytest.fixture
def make_client(tmp_path, monkeypatch, fake_popen):
    """`make_client(roots=None, token=None)` -> FastAPI TestClient for `server.app.create_app`; roots default to `tmp_path`. Server state (`~/.strata360/state.json`), the job tables and worker
    processes are isolated: no real worker is ever started (see `fake_popen`)."""
    from fastapi.testclient import TestClient
    from strata360.server import app
    monkeypatch.setattr(app, 'STATE', str(tmp_path / '_state.json'))
    for table in ('JOBS', 'FINAL_JOBS', 'FILM_JOBS', 'SCRIPT_JOBS', 'SCRIPT2_JOBS', 'PLAN_JOBS', 'GAP_JOBS'): monkeypatch.setattr(app, table, {})
    def make(roots=None, token=None, **kw):
        rs = [os.path.realpath(str(r)) for r in (roots if roots is not None else [tmp_path])]
        return TestClient(app.create_app(rs, token=token), **kw)
    return make


@pytest.fixture
def client(make_client): return make_client()


@pytest.fixture(scope='session', autouse=True)
def machine_watchdog():
    """The test run (and every process it starts) is stopped, with a message, when the machine gets short of memory, starts swapping heavily or is overloaded: a run of the suite must never take the computer down.
    STRATA_NO_RESOURCE_LIMITS=1 (set on CI) turns it off, like every other guard."""
    stop = guard.watch('the test run', max_gb=6.0); yield; stop()
