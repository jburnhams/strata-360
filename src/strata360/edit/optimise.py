"""Joint edit optimisation (README 16.2): choose the whole timeline at once.

Decisions: an ordered sequence of segments (candidate, technique, length in beats) that fills the music exactly with every cut on a beat.
Hard constraints: exact total, beat-aligned lengths, technique duration ranges and hard content needs, dialogue candidates get only
dialogue-safe techniques, caps (uses, share, hero total), cooldowns, no consecutive repeats beyond the limit, each candidate once.
Objective: quality x duration + technique fit + duration fit + energy match + beat quality, minus variety penalties (recent repeats with
decay, hero effects, same family or scale in a row, exceeding a technique's share). Randomness is seeded: noise perturbs the search only,
so a seed reproduces a plan exactly and `evaluate` gives the noise-free objective.

Solver: beam search over beat positions (state = usage counts and recent techniques, so the variety terms are exact along each path),
then seeded simulated annealing over swaps and beat trades with the exact evaluator.
"""
import math
from dataclasses import dataclass, field
import numpy as np

SCALE_ID = {'wide': 0, 'medium': 1, 'tight': 2}


class Infeasible(Exception):
    pass


@dataclass
class Music:
    bpm: float
    beats: int                                   # the target: the plan fills exactly this many beats
    bar_beats: int = 4
    sections: list = field(default_factory=lambda: [(0, 10 ** 9, 0.5)])   # (start_beat, end_beat, energy 0..1)

    @property
    def beat_s(self): return 60.0 / self.bpm
    def energy_at(self, b):
        for s, e, en in self.sections:
            if s <= b < e: return en
        return self.sections[-1][2]
    def section_start(self, b): return any(s == b for s, _, _ in self.sections)


@dataclass
class Candidate:
    id: str
    clip: str
    quality: float                               # 0..1 interest
    energy: float                                # 0..1 motion / intensity of the footage
    min_dur: float                               # trim handles: usable length range in seconds
    max_dur: float
    features: dict = field(default_factory=dict)  # steady, clear_nadir, open_ground, canopy, subject, speech, protagonist, low_obstruction, resolution (0..1)
    group: str = None                            # candidates of one group overlap: at most one is used

    @property
    def speech(self): return self.features.get('speech', 0.0) >= 0.5


@dataclass
class Settings:
    seed: int = 0
    beam: int = 40
    expand: int = 6                              # options kept per state
    temperature: float = 0.15                    # search noise (Gumbel scale); 0 = deterministic greedy-beam
    variety: float = 1.0                         # scales every variety term
    sa_iters: int = 1500
    w_quality: float = 1.0; w_fit: float = 0.8; w_dur: float = 0.5; w_energy: float = 0.6; w_bar: float = 0.15; w_section: float = 0.3
    w_pace: float = 0.8                          # shot lengths follow the music: shorter cuts when the energy is high (target_len)
    w_first: float = 0.5                         # bonus the first time each technique is used: encourages trying the whole toolbox
    share_caps: dict = field(default_factory=lambda: {'dialogue_hold': 0.15})   # per-technique share overrides (dialogue is optional in a music-driven edit)
    dur_power: float = 0.6                       # segment value scales with duration ** dur_power
    pen_recent: float = 0.8; recent_decay: float = 0.7; recent_window: int = 6; pen_hero_recent: float = 1.5
    pen_family: float = 0.25; pen_scale: float = 0.15; pen_share: float = 6.0
    share_hard: float = 1.25                     # hard limit: share may not exceed max_share * this
    hero_total_share: float = 0.20               # all hero techniques together may fill at most this share of the runtime
    bans_cands: frozenset = frozenset(); bans_techs: frozenset = frozenset()
    budgets: dict = field(default_factory=dict)  # technique id -> max uses (overrides the library)
    fixed: dict = field(default_factory=dict)    # start_beat -> (cand_id, tech_id, beats): locked segments (kept exactly)


@dataclass
class Segment:
    cand: Candidate
    tech: object
    beats: int
    start: int
    variant_seed: int
    parts: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------ feasibility
def target_len(energy):
    """Preferred shot length in seconds for a music energy in 0..1: about 4.7 s when calm, 2.2 s in a chorus, 1.5 s at the peak."""
    return max(1.5, 6.0 - 4.5 * energy)


