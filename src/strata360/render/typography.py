"""Typography: a library of fonts, each tagged with its vibes and the roles it suits, and a typography scheme for a project, chosen like its colour scheme (analysis/palette_cluster.py) so that every card of the film speaks in the same few voices.

  FONT_TABLE      every font the film may use: file, the variable-font axes that pin its weight, category, the vibes it carries, the roles it suits, and what it can bear (smallest sensible size, outline, numerals)
  infer_vibes     the project's vibes (word -> weight) from what is known of it: the colour palettes' mood, the words of its title and notes and scene labels, and words the user gives
  choose          the scheme: one font for each role (display, subtitle, meta, numerals, quote), picked by how well its vibes match the project's, with pairing rules (at most 3 families, a subtitle that contrasts with the display face, a meta line that stays in the subtitle's family)
  for_project     the scheme of a project folder (typography.json, written once and kept; the user can edit it or ask for other vibes)
  specimen        a picture of the scheme, in the project's own colours

Roles: `display` the big word of a card; `subtitle` the second line, a headline in small caps; `meta` the small lines (times, places, credits); `numerals` figures that must align and stay legible (kilometres, pace, elevation, clocks); `quote` words someone said, set apart from the card's facts.

The vibes are a fixed vocabulary (VIBES) so that tags and project signals meet. Fonts are open-licence (SIL OFL, one Apache) and live in render/title_fonts/ with their licence texts."""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__)); FONT_DIR = os.path.join(HERE, 'title_fonts')
FILE = 'typography.json'
ROLES = ('display', 'subtitle', 'meta', 'numerals', 'quote')
ROLE_EM = dict(display=0.12, subtitle=0.07, meta=0.04, numerals=0.05, quote=0.06)          # a typical size of each role (fraction of the frame height): a font whose smallest sensible size is above it is not offered for the role
VIBES = ('athletic', 'rugged', 'industrial', 'outdoors', 'urban', 'vintage', 'heritage', 'editorial', 'elegant', 'refined', 'quiet', 'cinematic', 'warm', 'human', 'personal', 'handmade', 'documentary', 'raw', 'technical', 'data',
         'modern', 'clean', 'minimal', 'friendly', 'confident', 'bold', 'loud', 'energetic')
MAX_FAMILIES = 3


def _f(file, family, category, desc, vibes, roles, axes=None, caps=False, min_em=0.04, outline=0.7, tabular=False, weight=400):
    return dict(file=file, family=family, category=category, desc=desc, vibes=list(vibes), roles=list(roles), axes=axes or {}, caps=caps, min_em=min_em, outline=outline, tabular=tabular, weight=weight)


