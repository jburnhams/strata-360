"""Re-size the blocks to the measured voice-over (implementation plan V4; overview 17.1 step 6).

Input: the rough plan's blocks (`edit/blocks.py`), the block script (`script.write_block_script`), the measured lines (`vo_measure.measure_script`, `vo.json`) and, optionally, the music's
analysis (`edit/music.py`) or a target length. Output: every block's length and start in the film, every line's provisional start and end in film time, the film length and where the
music sits, plus everything that did not fit, each with the choices open to the user.

A block's length is its lead-in, its lines (as measured), the pauses between them, its dialogue (padded) and its lead-out, never less than the block's minimum. Lines are laid out in
this order: the lines before the dialogue, the dialogue gap, the lines after it. A block never needs more than its usable footage: when it would, a **synthetic** line is first
played faster (one factor for the block's synthetic lines, at most `max_tempo`, 1.25 as before; the voice-over is re-spoken at that speed, not time-stretched), and only the
remainder is reported as an overflow. A recording is never changed.

Film length (D7): the film is never shorter than the voice-over V (the sum of the blocks) and ideally as long as the music M (from its first downbeat). When M > V the difference is spread
over the blocks (longer holds and pauses, a music-only intro and outro of a few bars) as far as the footage allows; what cannot be filled is cut from the music's end with a fade, and
reported when it is more than `fade_max_s`. When M < V the film is V and the music sits inside it with silence before and after, each within its limit; what does not fit is reported."""
import math
from dataclasses import dataclass, field, asdict

from strata360.edit import vo_measure as M


@dataclass
class FitSettings:
    gap_s: float = 0.4                # pause between two lines (and around the dialogue)
    paragraph_gap_s: float = 0.9      # pause after a line marked `paragraph_after`
    lead_in_s: float = 0.5            # picture before a block's first sound, so a line never starts on a cut
    lead_out_s: float = 0.5
    max_tempo: float = 1.25           # fastest a synthetic line may be played to fit its footage
    fade_max_s: float = 8.0           # most of the music that may be lost to an early fade-out
    lead_silence_max_s: float = 4.0   # silence before the music starts
    tail_silence_max_s: float = 6.0   # silence after it ends
    intro_bars: int = 2               # music-only picture at the start and the end, at most this many bars each
    outro_bars: int = 2
    words_per_minute: float = 150.0   # for a line that was never measured


CHOICES_OVERFLOW = ['shorten the line', 'borrow time from the next block', 'allow a hold on the last frame']
CHOICES_MUSIC_SHORT = ['pick a longer track', 'loop a section of the track at a bar line', 'shorten the script']
CHOICES_MUSIC_LONG = ['add footage or clips', 'pick a shorter track', 'accept the earlier fade-out']


@dataclass
class PlacedLine:
    key: str
    block: int
    anchor: str | None
    text: str
    take: str | None            # 'synth' | 'recorded' | None (not measured)
    start_s: float = 0.0        # film time
    end_s: float = 0.0
    natural_speech_s: float = 0.0
    tempo: float = 1.0
    estimated: bool = False     # the length is a guess from the words (no usable measurement)
    applied: float = 1.0        # speed already in the measured audio (the line was re-spoken faster); the limit counts it


@dataclass
class FitBlock:
    clip: str
    index: int
    start_s: float = 0.0
    length_s: float = 0.0
    voiced_s: float = 0.0       # what the lines, pauses, dialogue and lead-in/out need
    min_s: float = 0.0
    cap_s: float = 0.0          # the block's usable footage
    lead_in_s: float = 0.0
    lead_out_s: float = 0.0
    extra_s: float = 0.0        # added to reach the film length
    overflow_s: float = 0.0     # needed beyond the usable footage (a hold, or fix the script)
    tempo: float = 1.0          # factor applied to the block's synthetic lines
    dialogue_s: float = 0.0
    dialogue_start_s: float | None = None
    dialogue_end_s: float | None = None
    lines: list = field(default_factory=list)

    @property
    def end_s(self): return self.start_s + self.length_s


