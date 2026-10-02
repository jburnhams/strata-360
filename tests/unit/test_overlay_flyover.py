"""overlay/flyover.py: the camera plan (pure arrays), the style, the mbgl-render command and the frames, with `mbgl-render` replaced by a fake that draws a flat picture."""
import subprocess
import cv2, numpy as np
import pytest
from overlay_fakes import T0, race_track
from strata360 import hw
from strata360.overlay import flyover as FO, mapclip as MC
from strata360.overlay.series import Series


@pytest.fixture
def series(): return Series(race_track(n=3600, speed=3.0, grade=0.02, heading='east'))


@pytest.fixture
def fake_mbgl(monkeypatch, tmp_path):
    """subprocess.run in flyover.py: `.calls` are the command lines; each writes a flat grey picture of the size asked for (-w x -h, times -r)."""
    calls = []; real = subprocess.run

    def run(cmd, **kw):
        if '-o' not in cmd or '-z' not in cmd: return real(cmd, **kw)                                                       # anything that is not mbgl-render (hw.py asks ffmpeg for its encoders on a Mac or Windows)
        calls.append(cmd); arg = lambda f: cmd[cmd.index(f) + 1]; r = float(arg('-r')); w, h = int(int(arg('-w')) * r), int(int(arg('-h')) * r)
        cv2.imwrite(arg('-o'), np.full((h, w, 3), (30, 90, 160), np.uint8)); return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(FO.subprocess, 'run', run); run.calls = calls; return run


def clip(series, seconds=4.0, fps=10.0, size=(1280, 720), tmp=None, **kw): return FO.FlyoverClip(series, T0 + 300, T0 + 3300, seconds, fps=fps, size=size, mbgl='/fake/mbgl-render', cache=str(tmp / 'c.db') if tmp else FO.CACHE, **kw)


# ---- the camera ----

def test_zoom_and_pitch_fall_together_as_the_camera_slows():
    z, p = FO.zoom_pitch_for([2.5, 0.375, 0.05, 0.0, 50.0]); assert z == pytest.approx([11.56, 13.0, 14.5, 14.5, 11.5], abs=0.1)
    assert p[0] > p[1] > p[2] and p[3] == pytest.approx(30.0) and p[4] == pytest.approx(55.0)


def test_shots_follow_the_runner_and_zoom_by_speed(series):
    fast = FO.plan_shots(series, T0 + 300, T0 + 3300, 4.0); slow = FO.plan_shots(series, T0 + 300, T0 + 3300, 400.0)
    assert fast[0]['t'] == 0 and fast[-1]['t'] == pytest.approx(4.0) and fast[0]['km'] == pytest.approx(0.9, abs=0.01) and fast[-1]['km'] == pytest.approx(9.9, abs=0.01)
    assert all(b['km'] >= a['km'] for a, b in zip(fast, fast[1:])) and np.mean([s['zoom'] for s in slow]) > np.mean([s['zoom'] for s in fast])


def test_a_stop_is_a_pause_in_the_shots(tmp_path):
    tr = race_track(n=3600, speed=3.0); tr['dist'][1800:] -= 3.0 * np.arange(1800, 3600) - 3.0 * 1800                       # standing still from half way
    s = Series(tr); k = FO.plan_shots(s, T0, T0 + 3599, 40.0); assert k[-1]['km'] == pytest.approx(k[20]['km'], abs=0.2) and k[-1]['zoom'] == pytest.approx(14.5, abs=0.2)


def test_a_stretch_with_no_distance_is_refused(series):
    with pytest.raises(ValueError): FO.plan_shots(series, T0 + 99000, T0 + 99100, 5.0)


def test_the_deadband_ignores_small_swings_and_follows_real_turns():
    wiggle = 10 * np.sin(np.linspace(0, 12, 200)); assert np.ptp(np.unwrap(np.radians(FO.deadband(wiggle, 15)))) == 0
    turn = np.r_[np.zeros(50), np.full(50, 90.0)]; out = FO.deadband(turn, 15); assert out[0] == 0 and out[-1] == pytest.approx(75.0)


def test_turning_is_counted_in_degrees_and_reversals():
    tv, rev = FO.travel(np.r_[np.linspace(0, 40, 20), np.linspace(40, 10, 20)]); assert tv == pytest.approx(70.0) and rev == 1


def test_smoothing_limits_how_fast_the_heading_turns():
    out = FO.smooth_bearings(np.r_[np.zeros(100), np.full(100, 90.0)], 10.0, 1.0, 6.0); assert np.abs(np.diff(np.unwrap(np.radians(out)))).max() * 10 * 57.3 <= 6.01


def test_projection_puts_the_look_at_point_in_the_middle_and_points_ahead_higher_up():
    g = np.arange(0, 5000, 10.0); lat = 50.0 + g / 111320; lon = np.full(len(g), 5.0); alt = np.full(len(g), 300.0)
    x, y, ok = FO.project(g, lat, lon, alt, np.array([2000.0, 2500.0]), (50.0 + 2000 / 111320, 5.0, 300.0 * 1.5), 0.0, 13, 45, (1280, 820), 1.5)
    assert ok.all() and x == pytest.approx([640, 640], abs=1) and y[0] == pytest.approx(410, abs=1) and y[1] < y[0]


