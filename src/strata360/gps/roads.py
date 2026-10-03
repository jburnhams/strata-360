"""Where on a track was the runner actually ON a road (not a trail beside one)? Answers come from OpenStreetMap through the cached, mirrored lookup service (gps/osm.py).

`stretches(lat, lon, dist, cache_dir)` returns the runs of the track where every sample (every `step_m` of distance) is within `on_m` metres of a drivable road, at least `min_m` long:
[{km0, km1, length_m, i0, i1, highways, names}]. The road shapes are fetched per `TILE` degree tile around the track (so a long race is a few dozen cached queries, not one huge one), in parallel over the mirrors."""
import collections, math

import numpy as np

from strata360.gps import osm

TILE = 0.1


def _metres(p, a, b):
    k = math.cos(math.radians(p[0])); ax, ay = (a[1] - p[1]) * k * 111320, (a[0] - p[0]) * 111320; bx, by = (b[1] - p[1]) * k * 111320, (b[0] - p[0]) * 111320
    dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy; t = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L)); return math.hypot(ax + t * dx, ay + t * dy)


def sample(lat, lon, dist, step_m=20.0):
    """The track every `step_m` metres of distance: (lat, lon, distance_m) arrays."""
    ok = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(dist); lat, lon, dist = lat[ok], lon[ok], dist[ok]
    d = np.arange(0, dist.max() if len(dist) else 0, step_m); i = np.searchsorted(dist, d).clip(0, max(len(lat) - 1, 0)); return lat[i], lon[i], d


def tiles(lat, lon, pad=0.002):
    """The (south, west, north, east) boxes, one per TILE-degree square the track touches, widened by `pad`."""
    keys = sorted({(math.floor(a / TILE), math.floor(b / TILE)) for a, b in zip(lat, lon)})
    return [(i * TILE - pad, j * TILE - pad, (i + 1) * TILE + pad, (j + 1) * TILE + pad) for i, j in keys]


def distances(lat, lon, ways, cell=0.001):
    """For each point, (metres to the nearest way, that way's index or -1), by a grid over the ways' vertices."""
    grid = collections.defaultdict(set)
    for i, w in enumerate(ways):
        g = w['geometry']
        for j in range(len(g) - 1):                                                    # every cell a segment passes through, not just its ends (a long straight road has few vertices)
            n = max(1, int(math.hypot(g[j + 1][0] - g[j][0], g[j + 1][1] - g[j][1]) / (cell / 2)))
            for k in range(n + 1): grid[(int((g[j][0] + (g[j + 1][0] - g[j][0]) * k / n) / cell), int((g[j][1] + (g[j + 1][1] - g[j][1]) * k / n) / cell))].add(i)
        if len(g) == 1: grid[(int(g[0][0] / cell), int(g[0][1] / cell))].add(i)
    out = []
    for a, b in zip(lat, lon):
        best, who = 1e9, -1
        for i in {i for da in (-1, 0, 1) for db in (-1, 0, 1) for i in grid.get((int(a / cell) + da, int(b / cell) + db), ())}:
            g = ways[i]['geometry']
            for j in range(len(g) - 1):
                d = _metres((a, b), g[j], g[j + 1])
                if d < best: best, who = d, i
        out.append((best, who))
    return out


def stretches(lat, lon, dist, cache_dir, on_m=8.0, min_m=300.0, step_m=20.0, svc=None, kinds=osm.DRIVABLE):
    """Runs of the track on a drivable road (see the module doc). Raises RuntimeError naming the tiles if the lookup service could not answer for some of them."""
    la, lo, d = sample(np.asarray(lat, float), np.asarray(lon, float), np.asarray(dist, float), step_m)
    boxes = tiles(la, lo); svc = svc or osm.pool(cache_dir); got = svc.query_many([osm.ways_ql(b, kinds) for b in boxes])
    missing = [b for b, r in zip(boxes, got) if r is None]
    if missing: raise RuntimeError(f'OpenStreetMap lookup failed for {len(missing)} of {len(boxes)} tiles: {missing[:3]}')
    ways = list({w['id']: w for r in got for w in osm.ways(r)}.values()); dd = distances(la, lo, ways); on = [m <= on_m for m, _ in dd]; need = max(1, int(round(min_m / step_m))); out = []; s = None
    for i in range(len(on) + 1):
        v = i < len(on) and on[i]
        if v and s is None: s = i
        if not v and s is not None:
            if i - s >= need:
                us = [ways[w] for _, w in dd[s:i] if w >= 0]
                out.append(dict(i0=s, i1=i, km0=round(d[s] / 1000, 3), km1=round(d[i - 1] / 1000, 3), length_m=int((i - s) * step_m),
                                highways=sorted({u['highway'] for u in us}), names=sorted({u['name'] for u in us if u['name']})))
            s = None
    return out
