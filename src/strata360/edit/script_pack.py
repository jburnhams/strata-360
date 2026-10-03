"""The context pack for the whole-race script writer (implementation plan K / V2): everything the writer should know about every clip, in shooting order, as plain data and as text for a prompt.

build(folder) -> dict(race=..., clips=[...]); render(pack) -> str.
Per clip: a short label (the clip number, 0023), local time and race facts from the track, the length and usable footage, the place, what the scene model saw, the runner's note, and the wearer's own words as numbered
LINES with exact times (the word alignment where it passed its checks, else the recogniser's times shifted by its usual 0.15 s lag). Nothing but text leaves the machine: no audio, pictures or faces."""
import json, os, re

WHISPER_LAG_S = 0.15


def words(s): return len(re.findall(r"[\w'’-]+", s))


def norm_label(x):
    """A clip label as the script and the pack write it: a camera clip's number padded to four digits (`23` -> `0023`), a generated clip's name as it is (`g03` -> `G03`)."""
    x = str(x or '').strip(); return x.zfill(4) if x.isdigit() else x.upper()


def label_of(clip_id):
    m = re.search(r'_(\d{4})_[A-Z]$', clip_id); return m.group(1) if m else clip_id[-6:]


def label_of_id(line_id): return line_id.split('.')[0]


def merge(iv, gap=1e-6):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + gap: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out


def transcript_lines(cdir, label):
    """The wearer's speech as lines [{id, t0, t1, text, words, lang, mark, si, w0, w1}] with exact times (`si` the segment, `w0`..`w1` the recognised words it covers, end exclusive); flagged and empty segments are left out. A line is split wherever the user's mark changes (MUST USE, NEVER USE,
    none; edit/../analysis/transcript_marks.py), so every line has one state: the pieces get ids `<clip>.<segment>.<n>`; an unsplit line is `<clip>.<segment>`. `mark` is 'must', 'never' or None."""
    from strata360.analysis import transcript_edits as TE, transcript_marks as TM
    if not os.path.exists(os.path.join(cdir, 'transcript.json')): return []
    tr = TE.load_effective(cdir); mk = TM.states(cdir); ap = os.path.join(cdir, 'alignment.json')
    al = {a['index']: a for a in (json.load(open(ap)).get('segments') or []) if a} if os.path.exists(ap) else {}; out = []

    def span(ws, aw, a, b):
        got = []
        for k in range(a, b):
            x = aw[k] if k < len(aw) else None
            got.append((x['a0'], x['a1']) if x and x.get('ok') and x.get('a0') is not None and x.get('a1') is not None else (ws[k]['t0'] + WHISPER_LAG_S, ws[k]['t1'] + WHISPER_LAG_S))
        return min(g[0] for g in got), max(g[1] for g in got)

    for si, s in enumerate(tr['segments']):
        text = (s.get('text_en') or s.get('text') or '').strip()
        if not text or s.get('flags'): continue
        ws = s.get('words') or []; aw = (al.get(si) or {}).get('words') or []; ms = [mk.get((si, k)) for k in range(len(ws))]
        foreign = s.get('lang', 'en') != 'en' and s.get('text_en') and s['text_en'].strip() != (s.get('text') or '').strip()
        w = [x for x in aw if x.get('ok') and x.get('a0') is not None and x.get('a1') is not None]
        whole_t = (min(x['a0'] for x in w), max(x['a1'] for x in w)) if w else (s['t0'] + WHISPER_LAG_S, s['t1'] + WHISPER_LAG_S)
        if foreign or not ws or len(set(ms)) <= 1:                                       # one state: the whole line, as before
            state = 'never' if 'never' in ms else 'must' if 'must' in ms else None
            out.append(dict(id=f'{label}.{si:02d}', t0=round(whole_t[0], 2), t1=round(whole_t[1], 2), text=text, words=words(text), lang=s.get('lang', 'en'), mark=state, si=si, w0=0, w1=len(ws))); continue
        groups = []; a = 0
        for k in range(1, len(ws) + 1):
            if k == len(ws) or ms[k] != ms[a]: groups.append((a, k, ms[a])); a = k
        for n, (a, b, state) in enumerate(groups, 1):
            t = ' '.join(x['w'].strip() for x in ws[a:b] if x['w'].strip()); t0, t1 = span(ws, aw, a, b)
            out.append(dict(id=f'{label}.{si:02d}.{n}', t0=round(t0, 2), t1=round(t1, 2), text=t, words=words(t), lang=s.get('lang', 'en'), mark=state, si=si, w0=a, w1=b))
    return out


