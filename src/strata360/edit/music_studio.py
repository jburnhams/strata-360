"""What the Music studio screen shows (docs/ai-music.md): the track's grid and bars, a preview of the build for a length (no audio made: the re-sequencing plan, the intensity levels, the layer gains), and the built track's score.

  state(rd, rel)  -> dict(grid=summary|None, built=score|None, stems=bool)
  preview(rd, rel, length_s, preset='arc', levels=None, windows=()) -> dict(bars, bar_s, levels, gains, plan, sim, energy, windows) for the screen; needs the grid (music_build.grid)
  presets: flat (the middle level), arc (full at the start and finish, a slow wave between), build (rising to the finish), quiet (sparse throughout)"""
import json, os
import numpy as np
from strata360.edit import intensity, layers, music_build as MB, remix

PRESETS = ('flat', 'arc', 'build', 'quiet', 'manual')


def levels_for(preset, n, levels=None):
    if preset == 'manual' and levels is not None:
        lv = np.asarray(levels, float); return lv if len(lv) == n else np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(lv)), lv)
    if preset == 'quiet': return np.full(n, intensity.LEVELS[0])
    if preset == 'build': raw = np.linspace(0.1, 1.0, n)
    elif preset == 'arc':
        x = np.linspace(0, 1, n); raw = 0.35 + 0.2 * np.sin(x * 6 * np.pi); raw[:max(4, n // 12)] = 1.0; raw[-max(4, n // 12):] = 1.0
    else: return np.full(n, intensity.LEVELS[1])
    return np.array(intensity.curve(n, 1.0, [dict(t=np.arange(n) + 0.5, v=raw)])['levels'])


def grid_summary(g):
    return dict(bpm=g['bpm'], key=g['key'], bars=len(g['downbeats']) - 1, duration_s=g['duration_s'], bar_s=round((g['downbeats'][-1] - g['downbeats'][0]) / (len(g['downbeats']) - 1), 3), downbeats=g['downbeats'], energy=g['energy'])


def read_grid(rd, rel):
    try:
        g = json.load(open(os.path.join(rd, 'music', 'grid.json')))
        return g if g.get('version') == 2 and g.get('file') == rel and g.get('sig') == MB.MU._sig(os.path.join(rd, rel)) else None
    except (OSError, ValueError): return None


def read_built(rd):
    try: return json.load(open(os.path.join(rd, 'music', 'built.json')))
    except (OSError, ValueError): return None


def state(rd, rel):
    g = read_grid(rd, rel); return dict(grid=grid_summary(g) if g else None, built=read_built(rd), stems=os.path.exists(os.path.join(rd, 'music', 'stems', 'stems.json')))


def windows_to_bars(spans, bar_s, n):
    """Film-second spans [(t0, t1)] -> whole film bars [(first, end)] inside 0..n."""
    out = [(max(0, int(t0 // bar_s)), min(n, int(-(-t1 // bar_s)))) for t0, t1 in spans if t1 > t0]; return [w for w in out if w[0] < w[1]]


def preview(rd, rel, length_s, preset='arc', levels=None, windows=()):
    g = read_grid(rd, rel)
    if not g: raise RuntimeError('analyse the track first')
    T, bar_s = MB.bar_count(g, length_s); lv = levels_for(preset, T, levels); sim = np.array(g['sim']); en = np.asarray(g['energy'], float)
    plan = remix.plan(sim, T, levels=lv, energy=en); gains = layers.open_vocals(layers.layer_gains(lv), windows)
    return dict(bars=T, bar_s=round(bar_s, 3), length_s=round(T * bar_s, 2), levels=[round(float(v), 3) for v in lv], windows=[list(w) for w in windows], plan=dict(bars=plan['bars'], runs=[list(r) for r in plan['runs']], joins=plan['joins'], worst_join=plan['worst_join']),
                gains={n: [round(float(v), 3) for v in a] for n, a in gains.items()}, sim=g['sim'], energy=g['energy'])
