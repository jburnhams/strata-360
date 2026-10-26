"""Integration tests for rendering still pictures of the final film."""
import os
import pytest


from strata360.edit import project as PJ
from strata360.render import still

from tests.integration.test_render import patch_for_synthetic, two_window_project

def test_pick_moments():
    """Milestone I1: moments are picked based on differing clips and tightness, spreading over time."""
    plan = {
        'film': {'length_s': 2.0},
        'segments': [
            {'id': 'S1', 'clip': 'C1', 'film_start_s': 0.0, 'dur_s': 0.5},
            {'id': 'S2', 'clip': 'C1', 'film_start_s': 0.5, 'dur_s': 0.5},
            {'id': 'S3', 'clip': 'C2', 'film_start_s': 1.0, 'dur_s': 0.5},
            {'id': 'S4', 'clip': 'C2', 'film_start_s': 1.5, 'dur_s': 0.5, 'synthetic': True}
        ]
    }
    framing = {
        'S1': {'keyframes': [{'t': 0, 'fov': 90}], 'ref': 'body'}, # wide
        'S2': {'keyframes': [{'t': 0, 'fov': 70}], 'ref': 'body'}, # medium
        'S3': {'keyframes': [{'t': 0, 'fov': 50}], 'ref': 'body'}, # tight
        'S4': {'keyframes': [{'t': 0, 'fov': 50}], 'ref': 'body'}
    }

    # default n=4 (moment_count for < 2 min)
    res = still.pick_moments(plan, framing)
    assert len(res) == 4
    # Check that they grab diverse clips and tightness
    assert [r['clip'] for r in res] == ['C1', 'C1', 'C2', 'C2']
    assert [r['id'] for r in res] == ['S1', 'S2', 'S3', 'S4']
    assert 'wide' in res[0]['label']
    assert 'medium' in res[1]['label']
    assert 'tight' in res[2]['label']
    assert 'generated' in res[3]['label']

def test_render_still_and_meta(processed, monkeypatch):
    """Milestone I2: render_still writes a valid PNG frame and its JSON metadata; repeating it returns the same immediately."""
    plan, _ = two_window_project(processed, monkeypatch)
    framing = {'S1': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 90, 'roll': 0}], 'ref': 'body'}, 'S2': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 60, 'roll': 0}], 'ref': 'body'}}
    PJ.save(processed, {'plan': plan, 'framing': framing})

    t = 0.6
    out_path = still.render_still(processed, plan, framing, t, size=(128, 64), fps=50.0)

    assert os.path.exists(out_path)
    assert out_path.endswith('.png')

    # check that the png is valid
    assert os.path.getsize(out_path) > 100

    # check metadata
    meta = still.read_meta(out_path)
    assert meta is not None
    assert meta['t'] == 0.6
    assert meta['frame'] == 30  # 0.6 * 50
    assert meta['size'] == [128, 64]
    assert len(meta['shots']) == 1
    assert meta['shots'][0]['id'] == 'S2'

    # Repeated call returns same file path without rendering
    # We can mock render_piece to verify it's not called
    def fail_render(*args, **kwargs):
        raise RuntimeError("Should not be called again")
    monkeypatch.setattr(still, 'render_piece', fail_render)
    out_path_2 = still.render_still(processed, plan, framing, t, size=(128, 64), fps=50.0)
    assert out_path == out_path_2

def test_render_still_cli_entrypoint(processed, cli, monkeypatch):
    """Milestone I3: main script CLI renders stills for multiple times."""
    plan, _ = two_window_project(processed, monkeypatch)
    framing = {'S1': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 90, 'roll': 0}], 'ref': 'body'}, 'S2': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 60, 'roll': 0}], 'ref': 'body'}}
    PJ.save(processed, {'plan': plan, 'framing': framing})

    r = cli('still', processed, '--t', '0.2', '--t', '0.7', '--size', '3840x2160', '--fps', '25')
    lines = r.out.strip().split('\n')
    assert len(lines) == 2
    for out_path in lines:
        assert os.path.exists(out_path)
        meta = still.read_meta(out_path)
        assert meta['t'] in [0.2, 0.7]
        assert meta['size'] == [3840, 2160]
        assert meta['fps'] == 25.0

