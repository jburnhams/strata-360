"""Map tiles for the overlay: Web Mercator maths, a disk cache shared by every race, and the map picture around a place at any scale.

Positions are 'world pixels at zoom 0' (the whole world is 256 x 256); a map is drawn at a scale `k` (picture pixels per world pixel at zoom 0, so k = 2**14 is zoom 14 with ordinary
256-pixel tiles). The tiles are fetched at the zoom that gives at least that much detail (512-pixel '@2x' tiles where the style has them, which is what makes the maps crisp at 4K) and resized to
the exact scale.

Fetching tiles sends the areas of the route to the tile service, so each tile is fetched once and kept under ~/.strata360/tiles/<style>/ (nothing else is written there: no key, no track). A style
that needs a key reads it from the environment or the project's gitignored secrets.env (edit/llm_remote.secret), never from race.json, and the key never appears in an error or a log."""
import collections, io, math, os, urllib.error, urllib.request
import numpy as np
from PIL import Image

TILE = 256
MAX_ZOOM = 18
TF = 'https://tile.thunderforest.com/{name}/{z}/{x}/{y}{r}.png?apikey={key}'
STYLES = {                                  # name -> url, key variable, whether '@2x' tiles exist, the credit the map needs
    **{f'tf-{n}': dict(url=TF.replace('{name}', n), key='THUNDERFOREST_API_KEY', retina=True, credit='Maps © Thunderforest, data © OpenStreetMap contributors')
       for n in ('outdoors', 'landscape', 'cycle', 'transport', 'atlas')},
    'osm': dict(url='https://tile.openstreetmap.org/{z}/{x}/{y}.png', key=None, retina=False, credit='© OpenStreetMap contributors'),
}


class TileError(RuntimeError):
    pass


class MissingKey(TileError):
    pass


def world(lat, lon):
    """(x, y) world pixels at zoom 0 of degrees lat/lon (scalars or arrays)."""
    lat = np.clip(np.asarray(lat, float), -85.0511, 85.0511); lr = np.radians(lat)
    return (np.asarray(lon, float) + 180.0) / 360.0 * TILE, (1.0 - np.log(np.tan(lr) + 1.0 / np.cos(lr)) / math.pi) / 2.0 * TILE


def cache_root(): return os.path.join(os.path.expanduser('~'), '.strata360', 'tiles')


def needs_key(style): return bool(STYLES[style]['key'])


class Tiles:
    """Tiles of one style. `fetch(url) -> bytes` defaults to an HTTP GET; `offline` uses only the cache. The last MEM tiles used are also kept in memory."""
    MEM = 256

    def __init__(self, style='tf-outdoors', key=None, cache_dir=None, offline=False, fetch=None):
        if style not in STYLES: raise TileError(f'unknown map style {style!r}: one of {", ".join(sorted(STYLES))}')
        self.style, self.spec, self.offline = style, STYLES[style], offline; self.px = 512 if self.spec['retina'] else 256
        if self.spec['key'] and not key:
            from strata360.edit.llm_remote import secret
            key = secret(self.spec['key'])
        if self.spec['key'] and not key and not offline: raise MissingKey(f"the map style {style} needs a key: put {self.spec['key']}=... in secrets.env (it is never stored in the project)")
        self.key = key; self.dir = os.path.join(cache_dir or cache_root(), style + ('@2x' if self.spec['retina'] else '')); self.fetch = fetch or _get; self.fetched = 0; self._mem = collections.OrderedDict()

    def tile(self, z, x, y):
        """One tile as an RGB image (self.px square). x wraps round the world; rows above or below the map are blank."""
        n = 2 ** z; x %= n
        if not 0 <= y < n: return Image.new('RGB', (self.px, self.px), (200, 200, 200))
        if (z, x, y) in self._mem: self._mem.move_to_end((z, x, y)); return self._mem[(z, x, y)]
        p = os.path.join(self.dir, str(z), str(x), f'{y}.png')
        if not os.path.exists(p):
            if self.offline: raise TileError(f'map tile {self.style} {z}/{x}/{y} is not in the cache and fetching is off')
            url = self.spec['url'].format(z=z, x=x, y=y, r='@2x' if self.spec['retina'] else '', key=self.key or '')
            try: data = self.fetch(url)
            except urllib.error.HTTPError as e: raise TileError(f'map tile {self.style} {z}/{x}/{y}: HTTP {e.code}' + (' (is the map key right?)' if e.code in (401, 403) else '')) from None
            except (urllib.error.URLError, OSError) as e: raise TileError(f'map tile {self.style} {z}/{x}/{y}: {getattr(e, "reason", e)}') from None
            try: Image.open(io.BytesIO(data)).verify()
            except Exception: raise TileError(f'map tile {self.style} {z}/{x}/{y}: not an image') from None
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p + '.part', 'wb').write(data); os.replace(p + '.part', p); self.fetched += 1
        im = Image.open(p).convert('RGB'); im = im if im.size == (self.px, self.px) else im.resize((self.px, self.px), Image.LANCZOS)
        self._mem[(z, x, y)] = im
        if len(self._mem) > self.MEM: self._mem.popitem(last=False)
        return im

    def picture(self, cx, cy, k, w, h):
        """RGB image w x h centred on world point (cx, cy) at scale k. Picture pixel (u, v) shows world point (cx + (u - w/2) / k, cy + (v - h/2) / k)."""
        f = self.px / TILE; z = int(min(MAX_ZOOM, max(0, math.ceil(math.log2(k / f) - 1e-9))))   # tiles with at least the detail asked for
        m = f * 2 ** z / k                                                                              # tile pixels per picture pixel (>= 1: resized down)
        x0, y0 = cx * f * 2 ** z - w / 2 * m, cy * f * 2 ** z - h / 2 * m; x1, y1 = x0 + w * m, y0 + h * m
        tx0, ty0, tx1, ty1 = int(math.floor(x0 / self.px)), int(math.floor(y0 / self.px)), int(math.floor((x1 - 1e-9) / self.px)), int(math.floor((y1 - 1e-9) / self.px))
        big = Image.new('RGB', ((tx1 - tx0 + 1) * self.px, (ty1 - ty0 + 1) * self.px))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1): big.paste(self.tile(z, tx, ty), ((tx - tx0) * self.px, (ty - ty0) * self.px))
        ox, oy = tx0 * self.px, ty0 * self.px
        return big.resize((w, h), Image.LANCZOS, box=(x0 - ox, y0 - oy, x1 - ox, y1 - oy))


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'strata360 (personal race film overlay)'}), timeout=30) as r: return r.read()
