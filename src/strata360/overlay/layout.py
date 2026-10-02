"""The overlay: what it shows and where, drawn for any frame size at the exact time of each frame.

The elements follow the overlay made before with gopro-dashboard-overlay (scripts/overlay/layout.xml, used as a guide; no code taken from it): date and time top left, distance so far, pace,
and a bottom row of altitude, slope and heart rate with icons; the whole route with the position marker top right and a close-up map that moves with the runner below it.

Positions and sizes are written for a 1920 x 1080 frame and scaled to the film (so 4K is drawn at 4K, not enlarged); each element keeps its distance from the edges it is anchored to, so a
frame of another shape still has everything in its corner. race.json `overlay` changes it:

  {"enabled": true, "elements": ["clock", "distance", ...], "scale": 1.0, "map_opacity": 0.6, "local_zoom": 14, "auto_zoom": true, "zoom_range": 1.5,
   "style": null, "font": null, "label_font": null, "layout": {"pace": {"y": 860}, "route_map": {"style": "osm"}}}

`elements` picks and orders what is shown (any of ELEMENTS); `layout` overrides any field of an element; `font`/`label_font` are paths to other TTF/OTF files.
Map styles: the whole-route map is plain (tf-landscape: towns, main roads, relief); the close-up shows the ground (tf-outdoors: contours, paths, hill shading). `style` sets
one style for both. The close-up zooms by itself (overlay/zoom.py: closer where the map is busy, wider on straight stretches) within local_zoom +/- zoom_range, unless
auto_zoom is false.

Nothing is stored per frame: the overlay is drawn onto each frame as it is rendered; what does not change is drawn once and reused (each distinct text, the whole-route map,
the close-up map while the runner stands still); the clock and the marker follow every frame."""
import datetime as dt, json, math, os
from zoneinfo import ZoneInfo
import numpy as np, cv2
from strata360.overlay import draw as D
from strata360.overlay.tiles import Tiles, STYLES, world

REF_W, REF_H = 1920, 1080
ELEMENTS = {   # reference positions on a 1920 x 1080 frame; h/v: the edges the element keeps its distance from
    'profile': dict(kind='profile', height=120),
    'clock': dict(kind='clock', x=200, y=24),
    'distance': dict(kind='big', x=150, y=124, metric='dist', label='km'),
    'pace': dict(kind='big', x=150, y=745, v='bottom', metric='pace', label='min/km'),
    'altitude': dict(kind='stat', x=16, y=850, v='bottom', icon='mountain', metric='alt', label='ALT (m)'),
    'slope': dict(kind='stat', x=220, y=850, v='bottom', icon='slope', metric='slope', label='SLOPE (%)'),
    'heart_rate': dict(kind='stat', x=1900, y=850, h='right', v='bottom', icon='heart', metric='hr', label='BPM', align='right'),
    'route_map': dict(kind='route_map', x=1644, y=24, h='right', size=256, radius=35, style='tf-landscape'),
    'local_map': dict(kind='local_map', x=1644, y=304, h='right', size=256, radius=35, outline=(255, 0, 0), style='tf-outdoors'),
    'credit': dict(kind='credit', x=1900, y=566, h='right', size=11),
}
DEFAULTS = dict(enabled=True, style=None, elements=[e for e in ELEMENTS if e != 'credit'], scale=1.0, map_opacity=0.6, local_zoom=14, auto_zoom=True, zoom_range=1.5, font=None, label_font=None, layout={})
DASH = '–'


def fmt(metric, v):
    if v is None or not math.isfinite(v): return '-:--' if metric == 'pace' else DASH
    if metric == 'dist': return f'{v / 1000:.1f}'
    if metric == 'pace': s = int(round(v)); return f'{s // 60}:{s % 60:02d}'
    return str(round(v))


METRIC = dict(dist='dist_m', pace='pace_s_km', alt='alt_m', slope='slope_pct', hr='hr')


class _Ctx:
    """What the widgets share: frame size and scale, fonts, the series, the tiles, the time zone and a cache of drawn text."""
    def __init__(self, series, size, st, tz, tiles):
        self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H) * float(st['scale']); self.series, self.st, self.tz = series, st, ZoneInfo(tz)
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

    def icon(self, el, name, x, y, px):
        key = ('icon', name, px)
        if key not in self._text: self._text[key] = D.icon(name, px * self.s)
        rgba, pad = self._text[key]; X, Y = self.at(el, x, y); return (X - pad, Y - pad, rgba)


class Clock:
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        lt = dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(self.c.tz); x, y = self.el['x'], self.el['y']
        return [self.c.text(self.el, x, y, lt.strftime('%Y/%m/%d'), 32, align='right'), self.c.text(self.el, x, y + 40, lt.strftime('%H:%M:%S'), 40, align='right')]


