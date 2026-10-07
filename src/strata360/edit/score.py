"""The score plan for the film's music (Milestone G2, docs/ai-music.md 4.2 to 4.5): which bars of the film are the uploaded track's own audio, which are generated, and where the original is sung. Pure: it takes numbers and returns a plan, so every rule is tested without audio.

  quiet_bars(n_bars, bar_s, speech) -> [bool per bar]   no voice-over or clip speech touches the bar
  sung_window(phrase, downbeats, film_t, bar_s, n_bars) -> dict(first, end, phrase_bar, offset_beats, shift_s)   a sung phrase placed on its own beat of a bar, with a bar of lead-in and lead-out
  place_sung(phrases, downbeats, bar_s, n_bars, speech, ...) -> (windows, rejected)   the moments that fit, and those that did not with why
  sections(levels, phrase_bars) -> [dict(first, end, level)]   the film cut where the intensity level changes
  plan(levels, bar_s, energy, sim=None, fidelity=0.75, sung=(), pins=None, phrase_bars=4) -> dict(sections, share_original, unreachable, fidelity, key_of each section)

Fidelity (4.5): one 0..1 setting. Every section is given a mismatch, how far the track's own bars are from the section's level, which does not depend on the setting. A section plays the original when its mismatch is within a tolerance that widens as fidelity rises, so the share of original bars never falls as the slider goes up. At 1.0 nothing is generated; at 0.0 no original audio plays outside the sung moments. A pin ('original' or 'generate') ignores the slider. The key of a section covers only what changes its sound (source, strength, reference, level, bars), so moving the slider rebuilds only the sections whose key moved."""
import hashlib, json, math
import numpy as np

SING_LEAD_BARS = 1                     # a bar before and after the sung phrase
MAX_SING = 4                           # sung moments in one film
MIN_SING_GAP_S = 30.0                  # two sung moments closer than this are too close
MISMATCH_TOLERANCE = 0.35              # at fidelity just under 1, an original stretch this far from the level is still accepted
UNREACHABLE = 0.45                     # the original has nothing within this of the level: reported, not hidden
FORM_B_BELOW = 0.5                     # below this fidelity a sung moment is the vocal stem over the film's own accompaniment (4.3 b)
REPAINT_FROM = 0.75                    # at and above this a generated bar grows out of the neighbouring original bars


