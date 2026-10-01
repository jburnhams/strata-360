"""overlay/zoom.py: the close-up map's automatic zoom: closer where the map is busy, wider on straight stretches, smooth, steady when standing still."""
import io, re
import numpy as np
import pytest
from PIL import Image
from overlay_fakes import T0, TileServer, race_track
from strata360.overlay import tiles as TL
from strata360.overlay.series import Series
from strata360.overlay.zoom import Zoom, _rank, edge_share


def busy_east_of(lon_deg):
    """A tile service whose tiles are striped (busy) east of a longitude, plain west of it."""
    class Srv(TileServer):
        def __call__(self, url):
            self.urls.append(url); z, x, y = map(int, re.search(r'/(\d+)/(\d+)/(\d+)\.png', url).groups())
            im = np.full((256, 256, 3), 230, np.uint8)
            if x / 2 ** z * 360 - 180 > lon_deg: im[::6] = 20
            b = io.BytesIO(); Image.fromarray(im).save(b, 'PNG'); return b.getvalue()
    return Srv()


def zigzag(n=1200, speed=3.0):
    tr = race_track(n=n, speed=speed, fit=False); t = np.arange(n); tr['lon'] = 5.79 + 0.002 * np.abs(((t / 40.0) % 2) - 1); return tr          # distance measured along the zigzag


@pytest.fixture
def tiles(tmp_path): return TL.Tiles('osm', cache_dir=str(tmp_path), fetch=TileServer(colour=(220, 220, 210)))


def test_edge_share():
    plain = np.full((50, 50, 3), 200, np.uint8); lines = plain.copy(); lines[::5] = 0
    assert edge_share(plain) == 0 and 0.2 < edge_share(lines) < 0.6


@pytest.mark.parametrize('x, r', [([3, 1, 2], [1, 0, 0.5]), ([5, 5, 5], [0.5, 0.5, 0.5]), ([1, 2, 2, 3], [0, 0.5, 0.5, 1]), ([7], [0.5])])
def test_rank(x, r): assert _rank(np.array(x, float)) == pytest.approx(r)


def test_straight_quiet_road_zooms_out(tiles):
    z = Zoom(Series(race_track(n=1200)), tiles, base=14, range_=1.5); assert z.at(T0 + 600) == pytest.approx(14 - 0.9, abs=0.01)


def test_winding_route_stays_closer_than_a_straight_one(tiles):
    assert Zoom(Series(zigzag()), tiles).at(T0 + 600) > Zoom(Series(race_track(n=1200)), tiles).at(T0 + 600) + 0.5


def test_busy_map_zooms_in(tmp_path):
    tr = race_track(n=2400, heading='east')                                       # 7.2 km east from 5.79
    z = Zoom(Series(tr), TL.Tiles('osm', cache_dir=str(tmp_path), fetch=busy_east_of(5.84)), base=14, range_=1.5, straight_weight=0.0)
    assert z.at(T0 + 2300) > 14.5 and z.at(T0 + 100) < 13.5 and np.all(np.diff(z.z) >= -1e-9)                   # the plain half shares one rank, as does the busy half


def test_within_range_and_smooth(tmp_path):
    z = Zoom(Series(race_track(n=2400, heading='east')), TL.Tiles('osm', cache_dir=str(tmp_path), fetch=busy_east_of(5.84)), base=14, range_=1.5)
    assert z.z.min() >= 12.5 - 1e-9 and z.z.max() <= 15.5 + 1e-9 and np.abs(np.diff(z.z)).max() < 0.05      # under 0.05 of a zoom level per second


def test_holds_while_standing_still(tiles):
    tr = zigzag(); tr['dist'][500:700] = tr['dist'][500]; z = Zoom(Series(tr), tiles); assert z.at(T0 + 560) == pytest.approx(z.at(T0 + 640), abs=1e-6)


def test_base_outside_the_track_and_for_a_short_track(tiles):
    z = Zoom(Series(race_track(n=1200)), tiles, base=14); assert z.at(T0 - 50) == 14 and z.at(T0 + 1e6) == 14
    assert Zoom(Series(race_track(n=20)), tiles, base=13).at(T0 + 10) == 13


def test_probes_the_route_every_step(tiles):
    z = Zoom(Series(race_track(n=1000, speed=2.0)), tiles, step_m=100); assert len(z.samples['dist_m']) == 20