# Axis keys are the four-letter OpenType tags: wght (weight), wdth (width), opsz (optical size), SOFT (softness), WONK (wonky forms).
FONT_TABLE = {
    'bebas': _f('BebasNeue-Regular.ttf', 'Bebas Neue', 'sans', 'tall condensed capitals, athletic and clean', ('athletic', 'clean', 'modern', 'confident'), ('display', 'subtitle'), caps=True, min_em=0.05, outline=0.8),
    'anton': _f('Anton-Regular.ttf', 'Anton', 'sans', 'heavy condensed poster capitals, loud', ('loud', 'bold', 'urban', 'energetic'), ('display',), caps=True, min_em=0.07, outline=0.9),
    'archivo_black': _f('ArchivoBlack-Regular.ttf', 'Archivo', 'sans', 'wide heavy sans, bold and modern', ('bold', 'modern', 'confident', 'energetic'), ('display', 'subtitle'), min_em=0.05, outline=0.9, weight=900),
    'barlow_cond_light': _f('BarlowCondensed-Light.ttf', 'Barlow Condensed', 'sans', 'light condensed sans, elegant and technical', ('elegant', 'technical', 'minimal', 'modern'), ('subtitle',), min_em=0.09, outline=0.3, weight=300),
    'barlow_cond_bold': _f('BarlowCondensed-Bold.ttf', 'Barlow Condensed', 'sans', 'bold condensed sans, sporty and legible', ('athletic', 'technical', 'clean', 'confident'), ('subtitle', 'meta', 'numerals'), min_em=0.03, tabular=True, weight=700),
    'barlow': _f('Barlow-Medium.ttf', 'Barlow', 'sans', 'plain medium sans for small lines', ('clean', 'friendly', 'modern'), ('subtitle', 'meta', 'numerals'), min_em=0.03, tabular=True, weight=500),
    'dm_serif': _f('DMSerifDisplay-Regular.ttf', 'DM Serif Display', 'serif', 'high-contrast display serif, editorial and warm', ('editorial', 'warm', 'elegant', 'heritage'), ('display', 'quote'), min_em=0.06, outline=0.5),
    'dm_serif_italic': _f('DMSerifDisplay-Italic.ttf', 'DM Serif Display', 'serif', 'italic display serif, personal and soft', ('personal', 'warm', 'elegant'), ('quote',), min_em=0.06, outline=0.5),
    'inter': _f(os.path.join('..', '..', 'overlay', 'fonts', 'Inter-SemiBold.ttf'), 'Inter', 'sans', 'neutral semibold sans', ('clean', 'minimal', 'documentary'), ('subtitle', 'meta', 'numerals'), min_em=0.03, weight=600),
    'big_shoulders': _f('BigShouldersDisplay-Variable.ttf', 'Big Shoulders Display', 'sans', 'industrial condensed capitals with an athletic stance', ('athletic', 'industrial', 'bold', 'urban'), ('display', 'numerals'), axes=dict(wght=800), caps=True, min_em=0.05, outline=0.85, tabular=True, weight=800),
    'league_gothic': _f('LeagueGothic-Variable.ttf', 'League Gothic', 'sans', 'tall vintage gothic, heritage poster and race bib', ('vintage', 'heritage', 'athletic', 'outdoors', 'confident'), ('display',), axes=dict(wdth=100), caps=True, min_em=0.06, outline=0.8),
    'oswald': _f('Oswald-Variable.ttf', 'Oswald', 'sans', 'rugged condensed workhorse, works as a headline or a title', ('rugged', 'outdoors', 'athletic', 'confident', 'documentary'), ('display', 'subtitle'), axes=dict(wght=600), caps=True, min_em=0.04, outline=0.8, weight=600),
    'alfa_slab': _f('AlfaSlabOne-Regular.ttf', 'Alfa Slab One', 'slab', 'heavy slab serif, rugged, trail signs and old outfitters', ('rugged', 'outdoors', 'vintage', 'bold'), ('display',), min_em=0.07, outline=0.9, weight=900),
    'fraunces': _f('Fraunces-Variable.ttf', 'Fraunces', 'serif', 'soft, wonky old-style serif: warm, human, with character', ('warm', 'human', 'editorial', 'elegant', 'personal'), ('display', 'quote', 'subtitle'), axes=dict(opsz=72, wght=600, SOFT=50, WONK=1), min_em=0.05, outline=0.6, weight=600),
    'playfair': _f('PlayfairDisplay-Variable.ttf', 'Playfair Display', 'serif', 'high-contrast transitional serif, elegant and cinematic', ('elegant', 'editorial', 'heritage', 'refined', 'cinematic'), ('display', 'quote'), axes=dict(wght=700), min_em=0.06, outline=0.5, weight=700),
    'cormorant': _f('CormorantGaramond-Variable.ttf', 'Cormorant Garamond', 'serif', 'refined light garalde, quiet and emotional (large sizes only)', ('refined', 'quiet', 'elegant', 'cinematic'), ('quote',), axes=dict(wght=500), min_em=0.07, outline=0.3, weight=500),
    'space_grotesk': _f('SpaceGrotesk-Variable.ttf', 'Space Grotesk', 'sans', 'quirky modern grotesque, technical and urban', ('modern', 'technical', 'minimal', 'urban'), ('subtitle', 'meta', 'numerals'), axes=dict(wght=500), min_em=0.03, tabular=True, weight=500),
    'montserrat': _f('Montserrat-Variable.ttf', 'Montserrat', 'sans', 'geometric sans, clean and friendly, sturdy small', ('clean', 'friendly', 'modern', 'confident'), ('subtitle', 'meta', 'numerals'), axes=dict(wght=600), min_em=0.03, weight=600),
    'plex_mono': _f('IBMPlexMono-Medium.ttf', 'IBM Plex Mono', 'mono', 'monospaced, honest, telemetry and readouts', ('data', 'technical', 'documentary', 'raw'), ('meta', 'numerals'), min_em=0.03, tabular=True, weight=500),
    'caveat': _f('Caveat-Variable.ttf', 'Caveat', 'hand', 'handwriting, a note in the margin', ('handmade', 'personal', 'warm', 'friendly'), ('quote',), axes=dict(wght=700), min_em=0.06, outline=0.5, weight=700),
    'special_elite': _f('SpecialElite-Regular.ttf', 'Special Elite', 'typewriter', 'worn typewriter, documents and field notes', ('documentary', 'vintage', 'raw', 'handmade'), ('quote',), min_em=0.05, outline=0.6),
}
AXIS_NAMES = dict(wght='Weight', wdth='Width', opsz='Optical Size', SOFT='Softness', WONK='Wonky', slnt='Slant', ital='Italic')


