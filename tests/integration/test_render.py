import pytest
import os
import json
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import library

def patch_for_synthetic(monkeypatch, processed):
    from strata360.render import flat
    c1 = 'CAM_20260221120007_0019_D'
    with open(os.path.join(processed, 'strata360', 'clips', c1, 'clip.json')) as f:
        cj = json.load(f)
    W = cj['video']['width']
    monkeypatch.setattr(flat, 'LS', W)

def test_flat_render_cli(processed, cli, monkeypatch):
    """Test the CLI flat renderer with media assertions."""
    patch_for_synthetic(monkeypatch, processed)
    c1 = 'CAM_20260221120007_0019_D'
    with open(os.path.join(processed, 'strata360', 'clips', c1, 'clip.json')) as f:
        cj = json.load(f)
    osv_path = cj['source_files']['osv']
    out = os.path.join(processed, 'strata360', 'out_flat.mp4')

    r = cli('render', osv_path, out, '--frames', '10', '--size', '128x64', '--audio', 'none', check=False)
    assert r.code == 0
    assert os.path.exists(out)

    # Assert media properties using ffprobe
    probe = library.ffprobe(out)
    assert float(probe['format']['duration']) == pytest.approx(0.2, abs=0.05)
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert video_stream['width'] == 128
    assert video_stream['height'] == 64
    assert video_stream['codec_name'] == 'hevc'

    # Test with some parameters that affect branches
    r = cli('render', osv_path, out, '--frames', '5', '--size', '128x64', '--audio', 'none', '--gain', 'auto', '--seam', 'off', '--parallax', 'off', check=False)
    assert r.code == 0

    # Test path json
    path_json = os.path.join(processed, 'path.json')
    with open(path_json, 'w') as f:
        json.dump({"ref": "world", "keyframes": [{"t": 0, "yaw": 0, "pitch": 0, "fov": 90}]}, f)
    r2 = cli('render', osv_path, out, '--frames', '5', '--size', '128x64', '--audio', 'none', '--path', path_json, check=False)
    assert r2.code == 0

    # Test path json missing but with missing flag -> should fail
    with pytest.raises(FileNotFoundError):
        r3 = cli('render', osv_path, out, '--frames', '5', '--size', '128x64', '--audio', 'none', '--path', 'missing.json', check=False)

