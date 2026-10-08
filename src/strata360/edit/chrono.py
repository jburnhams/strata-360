"""Chronological film planner (README 16.2b): the film follows the day, the optimiser decides how each clip is edited.

Rules
  * the film is in **time order**: clips in the order they were shot, and inside a clip its segments in time order;
  * **every clip contributes**: each source clip gets at least one segment (a clip with no usable moment contributes its best unusable stretch, flagged), and a long clip may contribute
    several segments, as many as its share of the film justifies;
  * a clip's candidates OVERLAP (they are different ways to see the same footage: the whole stretch, its best parts, you talking, other people in view ...); segments of one clip never overlap, so
    the planner keeps an occupancy map of each clip and a window may only use footage nobody else has taken;
  * segments of one clip **never overlap**; several adjacent selections from one clip are welcome (they allow a different view, technique or cut for each);
  * the optimiser still chooses how much of the film each clip gets, which moments, the segment lengths, and the technique of every segment, with the same variety rules as before
    (repeats, hero effects, cooldowns, shares), beat-aligned to the music and filling it exactly.

Three steps: (1) split the beats between the clips (concave value, so every clip gets something and long or good clips get more); (2) cut each clip's share into non-overlapping windows
inside its usable stretches; (3) beam search over the ordered windows for the techniques, seeded so a seed reproduces a plan exactly."""
import heapq, math
from dataclasses import dataclass, field
import numpy as np
from strata360.edit import optimise as O, pans as PN

MIN_SEG_S = 2.0          # shortest window (the shortest everyday technique needs 2 s; whip pans are transitions, not windows)
MAX_SEG_S = 8.0          # longest window: longer ones are split into adjacent windows, each with its own view
MAX_CLIP_SHARE = 0.25    # no clip takes more than this share of the film (unless it is the only way to fill it)


@dataclass
class Settings:
    seed: int = 0
    beam: int = 30
    temperature: float = 0.15
    w_quality: float = 1.0; w_fit: float = 0.8; w_dur: float = 0.5; w_energy: float = 0.6; w_first: float = 0.4; w_glide: float = 0.3
    w_camlist: float = 0.5                               # a technique that lies inside a good camera of its kind (the clip's camera list, edit/cameras.py) is favoured, per second of the window
    w_cam: float = 0.6                                   # a point camera you set up is favoured where a window lies inside it (per second of the window, like the other scores)
    w_establish: float = 0.6; pen_talk: float = 0.3          # the talking shot (dialogue_hold) is favoured where someone starts speaking in a clip, to show who it is, and is a little discouraged after that so the other views of you are cut in
    dur_power: float = 0.6
    pen_recent: float = 0.8; recent_decay: float = 0.7; pen_family: float = 0.25; pen_scale: float = 0.15; pen_share: float = 6.0
    hero_share: float = 0.2
    max_clip_share: float = MAX_CLIP_SHARE
    min_seg_s: float = MIN_SEG_S
    dialogue_share: float = 0.15
    bans_techs: frozenset = frozenset()
    share_caps: dict = field(default_factory=lambda: {'dialogue_hold': 0.12})
    tech_bias: dict = field(default_factory=lambda: {'selfie_hold': 0.25})        # a little extra score for a technique (per second of its window, as the other scores): the mid view of you is the one to reach for
    # the user's overrides (project.json): windows are identified by `wid` = "<clip>@<start seconds in the clip, 2 decimals>"
    locked: tuple = ()                                   # [{wid, clip, start_s, beats, cand_id, tech}]: kept exactly (clip window, length and technique)
    tech_force: dict = field(default_factory=dict)       # wid -> technique id that window must use (if feasible)
    prefer: dict = field(default_factory=dict)           # wid -> technique chosen last time: kept unless something better is worth it (keeps a re-plan from reshuffling)
    w_keep: float = 1.5
    bans_cands: frozenset = frozenset()                  # stretches (candidate ids) not to use
    clip_weight: dict = field(default_factory=dict)      # clip id -> factor on its share of the film (2 = more, 0.5 = less)


@dataclass
class Seg:
    start: int               # in beats from the start of the film
    beats: int
    cand: object             # O.Candidate of the usable stretch the window lies in (id, clip, features, ...)
    tech: object
    in_s: float              # offset of the window inside its stretch (seconds)
    clip_index: int
    clip_start_s: float      # the window's start inside the clip (clip-relative seconds)
    variant_seed: int = 0
    parts: dict = field(default_factory=dict)
    forced: bool = False     # the clip had no usable moment; this is its best unusable stretch

    @property
    def dur_s(self): return self.beats * self._beat_s
    _beat_s: float = 0.5


