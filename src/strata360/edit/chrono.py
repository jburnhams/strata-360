"""Chronological film planner (README 16.2b): the film follows the day, the optimiser decides how each clip is edited.

Rules
  * the film is in **time order**: clips in the order they were shot, and inside a clip its segments in time order;
  * **every clip contributes**: each source clip gets at least one segment (a clip with no usable moment contributes its best unusable stretch, flagged), and a long clip may contribute
    several segments, as many as its share of the film justifies;
  * segments of one clip **never overlap**; several adjacent selections from one clip are welcome (they allow a different view, technique or cut for each);
  * the optimiser still chooses how much of the film each clip gets, which moments, the segment lengths, and the technique of every segment, with the same variety rules as before
    (repeats, hero effects, cooldowns, shares), beat-aligned to the music and filling it exactly.

Three steps: (1) split the beats between the clips (concave value, so every clip gets something and long or good clips get more); (2) cut each clip's share into non-overlapping windows
inside its usable stretches; (3) beam search over the ordered windows for the techniques, seeded so a seed reproduces a plan exactly."""
import heapq, math
from dataclasses import dataclass, field
import numpy as np
from strata360.edit import optimise as O

MIN_SEG_S = 2.0          # shortest window (the shortest everyday technique needs 2 s; whip pans are transitions, not windows)
MAX_SEG_S = 8.0          # longest window: longer ones are split into adjacent windows, each with its own view
MAX_CLIP_SHARE = 0.25    # no clip takes more than this share of the film (unless it is the only way to fill it)


@dataclass
class Settings:
    seed: int = 0
    beam: int = 30
    temperature: float = 0.15
    w_quality: float = 1.0; w_fit: float = 0.8; w_dur: float = 0.5; w_energy: float = 0.6; w_first: float = 0.4
    dur_power: float = 0.6
    pen_recent: float = 0.8; recent_decay: float = 0.7; pen_family: float = 0.25; pen_scale: float = 0.15; pen_share: float = 6.0
    hero_share: float = 0.2
    max_clip_share: float = MAX_CLIP_SHARE
    min_seg_s: float = MIN_SEG_S
    dialogue_share: float = 0.15
    bans_techs: frozenset = frozenset()
    share_caps: dict = field(default_factory=lambda: {'dialogue_hold': 0.15})


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


def clip_candidates(clip):
    """O.Candidate list for one clip dict {id, candidates: [...], unusable: [...]}; a clip with none gets its best unusable stretch (forced)."""
    out = []
    for c in clip.get('candidates') or []:
        out.append(O.Candidate(id=c['id'], clip=c['clip'], quality=c['quality'], energy=c['energy'], min_dur=c['min_dur'], max_dur=c['max_dur'], features=dict(c['features']), group=None))
        out[-1].start_s = c['start_s']; out[-1].end_s = c['end_s']; out[-1].forced = False
    if out: return out
    un = sorted(clip.get('unusable') or [], key=lambda u: -((u['end_s'] - u['start_s']) * (0.2 + float((u.get('stats') or {}).get('score') or 0))))
    for k, u in enumerate(un[:1]):
        f = dict(steady=0.2, clear_nadir=0.5, open_ground=0.3, canopy=0.3, subject=0.2, speech=0.0, protagonist=0.0, low_obstruction=0.5, resolution=0.5)
        c = O.Candidate(id=f"{clip['id']}#forced", clip=clip['id'], quality=0.25, energy=0.5, min_dur=1.0, max_dur=u['end_s'] - u['start_s'], features=f)
        c.start_s = u['start_s']; c.end_s = u['end_s']; c.forced = True; out.append(c)
    return out