def look_of(cdir, scale):
    """How good the picture of a clip is (scenes v3, edit/quality_scale.py): the scenery ahead and behind on this race's own 0..10 scale, and the clarity (1 to 5); None for a clip without the ratings."""
    from strata360.edit import quality_scale as QS
    try: return QS.look(json.load(open(os.path.join(cdir, 'scenes.json'))), scale)
    except (OSError, ValueError): return None


def scene_summary(cdir):
    p = os.path.join(cdir, 'scenes.json')
    if not os.path.exists(p): return {}
    items = [i for i in json.load(open(p)).get('items') or [] if i.get('ok')]
    if not items: return {}
    from collections import Counter
    def top(k, n=3): return [v for v, _ in Counter(i[k] for i in items if i.get(k) and i[k] != 'unknown').most_common(n)]
    desc = []
    for i in items:
        if i['view'] == 'front' and i.get('description') and i['description'] not in desc: desc.append(i['description'])
    step = max(len(desc) // 3, 1)
    return dict(settings=top('setting'), weather=top('weather', 2), lighting=top('lighting', 2), crowd=top('crowd', 1), seen=desc[::step][:3], lens_problems=[v for v in top('lens_problems', 2) if v != 'none'])


MAX_GAP_S = 45.0                       # the longest a gap is shown in the film (edit/synthetic.default_seconds caps at the same)
FLYOVER_NOTE = 'a 3D terrain flyover: the default for a gap, shows the land crossed'


def you_views(cands):
    """How much of a clip's usable time has each view of you (K6): {mid, close, far} as shares 0..1 (edit/techniques selfie_hold, selfie_close, selfie_far), from the candidates' features weighted by their length; None when you are hardly in the clip."""
    spans = [c for c in cands if c.get('kind', 'span') == 'span' and c['end_s'] > c['start_s']] or list(cands); tot = sum(c['end_s'] - c['start_s'] for c in spans)
    if not tot: return None
    share = lambda k: sum((c['end_s'] - c['start_s']) * (c.get('features') or {}).get(k, 0.0) for c in spans) / tot
    mid, close, far = share('protagonist'), share('you_close'), share('you_far')
    return None if mid < 0.1 else dict(mid=round(mid, 2), close=round(close, 2), far=round(far, 2))


def gap_clips(folder, tr, tz):
    """Every gap in the footage (gps/gaps.py: 20 minutes or more between clips on the track) as a pack clip `G01`..., in time order: no footage, no words, picture only, with the choices for filling it (the animated 2D map, or
    a 3D flyover with the same numbers on screen), the length it gets by default and the state of any clip already planned for it (edit/synthetic.py)."""
    import datetime as dt
    from strata360.edit import synthetic as SY
    from strata360.gps import context as X, gaps as GP
    if tr is None: return []
    from strata360.pipeline import notes as N
    planned = {c['id']: c for c in SY.load(folder)['clips']}; out = []; notes = N.load(folder).get('clips') or {}; choices = SY.settings(folder)
    for g in GP.find_gaps(GP.load_spans(folder), tr, 1200.0, tz):
        c = planned.get(g['id']); sec = round(c['seconds'], 1) if c else SY.default_seconds(g['duration_s']); mine = SY.gap_settings(folder, g['id'])
        if mine['mode'] == 'set': sec = float(mine['seconds'])                                           # a length you set
        elif mine['mode'] == 'min': sec = max(sec, float(mine['seconds']))                               # at least the length you gave
        ctx = X.context_at(tr, g['t0'], g['t1'], tz)
        d = dict(label=norm_label(g['id']), clip=g['id'], start_utc=dt.datetime.fromtimestamp(g['t0'], dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), duration_s=sec, usable_s=MAX_GAP_S, usable=[(0.0, MAX_GAP_S)], synthetic=True, race_s=g['duration_s'],
                 speedup=round(g['duration_s'] / sec, 1), scene={}, note=(notes.get(g['id']) or '').strip(), settings=mine, lines=[], speech_s=0.0, speech_words=0, track=X.describe(ctx),
                 gap={k: g.get(k) for k in ('local_start', 'local_end', 'km_start', 'km_end', 'distance_km', 'ascent_m', 'daylight', 'moving_share')},
                 options=[dict(kind='map', default_seconds=sec), dict(kind='flyover', default_seconds=sec, note=FLYOVER_NOTE)], planned=dict(kind=c['kind'], seconds=c['seconds'], status=c.get('status'), approved=c.get('approved', True)) if c else None)
        if ctx.get('covered'): d['km'] = ctx.get('distance_km'); d['elapsed_h'] = ctx.get('elapsed_h'); d['local'] = f"{ctx['local_date']} {ctx['local_time']}"
        out.append(d)
    return out


MAX_PHOTO_S = 12.0                     # the longest a photo is shown in the film
MIN_PHOTO_S = 2.5


def photo_clips(folder, tr, tz):
    """Every photo of the project (photos.py) as a pack clip `P1`..., in time order with the clips: no footage and no words, a still the writer may show for a few seconds (a `photo` item) or put narration over; with when and where it was taken, what the photo analysis found in it
    (the scene, the place, who is in it, the objects) and whether you marked it to be used."""
    import datetime as dt
    from strata360 import photos as PH
    from strata360.analysis import photo_analysis as PA
    from strata360.gps import context as X
    from strata360.pipeline import config
    rd = config.race_dir(folder); rows = PH.load(rd)['photos']
    if not rows: return []
    out = []
    for e in rows:
        lab = PH.label_of(e); mo = PH.motion_of(e); doc = PA.load_doc(rd, e['id']); a = PA.summary(doc); sec = round(min(max(float(mo['seconds']), MIN_PHOTO_S), MAX_PHOTO_S), 1); t = e['taken_utc']
        d = dict(label=lab, clip=lab, start_utc=dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), duration_s=sec, usable_s=MAX_PHOTO_S, usable=[(0.0, MAX_PHOTO_S)], synthetic=True, photo=True, race_s=0.0, speedup=1.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0,
                 settings=dict(kind=None, mode=None, seconds=None, must=bool(e.get('must'))), planned=None, photo_facts=dict(name=e['name'], camera=e.get('camera') or '', **{k: v for k, v in a.items() if k != 'stages'}))
        if tr is not None:
            ctx = X.context_at(tr, t, t, tz); d['track'] = X.describe(ctx)
            if ctx.get('covered'): d['km'] = ctx.get('distance_km'); d['elapsed_h'] = ctx.get('elapsed_h'); d['local'] = f"{ctx['local_date']} {ctx['local_time']}"
        out.append(d)
    return out