@dataclass
class Window:
    clip_index: int; cand: object; in_s: float; beats: int; q: float; forced: bool = False
    fixed: bool = False; tech_id: str = None; speech: bool = False     # a locked window: its technique is fixed too

    @property
    def abs_start(self): return self.cand.start_s + self.in_s


def wid_of(clip, start_s): return f'{clip}@{start_s:.2f}'


def clip_candidates(clip):
    """O.Candidate list for one clip dict {id, candidates: [...], unusable: [...]}; a clip with none gets its best unusable stretch (forced)."""
    out = []
    for c in clip.get('candidates') or []:
        out.append(O.Candidate(id=c['id'], clip=c['clip'], quality=c['quality'], energy=c['energy'], min_dur=c['min_dur'], max_dur=c['max_dur'], features=dict(c['features']), group=None))
        out[-1].start_s = c['start_s']; out[-1].end_s = c['end_s']; out[-1].forced = False; out[-1].kind = c.get('kind', 'span'); out[-1].view = c.get('view', 'ahead')
    if out: return out
    un = sorted(clip.get('unusable') or [], key=lambda u: -((u['end_s'] - u['start_s']) * (0.2 + float((u.get('stats') or {}).get('score') or 0))))
    for k, u in enumerate(un[:1]):
        f = dict(steady=0.2, clear_nadir=0.5, open_ground=0.3, canopy=0.3, subject=0.2, speech=0.0, protagonist=0.0, low_obstruction=0.5, resolution=0.5)
        c = O.Candidate(id=f"{clip['id']}#forced", clip=clip['id'], quality=0.25, energy=0.5, min_dur=1.0, max_dur=u['end_s'] - u['start_s'], features=f)
        c.start_s = u['start_s']; c.end_s = u['end_s']; c.forced = True; c.kind = 'forced'; c.view = 'ahead'; out.append(c)
    return out


def snap(x, grid, up):
    return (math.ceil(x / grid - 1e-9) if up else math.floor(x / grid + 1e-9)) * grid


def subtract(cs, blocked, min_len, grid=None):
    """Stretches with the locked windows cut out: a list of derived stretches (same id and features; `orig` points to the real stretch) of at least `min_len` seconds."""
    out = []
    for c in cs:
        pieces = [(c.start_s, c.end_s)]
        for a, b in sorted(blocked):
            nxt = []
            for x, y in pieces:
                if b <= x or a >= y: nxt.append((x, y)); continue
                if a > x: nxt.append((x, a))
                if b < y: nxt.append((b, y))
            pieces = nxt
        for x, y in pieces:
            if grid: x, y = snap(x, grid, True), snap(y, grid, False)                                  # stay on the beat grid, so no fraction of a beat is ever stranded
            if y - x >= min_len - 1e-9:
                d = O.Candidate(id=c.id, clip=c.clip, quality=c.quality, energy=c.energy, min_dur=c.min_dur, max_dur=y - x, features=c.features, group=None)
                d.start_s, d.end_s, d.forced, d.orig = x, y, getattr(c, 'forced', False), getattr(c, 'orig', None) or c; d.kind = getattr(c, 'kind', 'span'); d.view = getattr(c, 'view', 'ahead'); out.append(d)
    return out


def coverage(cs, step=0.25):
    """(seconds of footage the candidates cover together, mean of the best quality available at each covered moment): overlapping candidates are one piece of footage, counted once."""
    if not cs: return 0.0, 0.0
    t0 = min(c.start_s for c in cs); t1 = max(c.end_s for c in cs); g = np.arange(t0 + step / 2, t1, step); best = np.full(len(g), -1.0)
    for c in cs: m = (g >= c.start_s) & (g < c.end_s); best[m] = np.maximum(best[m], c.quality)
    cov = best >= 0; return float(cov.sum() * step), float(best[cov].mean()) if cov.any() else 0.0


def free_parts(c, occ):
    """The parts of candidate c not taken by the (absolute-seconds) intervals in occ: [(start, end)]."""
    pieces = [(c.start_s, c.end_s)]
    for a, b in occ:
        nxt = []
        for x, y in pieces:
            if b <= x or a >= y: nxt.append((x, y)); continue
            if a > x: nxt.append((x, a))
            if b < y: nxt.append((b, y))
        pieces = nxt
    return pieces


