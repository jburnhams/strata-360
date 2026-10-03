"""The race overlay drawn on the final film (implementation plan A2): the numbers and maps of the race track at the exact time of every frame.

series.py   the track's values at any instant (smoothed once over the whole race)
tiles.py    map tiles: Web Mercator, a shared disk cache, the map around a place at any scale
draw.py     text, icons, marker, map frames as RGBA patches; laying them on a frame
layout.py   what is shown where (configurable from race.json `overlay`), and Overlay itself
zoom.py     the close-up map's automatic zoom

`for_project(folder, size)` gives the overlay of a project's final film, or None when it is off or there is no track; `build(cfg, track, size)` the overlay for given settings and
track file."""
import functools, hashlib, json, os


def inputs_signature(folder):
    """Identity of what the overlay shows besides the track and the clip: the overlay settings, the time zone and the tracks' manifest (kinds, checkpoints, cut-offs). When it changes the thumbnails with the overlay and the film preview are out of date."""
    from strata360.gps import tracks
    from strata360.pipeline import config
    cfg = config.load(folder)
    try: man = open(os.path.join(config.race_dir(folder), tracks.MANIFEST)).read()
    except OSError: man = ''
    return hashlib.sha1(json.dumps([cfg.get('overlay'), cfg.get('timezone'), man], sort_keys=True, default=str).encode()).hexdigest()[:12]


@functools.lru_cache(maxsize=4)
def _series(path, mtime):
    from strata360.gps import track as TR
    from strata360.overlay.series import Series
    return Series(TR.load(path))


@functools.lru_cache(maxsize=4)
def _schedule(rd, stamp, tz):
    from strata360.gps import tracks
    try:
        sched = tuple(tracks.stage_schedule(rd))
        try: prog = tracks.stage_progress(rd)
        except Exception as e:                                              # without it a stage shows only the distance run, never the route's progress beside it (dropped loudly)
            print(f'overlay: no route progress for the stages: {type(e).__name__}: {e}'); prog = {}
        try: cuts = tracks.overlay_cutoffs(rd, tz)
        except Exception as e:
            print(f'overlay: no cut-offs: {type(e).__name__}: {e}'); cuts = {}
        try: places = tracks.overlay_places(rd)
        except Exception as e:                                              # the maps then show no start, finish or checkpoints (dropped loudly)
            print(f'overlay: no places for the maps: {type(e).__name__}: {e}'); places = None
        return sched, prog, cuts, places
    except Exception as e:                                                  # the stage text is dropped (loudly), the rest of the overlay stays
        print(f'overlay: no stage text: {type(e).__name__}: {e}'); return (), None, {}, None


def _stages(track, tz='Europe/Brussels'):
    """The stage schedule of the project the track file belongs to (its folder, or the folder above `tracks/`); empty for a track kept elsewhere."""
    import os
    rd = os.path.dirname(os.path.abspath(track)); rd = os.path.dirname(rd) if os.path.basename(rd) == 'tracks' else rd
    if not os.path.exists(os.path.join(rd, 'race.json')) and not os.path.exists(os.path.join(rd, 'tracks.json')): return (), None, {}, None
    stamp = tuple(os.path.getmtime(os.path.join(rd, n)) if os.path.exists(os.path.join(rd, n)) else 0 for n in ('tracks.json', 'track.fit', 'track.gpx', 'track.merged.npz'))
    return _schedule(rd, stamp, tz)


def build(cfg, track, size, tiles=None, maps=True):
    """The overlay with race settings `cfg` (race.json merged) over the track file `track`; maps=False leaves the maps (and their credit) out."""
    import os
    from strata360.overlay.layout import Overlay, settings
    st = settings(cfg.get('overlay'))
    if not maps: st = {**st, 'elements': [e for e in st['elements'] if e not in ('route_map', 'local_map', 'credit')]}
    tz = cfg.get('timezone') or 'Europe/Brussels'; stages, progress, cuts, places = _stages(track, tz) if {'stage', 'route_map', 'local_map'} & set(st['elements']) else ((), None, {}, None)
    return Overlay(_series(track, os.path.getmtime(track)), size, st, tz=cfg.get('timezone') or 'Europe/Brussels', tiles=tiles, stages=stages, progress=progress, cutoffs=cuts, places=places)


def for_project(folder, size, tiles=None):
    from strata360.pipeline import config
    cfg = config.load(folder); path = config.track_path(folder, cfg)
    if not (cfg.get('overlay') or {}).get('enabled', True) or not path: return None
    return build(cfg, path, size, tiles)