def music_facts(folder):
    """What the writer is told about the music, in FILM time (the film starts at the track's first downbeat): its length, tempo, the sections with their energy, and the lyrics (lyrics.py): where it is sung and the words heard
    (rough: the times are right, the words are often wrong). None when there is no track."""
    from strata360.edit import project as PJ, lyrics as LY
    edit = PJ.load(folder); mus = PJ.music_record(folder, edit['settings'])
    if not mus: return None
    a = mus['analysis']; beat = 60.0 / float(a['bpm']); off = float(a['offset_s']); length = round(float(a['usable_beats']) * beat, 1)
    out = dict(length_s=length, bpm=round(float(a['bpm']), 1), bar_s=round(beat * int(a['bar_beats']), 2), sections=[dict(t0=round(s0 * beat, 1), t1=round(s1 * beat, 1), energy=round(float(e), 2)) for s0, s1, e in a['sections']], lyrics=None)
    v = LY.view(folder)
    if v and not v['instrumental']:
        film = lambda t: round(t - off, 1); spans = [[film(x), film(y)] for x, y in v['vocal_spans'] if y - off > 0 and x - off < length]
        out['lyrics'] = dict(language=v.get('language'), vocal_spans=[[max(x, 0.0), min(y, length)] for x, y in spans], phrases=[dict(t0=max(film(p['t0']), 0.0), t1=film(p['t1']), text=p['text'], doubtful=p['doubtful']) for p in v['phrases'] if p['counts'] and p['t1'] - off > 0 and p['t0'] - off < length])
    elif v: out['lyrics'] = dict(instrumental=True)
    return out