def fit(c, t):
    """Weighted mean of the technique's needs met by the candidate (1.0 when it has none); None if a hard threshold fails."""
    if not t.needs: return 1.0
    tot = w = 0.0
    for f, (wt, thr) in t.needs.items():
        v = c.features.get(f, 0.0)
        if thr is not None and v < thr: return None
        tot += wt * v; w += wt
    return tot / w


def option_table(cands, lib, music, st):
    """All feasible (candidate, technique, beats) triples with their position-independent value. Returns a dict of arrays."""
    rows = []
    for ci, c in enumerate(cands):
        if c.id in st.bans_cands: continue
        for t in lib.values():
            if t.id in st.bans_techs: continue
            if c.speech and not t.dialogue_ok: continue                     # dialogue: only steady dialogue-safe framing (README 16.4)
            f = fit(c, t)
            if f is None: continue
            lo = max(t.dmin, c.min_dur); hi = min(t.dmax, c.max_dur)
            k0, k1 = math.ceil(lo / music.beat_s - 1e-9), math.floor(hi / music.beat_s + 1e-9)
            for k in range(max(k0, 1), k1 + 1):
                if t.beats == 'bar' and k % music.bar_beats: continue
                d = k * music.beat_s; sig = max((t.dmax - t.dmin) / 3.0, 0.4)
                durfit = math.exp(-0.5 * ((d - t.dideal) / sig) ** 2)
                rows.append((ci, t.id, k, d, f, durfit))
    if not rows: raise Infeasible('no feasible (candidate, technique, length) combination at all: check bans, needs and the music tempo')
    ids = list(lib.keys()); ti = {tid: i for i, tid in enumerate(ids)}
    A = dict(c=np.array([r[0] for r in rows]), t=np.array([ti[r[1]] for r in rows]), k=np.array([r[2] for r in rows]), d=np.array([r[3] for r in rows]),
             fit=np.array([r[4] for r in rows]), durfit=np.array([r[5] for r in rows]), tech_ids=ids)
    q = np.array([cands[i].quality for i in A['c']]); ce = np.array([cands[i].energy for i in A['c']]); te = np.array([lib[ids[i]].energy for i in A['t']])
    scale = A['d'] ** st.dur_power
    A['base'] = scale * (st.w_quality * q + st.w_fit * A['fit'] + st.w_dur * A['durfit'])
    A['seg_energy'] = 0.5 * ce + 0.5 * te; A['scale'] = scale
    A['hero'] = np.array([lib[ids[i]].hero for i in A['t']]); A['tscale'] = np.array([SCALE_ID[lib[ids[i]].scale] for i in A['t']])
    A['family'] = np.array([hash(lib[ids[i]].family) & 0xFFFF for i in A['t']])
    gnames = {}
    A['grp'] = np.array([gnames.setdefault(cands[i].group or f'_{cands[i].id}', len(gnames)) for i in A['c']]); A['ngroups'] = len(gnames)
    return A


def check_capacity(cands, lib, music, st, A):
    """Cheap necessary conditions, so an impossible request fails with the constraint that binds."""
    usable = sum(min(c.max_dur, max(lib[t].dmax for t in lib)) for c in cands if c.id not in st.bans_cands)
    target = music.beats * music.beat_s
    if usable < target - 1e-9: raise Infeasible(f'not enough footage: usable candidates total {usable:.1f} s but the music needs {target:.1f} s')
    kmin = int(A['k'].min())
    if music.beats < kmin: raise Infeasible('the music is shorter than the shortest allowed segment')


# ----------------------------------------------------------------------------------------------------- state
class State:
    __slots__ = ('p', 'true', 'noisy', 'segs', 'used', 'grp_used', 'uses', 'secs', 'last', 'lastpos', 'nshots', 'hero_secs', 'consec')

    def __init__(self, ntech, ngroups=0):
        self.p = 0; self.true = 0.0; self.noisy = 0.0; self.segs = []; self.used = set(); self.grp_used = np.zeros(ngroups, bool)
        self.uses = np.zeros(ntech, int); self.secs = np.zeros(ntech); self.last = []; self.lastpos = np.full(ntech, -10 ** 6); self.nshots = 0; self.hero_secs = 0.0; self.consec = 0

    def copy(self):
        s = State(len(self.uses), len(self.grp_used)); s.p, s.true, s.noisy = self.p, self.true, self.noisy; s.segs = list(self.segs); s.used = set(self.used); s.grp_used = self.grp_used.copy()
        s.uses = self.uses.copy(); s.secs = self.secs.copy(); s.last = list(self.last); s.lastpos = self.lastpos.copy(); s.nshots = self.nshots; s.hero_secs = self.hero_secs; s.consec = self.consec
        return s


