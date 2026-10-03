"""The overlay: what it shows and where, drawn for any frame size at the exact time of each frame.

The elements follow the overlay made before with gopro-dashboard-overlay (scripts/overlay/layout.xml, used as a guide; no code taken from it): elapsed time and the day of the race with the date and time top left, distance so far, pace,
and a bottom row of altitude, slope and heart rate with icons; the whole route with the position marker top right and a close-up map that moves with the runner below it.

Positions and sizes are written for a 1920 x 1080 frame and scaled to the film (so 4K is drawn at 4K, not enlarged); each element keeps its distance from the edges it is anchored to, so a
frame of another shape still has everything in its corner. race.json `overlay` changes it:

  {"enabled": true, "elements": ["clock", "distance", ...], "scale": 1.0, "map_opacity": 0.6, "local_zoom": 14, "auto_zoom": true, "zoom_range": 1.5,
   "style": null, "font": null, "label_font": null, "layout": {"pace": {"y": 860}, "route_map": {"style": "osm"}}}

`elements` picks and orders what is shown (any of ELEMENTS; `stage` is the Before Race / At Start / Stage N / Checkpoint N / At Finish / After Race text); `layout` overrides any field of an element; `font`/`label_font` are paths to other TTF/OTF files.
Map styles: the whole-route map is plain (tf-landscape: towns, main roads, relief); the close-up shows the ground (tf-outdoors: contours, paths, hill shading). `style` sets
one style for both. The close-up zooms by itself (overlay/zoom.py: closer where the map is busy, wider on straight stretches) within local_zoom +/- zoom_range, unless
auto_zoom is false.

Nothing is stored per frame: the overlay is drawn onto each frame as it is rendered; what does not change is drawn once and reused (each distinct text, the whole-route map,
the close-up map while the runner stands still); the clock and the marker follow every frame."""
import bisect, datetime as dt, json, math, os
from zoneinfo import ZoneInfo
import numpy as np, cv2
from strata360.overlay import draw as D
from strata360.overlay.tiles import Tiles, STYLES, world

REF_W, REF_H = 1920, 1080
ELEMENTS = {   # reference positions on a 1920 x 1080 frame; h/v: the edges the element keeps its distance from
    'profile': dict(kind='profile', height=120),
    'clock': dict(kind='clock', x=16, y=24),
    'stage': dict(kind='stage', x=16, y=164),
    'distance': dict(kind='big', x=520, y=28, metric='dist', label='km'),
    'pace': dict(kind='big', x=150, y=745, v='bottom', metric='pace', label='min/km'),
    'altitude': dict(kind='stat', x=16, y=850, v='bottom', icon='mountain', metric='alt', label='ALT (m)'),
    'slope': dict(kind='stat', x=220, y=850, v='bottom', icon='slope', metric='slope', label='SLOPE (%)'),
    'climb': dict(kind='climb', x=16, y=914, v='bottom'),
    'heart_rate': dict(kind='stat', x=1900, y=850, h='right', v='bottom', icon='heart', metric='hr', label='BPM', align='right'),
    'route_map': dict(kind='route_map', x=1644, y=24, h='right', size=256, radius=35, style='tf-landscape'),
    'local_map': dict(kind='local_map', x=1644, y=304, h='right', size=256, radius=35, outline=(255, 0, 0), style='tf-outdoors'),
    'credit': dict(kind='credit', x=1900, y=566, h='right', size=11),
}
DEFAULTS = dict(enabled=True, line_opacity=1.0, style=None, elements=[e for e in ELEMENTS if e != 'credit'], scale=1.0, map_opacity=0.6, local_zoom=14, auto_zoom=True, zoom_range=1.5, font=None, label_font=None, layout={})
DASH = '–'


def fmt(metric, v):
    if v is None or not math.isfinite(v): return '-:--' if metric == 'pace' else DASH
    if metric == 'dist': return f'{v / 1000:.1f}'
    if metric == 'pace': s = int(round(v)); return f'{s // 60}:{s % 60:02d}'
    return str(round(v))


METRIC = dict(dist='dist_m', pace='pace_s_km', alt='alt_m', slope='slope_pct', hr='hr')