def path_of(fid): return os.path.normpath(os.path.join(FONT_DIR, FONT_TABLE[fid]['file']))


def load_font(fid, px):
    """The PIL font `fid` at `px` pixels, its variable axes pinned to the entry's values (other axes at their defaults)."""
    from PIL import ImageFont
    f = ImageFont.truetype(path_of(fid), max(int(round(px)), 4)); axes = FONT_TABLE[fid]['axes']
    if axes:
        want = {AXIS_NAMES.get(k, k): v for k, v in axes.items()}
        vals = [want.get((a['name'].decode() if isinstance(a['name'], bytes) else a['name']), a['default']) for a in f.get_variation_axes()]; f.set_variation_by_axes(vals)
    return f


# What words in a project's title, notes and scene labels say about its vibe.
KEYWORDS = (
    (r'ultra|marathon|race|run(ning|ner)?|trail|sprint|cycl|bike|ride', dict(athletic=0.6, energetic=0.3)),
    (r'mountain|alps?|alpine|swiss|switzerland|dolomit|pyrenee|highland|peak|summit|ridge|forest|wood|valley|glacier|snow|trail|hike|hiking|wild|canyon|moor', dict(rugged=0.5, outdoors=0.6)),
    (r'night|dusk|dawn|moon|dark|tunnel', dict(cinematic=0.5, quiet=0.2)),
    (r'city|street|town|crowd|urban|station|bridge|market|square', dict(urban=0.5, modern=0.2)),
    (r'famil|baby|child|kid|wedding|birthday|holiday|love|home|friend', dict(warm=0.6, personal=0.5, friendly=0.3)),
    (r'diary|journal|note|memor|letter', dict(handmade=0.4, personal=0.4)),
    (r'history|heritage|old|classic|vintage|castle|church|ruin', dict(heritage=0.5, vintage=0.4, editorial=0.2)),
    (r'film|cinema|story|travel|journey|adventure|crossing|traverse|expedition', dict(cinematic=0.3, editorial=0.2, athletic=0.2)),
    (r'data|stat|km|pace|elevation|gps|track|telemetry', dict(data=0.3, technical=0.4)),
    (r'quiet|calm|still|peace|lake|sunset|sunrise|fog|mist', dict(quiet=0.5, refined=0.3, elegant=0.2)),
    (r'party|festival|concert|dance|music|beach', dict(energetic=0.5, loud=0.3, bold=0.3)),
)
PRIOR = dict(athletic=0.3, confident=0.2, clean=0.2)               # what a race film is, before anything else is known


