"""Build music for the film from the uploaded track (Milestone G0): the track's own bars re-sequenced to the film's length (edit/remix.py), its stems layered to follow an intensity curve (edit/layers.py), its vocals let through only in given windows.

  grid(rd, rel) -> dict(bpm, downbeats, beats, key ...) of the track, kept in music/grid.json for this file's signature
  build(rd, rel, length_s, levels=None, windows=(), ...) -> the score dict, and music/built.flac + music/built.json (the score: source bars, runs, joins, the film's downbeats, gains, the vocal windows, the stray-vocal check)
  `levels` is a 0..1 level per film bar (edit/intensity.py); with none, every bar is the middle level. `windows` are film bars [(first, end)] where the original's vocals play.
  With fidelity below 1 the score (edit/score.py) marks sections to generate; with a `style` and a `generator` (audio/music_gen.Generator, G3) they are made, fitted to the grid and spliced in (edit/music_fit.py, G5), else they stay the track's own bars and say why. Every build is cut to the film's length and checked: the downbeats against the grid, the stray singing, singing in a generated take.
built.json is the record; project.use_built makes it the film's music."""
import json, os
import numpy as np
from strata360.edit import music as MU, remix, layers, stems as ST, score as SC, music_fit as MF
from strata360.audio import music_gen as MG

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


def build(rd, rel, length_s, levels=None, windows=(), spans=None, separator=None, decode=None, write=None, read=None, ending_bars=2, keep_intro=True, ending='original', fade_s=3.0, pins=(),
          fidelity=1.0, section_pins=None, style=None, generator=None, takes=None, stretch=None, vocals_of=None, fps=25.0, log=print):
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
    old = read_built(rd); sp = SC.plan(lv if lv is not None else np.full(T, 0.5), bar_s, g['energy'], fidelity, sung=[dict(first=a, end=b) for a, b in windows], pins=section_pins)
    y, made, runs = generate(y, sr, marks, sp, plan['bars'], lv if lv is not None else np.full(T, 0.5), st, db, g, bar_s, P, ending_bars, windows, rd, style, generator, takes or {}, stretch, vocals_of, log)       # generator(sr) -> the generator for this rate (audio/music_gen.Generator)
    y, fit = MF.fit_length(y, sr, length_s, fade_s, fps)
    try:
        mk = [m for m in marks if m < len(y) / sr - 0.05]; dbe = list(db) + [end_s or g.get('duration_s')]
        gc = MF.grid_check(y, sr, mk, ref=(decode or MU.decode)(os.path.join(rd, rel)), ref_sr=MU.SR, ref_marks=[dbe[b] for b in plan['bars'][:len(mk)]], beat_s=bar_s / 4, end_s=len(y) / sr, skip={k for p in made if not p.get('kept_original') for k in range(p['first'], p['end'])})     # each bar lined up with its bar of the original; new bars were judged as takes
    except (RuntimeError, ValueError) as e: gc = dict(ok=None, why=str(e))
    out = os.path.join(rd, 'music', 'built.flac'); (write or ST.ffmpeg_write)(out, np.clip(y, -1, 1), sr)
    stray = None if leak == float('-inf') else leak; sung_gen = [p for p in made if p.get('singing_db') is not None and p['singing_db'] > MF_SINGING_DB]
    check = dict(grid=gc, length=fit, stray_vocal_db=stray, singing_in_generated=[p['first'] for p in sung_gen], failed=[p['first'] for p in made if not p['ok']])
    check['ok'] = bool(gc.get('ok') is not False and fit['ok'] and (stray is None or stray < STRAY_DB) and not sung_gen and not check['failed'])
    score = dict(version=SCORE_VERSION, source='built', file='music/built.flac', of=rel, length_s=round(len(y) / sr, 3), bpm=g['bpm'], key=g['key'], bars=plan['bars'], runs=plan['runs'], joins=plan['joins'], worst_join=plan['worst_join'], intro_bars=P, ending=ending, pins=[list(p) for p in pins], as_is_bars=None if natural is None else int(natural.sum()),
                 downbeats=marks, levels=None if lv is None else [round(float(v), 3) for v in lv], windows=[list(w) for w in windows], asked_windows=asked, partial_windows=dropped, stray_vocal_db=stray,       # None: silent (JSON has no -infinity)
                 fidelity=sp['fidelity'], sections=sp['sections'], sung=sp['sung'], share_original=sp['share_original'], unreachable=sp['unreachable'], section_pins={str(k): v for k, v in (section_pins or {}).items()}, style=style,
                 generated=made, remade=[s['first'] for s in MF.stale((old or {}).get('sections'), sp['sections']) if s['source'] == 'generate'], gen_runs=runs, check=check)
    json.dump(score, open(os.path.join(rd, 'music', 'built.json'), 'w'), indent=1); return score


STRAY_DB = -30.0                       # the vocal stem outside the sung moments, below its loudest bar: anything louder is heard
MF_SINGING_DB = -20.0                  # a generated take whose separated vocals are this loud against it has singing in it


def read_built(rd):
    try: return json.load(open(os.path.join(rd, 'music', 'built.json')))
    except (OSError, ValueError): return None