def build(folder, tz=None):
    import datetime as dt
    from strata360.pipeline import config, notes as N, meta as MT
    from strata360.edit import project as PJ
    from strata360.gps import track, context as X
    cfg = config.load(folder); rd = config.race_dir(folder); notes = N.load(folder); tp = config.track_path(folder, cfg); tr = track.load(tp) if tp else None; tz = tz or cfg.get('timezone', 'Europe/Brussels')
    clips, missing = PJ.load_clips(folder); out = []; from strata360.edit import quality_scale as QS; scale = QS.project_scale(os.path.join(rd, 'clips'))
    for c in sorted(clips, key=lambda c: c['start_utc']):
        cdir = os.path.join(rd, 'clips', c['id']); label = label_of(c['id']); t0 = dt.datetime.fromisoformat(c['start_utc'].replace('Z', '+00:00')).timestamp(); dur = float(c['duration_s'])
        usable = merge([(x['start_s'], x['end_s']) for x in c['candidates']]); usable_s = sum(b - a for a, b in usable)
        d = dict(label=label, clip=c['id'], start_utc=c['start_utc'], duration_s=round(dur, 1), usable_s=round(usable_s, 1), usable=[(round(a, 1), round(b, 1)) for a, b in usable], you_views=you_views(c['candidates']))
        if tr is not None:
            ctx = X.context_at(tr, t0, t0 + dur, tz); d['track'] = X.describe(ctx)
            if ctx.get('covered'): d['km'] = ctx.get('distance_km'); d['elapsed_h'] = ctx.get('elapsed_h'); d['local'] = f"{ctx['local_date']} {ctx['local_time']}"
        pl = os.path.join(cdir, 'places.json')
        if os.path.exists(pl):
            pj = json.load(open(pl))
            if pj.get('covered') and pj.get('summary'): d['place'] = pj['summary']['text'] + (f", on {pj['summary']['road']}" if pj['summary'].get('road') else '')
        d['look'] = look_of(cdir, scale); d['scene'] = scene_summary(cdir); d['note'] = (notes.get('clips', {}).get(c['id']) or '').strip(); d['lines'] = transcript_lines(cdir, label)
        d['speech_s'] = round(sum(l['t1'] - l['t0'] for l in d['lines']), 1); d['speech_words'] = sum(l['words'] for l in d['lines']); out.append(d)
    out = sorted(out + gap_clips(folder, tr, tz) + photo_clips(folder, tr, tz), key=lambda c: c['start_utc'])
    story = None
    try:
        from strata360.gps import tracks as TKS
        story = TKS.race_story(rd, tz)
    except Exception as e:                                                                       # the course facts are left out (loudly); the script is still written from the rest
        print(f'script pack: no course facts: {type(e).__name__}: {e}')
    if story:
        for c in out:
            t = dt.datetime.fromisoformat(c['start_utc'].replace('Z', '+00:00')).timestamp() + float(c.get('race_s') or c['duration_s']) / 2
            c['progress'] = TKS.story_line(TKS.story_at(story, t))
    speech_s = sum(c['speech_s'] for c in out); speech_w = sum(c['speech_words'] for c in out)
    race = dict(note=(notes.get('folder') or '').strip(), details=MT.describe(folder), km_total=MT.load(folder).get('distance_km'), speech_wpm=round(speech_w / speech_s * 60) if speech_s else None, clips_missing=missing)
    if story: race['course'] = TKS.story_text(story, tz)
    if tr is not None: race['track'] = f"the GPS recorded {tr['dist'][-1] / 1000:.0f} km over {(tr['t'][-1] - tr['t'][0]) / 3600:.0f} hours (the runner's own elapsed time: not a time limit, and the distance can exceed the official one because of detours). The km in each clip's track line is GPS distance from the start"
    return dict(race=race, clips=out, music=music_facts(folder))