def infer_vibes(palettes=(), text='', style=''):
    """{vibe: weight 0..1} for a project: a small prior, the mood of its colour palettes (palette.json documents), the keywords of `text` (title, notes, scene labels), and `style`: words the user gives (a comma or space separated list of VIBES, each weighing 1)."""
    v = dict(PRIOR); text = (text or '').lower()
    for pat, add in KEYWORDS:
        n = len(re.findall(pat, text))
        if n:
            for k, w in add.items(): v[k] = v.get(k, 0.0) + w * min(1.0 + 0.25 * (n - 1), 2.0)
    moods = [p['mood'] for p in palettes if p and p.get('mood')]
    if moods:
        share = lambda key, val: sum(m.get(key) == val for m in moods) / len(moods)
        v['warm'] = v.get('warm', 0.0) + 0.5 * share('temperature', 'warm'); v['cinematic'] = v.get('cinematic', 0.0) + 0.4 * share('tone', 'dark') * share('temperature', 'cool')
        v['energetic'] = v.get('energetic', 0.0) + 0.5 * share('saturation', 'vivid'); v['documentary'] = v.get('documentary', 0.0) + 0.12 * (share('saturation', 'grey') + share('saturation', 'muted')); v['minimal'] = v.get('minimal', 0.0) + 0.15 * share('saturation', 'grey')
    for w in re.split(r'[,;\s]+', style or ''):
        if w.lower() in VIBES: v[w.lower()] = v.get(w.lower(), 0.0) + 1.0
    top = max(v.values()) if v else 1.0
    return {k: round(x / top, 3) for k, x in sorted(v.items(), key=lambda kv: -kv[1]) if x > 0}


def fit(fid, vibes):
    """How well a font's vibes match a project's: the weights of the project's vibes the font carries, over the most it could match (so a font with few tags is not at a disadvantage)."""
    tags = FONT_TABLE[fid]['vibes']; return sum(vibes.get(t, 0.0) for t in tags) / max(sum(sorted(vibes.values(), reverse=True)[:len(tags)]), 1e-9)


def choose(vibes, exclude=()):
    """The typography scheme for `vibes`: dict(fonts={role: font id}, vibes={top vibes}, why={role: sentence}, alternatives={role: [next best ids]}). Display first, then a subtitle that contrasts with it, a meta line and numerals that keep to the subtitle's family where they can,
    and a quote that keeps to the display's family or category; never more than MAX_FAMILIES families."""
    ids = [k for k in FONT_TABLE if k not in exclude]; pick, alts = {}, {}; fam = lambda i: FONT_TABLE[i]['family']; cat = lambda i: FONT_TABLE[i]['category']
    def best(role, bonus):
        cands = [i for i in ids if role in FONT_TABLE[i]['roles'] and FONT_TABLE[i]['min_em'] <= ROLE_EM[role] + 1e-9]
        if not cands: cands = [i for i in ids if role in FONT_TABLE[i]['roles']] or ids
        have = {fam(i) for i in pick.values()}
        if len(have) >= MAX_FAMILIES:                                                                                     # a hard limit: once there are MAX_FAMILIES families only those are used; a role none of them suits takes the display face
            inside = [i for i in cands if fam(i) in have]; cands = inside or ([pick['display']] if 'display' in pick else cands)
        sc = sorted(((fit(i, vibes) + bonus(i), i) for i in cands), key=lambda x: (-x[0], x[1])); alts[role] = [i for _, i in sc[1:4]]; return sc[0][1]
    pick['display'] = best('display', lambda i: 0.0)
    d = pick['display']; pick['subtitle'] = best('subtitle', lambda i: (0.35 if cat(i) != cat(d) else 0.0) + (0.2 if 'clean' in FONT_TABLE[i]['vibes'] else 0.0) - (1.0 if fam(i) == fam(d) else 0.0))
    s = pick['subtitle']; pick['meta'] = best('meta', lambda i: (0.5 if fam(i) == fam(s) else 0.0) + (0.1 if FONT_TABLE[i]['outline'] >= 0.7 else 0.0))
    pick['numerals'] = best('numerals', lambda i: (0.5 if fam(i) == fam(pick['meta']) else (0.3 if fam(i) == fam(d) else 0.0)) + (0.2 if FONT_TABLE[i]['tabular'] else 0.0))
    families = {fam(pick[r]) for r in ('display', 'subtitle', 'meta', 'numerals')}
    pick['quote'] = best('quote', lambda i: (0.2 if fam(i) in families else 0.0) + (0.1 if cat(i) == cat(d) else 0.0))                  # keeping to the card's families is a tie-break, not a reason to ignore the vibe
    why = {}
    for r, i in pick.items():
        hit = [t for t in sorted(FONT_TABLE[i]['vibes'], key=lambda t: -vibes.get(t, 0.0)) if vibes.get(t, 0.0) > 0][:3]; why[r] = f"{FONT_TABLE[i]['family']}: " + (f"matches {', '.join(hit)}" if hit else 'the best fit for the role') + f"; {FONT_TABLE[i]['desc']}"
    return dict(fonts=pick, vibes=dict(list(vibes.items())[:8]), why=why, alternatives=alts, families=sorted({fam(i) for i in pick.values()}))