def pieces(sections, protected, min_bars=2):
    """The bars to generate: each 'generate' section split around the protected bars (the opening, the ending, the sung moments, which stay the original's), runs of at least min_bars. [(section, first, end)]."""
    out = []
    for s in sections:
        if s['source'] != 'generate': continue
        a = s['first']
        while a < s['end']:
            while a < s['end'] and protected[a]: a += 1
            b = a
            while b < s['end'] and not protected[b]: b += 1
            if b - a >= min_bars: out.append((s, a, b))
            a = b
    return out


def generate(y, sr, marks, sp, bars, levels, st, db, g, bar_s, intro, ending_bars, windows, rd, style, generator, takes, stretch, vocals_of, log):
    """The score's generated sections made (G3), fitted to the grid, matched in loudness to the bars around them and spliced in on their downbeats (G5). Without a generator or a style, they stay the original's bars and each says why. Returns (samples, [a report per piece], [the generator's runs: device, load time, each take's time and peak memory])."""
    T = len(bars); protected = np.zeros(T, bool); protected[:intro] = True; protected[max(0, T - ending_bars):] = True
    for a, b in windows: protected[max(0, a):max(0, b)] = True
    todo = pieces(sp['sections'], protected)
    if not todo: return y, [], []
    if not style or not generator:
        why = 'no style given for the generated sections (the genre, e.g. "rap rock, distorted guitar riff, live drums")' if not style else 'no generator (install ACE-Step 1.5)'
        return y, [dict(first=a, end=b, section=s['first'], ok=False, kept_original=True, why=why) for s, a, b in todo], []
    edge = list(marks) + [len(y) / sr]; t = lambda k: edge[min(k, len(edge) - 1)]; inst = sum(st[n] for n in ('drums', 'bass', 'other')); key_name = f"{g['key']['name']}"
    items = []
    for s, a, b in todo:
        c0, c1 = max(0, a - MG.CONTEXT_BARS), min(T, b + MG.CONTEXT_BARS); sec = dict(s, first=a, end=b, key=f"{s['key']}-{a}-{b}")
        spec = MG.spec(sec, bar_s, g['bpm'], key_name, style, [int(v) for v in bars[c0:c1]] + [round(float(v), 2) for v in levels[c0:c1]]); spec['take'] = takes.get(spec['key'])
        mid = (db[bars[a]] + db[min(bars[b - 1] + 1, len(db) - 1)]) / 2; r0 = max(0, int((mid - MG.REF_S / 2) * sr)); ref = inst[r0:r0 + int(MG.REF_S * sr)]
        if spec['mode'] == 'repaint': inp = dict(src=y[int(t(c0) * sr):int(t(c1) * sr)], r0=t(a) - t(c0), r1=t(b) - t(c0), ref=ref)
        else: inp = dict(src=y[int(t(a) * sr):int(t(b) * sr)], ref=ref if spec['strength'] > 0 else None)
        inp['marks'] = [t(k) - t(c0 if spec['mode'] == 'repaint' else a) for k in range(a, b + 1)]; items.append((spec, inp))                     # on the timeline of src: a repaint's take is its whole context
    generator = generator(sr); note = getattr(generator, 'note', None); seeds = [s['take'] if s.get('take') is not None else 0 for s, _ in items]
    try: res = MF.repair(items, generator, sr, stretch=stretch, seeds=seeds, note=note)
    except RuntimeError as e:
        log(f'generation failed: {e}'); return y, [dict(first=s['first'], end=s['end'], section=s.get('section_key'), key=s['key'], ok=False, kept_original=True, why=str(e)[:300]) for s, _ in items], []
    made = []
    for (spec, inp), (x, rep) in zip(items, res):
        a, b = spec['first'], spec['end']; d = dict(first=a, end=b, key=spec['key'], mode=spec['mode'], strength=spec['strength'], caption=spec['caption'], ok=rep['ok'], seed=rep['seed'], takes=rep['takes'], chosen=spec.get('take'))
        if x is None: d.update(kept_original=True, why='no take kept time with the grid' if spec.get('take') is None else f"take {spec['take']} does not keep time"); made.append(d); continue
        around = np.concatenate([y[int(t(max(0, a - 2)) * sr):int(t(a) * sr)], y[int(t(b) * sr):int(t(min(T, b + 2)) * sr)]]); before = MF.rms(x); x = MF.gain_match(x, around); d['gain'] = round(MF.rms(x) / before, 2) if before > 0 else None
        if vocals_of:
            try: d['singing_db'] = MF.singing_db(x, vocals_of(x, sr))
            except RuntimeError as e: d['singing_db'] = None; d['why'] = f'vocal check failed: {e}'
            if d.get('singing_db') == float('-inf'): d['singing_db'] = None
        y = MF.splice(y, sr, x, t(a), bar_s / 4); made.append(d)
    return y, made, getattr(generator, 'runs', [])


def bar_energy(x, downbeats):
    """Loudness of each source bar (between consecutive downbeats), scaled 0..1 as music.analyse does for its sections."""
    e = np.array([np.sqrt(np.mean(x[int(a * MU.SR):max(int(b * MU.SR), int(a * MU.SR) + 1)].astype(np.float64) ** 2)) for a, b in zip(downbeats[:-1], downbeats[1:])]); lo, hi = np.percentile(e, 10), np.percentile(e, 95)
    return [round(float(v), 3) for v in np.clip((e - lo) / max(hi - lo, 1e-9), 0, 1)]