@dataclass
class Fit:
    blocks: list
    voice_over_s: float         # V: the sum of the blocks as the voice-over needs them
    film_length_s: float        # L >= V
    target_s: float | None      # what was aimed for (the music's length, or the target length)
    music: dict | None
    intro_s: float = 0.0
    outro_s: float = 0.0
    problems: list = field(default_factory=list)       # overflows and shortfalls, each with `choices`
    warnings: list = field(default_factory=list)

    def to_dict(self): return asdict(self)


def _speech_s(m, text, fs):
    """(seconds of speech, estimated?) of a measured line; a line with no usable measurement is estimated from its words."""
    if m and m.get('status') not in (None, 'missing', 'silent') and m.get('speech_start_s') is not None and m.get('speech_end_s') is not None:
        return max(m['speech_end_s'] - m['speech_start_s'], 0.0), False
    return max(len(text.split()), 1) * 60.0 / fs.words_per_minute, True


def _as_dict(b): return b if isinstance(b, dict) else b.to_dict()


def _sequence(block, lines, fs):
    """The block's body in order: [('line', i) | ('gap', seconds) | ('dialogue', seconds)]."""
    has_d = block['dialogue_s'] > 0; before = [i for i, l in enumerate(lines) if (l.anchor != 'after') or not has_d]; after = [i for i, l in enumerate(lines) if has_d and l.anchor == 'after']
    seq = []
    def put(ids):
        for i in ids:
            if seq and seq[-1][0] != 'gap': seq.append(('gap', fs.gap_s))
            seq.append(('line', i))
    put(before)
    if has_d:
        if seq: seq.append(('gap', fs.gap_s))
        seq.append(('dialogue', block['dialogue_s']))
    put(after)
    return seq


def _paragraph_gaps(seq, lines, para, fs):
    """A line marked `paragraph_after` is followed by the longer pause."""
    out = []
    for n, item in enumerate(seq):
        if item[0] == 'gap' and n > 0 and seq[n - 1][0] == 'line' and para.get(seq[n - 1][1]): out.append(('gap', fs.paragraph_gap_s))
        else: out.append(item)
    return out


def _body(seq, lines):
    return sum((v if k != 'line' else lines[v].natural_speech_s / lines[v].tempo) for k, v in seq)