def role_for_size(size, kind='progress'):
    """The role of an element of this size (fraction of the frame height) in a card of this kind: large words are display, middle ones subtitle, small ones meta; the words of a quote card are `quote`."""
    if kind == 'quote': return 'quote'
    return 'display' if size >= 0.14 else ('subtitle' if size >= 0.075 else 'meta')


def apply_to_element(el, scheme, kind='progress'):
    """Set the font of one title element (a dict of render/titles.py) to the scheme's font for its role; a quote card's own words stay `quote`, and a number-only element takes the numerals font. Returns the old font id."""
    old = el.get('font'); text = str(el.get('text', '')); role = role_for_size(float(el.get('size', 0.1)), kind)
    if role != 'quote' and re.fullmatch(r'[\d\s.,:;/+\-–·%kmhKMHs]+', text.strip() or 'x') and role in ('meta', 'subtitle'): role = 'numerals'
    el['font'] = scheme['fonts'][role]; return old


INFERRED_SHARE = 0.4               # what the project says about itself counts this much beside the script writer's or the user's choice
SCRIPT_WEIGHT, USER_WEIGHT = 1.0, 2.0


def clean_words(words):
    """`words` (a list, or a comma/space separated string) as a list of vocabulary vibes, lower case, no repeats."""
    if isinstance(words, str): words = re.split(r'[,;\s]+', words)
    out = []
    for w in words or []:
        w = str(w).strip().lower()
        if w in VIBES and w not in out: out.append(w)
    return out


def combine(inferred, script=(), user=()):
    """{vibe: weight 0..1} from the three sources, in order of authority: what the project says about itself (a tie-break), the vibes the script writer chose, and the user's own choice. The user's choice, when there is one, replaces the writer's."""
    v = {k: INFERRED_SHARE * x for k, x in inferred.items()}
    for w in (list(user) if user else list(script)): v[w] = v.get(w, 0.0) + (USER_WEIGHT if user else SCRIPT_WEIGHT)
    top = max(v.values()) if v else 1.0
    return {k: round(x / top, 3) for k, x in sorted(v.items(), key=lambda kv: -kv[1]) if x > 0}


def script_vibes(folder):
    """The vibes the newest script draft chose (script_draft.py asks the writer for them), kept to the vocabulary."""
    try:
        from strata360.edit import script_draft as SD
        return clean_words((SD.load_draft(folder) or {}).get('vibes'))
    except Exception: return []


def read(folder):
    from strata360.pipeline import config
    try: return json.load(open(os.path.join(config.race_dir(folder), FILE)))
    except (OSError, ValueError): return None


