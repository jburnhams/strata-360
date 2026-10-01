"""The overlay: what it shows and where, drawn for any frame size at the exact time of each frame.

The elements follow the overlay made before with gopro-dashboard-overlay (scripts/overlay/layout.xml, used as a guide; no code taken from it): date and time top left, distance so far, pace,
and a bottom row of altitude, slope and heart rate with icons; the whole route with the position marker top right and a close-up map that moves with the runner below it.

Positions and sizes are written for a 1920 x 1080 frame and scaled to the film (so 4K is drawn at 4K, not enlarged); each element keeps its distance from the edges it is anchored to, so a
frame of another shape still has everything in its corner. race.json `overlay` changes it:

  {"enabled": true, "style": "tf-outdoors", "elements": ["clock", "distance", ...], "scale": 1.0, "map_opacity": 0.6, "local_zoom": 14,
   "font": null, "label_font": null, "layout": {"pace": {"y": 860}, "local_map": {"zoom": 15}}}

`elements` picks and orders what is shown (any of ELEMENTS); `layout` overrides any field of an element; `font`/`label_font` are paths to other TTF/OTF files."""
import datetime as dt, json, math, os
from zoneinfo import ZoneInfo
import numpy as np
from strata360.overlay import draw as D
from strata360.overlay.tiles import Tiles, STYLES, world

REF_W, REF_H = 1920, 1080
ELEMENTS = {   # reference positions on a 1920 x 1080 frame; h/v: the edges the element keeps its distance from
    'clock': dict(kind='clock', x=200, y=24),
    'distance': dict(kind='big', x=150, y=124, metric='dist', label='km'),
    'pace': dict(kind='big', x=150, y=875, v='bottom', metric='pace', label='min/km'),
    'altitude': dict(kind='stat', x=16, y=980, v='bottom', icon='mountain', metric='alt', label='ALT (m)'),
    'slope': dict(kind='stat', x=220, y=980, v='bottom', icon='slope', metric='slope', label='SLOPE (%)'),
    'heart_rate': dict(kind='stat', x=1900, y=980, h='right', v='bottom', icon='heart', metric='hr', label='BPM', align='right'),
    'route_map': dict(kind='route_map', x=1644, y=24, h='right', size=256, radius=35),
    'local_map': dict(kind='local_map', x=1644, y=304, h='right', size=256, radius=35, outline=(255, 0, 0)),
    'credit': dict(kind='credit', x=1900, y=566, h='right', size=11),
}
DEFAULTS = dict(enabled=True, style='tf-outdoors', elements=list(ELEMENTS), scale=1.0, map_opacity=0.6, local_zoom=14, font=None, label_font=None, layout={})
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
        self.W, self.H = size; self.s = min(self.W / REF_W, self.H / REF_H) * float(st['scale']); self.series, self.st, self.tz, self._tiles = series, st, ZoneInfo(tz), tiles
        self.vfont, self.lfont = st.get('font') or D.VALUE_FONT, st.get('label_font') or st.get('font') or D.LABEL_FONT; self._text = {}

    @property
    def tiles(self):
        if self._tiles is None: self._tiles = Tiles(self.st['style'])
        return self._tiles

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


class RouteMap:
    """The whole route on its map, the position marker moving along it."""
    def __init__(self, c, el): self.c, self.el = c, el; self.base = None

    def _build(self):
        c, e = self.c, self.el; S = int(round(e['size'] * c.s)); wx, wy = world(c.series.route_lat, c.series.route_lon)
        span = max(np.ptp(wx), np.ptp(wy), 1e-9); self.k = S * 0.86 / span; self.cx, self.cy = (wx.min() + wx.max()) / 2, (wy.min() + wy.max()) / 2; self.S = S
        pic = np.asarray(c.tiles.picture(self.cx, self.cy, self.k, S, S)).copy()
        D.route_line(pic, (wx - self.cx) * self.k + S / 2, (wy - self.cy) * self.k + S / 2, width=3 * c.s)
        self.base = D.framed(pic, e['radius'] * c.s, c.st['map_opacity'], outline=e.get('outline', (0, 0, 0)), outline_w=1.5 * c.s); self.dot = D.marker(6 * c.s)

    def patches(self, t, v):
        if self.base is None: self._build()
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); wx, wy = world(*self.c.series.position(t))
        u, w = (wx - self.cx) * self.k + self.S / 2, (wy - self.cy) * self.k + self.S / 2; r = self.dot.shape[0] / 2
        return [(X, Y, self.base), (X + u - r, Y + w - r, self.dot)]