class _Ctx:
    """What the widgets share: frame size and scale, fonts, the series, the tiles, the time zone and a cache of drawn text."""
    def __init__(self, series, size, st, tz, tiles, stages=(), progress=None):
        self.stages = list(stages); self.progress = progress or {}; self._rs = None; self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H) * float(st['scale']); self.series, self.st, self.tz = series, st, ZoneInfo(tz)
        self._tiles = tiles if callable(tiles) and not isinstance(tiles, Tiles) else (lambda style: tiles) if tiles is not None else None; self._made = {}
        self.vfont, self.lfont = st.get('font') or D.VALUE_FONT, st.get('label_font') or st.get('font') or D.LABEL_FONT; self._text = {}

    def style(self, el): return self.st.get('style') or el.get('style') or 'tf-outdoors'

    def tiles(self, style):
        """The tiles of a style (`tiles` given to Overlay: one Tiles for every style, or a function style -> Tiles)."""
        if style not in self._made: self._made[style] = self._tiles(style) if self._tiles else Tiles(style)
        return self._made[style]

    def at(self, el, x, y):
        """Frame position of reference point (x, y) of element `el` (scaled, kept at its distance from its edges)."""
        return (x * self.s if el.get('h', 'left') == 'left' else self.W - (REF_W - x) * self.s), (y * self.s if el.get('v', 'top') == 'top' else self.H - (REF_H - y) * self.s)

    def text(self, el, x, y, s, px, label=False, align='left'):
        """A text patch with its ascender-top at reference (x, y), its left (or right, with align='right') edge at x."""
        key = (s, px, label)
        if key not in self._text:
            if len(self._text) > 4000: self._text.clear()
            self._text[key] = D.text(s, px * self.s, self.lfont if label else self.vfont, tabular=not label)
        rgba, pad, w = self._text[key]; X, Y = self.at(el, x, y); return (X - pad - (w if align == 'right' else 0), Y - pad, rgba)

    def route_elapsed(self, t):
        """(metres of the routes covered so far, metres of all the routes): the completed stages' routes in full and the progress along the route of the stage in hand (gps/tracks.py `stage_progress`), so a run that strayed is behind where its distance says. None without route progress."""
        if not self.progress or not self.stages: return None
        if self._rs is None:
            times = [a for a, _ in self.stages]; names = [b for _, b in self.stages]; self._rs = []
            for name, pr in self.progress.items():
                k = names.index(name) if name in names else None
                self._rs.append((times[k] if k is not None else math.inf, times[k + 1] if k is not None and k + 1 < len(times) else math.inf, pr['route_m'], k is not None and k + 1 < len(names) and names[k + 1] != 'After Race', pr['t'], pr['prog']))
        done = 0.0
        for start, end, route, complete, ts, prog in self._rs:
            if t >= start and len(ts): done += route if (complete and t >= end) else float(np.interp(t, ts, prog))
        return done, sum(r[2] for r in self._rs)

    def runs(self, el, x, y, parts, px):
        """Text in several colours on one line, left to right from x: parts = [(string, fill)] or [(string, fill, shadow)] (a dark fill wants a light shadow)."""
        X, Y = self.at(el, x, y); out = []
        for p in parts:
            s, fill, shadow = (p + ((0, 0, 0),))[:3]; key = (s, px, False, fill, shadow)
            if key not in self._text:
                if len(self._text) > 4000: self._text.clear()
                self._text[key] = D.text(s, px * self.s, self.vfont, fill=fill, tabular=True, shadow=shadow)
            rgba, pad, w = self._text[key]; out.append((X - pad, Y - pad, rgba)); X += w
        return out

    def icon(self, el, name, x, y, px):
        key = ('icon', name, px)
        if key not in self._text: self._text[key] = D.icon(name, px * self.s)
        rgba, pad = self._text[key]; X, Y = self.at(el, x, y); return (X - pad, Y - pad, rgba)


def race_day(start, t, tz):
    """The calendar day of the race at time t (UTC seconds), 1 on the day it starts. Days change at local midnight, except that a start in the last hour before midnight (a first day shorter than an hour) does not count
    as a day of its own: that day goes on into the next calendar day, and the second day starts at the next midnight."""
    s0 = dt.datetime.fromtimestamp(start, dt.timezone.utc).astimezone(tz); mid = dt.datetime.combine(s0.date() + dt.timedelta(days=1), dt.time(), tzinfo=tz)
    n = (dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(tz).date() - s0.date()).days
    return max(1, n + 1 - (1 if (mid - s0).total_seconds() < 3600 and n >= 1 else 0))


