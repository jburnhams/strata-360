"""The subtitle track of the film: what the voice-over says and what the runner and others say, as text along the bottom of the picture, in the preview and in the final film, and as an .srt beside each.

Cues come from two places and are in FILM time:
  voice-over   voiceover/timings.json: every line with where it starts in the film and how long it plays; a long line is cut into phrases timed by their length
  speech       the transcript of each footage window of the plan (clip times become film times through the segment's film_start_s), English where the clip is in another language, with the Gemini word corrections applied;
               segments flagged as hallucinated or suspect are left out
`Captions.apply(img, frame)` draws the cue of that film frame (a copy; unchanged when there is none): white, outlined and shadowed, wrapped to two lines, faded in and out over a tenth of a second. A voice-over cue and a speech cue at the same
moment are stacked (the voice-over lower). The subtitles are a TRACK the player shows (an embedded mov_text track in the final film's mp4, WebVTT beside the preview), never burned into the picture unless STRATA_SUBTITLES=burn; the word-art cards are part of the picture."""
import json, os, re
import numpy as np

MAX_CHARS = 64                      # a cue's text, before it is cut into two
MAX_WORDS_SPEECH = 9
FADE_S = 0.12
STYLE = dict(vo=dict(font='dm_serif_italic', size=0.047, color=(1.0, 0.96, 0.84)), speech=dict(font='barlow', size=0.042, color=(1.0, 1.0, 1.0)))


def split_phrases(text, t0, t1, max_chars=MAX_CHARS):
    """[(t0, t1, text)] of a line cut at sentence ends and commas into pieces of at most `max_chars`, each timed by its share of the characters."""
    text = re.sub(r'\s+', ' ', str(text)).strip()
    if not text: return []
    parts = re.findall(r'[^.!?;:]+[.!?;:]*\s*', text); pieces = []
    for p in parts:
        p = p.strip()
        while len(p) > max_chars:
            cut = max([m.end() for m in re.finditer(r',\s', p[:max_chars])] or [p.rfind(' ', 0, max_chars) + 1 or max_chars]); pieces.append(p[:cut].strip()); p = p[cut:].strip()
        if p: pieces.append(p)
    total = sum(len(p) for p in pieces) or 1; out = []; t = t0
    for p in pieces: d = (t1 - t0) * len(p) / total; out.append((round(t, 3), round(t + d, 3), p)); t += d
    return out


def vo_cues(folder):
    from strata360.pipeline import config
    p = os.path.join(config.race_dir(folder), 'voiceover', 'timings.json')
    try: d = json.load(open(p))
    except (OSError, ValueError): return []
    out = []
    for ln in d.get('lines', []):
        t0 = float(ln.get('film_start_s') or 0.0); dur = float(ln.get('played_s') or ln.get('natural_s') or 0.0)
        for a, b, tx in split_phrases(ln.get('text', ''), t0, t0 + dur): out.append(dict(t0=a, t1=b, text=tx, kind='vo'))
    return out


def corrected_words(seg, edits, i):
    """The words of transcript segment `i` as (start, end, text) with the Gemini corrections applied (a correction that empties a word removes it)."""
    out = []
    for j, w in enumerate(seg.get('words') or []):
        e = ((edits.get(f'{i}:{j}') or {}).get('gemini') or {}).get('text'); txt = w['w'] if e is None else e
        if str(txt).strip(): out.append((float(w['t0']), float(w['t1']), str(txt).strip()))
    return out


def speech_cues(folder, plan):
    from strata360.pipeline import config
    out = []
    for g in plan['segments']:
        if g.get('synthetic'): continue
        d = os.path.join(config.race_dir(folder), 'clips', g['clip'])
        try: tj = json.load(open(os.path.join(d, 'transcript.json')))
        except (OSError, ValueError): continue
        try: edits = json.load(open(os.path.join(d, 'transcript_edits.json'))).get('edits', {})
        except (OSError, ValueError): edits = {}
        c0, c1, f0 = float(g['clip_start_s']), float(g['clip_start_s']) + float(g['dur_s']), float(g['film_start_s'])
        for i, s in enumerate(tj.get('segments', [])):
            if s.get('flags') or s.get('suspect') or s['t1'] < c0 or s['t0'] > c1: continue
            english = s.get('lang', 'en') == 'en' or not s.get('text_en')
            if english: words = [w for w in corrected_words(s, edits, i) if c0 <= w[0] < c1]
            else:
                ts = [max(s['t0'], c0), min(s['t1'], c1)]; ws = (s.get('text_en') or '').split(); words = [(ts[0] + (ts[1] - ts[0]) * k / max(len(ws), 1), ts[0] + (ts[1] - ts[0]) * (k + 1) / max(len(ws), 1), w) for k, w in enumerate(ws)]
            chunks = []; cur = []
            for w in words:                                                                                       # a new cue at a pause, after a sentence end, or at nine words
                if cur and (w[0] - cur[-1][1] > 0.6 or len(cur) >= MAX_WORDS_SPEECH or cur[-1][2][-1:] in '.!?'): chunks.append(cur); cur = []
                cur.append(w)
            if cur: chunks.append(cur)
            for chunk in chunks:
                a, b = f0 + chunk[0][0] - c0, f0 + chunk[-1][1] - c0; out.append(dict(t0=round(a, 3), t1=round(max(b, a + 0.8), 3), text=' '.join(w[2] for w in chunk), kind='speech'))
    return out