def update(folder, style=None, fonts=None, refresh=True):
    """Choose the project's scheme again and write typography.json, keeping what the user set: `style` (their vibes: a list or words; an empty list gives the choice back to the script writer) and `fonts` ({role: font id, or None to give the role back to the choice}); None leaves each as it is.
    Raises ValueError for a vibe, role or font outside the library."""
    from strata360.pipeline import config
    old = read(folder) or {}; user = list(old.get('style') or []); over = dict(old.get('overrides') or {})
    if style is not None:
        bad = [w for w in ([style] if isinstance(style, str) and not re.search(r'[,;\s]', style) else (re.split(r'[,;\s]+', style) if isinstance(style, str) else style)) if str(w).strip() and str(w).strip().lower() not in VIBES]
        if bad: raise ValueError(f'not vibes of the library: {bad}')
        user = clean_words(style)
    for r, fid in (fonts or {}).items():
        if r not in ROLES: raise ValueError(f'not a role: {r!r}')
        if fid is None: over.pop(r, None)
        elif fid not in FONT_TABLE: raise ValueError(f'not a font of the library: {fid!r}')
        else: over[r] = fid
    palettes, text = signals(folder); inferred = infer_vibes(palettes, text); script = script_vibes(folder); vibes = combine(inferred, script, user)
    sch = choose(vibes); sch['sources'] = dict(user=user, script=script, inferred=list(inferred)[:6]); sch['style'] = user; sch['overrides'] = {r: f for r, f in over.items() if r in ROLES}
    for r, fid in sch['overrides'].items():
        sch['fonts'][r] = fid; sch['why'][r] = f"{FONT_TABLE[fid]['family']}: chosen by you; {FONT_TABLE[fid]['desc']}"
    sch['families'] = sorted({FONT_TABLE[i]['family'] for i in sch['fonts'].values()}); sch['basis'] = 'user' if user else ('script' if script else 'project')
    path = os.path.join(config.race_dir(folder), FILE)
    try: os.makedirs(os.path.dirname(path), exist_ok=True); tmp = path + '.tmp'; json.dump(sch, open(tmp, 'w'), indent=1); os.replace(tmp, path)
    except OSError: pass
    return sch


def for_project(folder, style='', refresh=False):
    """The project's scheme: typography.json when it exists and still matches what the script writer chose, else chosen now and written. `style` (words) sets the user's vibes; `refresh` chooses again from what the project says about itself. Returns the scheme (a dict with `fonts`)."""
    old = read(folder)
    if style: return update(folder, style=style)
    if old and not refresh and (old.get('sources') or {}).get('script', []) == script_vibes(folder): return old                      # a new script draft with other vibes updates the scheme (unless the user chose their own)
    return update(folder)