def test_missing_and_malformed_inputs(processed):
    """Milestone I4: pick_moments gracefully handles empty plans or missing fov; frame_for clamps."""
    # frame_for
    plan = {
        'segments': [
            {'id': 'S1', 'film_start_s': 0.0, 'dur_s': 0.5},
            {'id': 'S2', 'film_start_s': 0.5, 'dur_s': 1.0}
        ]
    }
    # 1.5s total at 50 fps = 75 frames (0-74)
    assert still.frame_for(plan, 0.0, 50.0) == 0
    assert still.frame_for(plan, 1.0, 50.0) == 50
    assert still.frame_for(plan, 2.0, 50.0) == 74 # clamped

    # pick_moments with no segments
    assert still.pick_moments({'segments': []}, {}) == []

    # missing fov or keyframes
    bad_plan = {
        'segments': [
            {'id': 'S1', 'clip': 'C1', 'film_start_s': 0.0, 'dur_s': 0.5},
        ]
    }
    bad_framing = {'S1': {}} # No keyframes -> will trigger the exception block returning None fov
    res = still.pick_moments(bad_plan, bad_framing)
    assert len(res) == 4
    assert 'unknown' in res[0]['label']

def test_meta_reading():
    assert still.read_meta('non_existent.png') is None

def test_failing_still_cli(processed, monkeypatch, cli):
    """Milestone I5: a failure inside the still rendering is logged and the CLI fails."""
    plan, _ = two_window_project(processed, monkeypatch)

    def fake_render(*args, **kwargs):
        raise ValueError("Oops rendering failed")
    monkeypatch.setattr(still, 'render_piece', fake_render)

    r = cli('still', processed, '--t', '0.6', '--size', '3840x2160', '--fps', '25', check=False)
    assert r.code != 0
    assert 'Oops rendering failed' in r.out or 'Oops rendering failed' in r.stderr

def test_missing_plan_cli(processed, cli, monkeypatch):
    """Milestone I6: CLI fails nicely when there's no plan."""
    patch_for_synthetic(monkeypatch, processed)
    PJ.save(processed, {})
    r = cli('still', processed, '--t', '0.6', '--size', '3840x2160', check=False)
    assert r.code != 0
    assert 'no plan yet' in r.out or 'no plan yet' in r.stderr

def test_render_still_missing_frames(processed, monkeypatch):
    """Milestone I7: frame missing logic in render_still."""
    plan, _ = two_window_project(processed, monkeypatch)
    framing = {'S1': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 90, 'roll': 0}], 'ref': 'body'}, 'S2': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 60, 'roll': 0}], 'ref': 'body'}}
    PJ.save(processed, {'plan': plan, 'framing': framing})
    # fake render piece but don't emit anything
    def noop_render(*args, **kwargs):
        pass
    monkeypatch.setattr(still, 'render_piece', noop_render)
    with pytest.raises(RuntimeError) as exc:
        still.render_still(processed, plan, framing, 0.6, size=(128, 64), fps=50.0)
    assert 'the film has no frame' in str(exc.value)

def test_render_still_upscale(processed, monkeypatch):
    """Milestone I8: upscale option."""
    plan, _ = two_window_project(processed, monkeypatch)
    framing = {'S1': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 90, 'roll': 0}], 'ref': 'body'}, 'S2': {'keyframes': [{'t': 0.0, 'yaw': 0, 'pitch': 0, 'fov': 60, 'roll': 0}], 'ref': 'body'}}
    PJ.save(processed, {'plan': plan, 'framing': framing})

    # We want to hit the UP.load() line. We'll patch UP.load to track it.
    from strata360.edit import upscale as UP
    loaded = []
    def fake_load():
        loaded.append(True)
    monkeypatch.setattr(UP, 'load', fake_load)

    # Mock shot_factor to be > 1 to trigger upscale
    from strata360.render.final import FinalSource
    monkeypatch.setattr(FinalSource, 'shot_factor', lambda *args, **kwargs: 2.0)

    def fake_render(*args, **kwargs):
        raise RuntimeError("Stop early")
    monkeypatch.setattr(still, 'render_piece', fake_render)

    try:
        still.render_still(processed, plan, framing, 0.6, size=(128, 64), fps=50.0, upscale='full')
    except RuntimeError as e:
        if str(e) != "Stop early": raise

    assert loaded == [True]