def _variety_penalty(lib_ids, lib, A, idx, s, st, total_s):
    """Penalty for choosing option rows `idx` after state s (vectorised over the rows)."""
    t = A['t'][idx]; pen = np.zeros(len(idx))
    for j, prev in enumerate(reversed(s.last[-st.recent_window:])):                      # recent repeats, decaying with distance
        same = (t == prev); w = st.pen_recent * (st.recent_decay ** j)
        pen += np.where(same, np.where(A['hero'][idx], st.pen_hero_recent, 1.0) * w, 0.0)
    if s.last:
        pt = s.last[-1]; pen += np.where(A['family'][idx] == A['family_of_t'][pt], st.pen_family, 0.0) + np.where(A['tscale'][idx] == A['scale_of_t'][pt], st.pen_scale, 0.0)
    tgt = A['max_share_t'][t] * 0.7; over = np.maximum(0.0, (s.secs[t] + A['d'][idx]) / total_s - tgt)
    pen += st.pen_share * over ** 2 * A['d'][idx] ** st.dur_power
    return pen * st.variety


def _prepare(A, lib, st_caps=None):
    st_caps = st_caps or {}
    ids = A['tech_ids']
    A['family_of_t'] = np.array([hash(lib[i].family) & 0xFFFF for i in ids]); A['scale_of_t'] = np.array([SCALE_ID[lib[i].scale] for i in ids])
    A['max_share_t'] = np.array([st_caps.get(i, lib[i].max_share) for i in ids]); A['max_uses_t'] = np.array([lib[i].max_uses for i in ids])
    A['cooldown_t'] = np.array([lib[i].cooldown for i in ids]); A['maxcons_t'] = np.array([lib[i].max_consecutive for i in ids]); A['hero_t'] = np.array([lib[i].hero for i in ids])
    return A


def plan(cands, lib, music, st=None):
    """Return the best plan (list of Segment) for these candidates. Raises Infeasible with the binding constraint."""
    st = st or Settings(); rng = np.random.default_rng(st.seed)
    A = _prepare(option_table(cands, lib, music, st), lib, st.share_caps)
    for tid, n in st.budgets.items():
        if tid in A['tech_ids']: A['max_uses_t'][A['tech_ids'].index(tid)] = n
    check_capacity(cands, lib, music, st, A)
    N = music.beats; total_s = N * music.beat_s; ntech = len(A['tech_ids']); kmin = int(A['k'].min())
    beam = {0: [State(ntech, A['ngroups'])]}
    locked = sorted(st.fixed)
    cand_by_id = {c.id: i for i, c in enumerate(cands)}
    for p in range(N):
        states = beam.pop(p, [])
        if not states: continue
        fixed = st.fixed.get(p)
        for s in states:
            m = (s.p + A['k'] <= N) & ((N - s.p - A['k'] == 0) | (N - s.p - A['k'] >= kmin))
            m &= ~s.grp_used[A['grp']]
            m &= s.uses[A['t']] < A['max_uses_t'][A['t']]
            m &= (s.nshots - s.lastpos[A['t']]) > A['cooldown_t'][A['t']]
            if s.last: m &= ~((A['t'] == s.last[-1]) & (s.consec >= A['maxcons_t'][A['t']]))
            m &= (s.secs[A['t']] + A['d']) / total_s <= A['max_share_t'][A['t']] * st.share_hard + 1e-9
            m &= ~(A['hero'] & (s.hero_secs + A['d'] > st.hero_total_share * total_s + 1e-9))
            if fixed:
                fc, ft, fk = fixed; m &= (A['c'] == cand_by_id[fc]) & (A['t'] == A['tech_ids'].index(ft)) & (A['k'] == fk)
            else:
                for ls in locked: m &= ~((s.p < ls) & (s.p + A['k'] > ls))          # a free segment may not straddle a locked one
            idx = np.nonzero(m)[0]
            if len(idx) == 0: continue
            en = music.energy_at(s.p)
            pos = st.w_energy * (1.0 - np.abs(A['seg_energy'][idx] - en)) * A['scale'][idx]
            pos -= st.w_pace * np.log(A['d'][idx] / target_len(en)) ** 2 * A['scale'][idx]
            pos += st.w_first * (s.uses[A['t'][idx]] == 0)
            pos += (st.w_bar if s.p % music.bar_beats == 0 else 0.0) + (st.w_section if music.section_start(s.p) else 0.0)
            gain = A['base'][idx] + pos - _variety_penalty(A['tech_ids'], lib, A, idx, s, st, total_s)
            noise = st.temperature * rng.gumbel(size=len(idx))
            order = np.argsort(-((gain + noise) / A['k'][idx]))[:st.expand]          # rank by gain per beat, so short options are not starved by long ones
            for o in order:
                r = idx[o]; ns = s.copy(); t = int(A['t'][r]); c = int(A['c'][r]); k = int(A['k'][r]); d = float(A['d'][r])
                ns.true += float(gain[o]); ns.noisy += float(gain[o] + noise[o]); ns.used.add(c); ns.grp_used[A['grp'][r]] = True
                ns.consec = ns.consec + 1 if (ns.last and ns.last[-1] == t) else 1
                ns.uses[t] += 1; ns.secs[t] += d; ns.lastpos[t] = ns.nshots; ns.nshots += 1; ns.last.append(t)
                if A['hero_t'][t]: ns.hero_secs += d
                ns.segs.append((c, t, k, s.p)); ns.p = s.p + k
                beam.setdefault(ns.p, []).append(ns)
        for q in [q for q in beam if q > p]:                                  # prune buckets, keeping some diversity of recent techniques
            if len(beam[q]) > st.beam * 2:
                lst = sorted(beam[q], key=lambda x: -x.noisy); kept, per = [], {}
                for x in lst:
                    key = (x.last[-1] if x.last else -1, x.last[-2] if len(x.last) > 1 else -1)
                    if per.get(key, 0) >= 4: continue
                    per[key] = per.get(key, 0) + 1; kept.append(x)
                    if len(kept) >= st.beam: break
                beam[q] = kept
    finals = beam.get(N, [])
    if not finals: raise Infeasible(_why(cands, lib, music, st, A))
    best = max(finals, key=lambda x: x.noisy)
    segs = [Segment(cands[c], lib[A['tech_ids'][t]], k, b, int(rng.integers(1 << 30))) for c, t, k, b in best.segs]
    if st.sa_iters and not st.fixed: segs = anneal(segs, cands, lib, music, st, A, rng)
    ev = evaluate(segs, lib, music, st);
    for sg, parts in zip(segs, ev['parts']): sg.parts = parts
    return segs


