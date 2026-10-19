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


@pytest.fixture(autouse=True)
def software_encoder(monkeypatch):
    """The synthetic clips are a few dozen pixels wide, below what NVENC accepts (hevc_nvenc: 144 px; "Frame dimensions are less than the minimum supported value"), so a Windows machine with an NVIDIA GPU encodes them in software."""
    monkeypatch.setenv('STRATA_ENCODER', 'software')


@pytest.fixture(autouse=True)
def one_render_process(monkeypatch):
    """The tests shrink the lens size (flat.LS) in their own process; a helper process of a parallel render would not see that, so a test render uses one process (the claim logic has its own unit tests)."""
    monkeypatch.setenv('STRATA_RENDER_WORKERS', '1')


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


@pytest.fixture(scope='session')
def insta360_library(tmp_path_factory):
    """A read-only footage folder of two synthetic Insta360 X3 recordings 60 s apart (each an .insv pair with its trailer, plus an LRV proxy) and one front-lens file with no partner. See tests/utils/synthetic_insv.py;
    skipped when ffmpeg or libx264 is missing."""
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')): pytest.skip('ffmpeg/ffprobe not installed')
    from synthetic_insv import build_insv, names
    lib = tmp_path_factory.mktemp('insta360') / 'x3trip'
    try:
        build_insv(str(lib), name_time='20240720195607', number=1); build_insv(str(lib), name_time='20240720195707', number=2, lrv=False)
    except Exception as e: pytest.skip(f'cannot build the synthetic Insta360 clip: {e}')
    (lib / names('20240720195807', 3)[1]).write_bytes(b'x' * 10)
    return str(lib)


@pytest.fixture(scope='session')
def insta360_template(tmp_path_factory, insta360_library):
    """The Insta360 library taken through the model-free stages once for the whole session (read-only: use `insta360_processed`)."""
    lib = copy_project(insta360_library, tmp_path_factory.mktemp('insta360-processed') / 'x3trip')
    with pytest.MonkeyPatch.context() as mp:
        home = os.path.dirname(lib); mp.setenv('STRATA_NO_RESOURCE_LIMITS', '1'); mp.setenv('HOME', home); mp.setenv('USERPROFILE', home)
        _invoke(['open', lib, '--no-run'])
        r = _invoke(['run', lib, '--stages', STAGES])
        assert r.code == 0 and "'ok': 6" in r.out, r.out
    return lib


@pytest.fixture
def insta360_processed(insta360_template, tmp_path):
    """A private, writable copy of the processed Insta360 project (2 recordings: ingest, audio and exposure done) -> its footage folder."""
    return copy_project(insta360_template, tmp_path / 'x3trip')


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