def quiet_bars(n_bars, bar_s, speech):
    """True for each film bar that no span in `speech` [(t0, t1) seconds] touches."""
    q = np.ones(n_bars, bool)
    for a, b in speech:
        if b <= a: continue
        q[max(0, int(a // bar_s)):min(n_bars, int(-(-b // bar_s)))] = False
    return [bool(v) for v in q]


def sung_window(phrase, downbeats, film_t, bar_s, n_bars, lead=SING_LEAD_BARS):
    """Place a phrase ({t0, t1} in the original track's seconds) so its first sung moment is on the same beat of a bar as in the original. `film_t` is where the director put the item; the window starts on the nearest bar line, so the item moves by at most half a bar. Returns the window in film bars [first, end), the film bar the phrase starts in, its offset into that bar as a share of the bar, and the shift of the item in seconds."""
    d = np.asarray(downbeats, float); src_bar = int(np.clip(np.searchsorted(d, phrase['t0'], 'right') - 1, 0, len(d) - 2)); src_bar_s = float(d[src_bar + 1] - d[src_bar])
    offset = float(np.clip((phrase['t0'] - d[src_bar]) / src_bar_s, 0, 0.999)); length = max(phrase['t1'] - phrase['t0'], 0.0) / bar_s
    first = int(round(film_t / bar_s)); phrase_bar = first + lead; end = phrase_bar + int(math.ceil(offset + length - 1e-9)) + lead
    return dict(first=first, end=end, phrase_bar=phrase_bar, offset=round(offset, 3), shift_s=round(first * bar_s - film_t, 3), phrase_s=round(phrase['t1'] - phrase['t0'], 2))


def place_sung(items, downbeats, bar_s, n_bars, speech=(), max_sing=MAX_SING, min_gap_s=MIN_SING_GAP_S):
    """items: [{phrase: {id, t0, t1}, film_t}] in the order the director gave them. Returns (placed, rejected): placed are sung_window dicts with the phrase id; rejected are {id, why} for a moment beyond the limit, too close to an earlier one, past the end of the film, or with voice-over or clip speech inside its window (never squeezed in)."""
    quiet = quiet_bars(n_bars, bar_s, speech); placed = []; rejected = []
    for it in sorted(items, key=lambda i: i['film_t']):
        pid = it['phrase'].get('id'); w = sung_window(it['phrase'], downbeats, it['film_t'], bar_s, n_bars); w['id'] = pid
        if len(placed) >= max_sing: rejected.append(dict(id=pid, why=f'more than {max_sing} sung moments')); continue
        if w['first'] < 0 or w['end'] > n_bars: rejected.append(dict(id=pid, why='the window runs past the film')); continue
        if placed and (w['first'] - placed[-1]['end']) * bar_s < min_gap_s: rejected.append(dict(id=pid, why=f'closer than {min_gap_s:g} s to the sung moment before')); continue
        if not all(quiet[w['first']:w['end']]): rejected.append(dict(id=pid, why='voice-over or speech inside the window')); continue
        placed.append(w)
    return placed, rejected


def sections(levels, phrase_bars=4):
    """The film cut into runs of equal level (the curve only changes on phrase boundaries): [{first, end, level}]."""
    lv = list(levels); out = []
    for i, v in enumerate(lv):
        if out and abs(out[-1]['level'] - v) < 1e-9: out[-1]['end'] = i + 1
        else: out.append(dict(first=i, end=i + 1, level=float(v)))
    return out


def mismatch(level, energy, sim=None):
    """How far the original's bars are from `level`: the distance to the nearest bar's energy, 0 when some bar matches. (`sim` is accepted for the join quality of a later version; unused.)"""
    e = np.asarray(energy, float); return float(np.abs(e - level).min()) if e.size else 1.0


def tolerance(fidelity):
    """The mismatch an original stretch may have and still be used. 0 at fidelity 0 (never), unlimited at 1, growing with the setting between."""
    if fidelity >= 1.0: return float('inf')
    if fidelity <= 0.0: return -1.0
    return MISMATCH_TOLERANCE * fidelity / (1.0 - fidelity * 0.65)


def reference_strength(fidelity):
    """How strongly a generated section follows the original's audio: none at 0, rising with fidelity."""
    return 0.0 if fidelity <= 0.0 else round(min(1.0, fidelity) ** 1.5, 2)


def plan(levels, bar_s, energy, fidelity=0.75, sung=(), pins=None, phrase_bars=4):
    """levels: 0..1 per film bar; energy: 0..1 per bar of the original; sung: placed windows from place_sung (film bars); pins: {first bar of a section: 'original' | 'generate'}. Returns the sections, each with its source ('original' | 'generate'), its mismatch, whether it was pinned, its reference strength and repaint flag when generated, and a key; and the sung moments with their form ('a' the original's own bars, 'b' its vocal stem over the film's own accompaniment)."""
    fidelity = float(min(max(fidelity, 0.0), 1.0)); pins = pins or {}; tol = tolerance(fidelity); out = []; unreachable = []
    sung_bars = np.zeros(len(levels), bool)
    for w in sung: sung_bars[max(0, w['first']):max(0, w['end'])] = True
    for s in sections(levels, phrase_bars):
        m = mismatch(s['level'], energy); pin = pins.get(s['first']); touches = bool(sung_bars[s['first']:s['end']].any())
        if pin in ('original', 'generate'): src = pin
        elif fidelity <= 0.0: src = 'generate'
        elif fidelity >= 1.0: src = 'original'
        else: src = 'original' if m <= tol else 'generate'
        if fidelity >= 1.0 and m > UNREACHABLE and src == 'original': unreachable.append(s['first'])
        d = dict(s, source=src, mismatch=round(m, 3), pinned=pin is not None, sung=touches)
        if src == 'generate': d.update(strength=reference_strength(fidelity), repaint=fidelity >= REPAINT_FROM)
        d['key'] = section_key(d); out.append(d)
    form = 'a' if fidelity >= FORM_B_BELOW else 'b'; moments = [dict(w, form=form) for w in sung]
    n = sum(s['end'] - s['first'] for s in out); orig = sum(s['end'] - s['first'] for s in out if s['source'] == 'original')
    return dict(fidelity=fidelity, sections=out, sung=moments, share_original=round(orig / n, 3) if n else 0.0, unreachable=sorted(set(unreachable)))


def section_key(s):
    """What a take of this section depends on: nothing about the slider itself, only what it set."""
    body = [s['first'], s['end'], s['level'], s['source'], s.get('strength'), s.get('repaint'), s.get('sung')]
    return hashlib.sha1(json.dumps(body).encode()).hexdigest()[:10]
