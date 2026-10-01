"""The race overlay drawn on the final film (implementation plan A2): the numbers and maps of the race track at the exact time of every frame.

series.py   the track's values at any instant (smoothed once over the whole race)
tiles.py    map tiles: Web Mercator, a shared disk cache, the map around a place at any scale
draw.py     text, icons, marker, map frames as RGBA patches; laying them on a frame
layout.py   what is shown where (configurable from race.json `overlay`), and Overlay itself

`for_project(folder, size)` gives the overlay of a project's final film, or None when it is off or there is no track."""


def for_project(folder, size, tiles=None):
    from strata360.gps import track as TR
    from strata360.overlay.layout import Overlay
    from strata360.overlay.series import Series
    from strata360.pipeline import config
    cfg = config.load(folder); st = cfg.get('overlay') or {}; path = config.track_path(folder, cfg)
    if not st.get('enabled', True) or not path: return None
    return Overlay(Series(TR.load(path)), size, st, tz=cfg.get('timezone') or 'Europe/Brussels', tiles=tiles)