def elapsed_text(seconds):
    s = max(0, int(seconds)); return f'{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}'


class Clock:
    """Time since the start of the race track (large), the day of the race (calendar days: `race_day`), and the date and time of day (smaller)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        c, e = self.c, self.el; x, y = e['x'], e['y']; start = float(c.series._pt[0]); lt = dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(c.tz)
        return [c.text(e, x, y, elapsed_text(t - start), 52), c.text(e, x, y + 62, f'DAY {race_day(start, t, c.tz)}', 32), c.text(e, x, y + 104, lt.strftime('%Y/%m/%d  %H:%M:%S'), 22)]


def _hm(seconds):
    """3h4m, or 23m under an hour."""
    m = int(seconds // 60); return f'{m // 60}h{m % 60}m' if m >= 60 else f'{m}m'


class Stage:
    """Where the race is: Before Race (-4h3m: the time to the start), At Start, Stage N (km and time so far / in the whole stage), Checkpoint N (km from the start of the run, time there so far / in all), At Finish, After Race (+34h4m: the time since the end of the run); gps/tracks.py `stage_schedule`, worked out from the routes and the run. Nothing is drawn when there is no schedule."""
    def __init__(self, c, el): self.c, self.el = c, el; self.times = [a for a, _ in c.stages]; self.names = [b for _, b in c.stages]

    def _dist(self, t):
        d = self.c.series.at(t)['dist_m']; return float(d) if math.isfinite(d) else 0.0

    def patches(self, t, v):
        if not self.times: return []
        e = self.el; i = max(0, bisect.bisect_right(self.times, t) - 1); name = self.names[i]; out = [self.c.text(e, e['x'], e['y'], name.upper(), 30)]
        if name.startswith(('Stage', 'Checkpoint')) and i + 1 < len(self.times):
            a, b = self.times[i], self.times[i + 1]                                                                # a stage runs to the next checkpoint's arrival, a checkpoint to the departure
            pr = self.c.progress.get(name) if name.startswith('Stage') else None
            if pr is not None:                                                                                # the distance run so far over the length of the stage's route; where the run went off the route, the route's own progress comes first and what was actually run follows in red
                run = max(0.0, self._dist(min(t, b)) - self._dist(a)) / 1000; L = pr['route_m'] / 1000; p = float(np.interp(t, pr['t'], pr['prog'])) / 1000; RED, WHITE = (235, 40, 40), (255, 255, 255)
                final = self.names[i + 1] == 'After Race' and 'At Finish' not in self.names                    # the run stopped in this stage: its total time is only how long it lasted, in red
                dist = [(f'{p:.1f}/{L:.1f} km', WHITE), (f'  ran {run:.1f} km', RED)] if abs(run - p) > max(0.10 * max(run, p), 0.5) else [(f'{run:.1f}/{L:.1f} km', WHITE)]
                return out + self.c.runs(e, e['x'], e['y'] + 38, dist + [('  ·  ', WHITE), (f'{_hm(max(0.0, min(t, b) - a))}/', WHITE), (_hm(b - a), RED if final else WHITE)], 22)
            if name.startswith('Stage'): km = f'{max(0.0, self._dist(min(t, b)) - self._dist(a)) / 1000:.1f}/{(self._dist(b) - self._dist(a)) / 1000:.1f} km'
            else: km = f'{(self._dist(a) - self._dist(self.times[1] if len(self.times) > 1 else a)) / 1000:.1f} km'          # the way from the start of the run to the checkpoint
            out.append(self.c.text(e, e['x'], e['y'] + 38, f'{km}  ·  {_hm(max(0.0, min(t, b) - a))} / {_hm(b - a)}', 22))
        elif name == 'Before Race' and len(self.times) > 1: out.append(self.c.text(e, e['x'], e['y'] + 38, '-' + _hm(self.times[1] - t) if self.times[1] - t >= 60 else '0m', 22))           # the time to the start
        elif name == 'After Race': out.append(self.c.text(e, e['x'], e['y'] + 38, '+' + _hm(t - self.times[i]) if t - self.times[i] >= 60 else '0m', 22))                                # the time since the end of the run
        return out


class Big:
    """A large value with its unit under it (distance, pace)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        e = self.el; val = v[METRIC[e['metric']]]
        if e['metric'] == 'dist' and not (val is not None and math.isfinite(val)):                                     # before the run 0 km, after it the whole distance (the counter stays on the figure it reached)
            d = self.c.series.cols['dist_m']; d = d[np.isfinite(d)]
            if len(d): val = 0.0 if t <= float(self.c.series._pt[0]) else float(d[-1])
        out = [self.c.text(e, e['x'], e['y'], fmt(e['metric'], val), 48, align='right'), self.c.text(e, e['x'], e['y'] + 56, e['label'], 16, label=True, align='right')]
        if e['metric'] == 'dist' and (re_ := self.c.route_elapsed(t)) is not None:                                      # next to the small km: how far along the routes (all stages added up) of the whole route length
            out.append(self.c.text(e, e['x'] + 10, e['y'] + 56, f'route {re_[0] / 1000:.1f} / {re_[1] / 1000:.1f} km', 16, label=True))
        return out


