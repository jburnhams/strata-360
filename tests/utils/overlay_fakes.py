"""Doubles for the overlay tests: a race track made of arrays (no FIT/GPX libraries) and a tile service that answers from memory (no network)."""
import io, re
import numpy as np
from PIL import Image

T0 = 1_758_002_400.0          # 2025-09-16 06:00:00 UTC (08:00 in Brussels)


def race_track(n=600, t0=T0, step=1.0, speed=3.0, lat0=50.13, lon0=5.79, heading='north', grade=0.0, hr=150.0, fit=True):
    """A straight run at constant `speed` (m/s) along a meridian (or a parallel with heading='east'), climbing `grade` (a fraction). `fit=False` leaves out distance and speed, as a GPX has."""
    t = t0 + step * np.arange(n); d = speed * step * np.arange(n); deg = d / 111_195.0
    lat, lon = (lat0 + deg, np.full(n, lon0)) if heading == 'north' else (np.full(n, lat0), lon0 + deg / np.cos(np.radians(lat0)))
    nan = np.full(n, np.nan)
    return dict(t=t, lat=lat, lon=lon, alt=300.0 + grade * d, speed=np.full(n, speed) if fit else nan.copy(), hr=np.full(n, hr), cadence=nan.copy(), dist=d if fit else nan.copy(), temp=nan.copy(), power=nan.copy())


def png(colour, size=256):
    b = io.BytesIO(); Image.new('RGB', (size, size), colour).save(b, 'PNG'); return b.getvalue()


def tile_colour(z, x, y): return ((x * 37) % 256, (y * 53) % 256, (z * 11) % 256)


class TileServer:
    """fetch(url) for overlay.tiles.Tiles: a solid tile coloured by its z/x/y (tile_colour), or all one `colour`, `size` px square. `.urls` lists what was asked for; `.fail` (an exception)
    is raised instead."""
    def __init__(self, size=256, colour=None): self.size, self.colour, self.urls, self.fail = size, colour, [], None

    def __call__(self, url):
        self.urls.append(url)
        if self.fail is not None: raise self.fail
        z, x, y = map(int, re.search(r'/(\d+)/(\d+)/(\d+)(?:@2x)?\.png', url).groups()); return png(self.colour or tile_colour(z, x, y), self.size)