def _why(cands, lib, music, st, A):
    """The most likely binding constraint when the search finds no complete plan."""
    target = music.beats * music.beat_s; cap = {}
    for t in lib.values():
        cap[t.id] = t.max_share * target
    msgs = []
    fill = sum(min(max(c.max_dur for c in cands), 8.0) for c in cands)
    if any(c.speech for c in cands) and not any(t.dialogue_ok for t in lib.values() if t.id not in st.bans_techs): msgs.append('dialogue candidates exist but no dialogue-safe technique is allowed')
    hero_room = st.hero_total_share * target
    msgs.append(f'no complete plan of exactly {music.beats} beats satisfies the caps: technique shares and uses, cooldowns, the {st.hero_total_share:.0%} hero limit ({hero_room:.1f} s), '
                f'and one use per candidate; loosen a budget, add candidates, or allow longer clips')
    return '; '.join(msgs)


# -------------------------------------------------------------------------------------------- exact evaluator
def evaluate(segs, lib, music, st=None):
    """Noise-free objective of a plan, computed from scratch with the same terms as the search. Returns dict(score, parts, variety)."""
    st = st or Settings(); total_s = music.beats * music.beat_s; ids = list(lib.keys()); parts = []; score = 0.0
    last = []; secs = {}
    for s in segs:
        c, t, k = s.cand, s.tech, s.beats; d = k * music.beat_s; scale = d ** st.dur_power; f = fit(c, t)
        sig = max((t.dmax - t.dmin) / 3.0, 0.4); durfit = math.exp(-0.5 * ((d - t.dideal) / sig) ** 2)
        base = scale * (st.w_quality * c.quality + st.w_fit * f + st.w_dur * durfit)
        en = st.w_energy * (1.0 - abs(0.5 * c.energy + 0.5 * t.energy - music.energy_at(s.start))) * scale
        en -= st.w_pace * math.log(d / target_len(music.energy_at(s.start))) ** 2 * scale
        en += st.w_first * (1.0 if t.id not in secs else 0.0)
        beat = (st.w_bar if s.start % music.bar_beats == 0 else 0.0) + (st.w_section if music.section_start(s.start) else 0.0)
        pen = 0.0
        for j, prev in enumerate(reversed(last[-st.recent_window:])):
            if prev.id == t.id: pen += (st.pen_hero_recent if t.hero else 1.0) * st.pen_recent * (st.recent_decay ** j)
        if last:
            pen += (st.pen_family if last[-1].family == t.family else 0.0) + (st.pen_scale if last[-1].scale == t.scale else 0.0)
        over = max(0.0, (secs.get(t.id, 0.0) + d) / total_s - st.share_caps.get(t.id, t.max_share) * 0.7); pen += st.pen_share * over ** 2 * scale
        pen *= st.variety
        parts.append(dict(quality=c.quality, fit=round(f, 3), durfit=round(durfit, 3), base=round(base, 3), energy=round(en, 3), beat=round(beat, 3), variety_penalty=round(pen, 3), total=round(base + en + beat - pen, 4)))
        score += base + en + beat - pen; secs[t.id] = secs.get(t.id, 0.0) + d; last.append(t)
    return dict(score=score, parts=parts, variety=variety_report(segs, lib, music))