class Stat:
    """Icon, small label and value (altitude, slope, heart rate)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        e = self.el; x, y = e['x'], e['y']; r = e.get('align') == 'right'; tx = x - 70 if r else x + 70; al = 'right' if r else 'left'; val = v[METRIC[e['metric']]]
        name = e['icon'] + ('_down' if e['icon'] == 'slope' and val < 0 else '')                                   # NaN compares False: uphill icon
        return [self.c.icon(e, name, x - 64 if r else x, y, 64), self.c.text(e, tx, y, e['label'], 16, label=True, align=al),
                self.c.text(e, tx, y + 20, fmt(e['metric'], val), 32, align=al)]


class Climb:
    """The total ascent and descent so far, in a small line under altitude and slope (before the run 0, after it the totals)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        a, d = self.c.series.cols['ascent_m'], self.c.series.cols['descent_m']; s = self.c.series
        up, down = (float(a[0]), float(d[0])) if t <= s.t0 else (float(a[-1]), float(d[-1])) if t >= s.t1 else (float(np.interp(t, s.grid, a)), float(np.interp(t, s.grid, d)))
        e = self.el; return [self.c.text(e, e['x'], e['y'], f'ASCENT {up:,.0f} m   DESCENT {down:,.0f} m', 16)]


class Profile:
    """The elevation profile of the WHOLE race along the bottom of the frame, with where the runner is: the part already run in a light fill, the part to come darker, a cursor and a dot on the line. The same on every shot, camera or generated clip.
    The bottom row of numbers sits above it (ELEMENTS)."""
    def __init__(self, c, el): self.c, self.el = c, el; self.built = None

    def _build(self):
        c = self.c; W = c.W; H = max(8, int(round(self.el['height'] * c.s))); d = c.series.cols['dist_m']; a = c.series.cols['alt_m']; ok = np.isfinite(d) & np.isfinite(a); self.built = False
        if ok.sum() < 2: return
        dd, first = np.unique(d[ok], return_index=True); aa = a[ok][first]
        if len(dd) < 2 or dd[-1] - dd[0] <= 0: return
        self.d0, self.d1 = float(dd[0]), float(dd[-1]); alt = np.interp(np.linspace(self.d0, self.d1, W), dd, aa); alt = np.convolve(np.pad(alt, 4, mode='edge'), np.ones(9) / 9, 'valid')       # (smoothed a little: a 350 km profile in 1920 pixels)
        lo, hi = float(alt.min()), float(alt.max()); pad = 0.14 * H; ys = H - pad - (alt - lo) / max(hi - lo, 60.0) * (H - 2 * pad); self.ys = ys; self.H = H
        pts = np.stack([np.arange(W), ys], 1).round().astype(np.int32); poly = np.concatenate([pts, [[W - 1, H], [0, H]]]).reshape(-1, 1, 2); w = max(1, int(round(2 * c.s)))
        self.done = np.zeros((H, W, 4), np.uint8); self.todo = np.zeros((H, W, 4), np.uint8)
        cv2.fillPoly(self.done, [poly], (255, 255, 255, 105)); cv2.polylines(self.done, [pts.reshape(-1, 1, 2)], False, (255, 255, 255, 255), w, cv2.LINE_AA)
        cv2.fillPoly(self.todo, [poly], (0, 0, 0, 120)); cv2.polylines(self.todo, [pts.reshape(-1, 1, 2)], False, (255, 255, 255, 150), w, cv2.LINE_AA)
        self.dot = D.marker(6 * c.s); self.built = True

    def patches(self, t, v):
        if self.built is None: self._build()
        d = v['dist_m']
        if not self.built: return []
        if not math.isfinite(d): d = self.d0 if t <= float(self.c.series._pt[0]) else self.d1                    # before the track starts the cursor is at the start, after it ends at the end (the profile is on every shot)
        c = self.c; W = c.W; x = int(round(float(np.clip((d - self.d0) / (self.d1 - self.d0), 0.0, 1.0)) * (W - 1))); Y = c.H - self.H; r = self.dot.shape[0] / 2; cur = np.zeros((self.H, max(2, int(round(2 * c.s))), 4), np.uint8); cur[...] = (255, 255, 255, 235)
        out = [(0, Y, self.done[:, :x + 1]), (x + 1, Y, self.todo[:, x + 1:]), (x - cur.shape[1] / 2, Y, cur), (x - r, Y + float(self.ys[x]) - r, self.dot)]
        return [p for p in out if p[2].shape[1] > 0]