def render(pack, with_usable=False, marks=None):
    """The pack as prompt text. `marks` ({line id: 'must' | 'never'}, edit/script_pins.py) tags the lines the user fixed."""
    marks = marks or {}; r = pack['race']; L = ['THE RACE']
    if r.get('details'): L.append(r['details'])
    if r.get('track'): L.append('Track: ' + r['track'])
    if r.get('course'): L += ['The course, the checkpoints and the cut-offs (cut-offs are times since the start of the run):'] + r['course']
    if r.get('note'): L += ["The runner's own notes about the race:", r['note']]
    m = pack.get('music')
    if m:
        L += ['', 'THE MUSIC (times are FILM seconds: the film starts with the music and ends when it ends)', f"length {m['length_s']:.0f} s, {m['bpm']:g} bpm, a bar is {m['bar_s']:g} s. Sections by energy (0 quiet, 1 loud): " + '; '.join(f"{x['t0']:.0f}-{x['t1']:.0f} s {x['energy']:.2f}" for x in m['sections'])]
        ly = m.get('lyrics')
        if ly and ly.get('instrumental'): L.append('The track is instrumental: nothing is sung.')
        elif ly:
            L.append(f"Sung ({ly.get('language')}): " + (', '.join(f'{a:.0f}-{b:.0f} s' for a, b in ly['vocal_spans']) or 'nowhere') + '. Narration over singing is fine and often unavoidable (the music is turned down under it).')
            L.append('Words heard by speech recognition (rough: the times are right, the words are often wrong; use them for what the song is about and where, never quote them):')
            L += [f"  [{p['t0']:.0f} s] {p['text'][:70]}" + (' (doubtful)' if p['doubtful'] else '') for p in ly['phrases'][:45]]
    L += ['', f"CLIPS (all {len(pack['clips'])}, in shooting order; the film follows this order)"]
    for c in pack['clips']:
        L.append(f"\n=== {'PHOTO' if c.get('photo') else 'CLIP'} {c['label']}: {c['duration_s']} s long, {c['usable_s']} s usable" + (f" | {c['local']}" if c.get('local') else '') + (f" | km {c['km']}" if c.get('km') is not None else '') + ' ===')
        if c.get('photo'):
            f = c.get('photo_facts') or {}; L.append(f"A PHOTO the runner took (a still: no footage and no words); show it with a photo item of {MIN_PHOTO_S:g} to {MAX_PHOTO_S:g} s (the editor pans and zooms on it), or put a vo item over it. Use the ones that add to the story; leave the rest." + (' THE RUNNER WANTS THIS PHOTO IN THE FILM (MUST INCLUDE): give it a photo item.' if (c.get('settings') or {}).get('must') else ''))
            bits = [f.get('description'), ('place: ' + f['place']) if f.get('place') else '', ('setting: ' + f['setting'] + (', ' + f['weather'] if f.get('weather') and f['weather'] != 'unknown' else '')) if f.get('setting') else '', ('scenery ' + format(f['scenery'], 'g') + '/10') if f.get('scenery') is not None else '',
                    ('people in it: ' + str(f['people']) + (', the runner among them' + (' (face clear)' if f.get('face_clear') else ' (face not clear)' if f.get('face_clear') is False else '') if f.get('me') else '')) if f.get('people') is not None else '',
                    ('objects: ' + ', '.join((str(o['n']) + ' ' if o['n'] > 1 else '') + o['label'] for o in f['objects'])) if f.get('objects') else '', ('tags: ' + ', '.join(f['tags'])) if f.get('tags') else '', ('picture looks ' + f['exposure']) if f.get('exposure') not in (None, 'ok') else '', ('picture is ' + f['quality']) if f.get('quality') not in (None, 'ok') else '']
            L.append('the photo: ' + '; '.join(b for b in bits if b) if any(bits) else 'the photo has not been analysed (no description yet).')
        elif c.get('synthetic'):
            g = c.get('gap') or {}; pl = c.get('planned')
            L.append(f"NO FOOTAGE: a gap of {c['race_s'] / 3600:.1f} h between clips ({g.get('local_start')} to {g.get('local_end')}, km {g.get('km_start')} to {g.get('km_end')}, +{g.get('ascent_m')} m{', ' + g['daylight'] if g.get('daylight') else ''}); {int(round(100 * (g.get('moving_share') or 0)))}% of it spent moving. "
                     f"Fill it with a generated clip: a generated clip (the planner draws it as a 2D map or a 3D terrain flyover: you only give its length), each with the clock, distance, pace and altitude on screen; {c['duration_s']} s shows it at about x{c['speedup']:g}. Use a gap item (kind and seconds, 2 to {MAX_GAP_S:g}) or narration over it; it has no sound and no words."
                     + (f" Already planned: {pl['kind']}, {pl['seconds']} s ({pl['status']})." if pl else ''))
        if c.get('track'): L.append('track: ' + c['track'])
        if c.get('progress'): L.append('race progress: ' + c['progress'])
        if c.get('place'): L.append('place: ' + c['place'])
        s = c.get('scene') or {}
        lk = c.get('look')
        if lk and (lk.get('ahead') is not None or lk.get('behind') is not None): L.append('picture quality (scenery on this race\'s own 0 worst to 10 best scale, people ignored; clarity 1 foggy or wet to 5 sharp): ' + ', '.join(x for x in [f"scenery {lk['ahead']:.1f} ahead" if lk.get('ahead') is not None else '', f"{lk['behind']:.1f} behind" if lk.get('behind') is not None else '', f"clarity {lk['clarity_ahead']:.1f} ahead" if lk.get('clarity_ahead') is not None else '', f"{lk['clarity_behind']:.1f} behind" if lk.get('clarity_behind') is not None else ''] if x))
        if s: L.append('camera sees: ' + '; '.join(x for x in [', '.join(s.get('settings') or []), ('weather ' + ', '.join(s['weather'])) if s.get('weather') else '', ('lighting ' + ', '.join(s['lighting'])) if s.get('lighting') else '', ('crowd ' + ', '.join(s['crowd'])) if s.get('crowd') and s['crowd'] != ['none'] else '', ('; '.join(s['seen'])) if s.get('seen') else '', ('lens problems: ' + ', '.join(s['lens_problems'])) if s.get('lens_problems') else ''] if x))
        yv = c.get('you_views')
        if yv and (yv['close'] >= 0.3 or yv['far'] >= 0.3): L.append(f"views of you (ask for one with \"view\" on a clip or b-roll item): mid {yv['mid'] * 100:.0f}% of the usable time, close (a face zoom) {yv['close'] * 100:.0f}%, far (ultra wide, the whole body and the surroundings) {yv['far'] * 100:.0f}%")
        if c.get('note'): L.append("runner's note: " + c['note'])
        if with_usable and c.get('usable'): L.append('usable stretches (s): ' + ', '.join(f'{a}-{b}' for a, b in c['usable']))
        if c['lines']:
            L.append(f"the runner says ({c['speech_s']} s of speech, {c['speech_words']} words):")
            for l in c['lines']: L.append(f"  [{l['id']}] {l['t0']:.1f}-{l['t1']:.1f} s ({l['t1'] - l['t0']:.1f} s): {l['text']}" + ('' if l['lang'] == 'en' else f" (translated from {l['lang']})") + {'must': '   <<< MUST INCLUDE', 'never': '   <<< DO NOT USE'}.get(marks.get(l['id']), ''))
        elif not c.get('photo'): L.append('the runner says nothing in this clip.')
    return '\n'.join(L)
