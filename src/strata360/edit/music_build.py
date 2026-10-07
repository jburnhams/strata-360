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
        if g.get('version') == 3 and g.get('sig') == sig and g.get('file') == rel: return g
    except (OSError, ValueError): pass
    x = (decode or MU.decode)(p); S = MU.spectrogram(x); g = MU.beat_grid(x, S=S); t, mode, name, conf = MU.estimate_key(MU.chroma(S))
    g['energy'] = bar_energy(x, g['downbeats']); g['sim'] = [[round(float(v), 2) for v in r] for r in MU.bar_similarity(MU.bar_features(x, g['downbeats'], S=S))]; g.update(version=3, file=rel, sig=sig, key=dict(tonic=int(t), mode=mode, name=name, confidence=conf), duration_s=round(len(x) / MU.SR, 3)); os.makedirs(os.path.dirname(gp), exist_ok=True); json.dump(g, open(gp, 'w')); return g


def intro_bars(energy, high=0.8, low=0.45, back=0.5):
    """How many bars at the start make the iconic opening: the first build to a peak (a bar at `high` or more) and the first break after it (energy under `low`), up to the bar where the energy returns (`back`). 0 when the track has no such build and break."""
    e = list(energy); p = next((i for i, v in enumerate(e) if v >= high), None)
    if p is None: return 0
    b = next((i for i in range(p + 1, len(e)) if e[i] < low), None)
    if b is None: return 0
    return next((i for i in range(b + 1, len(e)) if e[i] >= back), 0)


def quick_end(energy, loud=0.75):
    """The number of the track's bars to keep for a quick ending: up to and including its last loud bar (the track's own ending is a long fade of quiet bars). 0 when no bar is loud."""
    return next((i + 1 for i in range(len(energy) - 1, -1, -1) if energy[i] >= loud), 0)


def bar_count(g, length_s):
    d = g['downbeats']; bar_s = (d[-1] - d[0]) / (len(d) - 1); return max(1, int(round(length_s / bar_s))), bar_s


def build(rd, rel, length_s, levels=None, windows=(), spans=None, separator=None, decode=None, write=None, read=None, ending_bars=2, keep_intro=True, ending='original', fade_s=3.0, pins=()):
    """pins: [(film_bar, source_bar, n_bars)] (music_studio.sing_pins): those source bars play at those film bars, and the vocals are open over them (a sung phrase placed where the script wants it); ending: 'original' plays the track's own last bars with their long fade; 'quick' ends on the track's last loud bar and fades out over fade_s seconds (quick_end); keep_intro: the track's own opening (its first build and break, intro_bars) plays exactly as it is, every stem on, and the re-sequencing starts after it, when the film is long enough to hold it and the ending; levels: a 0..1 level per film bar (resampled if the count differs); windows: film bars [(first, end)]; spans: where the original is sung, in its seconds (lyrics.view's vocal_spans): each window grows to hold every sung stretch it touches whole, or is dropped when the film does not play that stretch in one piece."""
    g = grid(rd, rel, decode); db = g['downbeats']; T, bar_s = bar_count(g, length_s); sim = np.array(g['sim']); end_s = g.get('duration_s'); k = quick_end(g['energy'])
    if ending == 'quick' and k > 1 and k < len(db): sim = sim[:k, :k]; end_s = db[k]                           # the track is cut after its last loud bar
    else: ending = 'original'
    lv = None if levels is None else np.asarray(levels, float)
    if lv is not None and len(lv) != T: lv = np.interp(np.linspace(0, 1, T), np.linspace(0, 1, len(lv)), lv)
    en = np.asarray(g['energy'], float) if lv is not None else None
    P = intro_bars(g['energy']) if keep_intro and T >= intro_bars(g['energy']) + ending_bars + 1 and intro_bars(g['energy']) < len(sim) - ending_bars else 0; plan = remix.plan(sim, T, ending_bars=ending_bars, levels=lv, energy=en, prefix=P, pins=pins); windows = layers.merge_windows(list(windows) + [(fb, fb + n) for fb, _, n in pins]); asked = [list(w) for w in windows]; dropped = []
    if spans is not None:
        windows, dropped = layers.snap_windows(windows, plan['bars'], db, spans)
        if dropped:                                                                                          # plan again with the sung stretches those windows touch held whole
            hold = layers.stretches_touched([d['window'] for d in dropped], plan['bars'], db, spans)
            plan = remix.plan(sim, T, ending_bars=ending_bars, levels=lv, energy=en, hold=hold, prefix=P, pins=pins); windows, dropped = layers.snap_windows(asked, plan['bars'], db, spans)
        windows = layers.merge_windows(list(windows) + [tuple(d['window']) for d in dropped])                  # better some singing than none: what cannot be made whole stays as asked, and is reported as partial
    gains = layers.layer_gains(lv if lv is not None else np.full(T, 0.5))
    natural = None
    if lv is not None:                                                                                    # a bar already as quiet as asked is the track's own: left alone, not thinned by turning stems down
        natural = layers.as_is_bars(lv, plan['bars'], g['energy']); gains = layers.keep_as_is(gains, natural)
    if P:                                                                                                  # the opening as the track has it: every stem full, its vocals too
        for n in ('drums', 'bass', 'other'): gains[n][:P] = 1.0
        windows = layers.merge_windows(list(windows) + [(0, P)])
    gains = layers.open_vocals(gains, windows)
    st, sr = ST.stems_for(rd, rel, separator, write, read); y, marks = layers.mix(st, sr, db, plan['bars'], gains, end_s=end_s)
    if ending == 'quick': n = min(len(y), int(fade_s * sr)); y[len(y) - n:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, n)))[:, None].astype(y.dtype)       # a short fade-out on the last bar
    leak = layers.stray_vocal_db(layers.mix(dict(vocals=st['vocals']), sr, db, plan['bars'], gains, end_s=end_s)[0], sr, marks, windows)     # the vocal stem as it is in the mix: silent outside the windows
    out = os.path.join(rd, 'music', 'built.flac'); (write or ST.ffmpeg_write)(out, np.clip(y, -1, 1), sr)
    score = dict(version=SCORE_VERSION, source='built', file='music/built.flac', of=rel, length_s=round(len(y) / sr, 3), bpm=g['bpm'], key=g['key'], bars=plan['bars'], runs=plan['runs'], joins=plan['joins'], worst_join=plan['worst_join'], intro_bars=P, ending=ending, pins=[list(p) for p in pins], as_is_bars=None if natural is None else int(natural.sum()),
                 downbeats=marks, levels=None if lv is None else [round(float(v), 3) for v in lv], windows=[list(w) for w in windows], asked_windows=asked, partial_windows=dropped, stray_vocal_db=None if leak == float('-inf') else leak)       # None: silent (JSON has no -infinity)
    json.dump(score, open(os.path.join(rd, 'music', 'built.json'), 'w'), indent=1); return score


def bar_energy(x, downbeats):
    """Loudness of each source bar (between consecutive downbeats), scaled 0..1 as music.analyse does for its sections."""
    e = np.array([np.sqrt(np.mean(x[int(a * MU.SR):max(int(b * MU.SR), int(a * MU.SR) + 1)].astype(np.float64) ** 2)) for a, b in zip(downbeats[:-1], downbeats[1:])]); lo, hi = np.percentile(e, 10), np.percentile(e, 95)
    return [round(float(v), 3) for v in np.clip((e - lo) / max(hi - lo, 1e-9), 0, 1)]