def test_final_film_render_in_proc(processed, cli, monkeypatch):
    """Test the CLI renders a final film piece and pieces it together."""
    patch_for_synthetic(monkeypatch, processed)
    from strata360.edit import project as PJ
    from strata360.pipeline import config
    c1, c2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'
    plan = {
        'film': {'length_s': 1.0, 'bpm': 120, 'music': None},
        'segments': [
            {'id': 'S1', 'clip': c1, 'clip_start_s': 0.0, 'film_start_s': 0.0, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:00:07Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'},
            {'id': 'S2', 'clip': c2, 'clip_start_s': 0.0, 'film_start_s': 0.5, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:01:07Z', 'transition': {'type': 'dissolve', 'dur_s': 0.1}, 'technique': 'hold_wide', 'subject': 'front'}
        ]
    }
    # To run final we need motion json for heading mode if it's there
    for c in [c1, c2]:
        with open(os.path.join(config.race_dir(processed), 'clips', c, 'motion.json'), 'w') as f:
            json.dump({"start_utc": "2026-02-21T12:00:07Z", "duration_s": 1.2, "dt": 0.1, "t": [0.0, 0.1, 0.2, 0.3], "world_heading_deg": [0, 0, 0, 0], "smooth_heading_deg": [0, 0, 0, 0], "bank_deg": [0, 0, 0, 0], "v_ground_ms": [0, 0, 0, 0], "v_up_ms": [0, 0, 0, 0]}, f)

    PJ.save(processed, {'plan': plan, 'framing': {'S1': {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0}, 'S2': {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0}}})

    # Test pieces
    r = cli('final', processed, '--size', '128x64', '--fps', '50.0', '--bitrate', '1M', '--pieces', '1', check=False)
    assert r.code == 0
    final_dirs = [d for d in os.listdir(os.path.join(processed, 'strata360', 'final')) if len(d) == 10]
    key = final_dirs[0]
    p_mov = os.path.join(processed, 'strata360', 'final', key, 'p0000.mov')
    assert os.path.exists(p_mov)

    probe = library.ffprobe(p_mov)
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert video_stream['width'] == 128
    assert video_stream['height'] == 64
    assert float(probe['format']['duration']) == pytest.approx(0.5, abs=0.05)

    # Test full final output
    r = cli('final', processed, '--size', '128x64', '--fps', '50.0', '--bitrate', '1M', check=False)
    assert r.code == 0
    film_mp4 = os.path.join(processed, 'strata360', 'final', key, 'film.mp4')
    assert os.path.exists(film_mp4)
    probe = library.ffprobe(film_mp4)
    assert float(probe['format']['duration']) == pytest.approx(1.0, abs=0.1)

def test_film_preview(processed, cli, monkeypatch):
    patch_for_synthetic(monkeypatch, processed)
    from strata360.edit import project as PJ
    c1, c2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'
    plan = {
        'film': {'length_s': 1.0, 'bpm': 120, 'music': None},
        'segments': [
            {'id': 'S1', 'clip': c1, 'clip_start_s': 0.0, 'film_start_s': 0.0, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:00:07Z', 'transition': {'type': 'whip', 'dur_s': 0.1}, 'technique': 'hold_wide', 'subject': 'front'},
            {'id': 'S2', 'clip': c2, 'clip_start_s': 0.0, 'film_start_s': 0.5, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:01:07Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'}
        ]
    }
    PJ.save(processed, {'plan': plan, 'framing': {'S1': {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0}, 'S2': {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0}}})

    r = cli('film', processed, '--px', '128', check=False)
    assert r.code == 0
    preview_dir = os.path.join(processed, 'strata360', 'preview')
    assert os.path.exists(preview_dir)

    # find the segment output
    film_dirs = [d for d in os.listdir(preview_dir) if d.startswith('film-')]
    key = film_dirs[0]
    seg_ts = os.path.join(preview_dir, key, 'seg00000.ts')
    assert os.path.exists(seg_ts)

    probe = library.ffprobe(seg_ts)
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert video_stream['codec_name'] == 'h264'
    assert video_stream['width'] == 128
    assert video_stream['height'] == 72

def test_proxy_render(processed, cli, monkeypatch):
    from strata360.render import proxy
    c1 = 'CAM_20260221120007_0019_D'
    with open(os.path.join(processed, 'strata360', 'clips', c1, 'clip.json')) as f:
        cj = json.load(f)
    W = cj['video']['width']
    osv = cj['source_files']['osv']

    # We must patch flat.LS directly because proxy.py uses flat.decoder and flat.read_frame
    from strata360.render import flat
    monkeypatch.setattr(flat, 'LS', W)

    out = os.path.join(processed, 'strata360', 'proxy.mp4')

    # Just run it manually
    side = proxy.make_proxy(osv, out, size='128x64', every=1, encoder='x265', frames_limit=5)
    assert len(side['frames']) == 5

    probe = library.ffprobe(out)
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert video_stream['codec_name'] == 'hevc'
    assert video_stream['width'] == 128
    assert video_stream['height'] == 64

def test_preview_from_proxy_render(processed, cli, monkeypatch):
    from strata360.render import proxy
    c1 = 'CAM_20260221120007_0019_D'
    with open(os.path.join(processed, 'strata360', 'clips', c1, 'clip.json')) as f:
        cj = json.load(f)
    W = cj['video']['width']
    osv = cj['source_files']['osv']

    from strata360.render import flat
    monkeypatch.setattr(flat, 'LS', W)

    proxy_out = os.path.join(processed, 'strata360', 'proxy.mp4')
    proxy.make_proxy(osv, proxy_out, size='128x64', every=1, encoder='x265', frames_limit=5)

    preview_out = os.path.join(processed, 'strata360', 'preview_from_proxy.mp4')
    proxy.make_preview_from_proxy(proxy_out, osv, preview_out, size='64x32')

    assert os.path.exists(preview_out)
    probe = library.ffprobe(preview_out)
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    assert video_stream['codec_name'] == 'h264'
    assert video_stream['width'] == 64
    assert video_stream['height'] == 32
