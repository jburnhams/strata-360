"""Rough plan: one block per clip, in seconds (implementation plan V1; the first level of the voice-over-driven cut).

A **block** is one clip's continuous part of the film (blocks are in shooting order). It carries the target length the later steps start from, the usable stretches it may draw
on, its preferred content (the best candidates by kind and priority) and any dialogue it must carry, with the exact speech span padded 60 ms before and 120 ms after (overview 16.4).
The voice-over (V3, V4) later re-sizes the blocks; the windows inside them (V5) and the cuts on the beat come after that.

Which clips (D9): a clip with no usable footage is dropped; every other clip gets at least its minimum (one minimum window plus its dialogue). Only when the target cannot hold all
the minimums are more clips dropped, lowest value first, each with its reason. Length (D8): the film target is given (the music's length or a target length), or automatic: each
clip's natural length (2 s + 1.5 x sqrt(usable seconds), capped at its usable footage, plus its dialogue) summed."""
import heapq, math
from dataclasses import dataclass, field, asdict

from strata360.edit.chrono import Settings, MIN_SEG_S, MAX_CLIP_SHARE

PAD_BEFORE_S = 0.06
PAD_AFTER_S = 0.12
STEP_S = 0.25                     # length is handed out in steps of this size
PREFERRED_KINDS = ('speech', 'you', 'person', 'scene', 'best')      # preferred content, in this order of interest; plain `span` is the fallback


@dataclass
class Block:
    clip: str
    index: int                     # position in shooting order
    start_utc: str
    usable: list                   # merged usable stretches [(start_s, end_s)] in clip seconds
    usable_s: float
    quality: float                 # mean of the best quality available over the usable footage
    dialogue: list                 # padded speech spans [(start_s, end_s)] the block must carry
    dialogue_s: float
    preferred: list                # [{id, kind, priority, start_s, end_s}] best first
    min_s: float
    max_s: float
    natural_s: float
    target_s: float = 0.0
    locked_s: float = 0.0

    def to_dict(self): return asdict(self)


@dataclass
class RoughPlan:
    blocks: list
    dropped: list                  # [{clip, reason}]
    target_s: float                # the film length the blocks add up to
    requested_s: float | None      # what was asked for (None: automatic)
    automatic: bool
    shortfall_s: float = 0.0       # asked for more than the usable footage can hold
    warnings: list = field(default_factory=list)

    def to_dict(self): return dict(blocks=[b.to_dict() for b in self.blocks], dropped=self.dropped, target_s=self.target_s, requested_s=self.requested_s, automatic=self.automatic, shortfall_s=self.shortfall_s, warnings=self.warnings)


def merge(iv, gap=1e-6):
    out = []
    for a, b in sorted(x for x in iv if x[1] > x[0]):
        if out and a <= out[-1][1] + gap: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def subtract(iv, cut):
    for a, b in cut:
        nxt = []
        for x, y in iv:
            if b <= x or a >= y: nxt.append((x, y)); continue
            if a > x: nxt.append((x, a))
            if b < y: nxt.append((b, y))
        iv = nxt
    return iv


def intersect(iv, other):
    return merge((max(a, c), min(b, d)) for a, b in iv for c, d in other if min(b, d) > max(a, c))


def length(iv): return sum(b - a for a, b in iv)


def speech_spans(clip, cands):
    """The exact spans of the wearer's speech, unpadded. For each `speech` candidate the aligned segments that lie mostly inside it give their first to last aligned word (else the segment's
    own times); a speech candidate with no alignment contributes its whole stretch. `clip['speech_spans']` overrides all of this."""
    if clip.get('speech_spans') is not None: return merge([tuple(s) for s in clip['speech_spans']])
    segs = clip.get('alignment') or []; out = []
    for c in cands:
        if c.get('kind') != 'speech': continue
        found = []
        for s in segs:
            t0, t1 = s['t0'], s['t1']; ov = min(t1, c['end_s']) - max(t0, c['start_s'])
            if t1 > t0 and ov >= 0.5 * (t1 - t0):
                w = [x for x in s.get('words') or [] if x.get('ok') and x.get('a0') is not None and x.get('a1') is not None]
                found.append((min(x['a0'] for x in w), max(x['a1'] for x in w)) if w else (t0, t1))
        out += found or [(c['start_s'], c['end_s'])]
    return merge(out)


def pad(spans, dur):
    return merge([(max(a - PAD_BEFORE_S, 0.0), min(b + PAD_AFTER_S, dur) if dur else b + PAD_AFTER_S) for a, b in spans])


def natural_s(usable_s, dialogue_s):
    avail = max(usable_s - dialogue_s, 0.0)
    return min(2.0 + 1.5 * math.sqrt(avail), avail) + dialogue_s


def _banned(st):
    ids, wins = set(), {}
    for key in st.bans_cands:
        if key.startswith('win:') and key.count('@') >= 2:
            cid, a, b = key[4:].rsplit('@', 2); wins.setdefault(cid, []).append((float(a), float(b)))
        else: ids.add(key)
    return ids, wins