# --------------------------------------------------------------------------------------------------------------------------------------------- 1. split the beats between clips
def allocate(clips_c, B, beat_s, st, clip_ids=None, has_lock=()):
    """Beats per clip: at least one minimum window each, at most what its usable stretches hold and its share cap; the rest by concave value (good and long clips get more, with diminishing returns)."""
    n = len(clips_c); bmin_seg = math.ceil(st.min_seg_s / beat_s - 1e-9); U = []; q = []
    for cs in clips_c:
        L, qm = coverage(cs); U.append(L); q.append(qm)
    bmax = [max(int(math.floor(U[i] / beat_s + 1e-9)), 0) for i in range(n)]; cap = int(math.ceil(st.max_clip_share * B))
    bmin = [min(bmin_seg, bmax[i]) if bmax[i] > 0 else 0 for i in range(n)]
    bmin = [0 if (i in has_lock) else b for i, b in enumerate(bmin)]                                 # a clip with a locked window already contributes
    if any(b == 0 and i not in has_lock for i, b in enumerate(bmin)): raise O.Infeasible('a clip has no stretch long enough for one segment')
    if sum(bmin) > B: raise O.Infeasible(f'too short to include something from every clip: {n} clips need at least {sum(bmin) * beat_s:.0f} s ({bmin_seg} beats each), the film is {B * beat_s:.0f} s')
    hi = [min(bmax[i], max(cap, bmin[i])) for i in range(n)]
    if sum(hi) < B: hi = list(bmax)                                                               # the share cap may be broken when it is the only way to fill the film
    if sum(hi) < B: raise O.Infeasible(f'not enough usable footage: {sum(bmax) * beat_s:.0f} s against a {B * beat_s:.0f} s film')
    b = list(bmin); ref = 4.0; w = [(0.4 + qi) * float(st.clip_weight.get(clip_ids[i] if clip_ids else None, 1.0)) for i, qi in enumerate(q)]

    def gain(i):
        return w[i] * (math.log1p((b[i] + 1) * beat_s / ref) - math.log1p(b[i] * beat_s / ref))
    heap = [(-gain(i), i) for i in range(n) if b[i] < hi[i]]; heapq.heapify(heap); left = B - sum(b)
    while left > 0 and heap:
        _, i = heapq.heappop(heap); b[i] += 1; left -= 1
        if b[i] < hi[i]: heapq.heappush(heap, (-gain(i), i))
    return b


