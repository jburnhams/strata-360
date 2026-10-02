"""overlay/mapclip.py: the animated gap map: frame k shows the race at t0 + k * speedup / fps, the marker moves a steady number of pixels, the zoom follows the speed, and a clip encodes."""
import numpy as np
import pytest
from overlay_fakes import T0, TileServer, race_track
from strata360.edit import llm_remote as L
from strata360.overlay import mapclip as MC, tiles as TL
from strata360.overlay.series import Series


@pytest.fixture(autouse=True)
def no_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)


@pytest.fixture
def tiles(tmp_path): return TL.Tiles('osm', cache_dir=str(tmp_path / 'tiles'), fetch=TileServer())


@pytest.fixture
def series(): return Series(race_track(n=3600, speed=3.0, grade=0.02))


def clip(series, tiles, seconds=4.0, fps=10.0, **kw): return MC.MapClip(series, T0 + 300, T0 + 3300, seconds, fps=fps, size=(320, 180), tiles=tiles, **kw)


def test_frame_k_shows_the_race_at_speedup_times_k_over_fps(series, tiles):
    c = clip(series, tiles); assert c.frames == 40 and c.speedup == pytest.approx(3000 / 4.0)
    assert c.time(0) == T0 + 300 and c.time(10) == pytest.approx(T0 + 300 + 10 * 750 / 10) and c.time(40) == pytest.approx(T0 + 3300)
    assert np.allclose(c.times()[:3], [c.time(0), c.time(1), c.time(2)])


def test_a_frame_is_an_rgb_picture_of_the_frame_size(series, tiles):
    f = clip(series, tiles).frame(5); assert f.shape == (180, 320, 3) and f.dtype == np.uint8


def test_the_marker_is_drawn_where_the_runner_is(series, tiles):
    c = MC.MapClip(series, T0 + 300, T0 + 3300, 4.0, fps=10.0, size=(960, 540), tiles=tiles); f = c.frame(20); blue = (f[..., 2] > 200) & (f[..., 0] < 60) & (f[..., 1] < 160); ys, xs = np.nonzero(blue)
    assert len(xs) > 5 and abs(np.median(xs) - 480) < 40 and abs(np.median(ys) - 270) < 40


def test_the_camera_follows_the_runner_and_the_marker_moves_steadily(series, tiles):
    c = clip(series, tiles); k = 2.0 ** c.z; px = np.hypot(np.diff(c.pos[0]) * k[1:], np.diff(c.pos[1]) * k[1:])
    assert np.all(np.isfinite(px)) and px[5:-5].max() < 0.02 * c.W and px[5:-5].min() > 0.001 * c.W


def test_the_zoom_is_closer_when_the_clip_is_slower(series, tiles):
    slow, fast = clip(series, tiles, seconds=40.0), clip(series, tiles, seconds=4.0)
    assert slow.z.mean() > fast.z.mean() and fast.z.min() >= MC.ZOOM[0] and slow.z.max() <= MC.ZOOM[1]


def test_the_picture_has_no_overlay_the_film_adds_its_own(series, tiles):
    c = clip(series, tiles); assert not hasattr(c, 'overlay') and not hasattr(c, 'gap') and c.frame(3).shape == (180, 320, 3)


def test_a_stretch_without_length_is_refused(series, tiles):
    with pytest.raises(ValueError): MC.MapClip(series, T0 + 100, T0 + 100, 5, size=(320, 180), tiles=tiles)


def test_render_writes_an_mp4(series, tiles, tmp_path):
    import shutil, subprocess
    if not shutil.which('ffmpeg'): pytest.skip('no ffmpeg')
    out = str(tmp_path / 'x' / 'g.mp4'); seen = []; MC.render(clip(series, tiles, seconds=1.0, fps=10.0), out, progress=lambda d, n: seen.append((d, n)), bitrate='1M')
    assert seen[-1] == (10, 10) and not (tmp_path / 'x' / 'g.mp4.part.mp4').exists()
    n = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', out], capture_output=True, text=True).stdout.strip(); assert n == '10'


def test_the_whole_route_on_screen_is_drawn_grey_under_the_stretch_so_the_before_and_after_show(series, tiles, monkeypatch):
    from strata360.overlay import draw as D
    calls = []; real = D.route_line
    monkeypatch.setattr(D, 'route_line', lambda img, u, v, colour=(230, 20, 20), width=3.0: (calls.append((tuple(colour), int(np.isfinite(u).sum()))), real(img, u, v, colour, width))[1])
    c = clip(series, tiles); c.frame(3)
    grey = [n for col, n in calls if col == MC.CONTEXT]; red = [n for col, n in calls if col == (230, 20, 20)]; white = [n for col, n in calls if col == (250, 250, 250)]
    assert grey == [len(series.route_lat)] and 0 < red[0] < len(series.route_lat) and 0 < white[0] < len(series.route_lat)                 # every point of the route; the stretch's parts are shorter
    assert [col for col, _ in calls].index(MC.CONTEXT) < [col for col, _ in calls].index((250, 250, 250))                                    # drawn first, the stretch over it