def make_block(clip, index, st, ids, wins, locked_s=0.0):
    """The block for one clip, or None when it has no usable footage."""
    cands = [c for c in clip.get('candidates') or [] if c['id'] not in ids]
    usable = subtract(merge([(c['start_s'], c['end_s']) for c in cands]), wins.get(clip['id'], []))
    usable = [(a, b) for a, b in usable if b - a >= 1e-6]
    if not usable: return None
    dur = clip.get('duration_s') or 0.0
    dlg = intersect(pad(speech_spans(clip, cands), dur), usable)                                      # only dialogue that lies in usable footage
    usable_s = length(usable); dialogue_s = length(dlg); avail = max(usable_s - dialogue_s, 0.0)
    q = _quality(cands, usable)
    pref = sorted([c for c in cands if c.get('kind', 'span') in PREFERRED_KINDS], key=lambda c: (c.get('priority', 1e9), PREFERRED_KINDS.index(c['kind'])))
    pref = [dict(id=c['id'], kind=c['kind'], priority=c.get('priority'), start_s=c['start_s'], end_s=c['end_s']) for c in pref]
    mn = min(dialogue_s + min(st.min_seg_s, avail), usable_s); mn = max(mn, min(locked_s, usable_s))
    nat = max(natural_s(usable_s, dialogue_s), mn)
    return Block(clip=clip['id'], index=index, start_utc=clip['start_utc'], usable=usable, usable_s=round(usable_s, 3), quality=q, dialogue=dlg, dialogue_s=round(dialogue_s, 3), preferred=pref,
                 min_s=round(mn, 3), max_s=round(usable_s, 3), natural_s=round(nat, 3), locked_s=locked_s)


def _quality(cands, usable, step=0.25):
    if not usable: return 0.0
    vals = []
    for a, b in usable:
        t = a + step / 2
        while t < b:
            vals.append(max([c['quality'] for c in cands if c['start_s'] <= t < c['end_s']] or [0.0])); t += step
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def value(b):
    """How much a clip is worth keeping when the target is too small: its quality, and some credit for dialogue and for footage to work with."""
    return b.quality + (0.3 if b.dialogue_s > 0 else 0.0) + 0.05 * math.log1p(b.usable_s)


def allocate_s(blocks, T, st, weights):
    """Seconds per block summing to T (or to the most the footage allows): at least each minimum, at most its footage and its share cap, the rest by concave value."""
    cap = st.max_clip_share * T; hi = [min(b.max_s, max(cap, b.min_s)) for b in blocks]
    if sum(hi) < T: hi = [b.max_s for b in blocks]                                                     # the share cap yields when it is the only way to fill the film
    t = [b.min_s for b in blocks]; w = [(0.4 + b.quality) * float(weights.get(b.clip, 1.0)) for b in blocks]
    gain = lambda i, step: w[i] * (math.log1p((t[i] + step) / 4.0) - math.log1p(t[i] / 4.0))
    heap = []
    for i in range(len(blocks)):
        s = min(STEP_S, hi[i] - t[i])
        if s > 1e-9: heap.append((-gain(i, s) / s, i))
    heapq.heapify(heap); left = T - sum(t)
    while left > 1e-9 and heap:
        _, i = heapq.heappop(heap); s = min(STEP_S, hi[i] - t[i], left)
        t[i] += s; left -= s
        s2 = min(STEP_S, hi[i] - t[i])
        if s2 > 1e-9: heapq.heappush(heap, (-gain(i, s2) / s2, i))
    return [round(x, 3) for x in t], max(left, 0.0)


def plan_blocks(clips, target_s=None, st=None, beat_s=0.5):
    """clips: [{id, start_utc, duration_s, candidates: [...], alignment?: [...], speech_spans?: [...]}] in any order. `target_s`: the film length guide (the music's length, or a
    target length); None means automatic (D8). Locks, bans and clip weights come from `st` (chrono.Settings) as for the beat planner."""
    st = st or Settings(); ids, wins = _banned(st); dropped = []; warnings = []
    locked = {}
    for L in st.locked: locked[L['clip']] = locked.get(L['clip'], 0.0) + float(L.get('seconds') or L['beats'] * beat_s)
    blocks = []
    for c in sorted(clips, key=lambda c: c['start_utc']):
        b = make_block(c, 0, st, ids, wins, locked.get(c['id'], 0.0))
        if b is None: dropped.append(dict(clip=c['id'], reason='no usable footage'))
        else: blocks.append(b)
    auto = target_s is None
    if auto: T = sum(b.natural_s for b in blocks)
    else:
        T = float(target_s)
        while blocks and sum(b.min_s for b in blocks) > T + 1e-9:                                    # the minimums do not fit: drop the lowest value first (never a clip holding a locked window)
            cand = [b for b in blocks if b.locked_s <= 0] or blocks
            v = min(cand, key=value); blocks.remove(v)
            dropped.append(dict(clip=v.clip, reason=f'the {T:.0f} s target cannot hold every clip\'s minimum (lowest value, {v.min_s:.1f} s needed)'))
    if not blocks: return RoughPlan([], dropped, 0.0, None if auto else float(target_s), auto, warnings=['no clip has usable footage'])
    for i, b in enumerate(blocks): b.index = i
    if auto:
        for b in blocks: b.target_s = b.natural_s
        short = 0.0
    else:
        ts, left = allocate_s(blocks, T, st, st.clip_weight)
        for b, t in zip(blocks, ts): b.target_s = t
        short = round(left, 3)
        if short > 0: warnings.append(f'not enough usable footage: {sum(b.max_s for b in blocks):.0f} s against a {T:.0f} s film')
    return RoughPlan(blocks, dropped, round(sum(b.target_s for b in blocks), 3), None if auto else float(target_s), auto, short, warnings)
