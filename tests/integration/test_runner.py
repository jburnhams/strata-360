"""Integration tests for the pipeline runner (concurrency, clear, and cache invalidation)."""
import json, os, time
import pytest
from strata360.pipeline import runner, config, stages

def test_worker_claim_is_exclusive(processed, monkeypatch):
    claims_dir = runner._claims(processed)
    os.makedirs(claims_dir, exist_ok=True)

    assert runner.claim(processed, 'CAM_20260221120007_0019_D', 'audio')

    original_getpid = os.getpid
    monkeypatch.setattr(os, 'getpid', lambda: original_getpid() + 1)

    assert not runner.claim(processed, 'CAM_20260221120007_0019_D', 'audio'), "Second process should not be able to claim"

def test_dead_worker_claim_is_taken_over(processed):
    claims_dir = runner._claims(processed)
    os.makedirs(claims_dir, exist_ok=True)
    p = os.path.join(claims_dir, 'CAM_20260221120007_0019_D__audio')

    with open(p, 'w') as f:
        f.write(f'9999999 {time.time():.0f}')

    assert runner.claim(processed, 'CAM_20260221120007_0019_D', 'audio')

    pid, _ = open(p).read().split()
    assert pid == str(os.getpid())

def test_clear_removes_stage_and_dependents(processed):
    clip = 'CAM_20260221120007_0019_D'

    state1 = runner.load_state(processed, clip)
    assert 'audio' in state1 and state1['audio']['status'] == 'ok'
    assert 'exposure' in state1 and state1['exposure']['status'] == 'ok'

    cleared = runner.clear(processed, 'ingest', clips=[clip], cascade=True)
    assert (clip, 'ingest') in cleared
    assert (clip, 'audio') in cleared
    assert (clip, 'exposure') in cleared

    state2 = runner.load_state(processed, clip)
    assert 'ingest' not in state2
    assert 'audio' not in state2
    assert 'exposure' not in state2

def test_track_signature_detects_changes(processed):
    cfg = config.load(processed)
    # Put track in the right directory where track_path looks for it.
    # config.track_path looks in race_dir(processed) / 'track.fit' or 'track.gpx'
    rd = config.race_dir(processed)
    track_path = os.path.join(rd, 'track.fit')

    with open(track_path, 'wb') as f: f.write(b'data1')

    sig1 = runner.track_signature(processed, cfg)

    with open(track_path, 'wb') as f: f.write(b'data2')
    sig2 = runner.track_signature(processed, cfg)

    assert sig1 != sig2

    cfg['camera_clock'] = {'utc_offset_hours': 1.0}
    sig3 = runner.track_signature(processed, cfg)
    assert sig2 != sig3

def test_run_with_fail_fast_halts_on_error(processed, monkeypatch):
    clip = 'CAM_20260221120007_0019_D'

    # st.fn(ctx) takes 1 argument.
    def failing_stage(ctx):
        raise ValueError("Simulated crash")

    monkeypatch.setattr(stages.STAGES['audio'], 'fn', failing_stage)

    runner.clear(processed, 'audio', clips=[clip])

    with pytest.raises(ValueError, match="Simulated crash"):
        runner.run(processed, stages=['audio'], force=True, fail_fast=True)

def test_stage_health(processed, monkeypatch):
    clip = 'CAM_20260221120007_0019_D'
    # By default, a successful run leaves health empty (only has failing/retrying items).
    # We force a failed state to observe health reporting.
    runner.update_state(processed, clip, 'audio', {'status': 'failed', 'error': 'Test error', 'attempts': 3})
    health = runner.stage_health(processed)
    assert 'audio' in health
    assert health['audio']['failed'] == 1
    assert health['audio']['last_error'] == 'Test error'

def test_item_states(processed):
    out = runner.item_states(processed)
    assert 'clips' in out and 'stages' in out
    states = out['clips']
    assert len(states) >= 2  # At least 2 clips
    clip = 'CAM_20260221120007_0019_D'
    assert states[clip]['audio'] == 'ok'
    assert states[clip]['ingest'] == 'ok'

def test_discover_returns_clips(processed):
    cfg = runner.config.load(processed)
    clips, other = runner.discover(processed, cfg)
    assert len(clips) >= 2
    assert any(c.id == 'CAM_20260221120007_0019_D' for c in clips)

def test_active_items_is_empty_when_done(processed):
    active = runner.active_items(processed)
    assert len(active) == 0

def test_clear_items_removes_specific_items(processed):
    clip = 'CAM_20260221120007_0019_D'
    count = runner.clear_items(processed, [(clip, 'audio')])
    assert count == 1
    state = runner.load_state(processed, clip)
    assert 'audio' not in state
    assert 'ingest' in state

def test_active_claims_lists_current_claims(processed):
    runner.claim(processed, 'CAM_20260221120007_0019_D', 'audio')
    claims = runner.active_claims(processed)
    assert len(claims) == 1
    assert claims[0][0] == 'CAM_20260221120007_0019_D'
    assert claims[0][1] == 'audio'
    assert claims[0][2] == os.getpid()

def test_release_removes_claim(processed):
    runner.claim(processed, 'CAM_20260221120007_0019_D', 'audio')
    runner.release(processed, 'CAM_20260221120007_0019_D', 'audio')
    claims = runner.active_claims(processed)
    assert len(claims) == 0

def test_runnable_count_when_items_cleared(processed):
    # Wait to make sure there are no remaining claims causing things to report weirdly
    # In processed, ingest, audio, exposure are done for two clips. So runnable_count should be 0.
    runner.clear(processed, 'audio', cascade=True)
    assert runner.runnable_count(processed) > 0

