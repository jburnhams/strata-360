"""End-to-end test of the scripted pipeline (ingest, audio, exposure) on a synthetic OSV built with ffmpeg (tests/utils/synthetic_osv.py).
Needs ffmpeg and ffprobe, no real footage and no models. Run: pytest tests/integration/test_pipeline.py
Transcription and alignment need models, so run them by hand (README section 0)."""
import json, os, shutil, subprocess, sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CLI = [sys.executable, '-m', 'strata360']
CLIP = 'CAM_20260221120007_0019_D'
STAGES = 'ingest,audio,exposure'


def cli(env, *args, check=True):
    r = subprocess.run([*CLI, *args], capture_output=True, text=True, env=env)
    if check and r.returncode: raise AssertionError(f'{args} failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}')
    return r


@pytest.fixture
def race(tmp_path, synthetic_osv):
    lib = tmp_path / 'lib'; lib.mkdir(); shutil.copy(synthetic_osv, lib / os.path.basename(synthetic_osv))
    (lib / '.hidden').write_text('x'); (lib / 'notes.txt').write_text('not a clip')
    env = dict(os.environ, STRATA_RACES=str(tmp_path / 'races'), PYTHONPATH=os.path.join(ROOT, 'src'))
    out = cli(env, 'init', 't', '--library', str(lib), '--languages', 'en,fr', '--clock-offset-hours', '0').stdout
    return env, tmp_path / 'races' / 't', out


def load(path): return json.load(open(path))


def test_init_ignores_hidden_files_and_reports_others(race):
    _, _, out = race
    assert '1 clips' in out and 'notes.txt' in out, out


def test_ingest_and_audio_facts(race):
    env, rd, _ = race
    r1 = cli(env, 'run', 't', '--stages', STAGES).stdout
    assert 'FAILED' not in r1 and "'ok': 3" in r1, r1
    cdir = rd / 'clips' / CLIP
    clip = load(cdir / 'clip.json')
    assert clip['time']['start_utc'] == '2026-02-21T12:00:07Z' and clip['time']['utc_status'] == 'provisional', clip['time']
    assert clip['video']['streams'] == 2 and clip['video']['nominal_fps'] == 50.0
    assert clip['video']['dropped_frames'] == 2 and clip['video']['gaps'][0]['after_frame'] == 29
    assert clip['camera']['model'] == 'Osmo 360' and clip['colour_mode'] == 'normal' and clip['calibration_slots'] == 16
    assert clip['audio']['channels'] == 2 and abs(clip['duration_s'] - 1.2) < 0.05
    au = load(cdir / 'audio.json')
    assert au['summary']['integrated_lufs'] < 0 and au['utc_hash'] == clip['time']['utc_hash']
    ex = load(cdir / 'exposure.json'); assert ex['clip_id'] == CLIP and ex['sampling']['n_samples'] > 0 and ex['utc_hash'] == clip['time']['utc_hash']


def test_stale_header_is_detected(race):
    env, rd, _ = race
    cli(env, 'run', 't', '--stages', STAGES)
    cdir = rd / 'clips' / CLIP; clip = load(cdir / 'clip.json'); au = load(cdir / 'audio.json')
    from strata360.pipeline.ingest import check_header
    check_header(clip, au)
    with pytest.raises(ValueError): check_header(clip, dict(au, utc_hash='000000000000'))


def test_caching_and_clock_change(race):
    env, rd, _ = race
    cli(env, 'run', 't', '--stages', STAGES)
    assert 'nothing left to do' in cli(env, 'run', 't', '--stages', STAGES).stdout                       # unchanged: nothing re-runs
    cfgp = rd / 'race.json'; cfg = load(cfgp); cfg['camera_clock'] = dict(utc_offset_hours=1.0, verified=True); json.dump(cfg, open(cfgp, 'w'))
    r = cli(env, 'run', 't', '--stages', STAGES).stdout                                                    # the clock changes ingest and everything after it
    cdir = rd / 'clips' / CLIP; clip = load(cdir / 'clip.json')
    assert clip['time']['start_utc'] == '2026-02-21T11:00:07Z' and clip['time']['utc_status'] == 'definitive', clip['time']
    assert 'ingest: ok' in r and load(cdir / 'audio.json')['utc_hash'] == clip['time']['utc_hash']
    assert "'ok': 3" in cli(env, 'run', 't', '--stages', STAGES, '--force').stdout


def test_status_and_report(race):
    env, _, _ = race
    cli(env, 'run', 't', '--stages', STAGES)
    st = cli(env, 'status', 't').stdout; assert CLIP in st and 'FAIL' not in st and 'stale' not in st, st
    rep = cli(env, 'report', 't').stdout; assert '1 clips' in rep and 'colour modes' in rep, rep