def test_a_route_that_bends_to_a_side_gets_a_heading_that_keeps_it_in_the_picture():
    g = np.arange(0, 6000, 10.0); lat = np.full(len(g), 50.0); lon = 5.0 + g / (111320 * np.cos(np.radians(50.0))); alt = np.full(len(g), 100.0)   # due east
    c = (50.0, 5.0 + 1500 / (111320 * np.cos(np.radians(50.0))), 150.0); b = FO.fit_bearing_screen(g, lat, lon, alt, 1000.0, c, 13.0, 45.0, 1.0, (1280, 820), 1.5, 720, 1500)
    assert abs(b - 90) <= 15


def test_the_camera_plan_has_a_value_per_frame_and_keeps_the_route_on_the_screen(series):
    route = FO.route_from_series(series); shots = FO.plan_shots(series, T0 + 300, T0 + 3300, 4.0); cam = FO.plan_camera(route, shots, 10.0, 40)
    assert all(len(cam[k]) == 40 for k in ('zoom', 'pitch', 'runner', 'lat', 'lon', 'alt', 'bearing', 'margin')) and np.all(np.diff(cam['runner']) >= 0) and cam['margin'].min() > 0
    assert np.all((cam['bearing'] > 60) & (cam['bearing'] < 120))                                                           # heading east


def test_the_route_is_on_the_overlays_distance(series):
    g, lat, lon, alt = FO.route_from_series(series); assert g[0] == pytest.approx(0, abs=1) and np.allclose(np.diff(g), 10.0) and abs(g[-1] - series.total_m) < 20 and np.all(np.isfinite(alt))


# ---- the style and the picture ----

def test_the_style_drapes_the_imagery_on_terrain_and_widens_lines_for_sharp_tiles():
    s = FO.make_style('esri', 1.5, [5.0, 5.1], [50.0, 50.1]); assert s['terrain'] == {'source': 'dem', 'exaggeration': 1.5} and 'World_Imagery' in s['sources']['img']['tiles'][0]
    assert s['sources']['route']['data']['geometry']['coordinates'] == [[5.0, 50.0], [5.1, 50.1]] and [l['id'] for l in s['layers']][-4:] == ['route-casing', 'route', 'me-halo', 'me']
    wide = FO.make_style('esri', 1.5, [5.0], [50.0], scale=3.0, dz=np.log2(3.0)); a, b = s['layers'][-3]['paint']['line-width'], wide['layers'][-3]['paint']['line-width']; assert b[3] == pytest.approx(a[3] + np.log2(3.0)) and b[4] == 3 * a[4] and b[6] == 3 * a[6]
    with pytest.raises(ValueError): FO.make_style('nope', 1.5, [], [])


def test_the_marker_is_a_ground_polygon_pointing_ahead():
    m = FO.marker(50.0, 5.0, 0.0, 200.0, 1); ring = m['geometry']['coordinates'][0]; assert m['id'] == 1 and ring[0] == ring[-1] and max(p[1] for p in ring) == ring[0][1] and ring[0][1] > 50.0


def test_sizes_are_16_9_and_a_multiple_of_640():
    for s in [(1280, 720), (1920, 1080), (3840, 2160)]: FO.check_size(s)
    for s in [(1920, 1000), (1000, 562), (3840, 3840)]:
        with pytest.raises(ValueError): FO.check_size(s)


def test_the_mbgl_command_renders_the_planned_view_at_the_pixel_ratio(series, tmp_path, monkeypatch):
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); monkeypatch.delenv('STRATA_MBGL_BACKEND', raising=False); c = clip(series, size=(3840, 2160), tmp=tmp_path, sharp=False); cmd = c.args(3, 'style.json', 'f.png'); a = lambda f: cmd[cmd.index(f) + 1]
    assert cmd[0] == '/fake/mbgl-render' and '--backend=metal' in cmd and (a('-w'), a('-h'), a('-r')) == ('1280', '820', '3') and float(a('-z')) == pytest.approx(c.cam['zoom'][3], abs=1e-3)
    assert float(a('-y')) == pytest.approx(c.cam['lat'][3], abs=1e-5) and float(a('-b')) == pytest.approx(c.cam['bearing'][3], abs=0.01) and a('-c') == str(tmp_path / 'c.db')


def test_sharp_tiles_are_the_default_and_render_the_full_size_at_a_higher_zoom(series, tmp_path):
    c = clip(series, size=(3840, 2160), tmp=tmp_path); cmd = c.args(3, 's', 'f'); a = lambda f: cmd[cmd.index(f) + 1]
    assert (a('-w'), a('-h'), a('-r')) == ('3840', '2460', '1') and float(a('-z')) == pytest.approx(c.cam['zoom'][3] + np.log2(3.0), abs=1e-3)


