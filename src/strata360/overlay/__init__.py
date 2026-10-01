"""The race overlay drawn on the final film (implementation plan A2): the numbers and maps of the race track at the exact time of every frame.

series.py   the track's values at any instant (smoothed once over the whole race)
tiles.py    map tiles: Web Mercator, a shared disk cache, the map around a place at any scale
draw.py     text, icons, marker, map frames as RGBA patches; laying them on a frame
layout.py   what is shown where (configurable from race.json `overlay`), and Overlay itself
zoom.py     the close-up map's automatic zoom

`for_project(folder, size)` gives the overlay of a project's final film, or None when it is off or there is no track; `build(cfg, track, size)` the overlay for given settings and
track file."""
import functools


@functools.lru_cache(maxsize=4)
def _series(path, mtime):
    from strata360.gps import track as TR
    from strata360.overlay.series import Series
    return Series(TR.load(path))


def build(cfg, track, size, tiles=None, maps=True):
    """The overlay with race settings `cfg` (race.json merged) over the track file `track`; maps=False leaves the maps (and their credit) out."""
    import os
    from strata360.overlay.layout import Overlay, settings
    st = settings(cfg.get('overlay'))
    if not maps: st = {**st, 'elements': [e for e in st['elements'] if e not in ('route_map', 'local_map', 'credit')]}
    return Overlay(_series(track, os.path.getmtime(track)), size, st, tz=cfg.get('timezone') or 'Europe/Brussels', tiles=tiles)


def for_project(folder, size, tiles=None):
    from strata360.pipeline import config
    cfg = config.load(folder); path = config.track_path(folder, cfg)
    if not (cfg.get('overlay') or {}).get('enabled', True) or not path: return None
    return build(cfg, path, size, tiles)
