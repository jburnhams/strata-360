"""End-to-end test of the scripted pipeline on the sample clip (about 30 s; add --slow to include transcription and alignment).
Run with the project venv:  .venv/bin/python tests/test_pipeline.py [--slow]"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))
SAMPLE = os.path.join(ROOT, 'videos', 'CAM_20260221120007_0019_D.OSV')
CLI = os.path.join(ROOT, 'strata360')

def cli(env, *args, check=True):
    r = subprocess.run([CLI, *args], capture_output=True, text=True, env=env)
    if check and r.returncode: raise AssertionError(f'{args} failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}')
    return r

def main():
    slow = '--slow' in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        lib = os.path.join(tmp, 'lib'); os.makedirs(lib); os.symlink(SAMPLE, os.path.join(lib, os.path.basename(SAMPLE)))
        open(os.path.join(lib, '.hidden'), 'w').write('x'); open(os.path.join(lib, 'notes.txt'), 'w').write('not a clip')
        env = dict(os.environ, STRATA_RACES=os.path.join(tmp, 'races'))
        out = cli(env, 'init', 't', '--library', lib, '--languages', 'en,fr', '--clock-offset-hours', '0').stdout
        assert '1 clips' in out and 'notes.txt' in out, out                          # hidden files ignored, other files reported
        stages = 'ingest,audio,exposure' + (',transcribe,align' if slow else '')
        r1 = cli(env, 'run', 't', '--stages', stages).stdout
        assert 'FAILED' not in r1 and "'ok': %d" % (5 if slow else 3) in r1, r1
        cdir = os.path.join(tmp, 'races', 't', 'clips', 'CAM_20260221120007_0019_D')
        clip = json.load(open(f'{cdir}/clip.json'))
        assert clip['time']['start_utc'] == '2026-02-21T12:00:07Z' and clip['time']['utc_status'] == 'provisional', clip['time']       # unverified clock is provisional
        assert clip['video']['dropped_frames'] == 2 and clip['video']['gaps'][0]['after_frame'] == 29 and clip['video']['nominal_fps'] == 50.0
        assert clip['colour_mode'] == 'normal' and clip['calibration_slots'] == 16 and clip['camera']['model'] == 'Osmo 360' and clip['audio']['channels'] == 2
        assert abs(clip['duration_s'] - 4.82) < 0.01
        au = json.load(open(f'{cdir}/audio.json')); assert au['summary']['dual_mono'] and abs(au['summary']['integrated_lufs'] + 23.5) < 0.2 and au['utc_hash'] == clip['time']['utc_hash']
        ex = json.load(open(f'{cdir}/exposure.json')); assert ex['sampling']['n_samples'] == 24 and ex['clip_id'] == clip['clip_id']
        from strata360.pipeline.ingest import check_header
        check_header(clip, au); check_header(clip, ex)                                # headers match clip.json
        bad = dict(au, utc_hash='000000000000')
        try: check_header(clip, bad); raise SystemExit('stale header was not detected')
        except ValueError: pass
        # caching: unchanged re-run does nothing; a config change re-runs only what depends on it; --force re-runs everything
        assert "'cached': %d" % (5 if slow else 3) in cli(env, 'run', 't', '--stages', stages).stdout
        cfgp = os.path.join(tmp, 'races', 't', 'race.json'); cfg = json.load(open(cfgp)); cfg['exposure_every_frames'] = 20; json.dump(cfg, open(cfgp, 'w'))
        r3 = cli(env, 'run', 't', '--stages', stages).stdout
        assert 'exposure: ok' in r3 and 'ingest: cached' in r3 and 'audio: cached' in r3, r3
        assert json.load(open(f'{cdir}/exposure.json'))['sampling']['n_samples'] == 12
        cfg['camera_clock'] = dict(utc_offset_hours=1.0, verified=True); json.dump(cfg, open(cfgp, 'w'))                 # the clock setting changes ingest and everything after it
        r4 = cli(env, 'run', 't', '--stages', stages).stdout
        clip2 = json.load(open(f'{cdir}/clip.json')); assert clip2['time']['start_utc'] == '2026-02-21T11:00:07Z' and clip2['time']['utc_status'] == 'definitive', clip2['time']
        assert 'ingest: ok' in r4 and json.load(open(f'{cdir}/audio.json'))['utc_hash'] == clip2['time']['utc_hash'], 'artefacts must follow the new time?'
        r5 = cli(env, 'run', 't', '--stages', stages, '--force').stdout; assert "'ok': %d" % (5 if slow else 3) in r5
        st = cli(env, 'status', 't').stdout; assert 'CAM_20260221120007_0019_D' in st and 'FAIL' not in st and 'stale' not in st, st
        rep = cli(env, 'report', 't').stdout; assert '1 clips' in rep and 'colour modes' in rep, rep
        if slow:
            al = json.load(open(f'{cdir}/alignment.json')); assert 'summary' in al
    print('pipeline test passed' + (' (slow: transcription and alignment included)' if slow else ''))

if __name__ == '__main__':
    main()