def sample_png(fid, text, px=96, color='#ffffff', bg=None):
    """PNG bytes of `text` set in font `fid` at `px` pixels: transparent unless `bg` is a colour; for showing a font in the app."""
    import io
    from PIL import Image, ImageDraw
    f = load_font(fid, px); box = f.getbbox(text); pad = max(px // 6, 8); w, h = box[2] + pad * 2, (box[3] - min(box[1], 0)) + pad * 2
    img = Image.new('RGBA', (max(w, 8), max(h, 8)), bg or (0, 0, 0, 0)); ImageDraw.Draw(img).text((pad, pad - min(box[1], 0)), text, font=f, fill=color); out = io.BytesIO(); img.save(out, 'PNG'); return out.getvalue()


def signals(folder):
    """([palette.json of each clip], text): what a project's folder says about its vibe."""
    from strata360.analysis import palette as PAL
    from strata360.pipeline import config, notes as N
    rd = config.race_dir(folder); cd = os.path.join(rd, 'clips'); palettes, words = [], [os.path.basename(os.path.abspath(str(folder))), str(config.load(folder).get('name', '')) if os.path.exists(os.path.join(rd, 'race.json')) else '']
    for c in sorted(os.listdir(cd)) if os.path.isdir(cd) else []:
        p = PAL.load(os.path.join(cd, c))
        if p: palettes.append(p)
        try:
            for it in json.load(open(os.path.join(cd, c, 'scenes.json'))).get('items', [])[:6]: words += [str(it.get(k, '')) for k in ('setting', 'description', 'tags')]
        except (OSError, ValueError, AttributeError): pass
    try: n = N.load(folder); words += [n.get('folder', '')] + list(n.get('clips', {}).values())
    except Exception: pass
    return palettes, ' '.join(str(w) for w in words)


SAMPLES = dict(display='DAY 2', subtitle='KILOMETRE 84', meta='SUN 06:38 · 1 842 M', numerals='3:45:12   8.4 KM/H', quote="Keep going, it's only another hill.")


def specimen(scheme, path, colours=None, size=(1400, 0)):
    """Write a picture of the scheme to `path` (PNG): each role in its font, on the project's dark colour in its base and accent colours (`colours`: dict(bg, base, accent, light), default a night scheme)."""
    from PIL import Image, ImageDraw, ImageFont
    c = dict(bg='#14181d', base='#f9ffb7', accent='#aeb846', light='#f2f2f2'); c.update(colours or {}); W = size[0]; rowh = 150; H = 90 + rowh * len(ROLES)
    img = Image.new('RGB', (W, H), c['bg']); d = ImageDraw.Draw(img); small = ImageFont.truetype(path_of('inter'), 20)
    d.text((24, 22), 'Typography: ' + ', '.join(f"{k} {v:.1f}" for k, v in list(scheme['vibes'].items())[:6]), font=small, fill=c['light']); d.text((24, 52), 'families: ' + ', '.join(scheme['families']), font=small, fill=c['accent'])
    for k, r in enumerate(ROLES):
        fid = scheme['fonts'][r]; y = 90 + k * rowh; px = {'display': 110, 'subtitle': 64, 'meta': 40, 'numerals': 52, 'quote': 54}[r]
        d.text((24, y + 8), r.upper(), font=small, fill=c['accent']); d.text((24, y + 34), fid, font=small, fill=c['light'])
        f = load_font(fid, px); d.text((260, y + 4), SAMPLES[r].upper() if FONT_TABLE[fid]['caps'] and r != 'quote' else SAMPLES[r], font=f, fill=c['base'] if r in ('display', 'quote') else c['light'])
    img.save(path); return path


def library_specimen(path, columns=3, colours=None):
    """Write a picture of every font in the library (PNG): its name and family, its vibes and roles, and a sample in the font itself."""
    from PIL import Image, ImageDraw, ImageFont
    c = dict(bg='#14181d', base='#f2f2f2', accent='#9bd1ff'); c.update(colours or {}); ids = list(FONT_TABLE); rows = -(-len(ids) // columns); cw, ch = 760, 190
    img = Image.new('RGB', (columns * cw, rows * ch + 20), c['bg']); d = ImageDraw.Draw(img); small = ImageFont.truetype(path_of('inter'), 17); tiny = ImageFont.truetype(path_of('inter'), 14)
    for n, fid in enumerate(ids):
        f = FONT_TABLE[fid]; x, y = (n % columns) * cw + 24, (n // columns) * ch + 16; d.text((x, y), f"{fid}  ·  {f['family']}  ·  {f['category']}", font=small, fill=c['accent'])
        d.text((x, y + 24), 'vibes: ' + ', '.join(f['vibes']), font=tiny, fill=c['base']); d.text((x, y + 44), 'roles: ' + ', '.join(f['roles']) + f"   (smallest ~{f['min_em']:.2f} of the frame)", font=tiny, fill=c['base'])
        sample = 'DAY 2 · KILOMETRE 84' if f['caps'] else ('Keep going, only a hill.' if 'quote' in f['roles'] and 'display' not in f['roles'] else 'Day 2 · Kilometre 84'); d.text((x, y + 70), sample, font=load_font(fid, 62 if 'display' in f['roles'] else 46), fill=c['base'])
    img.save(path); return path