# --------------------------------------------------------------------------------------------------------------------------------------------- 2. windows inside each clip
def cut_windows(clip_index, cs, b, beat_s, music, st, rng):
    """Non-overlapping windows for one clip: `b` beats split into parts of about the music-driven length, placed in the best usable stretches (good stretches first, several per stretch allowed,
    adjacent windows touch), then returned in time order."""
    bmin = math.ceil(st.min_seg_s / beat_s - 1e-9); bmax = int(MAX_SEG_S / beat_s + 1e-9)
    en = float(np.mean([c.energy for c in cs])); tl = O.target_len(en) / beat_s
    n = int(np.clip(round(b / max(tl, bmin)), 1, max(b // bmin, 1))); sizes = [len(x) for x in np.array_split(np.arange(b), n)]
    sizes = sorted([s for s in sizes if s > 0], reverse=True)
    order = sorted(cs, key=lambda c: -(c.quality + 0.002 * (c.end_s - c.start_s))); occ = []; wins = []          # quality decides; length only breaks ties; wins = []
    for s in sizes:
        need = s * beat_s; pick = None
        for c in order:                                                                           # the best candidate with a free stretch long enough; overlapping alternatives share one occupancy map
            opts = [(x, y) for x, y in free_parts(c, occ) if y - x >= need - 1e-9]
            if opts: pick = (c, opts); break
        if pick is None:                                                                          # nothing is big enough: shrink the part to the biggest free space anywhere
            best = max(((y - x, c, x, y) for c in order for x, y in free_parts(c, occ)), key=lambda z: z[0], default=None)
            if best is None or int(math.floor(best[0] / beat_s + 1e-9)) <= 0: continue
            s = int(math.floor(best[0] / beat_s + 1e-9)); need = s * beat_s; pick = (best[1], [(best[2], best[3])])
        c, opts = pick
        touch_l = [(x, y) for x, y in opts if any(abs(x - b) < 1e-6 for a, b in occ)]; touch_r = [(x, y) for x, y in opts if any(abs(y - a) < 1e-6 for a, b in occ)]      # next to a window already placed: adjacent selections
        if touch_l: x, y = touch_l[0]; start = x
        elif touch_r: x, y = touch_r[0]; start = y - need
        else: x, y = opts[0]; start = x + ((int(math.floor((y - x) / beat_s + 1e-9)) - s) // 2) * beat_s                 # a fresh stretch: the window in the middle of it (the edges of a stretch are the weakest part)
        occ.append((start, start + need)); tt = start - c.start_s
        pieces = [s] if s <= bmax else [len(z) for z in np.array_split(np.arange(s), int(math.ceil(s / bmax)))]
        for pc in pieces: wins.append(Window(clip_index, c, tt, pc, c.quality, getattr(c, 'forced', False))); tt += pc * beat_s
    wins.sort(key=lambda w: w.cand.start_s + w.in_s)
    return wins


def rebalance(windows, B, beat_s, st):
    """Make the windows add up to exactly B beats: grow a window into free room in its stretch (good ones first), or shrink one above the minimum."""
    bmin = math.ceil(st.min_seg_s / beat_s - 1e-9); bmax = int(MAX_SEG_S / beat_s + 1e-9)
    def room(w):                                                                                  # free beats after the window inside its stretch, up to the next window of the same stretch
        end = w.abs_start + w.beats * beat_s; nxt = min([x.abs_start for x in windows if x.clip_index == w.clip_index and x is not w and x.abs_start >= end - 1e-9] + [w.cand.end_s])
        return int(math.floor((nxt - end) / beat_s + 1e-9))
    tot = sum(w.beats for w in windows); guard = 0
    while tot < B and guard < 10000:
        guard += 1; cands = [w for w in windows if w.beats < bmax and room(w) > 0 and not w.fixed]
        if not cands: break
        max(cands, key=lambda w: (w.q, room(w))).beats += 1; tot += 1
    while tot > B and guard < 20000:
        guard += 1; cands = [w for w in windows if w.beats > bmin and not w.fixed]
        if not cands: break
        min(cands, key=lambda w: w.q).beats -= 1; tot -= 1
    return tot


# --------------------------------------------------------------------------------------------------------------------------------------------- 3. techniques
def plan(clips, lib, music, st=None):
    """clips: [{id, start_utc, duration_s, candidates: [...], unusable: [...]}] in any order. Returns the ordered list of Seg (each with `parts['options']`: the techniques that fit that window, best
    first, for the GUI). Overrides in `st` (locked windows, forced techniques, bans, clip weights) are honoured. Raises O.Infeasible with the binding constraint."""
    st = st or Settings(); rng = np.random.default_rng(st.seed); beat_s = music.beat_s; B = music.beats; warnings = []
    clips = sorted(clips, key=lambda c: c['start_utc']); clip_ids = [c['id'] for c in clips]; clips_c = [clip_candidates(c) for c in clips]
    for cs in clips_c:                                                                                # every stretch starts and ends on a beat of the clip's own time grid
        for c in cs: c.start_s, c.end_s = snap(c.start_s, beat_s, True), snap(c.end_s, beat_s, False)
    clips_c = [[c for c in cs if c.end_s - c.start_s >= beat_s - 1e-9] for cs in clips_c]
    for c, cs in zip(clips, clips_c):
        if not cs: raise O.Infeasible(f"clip {c['id']} has no usable or unusable stretch to include")
    by_clip = {cid: i for i, cid in enumerate(clip_ids)}; fixed = []; blocked = {i: [] for i in range(len(clips))}
    for key in st.bans_cands:                                                                         # a skipped moment blocks that footage whichever candidate shows it: "win:<clip>@<start>@<end>" or a candidate id
        if key.startswith('win:'):
            cid, a, b = key[4:].rsplit('@', 2) if key.count('@') >= 2 else (None, 0, 0)
            if cid in by_clip: blocked[by_clip[cid]].append((float(a), float(b)))
        else:
            for i, cs in enumerate(clips_c):
                for c in cs:
                    if c.id == key: blocked[i].append((c.start_s, c.end_s))
    for L in st.locked:
        i = by_clip.get(L['clip'])
        orig = next((c for c in clips_c[i] if c.id == L['cand_id']), None) if i is not None else None
        if orig is None: warnings.append(f"locked window {L['wid']} no longer exists (its stretch changed); it was dropped"); continue
        w = Window(i, orig, max(L['start_s'] - orig.start_s, 0.0), int(L['beats']), orig.quality, getattr(orig, 'forced', False), fixed=True, tech_id=L['tech']); fixed.append(w); blocked[i].append((L['start_s'], L['start_s'] + L['beats'] * beat_s))
    speech_blk = {i: [(c.start_s, c.end_s) for c in cs if getattr(c, 'kind', '') == 'speech'] for i, cs in enumerate(clips_c)}
    free_c = [subtract([c for c in cs if getattr(c, 'kind', '') != 'speech'], blocked[i] + speech_blk[i], st.min_seg_s, beat_s) + subtract([c for c in cs if getattr(c, 'kind', '') == 'speech'], blocked[i], st.min_seg_s, beat_s)
              for i, cs in enumerate(clips_c)]                                                        # footage where you talk is used as dialogue (its own candidate) or not at all: nothing else is cut over your voice
    locked_beats = sum(w.beats for w in fixed)
    has_lock = {w.clip_index for w in fixed}
    alloc = allocate([fc if fc else [] for fc in free_c], B - locked_beats, beat_s, st, clip_ids, has_lock) if any(free_c) else [0] * len(clips)
    windows = list(fixed)
    for i, (cs, b) in enumerate(zip(free_c, alloc)):
        if cs and b > 0: windows += cut_windows(i, cs, b, beat_s, music, st, rng)
    windows.sort(key=lambda w: (w.clip_index, w.abs_start))
    speech_iv = {i: [(c.start_s, c.end_s) for c in cs if getattr(c, 'kind', '') == 'speech'] for i, cs in enumerate(clips_c)}
    for w in windows:                                                                                     # a window on the wearer talking is dialogue, whichever candidate it was cut from
        a, b = w.abs_start, w.abs_start + w.beats * beat_s; w.speech = bool(w.cand.speech) or sum(max(0.0, min(b, y) - max(a, x)) for x, y in speech_iv[w.clip_index]) >= 0.25 * (b - a)
    if rebalance(windows, B, beat_s, st) != B: raise O.Infeasible('could not fit the windows into the film length: too little usable footage in some clips')
    return assign_techniques(windows, clips, lib, music, st, rng, warnings)

# --------------------------------------------------------------------------------------------------------------------------------------------- 3. techniques
STEADY_LOW, STEADY_HIGH = 0.15, 0.60        # the camera's steadiness (0 shaking .. 1 still) that counts as full motion / calm: a running clip is 0.1 to 0.3, a walk or a stop 0.5 and more
CLOSE_MAX_CALM, CLOSE_MAX_BUSY = 8.0, 3.0   # how long a close view of you may last in calm footage / in the busiest


def calm(steady):
    """0 (the busiest running) .. 1 (calm) from a candidate's `steady` feature; 1 when it is unknown."""
    return 1.0 if steady is None else float(min(max((float(steady) - STEADY_LOW) / (STEADY_HIGH - STEADY_LOW), 0.0), 1.0))


FACE_MIN_SHARE = 0.6           # the close view needs a clear face in at least this share of its seconds (when the clip has been analysed)
VIEW_TECH = {'mid': 'selfie_hold', 'close': 'selfie_close', 'far': 'selfie_far'}      # the views of you a window can ask for (K6)


VIEW_NEED_TEXT = {'protagonist': 'you are found in only {p}% of this footage (the mid view needs at least {t}%)', 'you_close': 'you are close enough to the camera for a face view in only {p}% of this footage (the close view needs at least {t}%)',
                  'you_far': 'you are far enough from the camera for the ultra wide view in only {p}% of this footage (the far view needs at least {t}%)'}


def view_blocked(tid, lib, w, c, d, st, music):
    """Why the technique `tid` (one of the views of you) is not allowed in window `w` of footage `c` lasting `d` seconds: the first of the planner's rules that stops it, in words with the numbers; None when none does.
    The rules are those of `assign_techniques`, in the same order."""
    t = lib.get(tid)
    if t is None: return f'the technique {tid} is not in the library'
    if tid in st.bans_techs: return f'{tid} is banned in the settings'
    if w.speech and not t.dialogue_ok: return f'the runner is speaking in this window and {tid} is not used over speech'
    if tid == 'selfie_close':
        limit = CLOSE_MAX_BUSY + (CLOSE_MAX_CALM - CLOSE_MAX_BUSY) * calm((getattr(c, 'features', None) or {}).get('steady'))
        if d > limit + 1e-9: return f'the window is {d:.1f} s but a close view of you may last at most {limit:.1f} s in footage this busy (steadiness {100 * calm((getattr(c, "features", None) or {}).get("steady")):.0f}%)'
        face = getattr(w, 'face', None)
        if face is not None and face < FACE_MIN_SHARE: return f'your face is clear in only {100 * face:.0f}% of this window (a close view needs {100 * FACE_MIN_SHARE:.0f}%)'
    if not (t.dmin - 1e-9 <= d <= t.dmax + 1e-9): return f'the window is {d:.1f} s but this view lasts {t.dmin:g} to {t.dmax:g} s'
    if t.beats == 'bar' and w.beats % music.bar_beats: return f'this view needs whole bars and the window is {w.beats} beats'
    if (w.forced and tid in ('hold_wide', 'follow_runner', 'selfie_hold')) or (w.speech and tid in ('dialogue_hold', 'selfie_hold')): return None          # (these are let through whatever the footage's own features say)
    feats = getattr(c, 'features', None) or {}
    for f, (wt, thr) in t.needs.items():
        v = feats.get(f)
        if thr is not None and (v is None or v < thr): return VIEW_NEED_TEXT.get(f, f'{f} is {0 if v is None else 100 * v:.0f}% (needs {100 * thr:.0f}%)').format(p=0 if v is None else round(100 * v), t=round(100 * thr))
    return None


CAM_SLACK_S = 0.5            # a window may run this far past the end of a point camera's stretch (windows are whole beats): the camera holds its last pose


def cam_fits(t, clip_id, start_s, d):
    """Does a window of `d` seconds from `start_s` in clip `clip_id` lie inside the stretch the point camera technique `t` covers?"""
    c = t.cam; return c['clip'] == clip_id and start_s >= c['t0'] - CAM_SLACK_S and start_s + d <= c['t1'] + CAM_SLACK_S


TECH_KIND = {'follow_runner': 'heading', 'hold_wide': 'heading', 'selfie_hold': 'you', 'selfie_close': 'you', 'selfie_far': 'you', 'scenery': 'scenery', 'free_view': 'free', 'person_hold': 'person'}          # the camera kind a technique shows (edit/cameras.py)


def camera_share(cams, tech_id, start_s, d):
    """0..1: how well a window of `d` seconds from `start_s` sits inside the best camera of the kind technique `tech_id` shows: the share of the window the camera covers times its score; 0 for a technique with no kind or a clip with no camera list."""
    kind = TECH_KIND.get(tech_id)
    if not cams or not kind or d <= 0: return 0.0
    return max((max(0.0, min(start_s + d, c['end_s']) - max(start_s, c['start_s'])) / d * c['score'] for c in cams if c['kind'] == kind), default=0.0)


def assign_techniques(windows, clips, lib, music, st, rng, warnings, B=None):
    """The beam search over an ordered list of windows for each window's technique; shared by the beat planner (`plan`) and the script planner (edit/script_plan.py). `windows` are in film order (their
    beats add up to `B`, default the music's); returns the ordered list of Seg."""
    beat_s = music.beat_s; B = B or music.beats
    ids = [t for t in lib if t not in st.bans_techs]; beams = [dict(score=0.0, true=0.0, seq=[], uses={}, secs={}, hero=0.0)]
    starts = []; pos = 0
    for w in windows: starts.append(pos); pos += w.beats
    wids = [wid_of(clips[w.clip_index]['id'], w.abs_start) for w in windows]; options = []
    establishing = [bool(w.speech) and (k == 0 or windows[k - 1].clip_index != w.clip_index or not windows[k - 1].speech) for k, w in enumerate(windows)]          # the first shot of a clip's speaking
    joined = [k > 0 and windows[k].clip_index == windows[k - 1].clip_index and abs(windows[k].abs_start - (windows[k - 1].abs_start + windows[k - 1].beats * beat_s)) <= PN.CONTIGUOUS_S for k in range(len(windows))]          # back to back in one clip: a glide can join them (edit/pans.py)
    for k, w in enumerate(windows):
        d = w.beats * beat_s; c = getattr(w.cand, 'orig', None) or w.cand; en = music.energy_at(starts[k]); opts = []
        for tid in ids:
            t = lib[tid]
            if w.speech and not t.dialogue_ok: continue
            if t.id == 'dialogue_hold' and not w.speech: continue
            if t.id == 'selfie_close' and not w.speech and st.tech_force.get(wids[k]) != 'selfie_close' and getattr(w, 'view', None) != 'close': continue            # the close view of you is for the best of the dialogue (or when asked for)
            if t.id == 'selfie_close' and st.tech_force.get(wids[k]) != 'selfie_close' and d > CLOSE_MAX_BUSY + (CLOSE_MAX_CALM - CLOSE_MAX_BUSY) * calm((getattr(c, 'features', None) or {}).get('steady')) + 1e-9: continue         # the busier the footage the shorter a close view may last: quick cuts, glided between
            if t.id == 'selfie_close' and getattr(w, 'face', None) is not None and w.face < FACE_MIN_SHARE and st.tech_force.get(wids[k]) != 'selfie_close': continue         # ... and only where the face is clear (not the top of the head): analysis/face_view.py
            if t.cam is not None and not cam_fits(t, clips[w.clip_index]['id'], w.abs_start, d): continue                 # a point camera is for windows inside the stretch it covers
            if t.id == 'person_hold' and camera_share(clips[w.clip_index].get('cameras'), 'person_hold', w.abs_start, d) <= 0: continue          # another person is shown only where the clip's camera list has a person camera
            if not (t.dmin - 1e-9 <= d <= t.dmax + 1e-9): continue
            if t.beats == 'bar' and w.beats % music.bar_beats: continue
            f = O.fit(c, t)
            if f is None and w.forced and tid in ('hold_wide', 'follow_runner', 'selfie_hold'): f = 0.2          # a clip with no usable moment still gets a plain shot of its best stretch
            if f is None and w.speech and tid in ('dialogue_hold', 'selfie_hold'): f = 0.2                    # the script plays these lines: a dialogue shot is allowed whatever the footage's own features say
            if f is None: continue
            sig = max((t.dmax - t.dmin) / 3.0, 0.4); durfit = math.exp(-0.5 * ((d - t.dideal) / sig) ** 2); scale = d ** st.dur_power
            base = scale * (st.w_quality * w.q + st.w_fit * f + st.w_dur * durfit) + st.w_energy * scale * (1.0 - abs(0.5 * c.energy + 0.5 * t.energy - en)) + st.tech_bias.get(tid, 0.0) * scale + (st.w_cam * scale if t.cam is not None else 0.0) + st.w_camlist * scale * camera_share(clips[w.clip_index].get('cameras'), tid, w.abs_start, d)
            opts.append((tid, base))
        options.append(sorted(opts, key=lambda x: -x[1])[:8])
        want = w.tech_id if w.fixed else st.tech_force.get(wids[k])
        view = getattr(w, 'view', None)
        if not want and view in VIEW_TECH:                                                                  # the script asked for a view of you (mid, close, far): used when the footage allows it
            if any(o[0] == VIEW_TECH[view] for o in opts): want = VIEW_TECH[view]
            else: warnings.append(f"{wids[k]}: the {view} view of you was asked for but is not possible in this window: {view_blocked(VIEW_TECH[view], lib, w, c, d, st, music) or 'the planner left it out for another rule'}; the planner chose its own shot")
        if want:
            if any(o[0] == want for o in opts): opts = [o for o in opts if o[0] == want]
            elif w.fixed: opts = [(want, 0.0)]                                                               # a locked window keeps its technique even if the rules would no longer allow it
            else: warnings.append(f'{wids[k]}: {want} does not fit this window any more; it was ignored')
        if not opts: raise O.Infeasible(f"no technique fits a {d:.1f} s window of {c.id} (a {w.beats}-beat window); widen the technique ranges or change the tempo")
        nxt = []
        for relaxed in (False, True):                                                                 # a dead end (every technique at a limit) is relaxed once: repeats rather than no film
          for b in beams:
              for tid, base in opts:
                  t = lib[tid]; seq = b['seq']; forced_now = bool(want)
                  if not relaxed:                                                                                   # (also for a view the script asked for)
                      if tid == 'dialogue_hold' and windows[k].speech and seq and seq[-1] == 'dialogue_hold': continue                      # the talking shot is not used twice in a row: the other views of you are cut in
                      if tid == 'selfie_close' and not ((joined[k] and seq and seq[-1] == 'selfie_hold') or (k + 1 < len(windows) and joined[k + 1])): continue                  # a close view of you glides in from a mid view just before it, or out to one just after it (edit/pans.py)
                      if seq and seq[-1] == 'selfie_close' and joined[k] and tid != 'selfie_hold' and not (len(seq) >= 2 and joined[k - 1] and seq[-2] == 'selfie_hold'): continue      # (so the one after a close view that had no mid before it is a mid view)
                  if not forced_now and not relaxed:
                      if t.cooldown and tid in seq[-t.cooldown:] and t.hero: continue
                      if t.cooldown and not t.hero and seq and seq[-1] == tid and sum(1 for x in seq[-t.max_consecutive:] if x == tid) >= t.max_consecutive: continue
                      if b['uses'].get(tid, 0) >= t.max_uses: continue
                      if t.hero and (b['hero'] + d) / (B * beat_s) > st.hero_share + 1e-9: continue
                  pen = 0.0
                  for j, prev in enumerate(reversed(seq[-6:])):
                      if prev == tid: pen += st.pen_recent * (st.recent_decay ** j) * (1.5 if t.hero else 1.0)
                  if seq:
                      pt = lib[seq[-1]]; pen += (st.pen_family if pt.family == t.family else 0.0) + (st.pen_scale if pt.scale == t.scale else 0.0)
                  share = (b['secs'].get(tid, 0.0) + d) / (B * beat_s); cap = st.share_caps.get(tid, t.max_share) * 0.7
                  pen += st.pen_share * max(0.0, share - cap) ** 2 * d ** st.dur_power
                  glide = st.w_glide if joined[k] and seq and PN.glide_pair(seq[-1], tid) else 0.0                 # two shots of one clip that can glide: no hard cut needed on the beat
                  first = st.w_first if tid not in b['uses'] else 0.0; keep = st.w_keep if st.prefer.get(wids[k]) == tid else 0.0
                  talk = (st.w_establish if establishing[k] else -st.pen_talk) * d ** st.dur_power if tid == 'dialogue_hold' and windows[k].speech else 0.0          # the talking shot opens a clip's speaking, then the other views of you are cut in
                  sc = b['true'] + base - pen + first + keep + glide + talk
                  nxt.append((sc + st.temperature * rng.gumbel(), sc, b, tid, d))
          if nxt: break
        if not nxt: raise O.Infeasible('every technique hit a limit (cooldown, caps): loosen the caps or add clips')
        nxt.sort(key=lambda x: -x[0]); new = []
        for noisy, sc, b, tid, d_ in nxt[:st.beam * 3]:
            t = lib[tid]; new.append(dict(score=noisy, true=sc, seq=b['seq'] + [tid], uses={**b['uses'], tid: b['uses'].get(tid, 0) + 1}, secs={**b['secs'], tid: b['secs'].get(tid, 0.0) + d_}, hero=b['hero'] + (d_ if t.hero else 0.0)))
        beams = sorted(new, key=lambda x: -x['score'])[:st.beam]
    best = max(beams, key=lambda x: x['true']); out = []; seq = list(best['seq'])
    for k, tid in enumerate(seq):                                                                          # a close view of you with no mid view next to it (the search had to relax its rules) is a mid view: it is for gliding in or out of one
        if tid != 'selfie_close' or windows[k].fixed or st.tech_force.get(wids[k]) == 'selfie_close': continue
        if not ((joined[k] and k > 0 and seq[k - 1] == 'selfie_hold') or (k + 1 < len(seq) and joined[k + 1] and seq[k + 1] == 'selfie_hold')) and any(o[0] == 'selfie_hold' for o in options[k]):
            seq[k] = 'selfie_hold'
            if getattr(windows[k], 'view', None) == 'close': warnings.append(f"{wids[k]}: the close view of you was asked for but there is no mid view of you next to it to glide with (the close view is for the windows of a talking stretch cut into shots); the planner chose the mid view")
    for k, (w, tid) in enumerate(zip(windows, seq)):
        orig = getattr(w.cand, 'orig', None) or w.cand; cs = round(w.abs_start, 3)
        sg = Seg(start=starts[k], beats=w.beats, cand=orig, tech=lib[tid], in_s=round(cs - orig.start_s, 3), clip_index=w.clip_index, clip_start_s=cs, variant_seed=int(rng.integers(0, 2 ** 31 - 1)), forced=w.forced)
        sg._beat_s = beat_s; sg.parts = dict(wid=wids[k], speech=bool(getattr(w, 'speech', False)), options=[dict(tech=o[0], score=round(o[1], 3)) for o in options[k]], fixed=w.fixed, warnings=warnings if k == 0 else []); out.append(sg)
    return out



OVERLAP_TOL_S = 2e-3      # window starts are stored to the millisecond, and a real tempo's beat is not a whole number of ms, so back-to-back windows can 'overlap' by up to 1 ms


def violations(segs, lib, music, clips):
    """Everything the plan must satisfy, as a list of messages (empty = valid)."""
    v = []; beat_s = music.beat_s; order = {c['id']: i for i, c in enumerate(sorted(clips, key=lambda c: c['start_utc']))}
    if sum(s.beats for s in segs) != music.beats: v.append(f'length {sum(s.beats for s in segs)} beats, not {music.beats}')
    pos = 0
    for s in segs:
        if s.start != pos: v.append(f'segment at beat {s.start} does not follow the previous one (expected {pos})')
        pos += s.beats
    for a, b in zip(segs, segs[1:]):
        ia, ib = order[a.cand.clip], order[b.cand.clip]
        if ib < ia: v.append(f'not chronological: {b.cand.clip} after {a.cand.clip}')
        if ia == ib and b.clip_start_s < a.clip_start_s + a.beats * beat_s - OVERLAP_TOL_S: v.append(f'overlap or disorder inside {a.cand.clip}: {a.clip_start_s:.2f}+{a.beats * beat_s:.2f} then {b.clip_start_s:.2f}')
    missing = set(order) - {s.cand.clip for s in segs}
    if missing: v.append(f'clips with nothing in the film: {sorted(missing)}')
    hero = sum(s.beats * beat_s for s in segs if s.tech.hero)
    if hero > 0.2 * music.beats * beat_s + 1e-6: v.append(f'hero effects take {hero:.1f} s (limit 20%)')
    for s in segs:
        d = s.beats * beat_s
        if not (s.tech.dmin - 1e-9 <= d <= s.tech.dmax + 1e-9): v.append(f'{s.tech.id} lasts {d:.2f} s, outside {s.tech.dmin}-{s.tech.dmax}')
        if s.tech.beats == 'bar' and s.beats % music.bar_beats: v.append(f'{s.tech.id} is not a whole number of bars')
        if (s.parts.get('speech') if 'speech' in s.parts else s.cand.speech) and not s.tech.dialogue_ok: v.append(f'{s.tech.id} on speech in {s.cand.id}')
        if s.in_s < -1e-6 or s.in_s + d > (s.cand.end_s - s.cand.start_s) + 1e-6: v.append(f'window outside its stretch {s.cand.id}')
    uses = {}
    for s in segs: uses[s.tech.id] = uses.get(s.tech.id, 0) + 1
    for tid, n in uses.items():
        if n > lib[tid].max_uses: v.append(f'{tid} used {n} times (max {lib[tid].max_uses})')
    return v