def fit(plan, script, vo, music=None, target_s=None, settings=None):
    """plan: a blocks.RoughPlan (or its dict); script: the block script document; vo: the vo.json document (or None: every line is estimated); music: the analysis dict of the track
    (`duration_s`, `offset_s`, `bpm`, `bar_beats`) or None; target_s: a length to aim for when there is no music. Returns a Fit."""
    fs = settings or FitSettings(); pd = plan if isinstance(plan, dict) else plan.to_dict(); blocks = [_as_dict(b) for b in pd['blocks']]; warnings = list(pd.get('warnings') or []); problems = []
    meas = {l['key']: l for l in (vo or {}).get('lines', [])}; by_block = {b['index']: [] for b in blocks}; para = {}
    for key, l in M.line_keys(script):
        t = (l.get('text') or '').strip()
        if not t: continue
        if l['block'] not in by_block: warnings.append(f"line {key} belongs to block {l['block']}, which is not in the plan: left out"); continue
        m = meas.get(key); s, est = _speech_s(m, t, fs)
        by_block[l['block']].append(PlacedLine(key, l['block'], l.get('anchor'), t, (m or {}).get('take'), natural_speech_s=round(s, 3), estimated=est, applied=float((m or {}).get('tempo_applied') or 1.0)))
        para[(l['block'], key)] = bool(l.get('paragraph_after'))
        if est: warnings.append(f"line {key} has no usable measurement ({(m or {}).get('status', 'not measured')}): its length is estimated from the words")
    fbs = []
    for b in blocks:
        lines = by_block[b['index']]; fb = FitBlock(clip=b['clip'], index=b['index'], min_s=b['min_s'], cap_s=b['max_s'], dialogue_s=b['dialogue_s'], lines=lines)
        seq = _paragraph_gaps(_sequence(b, lines, fs), lines, {i: para.get((b['index'], l.key)) for i, l in enumerate(lines)}, fs)
        fb._seq = seq                                                                                       # type: ignore[attr-defined]
        def need(): return (fs.lead_in_s + _body(seq, lines) + fs.lead_out_s) if seq else 0.0
        n = max(need(), fb.min_s)
        if n > fb.cap_s + 1e-9:                                                                              # too long for the footage: play the synthetic lines faster, within the limit
            syn = [l for l in lines if l.take == 'synth' or (l.take is None and l.estimated)]; S = sum(l.natural_speech_s for l in syn); r = n - fb.cap_s
            room = [fs.max_tempo / l.applied for l in syn]                                                   # how much faster each line may still go
            if S > r + 1e-9:
                f = min([S / (S - r)] + room); f = math.ceil(f * 1000 - 1e-9) / 1000
                for l, h in zip(syn, room): l.tempo = min(f, h)
            else:
                for l, h in zip(syn, room): l.tempo = h
            n = max(need(), fb.min_s)
        fb.tempo = max([l.tempo * l.applied for l in lines] or [1.0]); fb.voiced_s = round(n, 4); fb.length_s = n; fb.lead_in_s = fs.lead_in_s if seq else 0.0; fb.lead_out_s = fs.lead_out_s if seq else 0.0
        if seq: fb.lead_out_s += max(n - need(), 0.0)                                                         # a block held at its minimum: the spare time is lead-out
        else: fb.lead_in_s = n / 2; fb.lead_out_s = n / 2
        if n > fb.cap_s + 1e-9:
            fb.overflow_s = round(n - fb.cap_s, 3); longest = max(lines, key=lambda l: l.natural_speech_s / l.tempo, default=None)
            problems.append(dict(kind='overflow', block=b['index'], clip=b['clip'], line=longest.key if longest else None, needs_s=round(n, 2), usable_s=round(fb.cap_s, 2), overflow_s=fb.overflow_s,
                                 message=f"line {longest.key if longest else '-'} needs {n:.1f} s; clip {b['clip']} has {fb.cap_s:.1f} s usable" + (f" (voice already sped up {fb.tempo:.2f}x)" if fb.tempo > 1 else ''), choices=CHOICES_OVERFLOW))
        fbs.append(fb)
    V = sum(fb.length_s for fb in fbs)
    bar_s = (music['bar_beats'] * 60.0 / music['bpm']) if music else None
    M_s = max(float(music['duration_s']) - float(music.get('offset_s') or 0.0), 0.0) if music else None
    T = M_s if music else (float(target_s) if target_s else None)
    intro = outro = 0.0; unfilled = 0.0
    if T is not None and T > V + 1e-9 and fbs:
        E = T - V
        if bar_s:                                                                                              # a music-only intro and outro, a few bars each, but never more than a quarter of the extra
            intro = min(fs.intro_bars * bar_s, E / 4, max(fbs[0].cap_s - fbs[0].length_s, 0.0)); outro = min(fs.outro_bars * bar_s, E / 4, max(fbs[-1].cap_s - fbs[-1].length_s, 0.0))
            fbs[0].lead_in_s += intro; fbs[0].length_s += intro; fbs[-1].lead_out_s += outro; fbs[-1].length_s += outro; fbs[0].extra_s += intro; fbs[-1].extra_s += outro
        left = E - intro - outro; w = {fb.index: max(b['target_s'], 0.5) for fb, b in zip(fbs, blocks)}
        for _ in range(len(fbs) + 2):                                                                          # water-filling: by weight, no block beyond its footage
            act = [fb for fb in fbs if fb.cap_s - fb.length_s > 1e-9]
            if left <= 1e-9 or not act: break
            tw = sum(w[fb.index] for fb in act); given = 0.0
            for fb in act:
                x = min(left * w[fb.index] / tw, fb.cap_s - fb.length_s); fb.length_s += x; fb.extra_s += x; fb.lead_in_s += x / 2; fb.lead_out_s += x / 2; given += x
            left -= given
        unfilled = max(left, 0.0)
    elif T is not None and V > T + 1e-9 and not music: warnings.append(f"the voice-over ({V:.1f} s) is longer than the {T:.0f} s target: the film is {V:.1f} s")
    t = 0.0
    for fb in fbs:
        fb.start_s = round(t, 4); t += fb.length_s; fb.length_s = round(fb.length_s, 4)
        pos = fb.start_s + fb.lead_in_s; lines = fb.lines
        for kind, v in fb._seq:                                                                              # type: ignore[attr-defined]
            if kind == 'line':
                l = lines[v]; d = l.natural_speech_s / l.tempo; l.start_s = round(pos, 4); l.end_s = round(pos + d, 4); pos += d
            elif kind == 'dialogue': fb.dialogue_start_s = round(pos, 4); fb.dialogue_end_s = round(pos + v, 4); pos += v
            else: pos += v
        del fb._seq                                                                                          # type: ignore[attr-defined]
    L = round(sum(fb.length_s for fb in fbs), 4); mus = None
    if music:
        if unfilled > 1e-9:                                                                                  # the footage ran out: the music is cut at the film's end with a fade
            fade = min(max(bar_s, 2.0), L)
            mus = dict(start_s=0.0, end_s=L, length_s=round(M_s, 3), fade_out_s=round(fade, 3), cut_s=round(unfilled, 3), lead_silence_s=0.0, tail_silence_s=0.0, unplaced_s=0.0)
            if unfilled > fs.fade_max_s + 1e-9:
                out = [fb.clip for fb in fbs if fb.cap_s - fb.length_s <= 1e-9]
                problems.append(dict(kind='music_cut', lost_s=round(unfilled, 2), limit_s=fs.fade_max_s, clips=out, message=f"{unfilled:.1f} s of the music is lost (limit {fs.fade_max_s:.0f} s): these clips ran out of footage: {', '.join(out)}", choices=CHOICES_MUSIC_LONG))
        else:
            gap = max(L - M_s, 0.0); tail = min(fs.tail_silence_max_s, gap / 2); lead = min(fs.lead_silence_max_s, gap - tail); tail = min(fs.tail_silence_max_s, gap - lead); unplaced = max(gap - lead - tail, 0.0)
            mus = dict(start_s=round(lead, 3), end_s=round(lead + M_s, 3), length_s=round(M_s, 3), fade_out_s=0.0, cut_s=0.0, lead_silence_s=round(lead, 3), tail_silence_s=round(tail, 3), unplaced_s=round(unplaced, 3))
            if unplaced > 1e-9:
                problems.append(dict(kind='music_short', short_s=round(unplaced, 2), message=f"the music ({M_s:.1f} s) is {unplaced:.1f} s too short for the {L:.1f} s film beyond the allowed silence ({fs.lead_silence_max_s:.0f} s before, {fs.tail_silence_max_s:.0f} s after)", choices=CHOICES_MUSIC_SHORT))
    elif unfilled > 1e-9: warnings.append(f"not enough footage to reach the {T:.0f} s target: the film is {L:.1f} s")
    return Fit(fbs, round(V, 4), L, None if T is None else round(T, 3), mus, round(intro, 3), round(outro, 3), problems, warnings)