class Big:
    """A large value with its unit under it (distance, pace)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        e = self.el; return [self.c.text(e, e['x'], e['y'], fmt(e['metric'], v[METRIC[e['metric']]]), 48, align='right'), self.c.text(e, e['x'], e['y'] + 56, e['label'], 16, label=True, align='right')]


class Stat:
    """Icon, small label and value (altitude, slope, heart rate)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        e = self.el; x, y = e['x'], e['y']; r = e.get('align') == 'right'; tx = x - 70 if r else x + 70; al = 'right' if r else 'left'; val = v[METRIC[e['metric']]]
        name = e['icon'] + ('_down' if e['icon'] == 'slope' and val < 0 else '')                                   # NaN compares False: uphill icon
        return [self.c.icon(e, name, x - 64 if r else x, y, 64), self.c.text(e, tx, y, e['label'], 16, label=True, align=al),
                self.c.text(e, tx, y + 20, fmt(e['metric'], val), 32, align=al)]


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
        if not self.built or not math.isfinite(d): return []
        c = self.c; W = c.W; x = int(round(float(np.clip((d - self.d0) / (self.d1 - self.d0), 0.0, 1.0)) * (W - 1))); Y = c.H - self.H; r = self.dot.shape[0] / 2; cur = np.zeros((self.H, max(2, int(round(2 * c.s))), 4), np.uint8); cur[...] = (255, 255, 255, 235)
        out = [(0, Y, self.done[:, :x + 1]), (x + 1, Y, self.todo[:, x + 1:]), (x - cur.shape[1] / 2, Y, cur), (x - r, Y + float(self.ys[x]) - r, self.dot)]
        return [p for p in out if p[2].shape[1] > 0]


class RouteMap:
    """The whole route on its map, the position marker moving along it."""
    def __init__(self, c, el): self.c, self.el = c, el; self.base = None

    def _build(self):
        c, e = self.c, self.el; S = int(round(e['size'] * c.s)); wx, wy = world(c.series.route_lat, c.series.route_lon)
        span = max(np.ptp(wx), np.ptp(wy), 1e-9); self.k = S * 0.86 / span; self.cx, self.cy = (wx.min() + wx.max()) / 2, (wy.min() + wy.max()) / 2; self.S = S
        pic = np.asarray(c.tiles(c.style(e)).picture(self.cx, self.cy, self.k, S, S)).copy()
        D.route_line(pic, (wx - self.cx) * self.k + S / 2, (wy - self.cy) * self.k + S / 2, width=3 * c.s)
        self.base = D.framed(pic, e['radius'] * c.s, c.st['map_opacity'], outline=e.get('outline', (0, 0, 0)), outline_w=1.5 * c.s); self.dot = D.marker(6 * c.s)

    def patches(self, t, v):
        if self.base is None: self._build()
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); wx, wy = world(*self.c.series.position(t))
        u, w = (wx - self.cx) * self.k + self.S / 2, (wy - self.cy) * self.k + self.S / 2; r = self.dot.shape[0] / 2
        return [(X, Y, self.base), (X + u - r, Y + w - r, self.dot)]


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
            D.route_line(pic, (self.rw[0] - wx) * k + S / 2, (self.rw[1] - wy) * k + S / 2, width=3 * self.c.s)
            self.last = (key, D.framed(pic, self.el['radius'] * self.c.s, self.c.st['map_opacity'], outline=self.el.get('outline'), outline_w=2 * self.c.s))
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); r = self.dot.shape[0] / 2
        return [(X, Y, self.last[1]), (X + S / 2 - r, Y + S / 2 - r, self.dot)]


class Credit:
    """The maps' credit line (tile services ask for it where their maps are shown): one line per distinct credit of the map styles in use."""
    def __init__(self, c, el, styles=()): self.c, self.el = c, el; self.lines = list(dict.fromkeys(STYLES[s]['credit'] for s in styles))

    def patches(self, t, v):
        return [self.c.text(self.el, self.el['x'], self.el['y'] + 14 * i, line, self.el['size'], label=True, align='right') for i, line in enumerate(self.lines)]


KINDS = dict(profile=Profile, clock=Clock, big=Big, stat=Stat, route_map=RouteMap, local_map=LocalMap, credit=Credit)


def settings(st=None):
    """race.json `overlay` merged over DEFAULTS (unknown element names are an error, so a typo does not silently drop something)."""
    out = {**DEFAULTS, **(st or {})}; bad = [e for e in out['elements'] if e not in ELEMENTS] + [e for e in out['layout'] if e not in ELEMENTS]
    if bad: raise ValueError(f'unknown overlay element(s) {", ".join(bad)}: one of {", ".join(ELEMENTS)}')
    return out


class Overlay:
    """overlay.apply(frame, t) draws the overlay for UTC seconds t onto an RGB frame (uint8 or uint16) in place. `tiles` defaults to the configured style (fetched and cached on first use)."""

    def __init__(self, series, size, st=None, tz='Europe/Brussels', tiles=None):
        self.st = settings(st); self.c = _Ctx(series, size, self.st, tz, tiles)
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