def build_cues(folder, plan):
    """All cues of a plan in film time, sorted; a cue never runs into the next of its own kind."""
    cues = vo_cues(folder) + speech_cues(folder, plan); cues.sort(key=lambda c: (c['t0'], c['kind']))
    for kind in ('vo', 'speech'):
        mine = [c for c in cues if c['kind'] == kind]
        for a, b in zip(mine, mine[1:]): a['t1'] = round(min(a['t1'], b['t0']), 3) if b['t0'] > a['t0'] else a['t1']
    return [c for c in cues if c['t1'] - c['t0'] > 0.15]


def srt_time(t):
    t = max(t, 0.0); h, r = divmod(int(round(t * 1000)), 3600000); m, r = divmod(r, 60000); s, ms = divmod(r, 1000); return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def vtt_time(t): return srt_time(t).replace(',', '.')


def write_vtt(cues, path):
    """The cues as WebVTT, which a browser's video element shows as a track."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write('WEBVTT\n\n')
        for c in cues: f.write(f"{vtt_time(c['t0'])} --> {vtt_time(c['t1'])}\n{c['text']}\n\n")
    return path


def write_srt(cues, path):
    with open(path, 'w', encoding='utf-8') as f:
        for i, c in enumerate(cues, 1): f.write(f"{i}\n{srt_time(c['t0'])} --> {srt_time(c['t1'])}\n{c['text']}\n\n")
    return path


class Cards:
    """The word-art cards of film_text.json (edit/film_text.py), drawn by film time."""
    def __init__(self, cards, W, H, fps):
        self.cards = [(float(c['t']), float(c['t']) + float(c['dur_s']), c['spec'], float(c['dur_s'])) for c in cards if c.get('spec')]; self.W, self.H, self.fps = W, H, fps; self._t = {}

    def apply(self, img, frame, bgr=False):
        t = frame / self.fps
        for i, (a, b, spec, dur) in enumerate(self.cards):
            if not (a <= t <= b + 0.3): continue
            if i not in self._t:
                from strata360.render import titles as TT
                self._t[i] = TT.Title(spec, img.shape[1], img.shape[0], dur)
            rgb = np.ascontiguousarray(img[..., ::-1]) if bgr else img; out = self._t[i].apply(rgb, t - a); img = np.ascontiguousarray(out[..., ::-1]) if bgr else out
        return img


class Captions:
    def __init__(self, cues, W, H, fps, burn=None, cards=None):
        self.cues, self.W, self.H, self.fps, self.cards = cues, W, H, fps, cards; self.burn = (os.environ.get('STRATA_SUBTITLES') == 'burn') if burn is None else burn; self._t0 = np.array([c['t0'] for c in cues] or [0.0]); self._cache = {}

    @classmethod
    def for_project(cls, folder, plan, W, H, fps, key=None):
        """The track of a project: its subtitle cues and, when film_text.json was made for this plan (`key` is the plan's key as the preview makes it), its word-art cards."""
        cards = None
        if os.environ.get('STRATA_FILM_TEXT') != 'off':
            from strata360.pipeline import config
            try: doc = json.load(open(os.path.join(config.race_dir(folder), 'film_text.json')))
            except (OSError, ValueError): doc = None
            if doc and (key is None or doc.get('plan_key') in (None, key)): cards = Cards(doc.get('cards') or [], W, H, fps)
            elif doc: print('film_text.json was made for another plan: its cards are not drawn (strata360 filmtext makes them again)')
        return cls(build_cues(folder, plan), W, H, fps, cards=cards)

    def active(self, t):
        return [c for c in self.cues if c['t0'] <= t < c['t1']]

    def boxes(self, t0, t1, W=None, H=None):
        """[(x0, y0, x1, y1)] as fractions of the frame: where the subtitle cues that are on at any time in [t0, t1] are drawn (the same geometry `apply` uses), so other text can keep clear of them."""
        from strata360.render import titles as TT
        W, H = W or self.W, H or self.H; out = []; slot = 0.0
        for cue in sorted([c for c in self.cues if c['t0'] < t1 and c['t1'] > t0], key=lambda c: (c['t0'], 0 if c['kind'] == 'vo' else 1)):
            st = STYLE[cue['kind']]; px = st['size'] * H; f = TT.font(st['font'], px); lines = self._lines(cue); bh = px * 1.25 * len(lines) + px * 0.2; mw = max(f.getlength(l) for l in lines)
            y1 = H - 0.075 * H - (0.0 if cue['kind'] == 'vo' else bh + px * 0.3); out.append(((W - mw) / 2 / W, (y1 - bh) / H, (W + mw) / 2 / W, y1 / H))
        return out

    def _lines(self, cue):
        key = (cue['text'], cue['kind'])
        if key in self._cache: return self._cache[key]
        from strata360.render import titles as TT
        st = STYLE[cue['kind']]; px = st['size'] * self.H; f = TT.font(st['font'], px); words = cue['text'].split(); lines = []; cur = ''; limit = 0.82 * self.W
        for w in words:
            trial = (cur + ' ' + w).strip()
            if f.getlength(trial) <= limit or not cur: cur = trial
            else: lines.append(cur); cur = w
        if cur: lines.append(cur)
        if len(lines) > 2:                                                                                      # more than two lines: balance them into two
            half = len(words) // 2; lines = [' '.join(words[:half]), ' '.join(words[half:])]
        self._cache[key] = lines; return lines

    def apply(self, img, frame, bgr=False):
        """img: (H, W, 3) uint8 or uint16 (RGB, or BGR with `bgr`); returns it with the word-art cards of film frame `frame` drawn and, only when subtitles are burned in (`burn`), its subtitle (the same array when there is nothing to draw)."""
        if self.cards is not None: img = self.cards.apply(img, frame, bgr)
        if not self.burn or not self.cues: return img
        t = frame / self.fps; act = self.active(t)
        if not act: return img
        import cv2
        from PIL import Image, ImageDraw
        from strata360.render import titles as TT
        H, W = img.shape[:2]; top = 255.0 if img.dtype == np.uint8 else 65535.0; out = img.copy(); slot_y = 0.0
        for cue in sorted(act, key=lambda c: 0 if c['kind'] == 'vo' else 1):
            al = float(np.clip(min((t - cue['t0']) / FADE_S, (cue['t1'] - t) / FADE_S), 0, 1)); st = STYLE[cue['kind']]; px = st['size'] * H; f = TT.font(st['font'], px); lines = self._lines(cue); lh = px * 1.25; bh = lh * len(lines) + px * 0.2
            y1 = H - 0.075 * H - slot_y; y0 = y1 - bh; slot_y += bh + px * 0.3; mw = max(f.getlength(l) for l in lines); pad = int(px * 0.5)
            x0, xe = int(max((W - mw) / 2 - pad, 0)), int(min((W + mw) / 2 + pad, W)); ya, yb = int(max(y0 - pad, 0)), int(min(y1 + pad, H))
            tile = Image.new('L', (xe - x0, yb - ya), 0); dr = ImageDraw.Draw(tile); sw = max(int(round(px * 0.09)), 1)
            for k, l in enumerate(lines): dr.text(((xe - x0 - f.getlength(l)) / 2, y0 - ya + k * lh), l, font=f, fill=255, stroke_width=sw, stroke_fill=128)
            m = np.asarray(tile, np.float32) / 255.0; core = np.clip((m - 0.5) * 2.0, 0, 1) * 0 + (m >= 0.99).astype(np.float32); edge = np.clip(m * 2.0, 0, 1) * (1 - core)               # white letters inside a dark outline
            shadow = cv2.GaussianBlur(np.clip(m * 2.0, 0, 1), (0, 0), max(px * 0.12, 1.0)); roi = out[ya:yb, x0:xe].astype(np.float32) / top; col = np.array(st['color'][::-1] if bgr else st['color'], np.float32)
            roi *= 1 - 0.55 * al * shadow[..., None]; roi = roi * (1 - al * edge[..., None]) + 0.05 * al * edge[..., None]; roi = roi * (1 - al * core[..., None]) + col * al * core[..., None]
            out[ya:yb, x0:xe] = np.clip(roi * top + 0.5, 0, top).astype(img.dtype)
        return out