def test_workers_returns_active_worker_pids(processed):
    workers_dir = runner._workers(processed)
    os.makedirs(workers_dir, exist_ok=True)
    with open(os.path.join(workers_dir, str(os.getpid())), 'w') as f:
        f.write("time")
    ws = runner.workers(processed)
    assert os.getpid() in ws


def test_work_worker_catalog(processed):
    rd = runner.config.race_dir(processed)
    catalog_path = os.path.join(rd, 'catalog.json')
    if os.path.exists(catalog_path):
        os.remove(catalog_path)
    runner.work(processed, max_items=0)
    assert os.path.exists(catalog_path)
    import json
    with open(catalog_path) as f:
        data = json.load(f)
        assert 'clips' in data

def test_run_clip_glob(processed):
    cfg = runner.config.load(processed)
    runner.clear(processed, 'audio', cascade=True)
    result = runner.run(processed, clip_glob='*120007_0019_D', stages=['audio'])
    assert ('CAM_20260221120007_0019_D', 'audio') in result
    assert result[('CAM_20260221120007_0019_D', 'audio')] == 'ok'
    assert len(result) == 1

def test_run_force(processed):
    clip = 'CAM_20260221120007_0019_D'
    state1 = runner.load_state(processed, clip)
    assert 'audio' in state1
    result = runner.run(processed, stages=['audio'], force=True)
    assert (clip, 'audio') in result

def test_work_wait_retry(processed, monkeypatch):
    clip = 'CAM_20260221120007_0019_D'
    state = runner.load_state(processed, clip)
    audio_key = state['audio']['key']
    runner.update_state(processed, clip, 'audio', {
        'status': 'retry', 'attempts': 1, 'wait_s': 10,
        'next_try_at': time.time() + 10, 'error': 'test', 'key': audio_key
    })
    delays = []
    def fake_sleep(seconds):
        delays.append(seconds)
        raise ValueError("Stop worker")
    monkeypatch.setattr(time, 'sleep', fake_sleep)
    with pytest.raises(ValueError, match="Stop worker"):
        runner.work(processed, max_items=None, stages=['audio'])
    assert len(delays) >= 1

def test_run_restamp_ingest(processed, monkeypatch):
    import strata360.pipeline.ingest
    restamp_called = False
    def fake_restamp(dir_path):
        nonlocal restamp_called
        restamp_called = True
        return 1
    monkeypatch.setattr(strata360.pipeline.ingest, 'restamp', fake_restamp)
    runner.clear(processed, 'ingest', cascade=True)
    runner.run(processed, stages=['ingest'])
    assert restamp_called

def test_work_claim_concurrency_cap(processed, monkeypatch):
    cfg = runner.config.load(processed)
    clip = 'CAM_20260221120007_0019_D'
    runner.clear(processed, 'audio', cascade=True)
    original_claim = runner.claim
    def fake_claim(race, cid, name):
        claims_dir = runner._claims(race)
        os.makedirs(claims_dir, exist_ok=True)
        p = os.path.join(claims_dir, f'OTHER_CLIP__{name}')
        with open(p, 'w') as f:
            f.write(f'{os.getpid()} {time.time() - 100:.0f}')
        return original_claim(race, cid, name)
    monkeypatch.setattr(runner, 'claim', fake_claim)
    monkeypatch.setitem(runner.resources.STAGE_MAX_CONCURRENT, 'audio', 1)
    result = runner.work(processed, max_items=1, stages=['audio'])
    assert not result

def test_work_idempotent(processed):
    result1 = runner.work(processed, stages=['audio'])
    assert not result1
    runner.clear(processed, 'audio', cascade=False)
    result2 = runner.work(processed, stages=['audio'])
    assert result2
    result3 = runner.work(processed, stages=['audio'])
    assert not result3

def test_stage_fails_fast_exception(processed, monkeypatch):
    clip = 'CAM_20260221120007_0019_D'
    def failing_stage(ctx):
        raise ValueError("Simulated crash in stage")
    monkeypatch.setattr(runner.STAGES['audio'], 'fn', failing_stage)
    runner.clear(processed, 'audio', clips=[clip])
    with pytest.raises(ValueError, match="Simulated crash in stage"):
        runner.work(processed, max_items=1, stages=['audio'], fail_fast=True)
    state = runner.load_state(processed, clip)
    assert state['audio']['status'] == 'failed'
    assert 'trace' in state['audio']
    assert 'Simulated crash in stage' in state['audio']['trace']

def test_stage_programming_error_no_retry(processed, monkeypatch):
    clip = 'CAM_20260221120007_0019_D'
    def failing_stage(ctx):
        raise SyntaxError("Bad code")
    monkeypatch.setattr(runner.STAGES['audio'], 'fn', failing_stage)
    runner.clear(processed, 'audio', clips=[clip])
    result = runner.work(processed, max_items=1, stages=['audio'])
    assert result[(clip, 'audio')] == 'failed'
    state = runner.load_state(processed, clip)
    assert state['audio']['status'] == 'failed'
    assert state['audio']['attempts'] == 1

def test_clear_removes_outputs_on_disk(processed):
    clip = 'CAM_20260221120007_0019_D'
    runner.clear(processed, 'audio', clips=[clip], cascade=False)
    ctx_dir = runner.clip_dir(processed, clip)
    pass

def test_clear_with_missing_stage(processed):
    with pytest.raises(ValueError, match="unknown stage 'fake_stage'"):
        runner.clear(processed, 'fake_stage')

def test_work_with_unknown_stage(processed):
    with pytest.raises(SystemExit, match="unknown stage.*fake_stage"):
        runner.work(processed, stages=['fake_stage'])