def respeak(folder, f, script, engine_state=None, aligner=None):
    """Speak again, faster, every synthetic line the fit sped up: the voice is asked for `rate x tempo` words a minute (not time-stretched, which sounds worse), the new audio is measured
    and the measurement replaces the line's in `vo.json` with `tempo_applied` set. Returns the keys of the lines re-spoken. Run `fit` again afterwards to use the real lengths."""
    from strata360.edit import voiceover as V
    vo = M.load(folder) or dict(lines=[]); st = engine_state or V.load_state(folder); engine, voice = V.pick(st); by = {l['key']: l for l in vo['lines']}; done = []; texts = {k: l['text'] for k, l in M.line_keys(script)}
    for fb in f.blocks:
        for l in fb.lines:
            if l.tempo <= 1.0 + 1e-9 or l.take != 'synth' or l.key not in by: continue
            total = round(l.tempo * l.applied, 3); rate = int(round(st['rate'] * total))
            p = V.synth_line(folder, l.key, texts[l.key], engine, voice, rate)
            by[l.key].update(M.measure_take(p, texts[l.key], aligner), file=__import__('os').path.relpath(p, V.base(folder)), tempo_applied=total, sig=None); done.append(l.key)
    if done: M.save(folder, vo)
    return done


def fit_project(folder, plan, script, music=None, target_s=None, settings=None, aligner=None):
    """The whole step for a project: measure the lines (reusing what is unchanged), fit, re-speak the lines that were sped up, and fit again with their real lengths."""
    vo = M.measure_script(folder, script, aligner); f = fit(plan, script, vo, music, target_s, settings)
    if respeak(folder, f, script, aligner=aligner): f = fit(plan, script, M.load(folder), music, target_s, settings)
    return f