def test_the_backend_is_metal_on_a_mac_and_can_be_chosen(monkeypatch):
    monkeypatch.delenv('STRATA_MBGL_BACKEND', raising=False); monkeypatch.setattr(hw.sys, 'platform', 'linux'); assert hw.mbgl_backend() == 'opengl'
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); assert hw.mbgl_backend() == 'metal'; monkeypatch.setenv('STRATA_MBGL_BACKEND', 'vulkan'); assert hw.mbgl_backend() == 'vulkan'


def test_a_frame_is_a_4k_rgb_picture_cropped_from_the_taller_render_with_nothing_drawn_over_it(series, tmp_path, fake_mbgl):
    c = clip(series, size=(3840, 2160), tmp=tmp_path); f = c.frame(5); assert f.shape == (2160, 3840, 3) and f.dtype == np.uint8 and len(fake_mbgl.calls) == 1
    assert tuple(f[1000, 1900]) == (160, 90, 30)                                                                            # the fake's BGR (30, 90, 160) as RGB where nothing is drawn over it
    assert (f == np.array([160, 90, 30], np.uint8)).all()                                                                 # no overlay and no credit: the film adds its overlay; credits go with the distribution
    assert len(c.style['sources']['me']['data']['features']) == 2                                                             # the marker and its halo
    c.close()


def test_the_credit_names_the_imagery_and_the_terrain(series, tmp_path):
    c = clip(series, tmp=tmp_path, imagery='topo'); assert c.credit == 'Map © OpenTopoMap (CC-BY-SA), data © OpenStreetMap contributors · Terrain © Mapterhorn' and not hasattr(c, 'overlay')


def test_frame_k_shows_the_race_at_speedup_times_k_over_fps(series, tmp_path):
    c = clip(series, tmp=tmp_path); assert c.frames == 40 and c.speedup == pytest.approx(750.0) and c.time(10) == pytest.approx(T0 + 300 + 750.0) and np.allclose(c.times()[:2], [c.time(0), c.time(1)])


def test_it_renders_through_the_map_clip_encoder_interface(series, tmp_path, fake_mbgl, monkeypatch):
    monkeypatch.setenv('STRATA_ENCODER', 'software'); c = clip(series, seconds=1.0, fps=5.0, size=(1280, 720), tmp=tmp_path); seen = []
    class P:
        stdin = type('S', (), {'write': lambda s, b: seen.append(len(b)), 'close': lambda s: None})(); returncode = 0
        def wait(self): open(MC_TMP[0], 'wb').write(b'x'); return 0
    MC_TMP = [str(tmp_path / 'o.mp4.part.mp4')]; monkeypatch.setattr(MC.subprocess, 'Popen', lambda *a, **k: P())
    out = MC.render(c, str(tmp_path / 'o.mp4')); assert out.endswith('o.mp4') and seen == [1280 * 720 * 3] * 5 and len(fake_mbgl.calls) == 5


def test_a_failing_mbgl_is_reported_with_its_message(series, tmp_path, monkeypatch):
    monkeypatch.setattr(FO.subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, '', 'Error: no Metal device'))
    with pytest.raises(FO.FlyoverError, match='frame 0.*no Metal device'): clip(series, tmp=tmp_path).frame(0)


def test_a_picture_of_the_wrong_size_says_so(series, tmp_path, monkeypatch):
    def run(cmd, **kw): cv2.imwrite(cmd[cmd.index('-o') + 1], np.zeros((100, 100, 3), np.uint8)); return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(FO.subprocess, 'run', run)
    with pytest.raises(FO.FlyoverError, match='drew 100x100'): clip(series, tmp=tmp_path).frame(0)


def test_mbgl_is_found_by_variable_then_path_and_its_absence_is_an_error(tmp_path, monkeypatch):
    exe = tmp_path / 'mbgl-render'; exe.write_text('x'); monkeypatch.setattr(FO, 'MBGL_DEFAULT', str(tmp_path / 'none')); monkeypatch.delenv('MBGL_RENDER', raising=False); monkeypatch.setattr(FO.shutil, 'which', lambda n: None)
    with pytest.raises(FO.FlyoverError, match='terrain-flyover.md'): FO.find_mbgl()
    monkeypatch.setattr(FO.shutil, 'which', lambda n: str(exe)); assert FO.find_mbgl() == str(exe)
    other = tmp_path / 'other'; other.write_text('x'); monkeypatch.setenv('MBGL_RENDER', str(other)); assert FO.find_mbgl() == str(other)


def test_bad_arguments_are_refused(series, tmp_path):
    with pytest.raises(ValueError): FO.FlyoverClip(series, T0 + 100, T0 + 100, 5, size=(1280, 720))
    with pytest.raises(ValueError): clip(series, size=(1000, 600), tmp=tmp_path)
    with pytest.raises(ValueError): clip(series, tmp=tmp_path, imagery='nope')
