"""Integration-suite fixtures: the CLI, synthetic libraries, and a finished project built once per session (copying it is ~1000x cheaper than re-running ingest/audio/exposure)."""
import contextlib, io, os, shutil, subprocess, sys
from dataclasses import dataclass
import pytest
from library import copy_project, make_library

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
STAGES = 'ingest,audio,exposure'              # the stages that need only ffmpeg (no models): what a "processed" project has done


@pytest.fixture(autouse=True)
def no_resource_waits(monkeypatch):
    """The pipeline waits for free memory and an idle machine before a stage (pipeline/resources.py). A CI runner or a busy laptop may never have 4 GB free: the end-to-end tests must not wait for it."""
    monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1')


@dataclass
class Result:
    stdout: str; stderr: str; code: int
    @property
    def out(self): return self.stdout + self.stderr


def _invoke(args):
    """Run `strata360 <args>` in this process (fast, and counted by coverage): returns what it printed and its exit code."""
    from strata360 import cli
    out, err = io.StringIO(), io.StringIO(); old = sys.argv; sys.argv = ['strata360', *map(str, args)]; code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try: cli.main()
            except SystemExit as e: code = e.code if isinstance(e.code, int) else (1 if e.code else 0); err.write(str(e.code) + '\n' if isinstance(e.code, str) else '')
    finally: sys.argv = old
    return Result(out.getvalue(), err.getvalue(), code)


@pytest.fixture
def cli():
    """`cli('run', folder, '--stages', 'ingest')` -> Result(stdout, stderr, code), in-process. Raises AssertionError with the output on a non-zero exit unless `check=False`."""
    def run(*args, check=True):
        r = _invoke(args)
        if check and r.code: raise AssertionError(f'strata360 {" ".join(map(str, args))} exited {r.code}:\n{r.stdout[-800:]}\n{r.stderr[-800:]}')
        return r
    return run


@pytest.fixture
def cli_subprocess(monkeypatch):
    """The same through a real `python -m strata360` process: use for one smoke test of the entry point and for anything that must not share this process's state."""
    monkeypatch.setenv('PYTHONPATH', os.path.join(ROOT, 'src'))
    def run(*args, check=True):
        p = subprocess.run([sys.executable, '-m', 'strata360', *map(str, args)], capture_output=True, text=True)
        if check and p.returncode: raise AssertionError(f'strata360 {args} failed:\n{p.stdout[-800:]}\n{p.stderr[-800:]}')
        return Result(p.stdout, p.stderr, p.returncode)
    return run


@pytest.fixture
def library(tmp_path, synthetic_osv):                                  # (depends on synthetic_osv only to skip cleanly without ffmpeg/libx265)
    """`library(n=2, name='trip')` -> a footage folder of n distinct synthetic clips (plus ignorable junk files). See tests/utils/library.py."""
    return lambda n=1, **kw: make_library(tmp_path, n=n, **kw)


@pytest.fixture(scope='session')
def processed_template(tmp_path_factory, synthetic_osv):
    """Two clips taken through the model-free stages once for the whole session (read-only: use `processed`)."""
    base = tmp_path_factory.mktemp('processed'); lib = make_library(base, n=2)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('STRATA_NO_RESOURCE_LIMITS', '1'); mp.setenv('HOME', str(base)); mp.setenv('USERPROFILE', str(base))
        _invoke(['open', lib, '--no-run'])
        r = _invoke(['run', lib, '--stages', STAGES])
        assert r.code == 0 and "'ok': 6" in r.out, r.out
    return lib


@pytest.fixture
def processed(processed_template, tmp_path):
    """A private, writable copy of the processed project (2 clips: ingest, audio and exposure done) -> its footage folder. Edit it freely."""
    return copy_project(processed_template, tmp_path / 'trip')


@pytest.fixture
def served(processed, make_client):
    """`(client, folder)`: the HTTP API over the processed project (roots = its parent folder)."""
    return make_client(roots=[os.path.dirname(processed)]), processed


@pytest.fixture
def fake_engine(monkeypatch):
    """A speech engine that 'speaks' a tone 0.1 s per word, so voice-over tests need no TTS model: engine id 'fake', voices 'Test' and 'Other'."""
    from strata360.edit import voiceover as V
    from library import make_tone
    def speak(voice, rate, text, out): make_tone(out, max(1, len(text.split())) * 0.1, hz=300)
    monkeypatch.setattr(V, 'ENGINES', {'fake': ('Fake', lambda: True, lambda: [dict(name='Test', lang='en_GB'), dict(name='Other', lang='en_GB')], speak)})
    return V