def variety_report(segs, lib, music):
    total_s = music.beats * music.beat_s; secs = {}
    for s in segs: secs[s.tech.id] = secs.get(s.tech.id, 0.0) + s.beats * music.beat_s
    sh = np.array(list(secs.values())) / total_s; ent = float(-(sh * np.log(sh + 1e-12)).sum())
    run = best = 1
    for a, b in zip(segs, segs[1:]):
        run = run + 1 if a.tech.id == b.tech.id else 1; best = max(best, run)
    pos = {}; mind = 10 ** 6
    for i, s in enumerate(segs):
        if s.tech.id in pos: mind = min(mind, i - pos[s.tech.id])
        pos[s.tech.id] = i
    heroes = [i for i, s in enumerate(segs) if s.tech.hero]
    return dict(shares={k: round(v / total_s, 3) for k, v in sorted(secs.items())}, entropy=round(ent, 3), distinct=len(secs), longest_run=best, min_repeat_distance=None if mind == 10 ** 6 else mind,
                hero_count=len(heroes), hero_positions=heroes, segments=len(segs), shortest_s=round(min(s.beats for s in segs) * music.beat_s, 2), longest_s=round(max(s.beats for s in segs) * music.beat_s, 2))


def violations(segs, lib, music, st=None):
    """Every hard-constraint breach in a plan (empty list = valid). Used by the annealer, by tests, and as the final gate."""
    st = st or Settings(); v = []; total_s = music.beats * music.beat_s; pos = 0; secs = {}; uses = {}; used = set(); grp = set(); last = None; consec = 0; lastpos = {}; hero_s = 0.0
    for i, s in enumerate(segs):
        c, t, k = s.cand, s.tech, s.beats; d = k * music.beat_s
        if s.start != pos: v.append(f'segment {i}: starts at beat {s.start}, expected {pos}')
        pos = s.start + k
        if not (t.dmin - 1e-9 <= d <= t.dmax + 1e-9): v.append(f'segment {i}: {d:.2f} s outside {t.id} range {t.dmin}-{t.dmax}')
        if not (c.min_dur - 1e-9 <= d <= c.max_dur + 1e-9): v.append(f'segment {i}: {d:.2f} s outside the clip handles {c.min_dur}-{c.max_dur}')
        if t.beats == 'bar' and k % music.bar_beats: v.append(f'segment {i}: {t.id} must be whole bars')
        if fit(c, t) is None: v.append(f'segment {i}: {t.id} hard need not met by {c.id}')
        if c.speech and not t.dialogue_ok: v.append(f'segment {i}: dialogue clip {c.id} given {t.id}')
        if c.id in used: v.append(f'segment {i}: candidate {c.id} used twice')
        used.add(c.id)
        g = c.group or f'_{c.id}'
        if g in grp: v.append(f'segment {i}: overlapping candidates from group {g}')
        grp.add(g)
        if c.id in st.bans_cands or t.id in st.bans_techs: v.append(f'segment {i}: banned')
        uses[t.id] = uses.get(t.id, 0) + 1
        if uses[t.id] > st.budgets.get(t.id, t.max_uses): v.append(f'{t.id} used {uses[t.id]} times, budget {st.budgets.get(t.id, t.max_uses)}')
        consec = consec + 1 if last == t.id else 1
        if consec > t.max_consecutive: v.append(f'segment {i}: {t.id} repeated {consec} times in a row (max {t.max_consecutive})')
        if t.id in lastpos and i - lastpos[t.id] <= t.cooldown: v.append(f'segment {i}: {t.id} repeated after {i - lastpos[t.id] - 1} shots, cooldown {t.cooldown}')
        lastpos[t.id] = i; last = t.id; secs[t.id] = secs.get(t.id, 0.0) + d
        if secs[t.id] / total_s > st.share_caps.get(t.id, t.max_share) * st.share_hard + 1e-9: v.append(f'{t.id} share {secs[t.id] / total_s:.2f} over the limit')
        if t.hero: hero_s += d
    if pos != music.beats: v.append(f'plan covers {pos} beats, target {music.beats}')
    if hero_s / total_s > st.hero_total_share + 1e-9: v.append(f'hero effects fill {hero_s / total_s:.2f} of the runtime, limit {st.hero_total_share:.2f}')
    return v