# --------------------------------------------------------------------------------------------------------------------------------------------- 1. split the beats between clips
def allocate(clips_c, B, beat_s, st):
    """Beats per clip: at least one minimum window each, at most what its usable stretches hold and its share cap; the rest by concave value (good and long clips get more, with diminishing returns)."""
    n = len(clips_c); bmin_seg = math.ceil(st.min_seg_s / beat_s - 1e-9); U = []; q = []
    for cs in clips_c:
        L = sum(c.end_s - c.start_s for c in cs); U.append(L); q.append(sum((c.end_s - c.start_s) * c.quality for c in cs) / max(L, 1e-9))
    bmax = [max(int(math.floor(U[i] / beat_s + 1e-9)), 0) for i in range(n)]; cap = int(math.ceil(st.max_clip_share * B))
    bmin = [min(bmin_seg, bmax[i]) if bmax[i] > 0 else 0 for i in range(n)]
    if any(b == 0 for b in bmin): raise O.Infeasible('a clip has no stretch long enough for one segment')
    if sum(bmin) > B: raise O.Infeasible(f'too short to include something from every clip: {n} clips need at least {sum(bmin) * beat_s:.0f} s ({bmin_seg} beats each), the film is {B * beat_s:.0f} s')
    hi = [min(bmax[i], max(cap, bmin[i])) for i in range(n)]
    if sum(hi) < B: hi = list(bmax)                                                               # the share cap may be broken when it is the only way to fill the film
    if sum(hi) < B: raise O.Infeasible(f'not enough usable footage: {sum(bmax) * beat_s:.0f} s against a {B * beat_s:.0f} s film')
    b = list(bmin); ref = 4.0; w = [0.4 + qi for qi in q]

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
    cap = {c.id: int(math.floor((c.end_s - c.start_s) / beat_s + 1e-9)) for c in cs}; used = {c.id: 0 for c in cs}; placed = {c.id: [] for c in cs}; by_id = {c.id: c for c in cs}
    order = sorted(cs, key=lambda c: -(c.quality * 1.0 + 0.02 * (c.end_s - c.start_s)))
    for s in sizes:
        pick = next((c for c in order if cap[c.id] - used[c.id] >= s), None)
        if pick is None:                                                                          # nothing is big enough: shrink the part to the biggest free space
            pick = max(order, key=lambda c: cap[c.id] - used[c.id]); s = cap[pick.id] - used[pick.id]
            if s <= 0: continue
        placed[pick.id].append(s); used[pick.id] += s
    wins = []
    for cid, parts in placed.items():
        if not parts: continue
        c = by_id[cid]; total = sum(parts) * beat_s; off = max((c.end_s - c.start_s - total) / 2.0, 0.0); t = off
        for s in parts:                                                                           # adjacent windows, long ones split so each can have its own look
            pieces = [s] if s <= bmax else [len(x) for x in np.array_split(np.arange(s), int(math.ceil(s / bmax)))]
            for p in pieces: wins.append(Window(clip_index, c, t, p, c.quality, getattr(c, 'forced', False))); t += p * beat_s
    wins.sort(key=lambda w: w.cand.start_s + w.in_s)
    return wins


def rebalance(windows, B, beat_s, st):
    """Make the windows add up to exactly B beats: grow a window into free room in its stretch (good ones first), or shrink one above the minimum."""
    bmin = math.ceil(st.min_seg_s / beat_s - 1e-9); bmax = int(MAX_SEG_S / beat_s + 1e-9)
    def room(w):                                                                                  # free beats after the window inside its stretch, up to the next window of the same stretch
        end = w.in_s + w.beats * beat_s; nxt = min([x.in_s for x in windows if x.cand is w.cand and x.in_s >= end - 1e-9 and x is not w] + [w.cand.end_s - w.cand.start_s])
        return int(math.floor((nxt - end) / beat_s + 1e-9))
    tot = sum(w.beats for w in windows); guard = 0
    while tot < B and guard < 10000:
        guard += 1; cands = [w for w in windows if w.beats < bmax and room(w) > 0]
        if not cands: break
        max(cands, key=lambda w: (w.q, room(w))).beats += 1; tot += 1
    while tot > B and guard < 20000:
        guard += 1; cands = [w for w in windows if w.beats > bmin]
        if not cands: break
        min(cands, key=lambda w: w.q).beats -= 1; tot -= 1
    return tot


