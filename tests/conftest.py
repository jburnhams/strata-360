"""Shared pytest configuration. Tests under tests/integration get the `integration` marker automatically."""
import os, shutil, pytest


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