# ------------------------------------------------------------------------------------------------ refinement
def anneal(segs, cands, lib, music, st, A, rng):
    """Seeded simulated annealing over technique swaps, candidate replacements and beat trades between neighbours."""
    cur = list(segs); cur_s = evaluate(cur, lib, music, st)['score']; best, best_s = list(cur), cur_s
    techs = list(lib.values()); T0 = 0.3
    for it in range(st.sa_iters):
        T = T0 * (1 - it / st.sa_iters) + 1e-3; i = int(rng.integers(len(cur))); s = cur[i]; new = list(cur); mv = rng.integers(3)
        if mv == 0:                                                                     # swap technique
            t = techs[int(rng.integers(len(techs)))]
            if t.id == s.tech.id or (s.cand.speech and not t.dialogue_ok) or fit(s.cand, t) is None: continue
            new[i] = Segment(s.cand, t, s.beats, s.start, s.variant_seed)
        elif mv == 1:                                                                   # replace the candidate
            c = cands[int(rng.integers(len(cands)))]
            if c.id == s.cand.id or c.id in st.bans_cands or (c.speech and not s.tech.dialogue_ok) or fit(c, s.tech) is None: continue
            new[i] = Segment(c, s.tech, s.beats, s.start, s.variant_seed)
        elif i + 1 < len(cur):                                                          # trade a beat with the next segment
            dk = int(rng.choice([-1, 1])); a, b = cur[i], cur[i + 1]
            new[i] = Segment(a.cand, a.tech, a.beats + dk, a.start, a.variant_seed); new[i + 1] = Segment(b.cand, b.tech, b.beats - dk, b.start + dk, b.variant_seed)
            if new[i].beats < 1 or new[i + 1].beats < 1: continue
        else: continue
        if violations(new, lib, music, st): continue
        ns = evaluate(new, lib, music, st)['score']
        if ns >= cur_s or rng.random() < math.exp((ns - cur_s) / T):
            cur, cur_s = new, ns
            if cur_s > best_s: best, best_s = list(cur), cur_s
    return best


# ------------------------------------------------------------------------------------------- alternatives
def difference(a, b):
    """Share of segment slots (by start beat) whose candidate, technique or length differs between two plans."""
    da = {s.start: (s.cand.id, s.tech.id, s.beats) for s in a}; db = {s.start: (s.cand.id, s.tech.id, s.beats) for s in b}
    keys = set(da) | set(db); return sum(da.get(k) != db.get(k) for k in keys) / max(len(keys), 1)


def alternatives(cands, lib, music, st, n=3, min_diff=0.3, max_tries=20):
    """Best plan plus up to n-1 alternatives that differ from all earlier ones by at least min_diff (share of segments)."""
    out = []
    for i in range(max_tries):
        s2 = Settings(**{**st.__dict__, 'seed': st.seed + i}); p = plan(cands, lib, music, s2)
        if all(difference(p, q) >= min_diff for q in out): out.append(p)
        if len(out) >= n: break
    return out


def baseline_greedy(cands, lib, music, st=None):
    """Reference: fill the music with the highest-value option at each step, ignoring variety (for comparison in tests)."""
    st = Settings(**{**(st or Settings()).__dict__, 'variety': 0.0, 'temperature': 0.0, 'sa_iters': 0, 'beam': 8, 'expand': 3, 'pen_share': 0.0})
    return plan(cands, lib, music, st)