# --------------------------------------------------------------------------------------------------------------------------------------------- 3. techniques
def plan(clips, lib, music, st=None):
    """clips: [{id, start_utc, duration_s, candidates: [...], unusable: [...]}] in any order. Returns the ordered list of Seg. Raises O.Infeasible with the binding constraint."""
    st = st or Settings(); rng = np.random.default_rng(st.seed); beat_s = music.beat_s; B = music.beats
    clips = sorted(clips, key=lambda c: c['start_utc']); clips_c = [clip_candidates(c) for c in clips]
    for c, cs in zip(clips, clips_c):
        if not cs: raise O.Infeasible(f"clip {c['id']} has no usable or unusable stretch to include")
    alloc = allocate(clips_c, B, beat_s, st); windows = []
    for i, (cs, b) in enumerate(zip(clips_c, alloc)): windows += cut_windows(i, cs, b, beat_s, music, st, rng)
    windows.sort(key=lambda w: (w.clip_index, w.cand.start_s + w.in_s))
    if rebalance(windows, B, beat_s, st) != B: raise O.Infeasible('could not fit the windows into the film length: too little usable footage in some clips')
    ids = [t for t in lib if t not in st.bans_techs]; beams = [dict(score=0.0, true=0.0, seq=[], uses={}, secs={}, hero=0.0, pos=0)]
    n = len(windows); pos = 0; starts = []
    for w in windows: starts.append(pos); pos += w.beats
    for k, w in enumerate(windows):
        d = w.beats * beat_s; c = w.cand; en = music.energy_at(starts[k]); opts = []
        for tid in ids:
            t = lib[tid]
            if c.speech and not t.dialogue_ok: continue
            if t.id == 'dialogue_hold' and not c.speech: continue
            if not (t.dmin - 1e-9 <= d <= t.dmax + 1e-9): continue
            if t.beats == 'bar' and w.beats % music.bar_beats: continue
            f = O.fit(c, t)
            if f is None and w.forced and tid in ('hold_wide', 'follow_runner', 'selfie_hold'): f = 0.2          # a clip with no usable moment still gets a plain shot of its best stretch
            if f is None: continue
            sig = max((t.dmax - t.dmin) / 3.0, 0.4); durfit = math.exp(-0.5 * ((d - t.dideal) / sig) ** 2); scale = d ** st.dur_power
            base = scale * (st.w_quality * w.q + st.w_fit * f + st.w_dur * durfit) + st.w_energy * scale * (1.0 - abs(0.5 * c.energy + 0.5 * t.energy - en))
            opts.append((tid, base))
        if not opts: raise O.Infeasible(f"no technique fits a {d:.1f} s window of {c.id} (a {w.beats}-beat window); widen the technique ranges or change the tempo")
        nxt = []
        for b in beams:
            for tid, base in opts:
                t = lib[tid]; seq = b['seq']
                if t.cooldown and tid in seq[-t.cooldown:] and t.cooldown > 0 and t.hero: continue
                if t.cooldown and not t.hero and seq and seq[-1] == tid and t.cooldown > 0 and sum(1 for x in seq[-t.max_consecutive:] if x == tid) >= t.max_consecutive: continue
                if b['uses'].get(tid, 0) >= t.max_uses: continue
                if t.hero and (b['hero'] + d) / (B * beat_s) > st.hero_share + 1e-9: continue
                pen = 0.0
                for j, prev in enumerate(reversed(seq[-6:])):
                    if prev == tid: pen += st.pen_recent * (st.recent_decay ** j) * (1.5 if t.hero else 1.0)
                if seq:
                    pt = lib[seq[-1]]; pen += (st.pen_family if pt.family == t.family else 0.0) + (st.pen_scale if pt.scale == t.scale else 0.0)
                share = (b['secs'].get(tid, 0.0) + d) / (B * beat_s); cap = st.share_caps.get(tid, t.max_share) * 0.7
                pen += st.pen_share * max(0.0, share - cap) ** 2 * d ** st.dur_power
                first = st.w_first if tid not in b['uses'] else 0.0
                sc = b['true'] + base - pen + first
                nxt.append((sc + st.temperature * rng.gumbel(), sc, b, tid, d))
        if not nxt: raise O.Infeasible('every technique hit a limit (cooldown, caps): loosen the caps or add clips')
        nxt.sort(key=lambda x: -x[0]); new = []
        for noisy, sc, b, tid, d_ in nxt[:st.beam * 3]:
            t = lib[tid]; new.append(dict(score=noisy, true=sc, seq=b['seq'] + [tid], uses={**b['uses'], tid: b['uses'].get(tid, 0) + 1}, secs={**b['secs'], tid: b['secs'].get(tid, 0.0) + d_},
                                          hero=b['hero'] + (d_ if t.hero else 0.0), pos=k))
        beams = sorted(new, key=lambda x: -x['score'])[:st.beam]
    best = max(beams, key=lambda x: x['true']); out = []
    for k, (w, tid) in enumerate(zip(windows, best['seq'])):
        s = Seg(start=starts[k], beats=w.beats, cand=w.cand, tech=lib[tid], in_s=round(w.in_s, 3), clip_index=w.clip_index, clip_start_s=round(w.cand.start_s + w.in_s, 3), variant_seed=int(rng.integers(0, 2 ** 31 - 1)), forced=w.forced)
        s._beat_s = beat_s; out.append(s)
    return out


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
        if ia == ib and b.clip_start_s < a.clip_start_s + a.beats * beat_s - 1e-6: v.append(f'overlap or disorder inside {a.cand.clip}: {a.clip_start_s:.2f}+{a.beats * beat_s:.2f} then {b.clip_start_s:.2f}')
    missing = set(order) - {s.cand.clip for s in segs}
    if missing: v.append(f'clips with nothing in the film: {sorted(missing)}')
    hero = sum(s.beats * beat_s for s in segs if s.tech.hero)
    if hero > 0.2 * music.beats * beat_s + 1e-6: v.append(f'hero effects take {hero:.1f} s (limit 20%)')
    for s in segs:
        d = s.beats * beat_s
        if not (s.tech.dmin - 1e-9 <= d <= s.tech.dmax + 1e-9): v.append(f'{s.tech.id} lasts {d:.2f} s, outside {s.tech.dmin}-{s.tech.dmax}')
        if s.tech.beats == 'bar' and s.beats % music.bar_beats: v.append(f'{s.tech.id} is not a whole number of bars')
        if s.cand.speech and not s.tech.dialogue_ok: v.append(f'{s.tech.id} on speech in {s.cand.id}')
        if s.in_s < -1e-6 or s.in_s + d > (s.cand.end_s - s.cand.start_s) + 1e-6: v.append(f'window outside its stretch {s.cand.id}')
    uses = {}
    for s in segs: uses[s.tech.id] = uses.get(s.tech.id, 0) + 1
    for tid, n in uses.items():
        if n > lib[tid].max_uses: v.append(f'{tid} used {n} times (max {lib[tid].max_uses})')
    return v
