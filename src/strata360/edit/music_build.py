"""Build music for the film from the uploaded track (Milestone G0): the track's own bars re-sequenced to the film's length (edit/remix.py), its stems layered to follow an intensity curve (edit/layers.py), its vocals let through only in given windows.

  grid(rd, rel) -> dict(bpm, downbeats, beats, key ...) of the track, kept in music/grid.json for this file's signature
  build(rd, rel, length_s, levels=None, windows=(), ...) -> the score dict, and music/built.flac + music/built.json (the score: source bars, runs, joins, the film's downbeats, gains, the vocal windows, the stray-vocal check)
  `levels` is a 0..1 level per film bar (edit/intensity.py); with none, every bar is the middle level. `windows` are film bars [(first, end)] where the original's vocals play.
Not yet in music.json (that wiring is the score step, G2): built.json is its own record."""
import json, os
import numpy as np
from strata360.edit import music as MU, remix, layers, stems as ST

SCORE_VERSION = 1


def grid(rd, rel, decode=None):
    p = os.path.join(rd, rel); sig = MU._sig(p); gp = os.path.join(rd, 'music', 'grid.json')
    try:
        g = json.load(open(gp))
        if g.get('version') == 2 and g.get('sig') == sig and g.get('file') == rel: return g
    except (OSError, ValueError): pass
    x = (decode or MU.decode)(p); S = MU.spectrogram(x); g = MU.beat_grid(x, S=S); t, mode, name, conf = MU.estimate_key(MU.chroma(S))
    g['energy'] = bar_energy(x, g['downbeats']); g['sim'] = [[round(float(v), 2) for v in r] for r in MU.bar_similarity(MU.bar_features(x, g['downbeats'], S=S))]; g.update(version=2, file=rel, sig=sig, key=dict(tonic=int(t), mode=mode, name=name, confidence=conf), duration_s=round(len(x) / MU.SR, 3)); os.makedirs(os.path.dirname(gp), exist_ok=True); json.dump(g, open(gp, 'w')); return g


def bar_count(g, length_s):
    d = g['downbeats']; bar_s = (d[-1] - d[0]) / (len(d) - 1); return max(1, int(round(length_s / bar_s))), bar_s


def build(rd, rel, length_s, levels=None, windows=(), separator=None, decode=None, write=None, read=None, ending_bars=2):
    """levels: a 0..1 level per film bar (resampled if the count differs); windows: film bars [(first, end)]."""
    g = grid(rd, rel, decode); db = g['downbeats']; T, bar_s = bar_count(g, length_s); sim = np.array(g['sim'])
    lv = None if levels is None else np.asarray(levels, float)
    if lv is not None and len(lv) != T: lv = np.interp(np.linspace(0, 1, T), np.linspace(0, 1, len(lv)), lv)
    en = np.asarray(g['energy'], float) if lv is not None else None
    plan = remix.plan(sim, T, ending_bars=ending_bars, levels=lv, energy=en); gains = layers.layer_gains(lv if lv is not None else np.full(T, 0.5)); gains = layers.open_vocals(gains, windows)
    st, sr = ST.stems_for(rd, rel, separator, write, read); y, marks = layers.mix(st, sr, db, plan['bars'], gains, end_s=g.get('duration_s'))
    leak = layers.stray_vocal_db(layers.mix(dict(vocals=st['vocals']), sr, db, plan['bars'], gains, end_s=g.get('duration_s'))[0], sr, marks, windows)     # the vocal stem as it is in the mix: silent outside the windows
    out = os.path.join(rd, 'music', 'built.flac'); (write or ST.ffmpeg_write)(out, np.clip(y, -1, 1), sr)
    score = dict(version=SCORE_VERSION, source='built', file='music/built.flac', of=rel, length_s=round(len(y) / sr, 3), bpm=g['bpm'], key=g['key'], bars=plan['bars'], runs=plan['runs'], joins=plan['joins'], worst_join=plan['worst_join'],
                 downbeats=marks, levels=None if lv is None else [round(float(v), 3) for v in lv], windows=[list(w) for w in windows], stray_vocal_db=None if leak == float('-inf') else leak)       # None: silent (JSON has no -infinity)
    json.dump(score, open(os.path.join(rd, 'music', 'built.json'), 'w'), indent=1); return score


def bar_energy(x, downbeats):
    """Loudness of each source bar (between consecutive downbeats), scaled 0..1 as music.analyse does for its sections."""
    e = np.array([np.sqrt(np.mean(x[int(a * MU.SR):max(int(b * MU.SR), int(a * MU.SR) + 1)].astype(np.float64) ** 2)) for a, b in zip(downbeats[:-1], downbeats[1:])]); lo, hi = np.percentile(e, 10), np.percentile(e, 95)
    return [round(float(v), 3) for v in np.clip((e - lo) / max(hi - lo, 1e-9), 0, 1)]