RUN_COLOUR = (230, 20, 20)                                                                  # both maps: the whole route in this medium red,
TODO_W, DONE_W = 1.35, 1.65                                                                 # line widths on the whole-route map (px at 1080p): the whole route, and the part already run
DONE_DARK = (140, 0, 0)                                                                    # and the part already run in this darker red


def route_bearing(u, v, n, x0, y0, look, previous=0.0, step=5.0):
    """Degrees clockwise from up (rounded to `step`) of the direction the route takes from the marker at (x0, y0), which is at point n of the route (picture coordinates u, v): to the first later point `look` px away, so how far ahead is looked at is the map's scale; at the very end the previous bearing stays."""
    d = np.hypot(u[n:] - x0, v[n:] - y0); far = np.flatnonzero(d >= look); j = n + int(far[0]) if len(far) else (len(u) - 1 if n < len(u) else None)
    if j is None or np.hypot(u[j] - x0, v[j] - y0) < 0.5: return previous
    return round(math.degrees(math.atan2(u[j] - x0, -(v[j] - y0))) % 360 / step) * step % 360


class RouteMap:
    """The whole route on its map, the position marker moving along it."""
    def __init__(self, c, el): self.c, self.el = c, el; self.base = None

    def _build(self):
        c, e = self.c, self.el; S = int(round(e['size'] * c.s)); wx, wy = world(c.series.route_lat, c.series.route_lon)
        span = max(np.ptp(wx), np.ptp(wy), 1e-9); self.k = S * 0.86 / span; self.cx, self.cy = (wx.min() + wx.max()) / 2, (wy.min() + wy.max()) / 2; self.S = S
        pic = np.asarray(c.tiles(c.style(e)).picture(self.cx, self.cy, self.k, S, S)).copy()
        self.u, self.w = (wx - self.cx) * self.k + S / 2, (wy - self.cy) * self.k + S / 2
        self.route_layer = None
        self.base = D.framed(pic, e['radius'] * c.s, c.st['map_opacity'], outline=e.get('outline', (0, 0, 0)), outline_w=1.5 * c.s); self.dot = D.marker(6 * c.s); self.ahead = None
        self.round = D.rounded(S, e['radius'] * c.s); self.done = None
        self.route_layer = D.line_layer((S, S), [(self.u, self.w, TODO_W * c.s, RUN_COLOUR)], clip=self.round, opacity=float(c.st['line_opacity']))       # the whole route thin in the medium red, on its own (not part of the see-through map); the part already run is drawn over it darker (a little thinner) each frame

    def patches(self, t, v):
        if self.base is None: self._build()
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); u, w = self._xy(t)
        arrow = D.arrow(22 * self.c.s, self._bearing(t, u, w)); h = arrow.shape[0] / 2
        return [(X, Y, self.base), (X, Y, self.route_layer), (X, Y, self._run(t, u, w)), (X + u - h, Y + w - h, arrow)]

    def _bearing(self, t, u, w, look=12.0):
        """The direction the route goes on from the marker, looked at `look` px of the map ahead (a long way, on a map of the whole race): where the runner is going to go, not the way the last seconds went."""
        n = int(np.searchsorted(self.c.series._pt, t, 'right')); key = (n, round(u), round(w))
        if self.ahead is None or self.ahead[0] != key: self.ahead = (key, route_bearing(self.u, self.w, n, u, w, look * self.c.s, previous=self.ahead[1] if self.ahead else 0.0))
        return self.ahead[1]

    def _xy(self, t):
        wx, wy = world(*self.c.series.position(t)); return (wx - self.cx) * self.k + self.S / 2, (wy - self.cy) * self.k + self.S / 2

    def _run(self, t, u, w):
        """The part of the route already run (to the marker) in the darker red, as a patch with the lines' own opacity; drawn again only when the marker has moved on."""
        s = self.c.series; n = int(np.searchsorted(s._pt, t, 'right')); key = (n, round(u, 1), round(w, 1))
        if self.done is None or self.done[0] != key:
            shape = (self.S, self.S); step = max(1, n // 1500); layers = []
            if n >= 1: layers = [(np.concatenate([self.u[:n:step], [u]]), np.concatenate([self.w[:n:step], [w]]), DONE_W * self.c.s, DONE_DARK)]
            self.done = (key, D.line_layer(shape, layers, clip=self.round, opacity=float(self.c.st['line_opacity'])))
        return self.done[1]


class LocalMap:
    """A close-up map that moves with the runner (marker in the middle, the route drawn on it), at the zoom of the moment (overlay/zoom.py). The map around the position is fetched
    three times the map's size at the nearest whole zoom and reused while the position stays inside (a few are kept, so a dissolve between two places does not redraw every frame);
    each frame is resampled from it at the exact position and zoom, so the map pans and zooms smoothly rather than in whole-pixel steps."""
    KEEP = 4

    def __init__(self, c, el):
        self.c, self.el = c, el; self.S = int(round(el['size'] * c.s)); self.B = 3 * self.S; self.backs = []; self.dot = D.marker(6 * c.s); self.last = None; self.n = 0
        self.base = float(el.get('zoom', c.st['local_zoom'])); self.auto = bool(el.get('auto_zoom', c.st['auto_zoom'])); self._zoom = None
        self.rw = world(c.series.route_lat, c.series.route_lon); self.tiles = c.tiles(c.style(el))

    @property
    def zoom(self):
        if self._zoom is None:                                                                          # one profile per race, style and settings: shared by every overlay over the same series
            from strata360.overlay.zoom import Zoom
            rng = float(self.el.get('zoom_range', self.c.st['zoom_range'])); key = (self.tiles.style, self.base, rng); cache = self.c.series.__dict__.setdefault('_zooms', {})
            if key not in cache: cache[key] = Zoom(self.c.series, self.tiles, base=self.base, range_=rng)
            self._zoom = cache[key]
        return self._zoom

    def zoom_at(self, t): return self.zoom.at(t) if self.auto else self.base

    def _back(self, wx, wy, zb, r):
        kb = 2.0 ** zb * self.c.s; lim = (self.B - self.S / r) / 2 - 2
        for b in self.backs:
            if b[3] == zb and abs(wx - b[0]) * kb <= lim and abs(wy - b[1]) * kb <= lim: return b
        self.n += 1; b = (wx, wy, np.asarray(self.tiles.picture(wx, wy, kb, self.B, self.B)), zb, self.n); self.backs = (self.backs + [b])[-self.KEEP:]; return b

    def patches(self, t, v):
        z = self.zoom_at(t); wx, wy = world(*self.c.series.position(t)); S = self.S; key = (round(z, 4), round(float(wx), 10), round(float(wy), 10))
        if self.last is None or self.last[0] != key:
            zb = int(round(z)); k = 2.0 ** z * self.c.s; r = 2.0 ** (z - zb); b = self._back(wx, wy, zb, r); kb = 2.0 ** zb * self.c.s
            M = np.array([[1 / r, 0, (wx - b[0]) * kb + self.B / 2 - S / 2 / r], [0, 1 / r, (wy - b[1]) * kb + self.B / 2 - S / 2 / r]])
            pic = cv2.warpAffine(b[2], M, (S, S), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
            u, v = (self.rw[0] - wx) * k + S / 2, (self.rw[1] - wy) * k + S / 2; n = int(np.searchsorted(self.c.series._pt, t, 'right'))
            lines = D.line_layer((S, S), [(u, v, 2 * self.c.s, RUN_COLOUR), (np.concatenate([u[:n], [S / 2]]), np.concatenate([v[:n], [S / 2]]), 3 * self.c.s, DONE_DARK)],
                                 clip=D.rounded(S, self.el['radius'] * self.c.s), opacity=float(self.c.st['line_opacity']))     # the whole route in the medium red, the part already run over it in the darker red (as on the whole-route map, with the close-up's own thicknesses)
            bearing = route_bearing(u, v, n, S / 2, S / 2, 9 * self.c.s, previous=self.last[3] if self.last else 0.0)                            # a short way ahead: this map is zoomed in, so it is the local direction of the route
            self.last = (key, D.framed(pic, self.el['radius'] * self.c.s, self.c.st['map_opacity'], outline=self.el.get('outline'), outline_w=2 * self.c.s), lines, bearing)
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); arrow = D.arrow(20 * self.c.s, self.last[3]); h = arrow.shape[0] / 2
        return [(X, Y, self.last[1]), (X, Y, self.last[2]), (X + S / 2 - h, Y + S / 2 - h, arrow)]


class Credit:
    """The maps' credit line (tile services ask for it where their maps are shown): one line per distinct credit of the map styles in use."""
    def __init__(self, c, el, styles=()): self.c, self.el = c, el; self.lines = list(dict.fromkeys(STYLES[s]['credit'] for s in styles))

    def patches(self, t, v):
        return [self.c.text(self.el, self.el['x'], self.el['y'] + 14 * i, line, self.el['size'], label=True, align='right') for i, line in enumerate(self.lines)]


KINDS = dict(profile=Profile, clock=Clock, stage=Stage, climb=Climb, big=Big, stat=Stat, route_map=RouteMap, local_map=LocalMap, credit=Credit)


def settings(st=None):
    """race.json `overlay` merged over DEFAULTS (unknown element names are an error, so a typo does not silently drop something)."""
    out = {**DEFAULTS, **(st or {})}; bad = [e for e in out['elements'] if e not in ELEMENTS] + [e for e in out['layout'] if e not in ELEMENTS]
    if bad: raise ValueError(f'unknown overlay element(s) {", ".join(bad)}: one of {", ".join(ELEMENTS)}')
    return out


class Overlay:
    """overlay.apply(frame, t) draws the overlay for UTC seconds t onto an RGB frame (uint8 or uint16) in place. `tiles` defaults to the configured style (fetched and cached on first use)."""

    def __init__(self, series, size, st=None, tz='Europe/Brussels', tiles=None, stages=(), progress=None):
        self.st = settings(st); self.c = _Ctx(series, size, self.st, tz, tiles, stages, progress)
        els = {n: {**ELEMENTS[n], **self.st['layout'].get(n, {})} for n in self.st['elements']}
        styles = [self.c.style(e) for e in els.values() if e['kind'] in ('route_map', 'local_map')]
        for st_ in styles: self.c.tiles(st_)                                                                        # a missing map key is reported now, not hours into a render
        self.widgets = [Credit(self.c, e, styles) if e['kind'] == 'credit' else KINDS[e['kind']](self.c, e) for e in els.values()]

    def patches(self, t):
        v = self.c.series.at(t); return [p for w in self.widgets for p in w.patches(t, v)]

    def apply(self, frame, t):
        if not frame.flags.writeable: frame = frame.copy()
        return D.composite(frame, self.patches(t))

    def still(self, t):
        """The overlay alone at time t, as an RGBA uint8 array the size of the frame (for previews and checks)."""
        W, H = self.c.W, self.c.H; rgb = np.zeros((H, W, 3), np.float32); a = np.zeros((H, W, 1), np.float32)
        for x, y, p in self.patches(t):
            x, y = int(round(x)), int(round(y)); x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + p.shape[1], W), min(y + p.shape[0], H)
            if x0 >= x1 or y0 >= y1: continue
            q = p[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255; qa = q[..., 3:4]; ra = a[y0:y1, x0:x1]; na = qa + ra * (1 - qa)
            with np.errstate(invalid='ignore', divide='ignore'): rgb[y0:y1, x0:x1] = np.where(na > 0, (q[..., :3] * qa + rgb[y0:y1, x0:x1] * ra * (1 - qa)) / na, 0)
            a[y0:y1, x0:x1] = na
        return np.dstack([rgb, a]).__mul__(255).round().astype(np.uint8)


def signature(st, track):
    """What the overlay's look depends on, for the final film's cache key: the settings and the track file."""
    return json.dumps([settings(st), os.path.getmtime(track) if track and os.path.exists(track) else None], sort_keys=True, default=str)
