import pytest
import os
import json
import subprocess
import sys
import numpy as np
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


def two_window_project(processed, monkeypatch):
    """The synthetic project with a two-window plan (a dissolve between them), saved; returns (plan, the clip ids)."""
    patch_for_synthetic(monkeypatch, processed)
    from strata360.edit import project as PJ
    from strata360.pipeline import config
    c1, c2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'
    plan = {'film': {'length_s': 1.0, 'bpm': 120, 'music': None}, 'segments': [
        {'id': 'S1', 'clip': c1, 'clip_start_s': 0.0, 'film_start_s': 0.0, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:00:07Z', 'utc_end': '2026-02-21T12:00:07.5Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'},
        {'id': 'S2', 'clip': c2, 'clip_start_s': 0.0, 'film_start_s': 0.5, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:01:07Z', 'utc_end': '2026-02-21T12:01:07.5Z', 'transition': {'type': 'dissolve', 'dur_s': 0.2}, 'technique': 'hold_wide', 'subject': 'front'}]}
    for c in (c1, c2):
        json.dump({"start_utc": "2026-02-21T12:00:07Z", "duration_s": 1.2, "dt": 0.1, "t": [0.0, 0.1, 0.2, 0.3], "world_heading_deg": [0, 0, 0, 0], "smooth_heading_deg": [0, 0, 0, 0], "bank_deg": [0, 0, 0, 0], "v_ground_ms": [0, 0, 0, 0], "v_up_ms": [0, 0, 0, 0]}, open(os.path.join(config.race_dir(processed), 'clips', c, 'motion.json'), 'w'))
    PJ.save(processed, {'plan': plan, 'framing': {g: {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0} for g in ('S1', 'S2')}})
    return plan, (c1, c2)


def test_the_final_film_takes_the_footages_frame_rate_and_writes_a_time_map_that_the_overlay_clock_agrees_with(processed, cli, monkeypatch):
    """A2: no --fps means the clips' own rate (and half of it with --half-rate); each window's overlay clock is its clip's UTC to within a frame; the time map says the same."""
    import datetime as dt
    plan, (c1, c2) = two_window_project(processed, monkeypatch)
    from strata360.pipeline import config
    from strata360 import overlay as OV
    from strata360.render import timemap as TM
    src_fps = float(json.load(open(os.path.join(config.race_dir(processed), 'clips', c1, 'clip.json')))['video']['nominal_fps'])
    seen = []
    class Rec:
        def apply(self, img, t): seen.append(t); return img
    monkeypatch.setattr(OV, 'for_project', lambda folder, size, tiles=None: Rec())
    r = cli('final', processed, '--size', '128x64', '--bitrate', '1M'); assert r.code == 0
    d = os.path.join(processed, 'strata360', 'final'); key = next(x for x in os.listdir(d) if len(x) == 10); out = os.path.join(d, key)
    tm = json.load(open(os.path.join(out, 'timemap.json'))); assert tm['fps'] == pytest.approx(src_fps) and tm['frames'] == round(src_fps) and os.path.exists(os.path.join(out, 'timemap.csv'))
    probe = library.ffprobe(os.path.join(out, 'film.mp4')); vs = next(s for s in probe['streams'] if s['codec_type'] == 'video'); num, den = map(int, vs['avg_frame_rate'].split('/')); assert num / den == pytest.approx(src_fps, rel=0.01)
    ts = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    w0, w1 = tm['windows']; frame = 1.0 / src_fps
    assert any(abs(t - ts('2026-02-21T12:00:07Z')) <= frame for t in seen) and any(abs(t - ts('2026-02-21T12:01:07Z')) <= frame for t in seen)                        # each window drew its own clip's clock from its first frame
    assert abs(ts(TM.utc_at(tm, 0)) - ts(w0['utc_in'])) < 1e-6 and tm['transitions'][0]['incoming']['clip'] == c2 and w1['film_in'] == w0['film_out']
    seen.clear(); shutil_rmtree(out)
    r = cli('final', processed, '--size', '128x64', '--bitrate', '1M', '--half-rate'); assert r.code == 0
    key2 = next(x for x in os.listdir(d) if len(x) == 10 and x != key); assert json.load(open(os.path.join(d, key2, 'timemap.json')))['fps'] == pytest.approx(src_fps / 2)


def shutil_rmtree(p):
    import shutil; shutil.rmtree(p)


def test_the_final_film_opens_on_the_cold_open_with_its_own_sound(processed, cli, monkeypatch):
    """A chosen cold open (edit/cold_open.py) is rendered as its own piece ahead of the story, with the clip's own sound under it, and the film is that much longer."""
    patch_for_synthetic(monkeypatch, processed)
    from strata360.edit import project as PJ, cold_open as CO
    from strata360.pipeline import config
    c1, c2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'
    plan = {'film': {'length_s': 1.0, 'bpm': 120, 'music': None}, 'segments': [
        {'id': 'S1', 'clip': c1, 'clip_start_s': 0.0, 'film_start_s': 0.0, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:00:07Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'},
        {'id': 'S2', 'clip': c2, 'clip_start_s': 0.0, 'film_start_s': 0.5, 'dur_s': 0.5, 'utc_start': '2026-02-21T12:01:07Z', 'transition': {'type': 'cut', 'dur_s': 0.0}, 'technique': 'hold_wide', 'subject': 'front'}]}
    for c in [c1, c2]:
        with open(os.path.join(config.race_dir(processed), 'clips', c, 'motion.json'), 'w') as f:
            json.dump({"start_utc": "2026-02-21T12:00:07Z", "duration_s": 1.2, "dt": 0.1, "t": [0.0, 0.1, 0.2, 0.3], "world_heading_deg": [0, 0, 0, 0], "smooth_heading_deg": [0, 0, 0, 0], "bank_deg": [0, 0, 0, 0], "v_ground_ms": [0, 0, 0, 0], "v_up_ms": [0, 0, 0, 0]}, f)
    PJ.save(processed, {'plan': plan, 'framing': {s: {'mode': 'body', 'fov': 90, 'pitch': 0, 'yaw': 0, 'roll': 0} for s in ('S1', 'S2')}})
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=500:duration=1.2', '-ar', '48000', os.path.join(config.race_dir(processed), 'clips', c2, 'audio_original.flac')], check=True)          # the clip's sound
    cand = dict(id='cold-0', clip=c2, clip_start_s=0.4, dur_s=0.4, technique='hold_wide', view='ahead', speech=False, score=1.0)
    os.makedirs(CO.out_dir(processed)); json.dump(dict(schema=1, candidates=[cand], chosen='cold-0', by='score'), open(os.path.join(CO.out_dir(processed), 'cold_open.json'), 'w'))
    r = cli('final', processed, '--size', '128x64', '--fps', '50.0', '--bitrate', '1M', check=False); assert r.code == 0, r.out
    d = os.path.join(processed, 'strata360', 'final'); key = next(x for x in os.listdir(d) if len(x) == 10); film = os.path.join(d, key, 'film.mp4')
    assert float(library.ffprobe(film)['format']['duration']) == pytest.approx(1.4, abs=0.1)                          # the cold open, then the story
    pieces = open(os.path.join(d, key, 'pieces.txt')).read().splitlines(); assert 'cold-open-' in pieces[0] and len(pieces) == 3
    movie = pieces[0].split("'")[1]; assert float(library.ffprobe(movie)['format']['duration']) == pytest.approx(0.4, abs=0.05)
    sound = [x for x in os.listdir(os.path.join(d, key)) if x.startswith('cold-open-') and x.endswith('.wav')]
    assert len(sound) == 1                                                                                              # its own sound
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', film, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'], capture_output=True).stdout; x = np.frombuffer(raw, np.float32)
    assert np.sqrt(np.mean(x[400:2800] ** 2)) > 0.02                                                                   # heard under the cold open