class LocalMap:
    """A close-up map that moves with the runner (marker in the middle), with the route drawn on it. The map around the position is fetched in pieces three times the map's size and reused
    while the position stays inside (a few are kept, so a dissolve between two places does not redraw every frame)."""
    KEEP = 4

    def __init__(self, c, el):
        self.c, self.el = c, el; self.S = int(round(el['size'] * c.s)); self.k = 2.0 ** float(el.get('zoom', c.st['local_zoom'])) * c.s; self.B = 3 * self.S; self.backs = []; self.dot = D.marker(6 * c.s); self.last = None
        self.rw = world(c.series.route_lat, c.series.route_lon)

    def _back(self, wx, wy):
        lim = (self.B - self.S) / 2 - 1
        for b in self.backs:
            if abs(wx - b[0]) * self.k <= lim and abs(wy - b[1]) * self.k <= lim: return b
        pic = np.asarray(self.c.tiles.picture(wx, wy, self.k, self.B, self.B)).copy()
        D.route_line(pic, (self.rw[0] - wx) * self.k + self.B / 2, (self.rw[1] - wy) * self.k + self.B / 2, width=3 * self.c.s)
        b = (wx, wy, pic, len(self.backs) and self.backs[-1][3] + 1 or 1); self.backs = (self.backs + [b])[-self.KEEP:]; return b

    def patches(self, t, v):
        wx, wy = world(*self.c.series.position(t)); b = self._back(wx, wy); S = self.S
        u0, v0 = int(round((wx - b[0]) * self.k + (self.B - S) / 2)), int(round((wy - b[1]) * self.k + (self.B - S) / 2))
        if self.last is None or self.last[0] != (b[3], u0, v0):
            self.last = ((b[3], u0, v0), D.framed(np.ascontiguousarray(b[2][v0:v0 + S, u0:u0 + S]), self.el['radius'] * self.c.s, self.c.st['map_opacity'], outline=self.el.get('outline'), outline_w=2 * self.c.s))
        X, Y = self.c.at(self.el, self.el['x'], self.el['y']); r = self.dot.shape[0] / 2
        return [(X, Y, self.last[1]), (X + S / 2 - r, Y + S / 2 - r, self.dot)]


class Credit:
    """The map's credit line (tile services ask for it where their maps are shown)."""
    def __init__(self, c, el): self.c, self.el = c, el

    def patches(self, t, v):
        return [self.c.text(self.el, self.el['x'], self.el['y'], STYLES[self.c.st['style']]['credit'], self.el['size'], label=True, align='right')]


KINDS = dict(clock=Clock, big=Big, stat=Stat, route_map=RouteMap, local_map=LocalMap, credit=Credit)


def settings(st=None):
    """race.json `overlay` merged over DEFAULTS (unknown element names are an error, so a typo does not silently drop something)."""
    out = {**DEFAULTS, **(st or {})}; bad = [e for e in out['elements'] if e not in ELEMENTS] + [e for e in out['layout'] if e not in ELEMENTS]
    if bad: raise ValueError(f'unknown overlay element(s) {", ".join(bad)}: one of {", ".join(ELEMENTS)}')
    return out


class Overlay:
    """overlay.apply(frame, t) draws the overlay for UTC seconds t onto an RGB frame (uint8 or uint16) in place. `tiles` defaults to the configured style (fetched and cached on first use)."""

    def __init__(self, series, size, st=None, tz='Europe/Brussels', tiles=None):
        self.st = settings(st); self.c = _Ctx(series, size, self.st, tz, tiles)
        self.widgets = [KINDS[ELEMENTS[n]['kind']](self.c, {**ELEMENTS[n], **self.st['layout'].get(n, {})}) for n in self.st['elements']]
        if any(isinstance(w, (RouteMap, LocalMap)) for w in self.widgets): self.c.tiles                          # a missing map key is reported now, not hours into a render

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
