"""Wordlists for the object detector, and the numbers that say which words earn their place.

`vocab.json` (next to this file, in the repo) holds the words by category: `always` (people and worn gear, and a core of everyday things) plus categories such as farm_rural or forest_trail. A clip's scene labels
(scenes.json, front and rear apart) choose its categories (`categorise`: a local model matches the labels to the category descriptions, with plain rules as the fallback); the detector gets `always` plus the union of the
chosen categories, at most `cap` words (a longer list names things worse).

Each time the detector names a box and the labelling model then says what it is, the outcome is recorded against the word in a StatsBook (`vocab_stats.json` in the project folder): fired, agreed, mislabelled (and as
what), or a false positive (the label was ground, sky, a body part, "unclear"). Labels the model gives to boxes the detector could not name are counted as suggestions. `update` lets the model review the suggestions that
turn up often enough (is it a distinct thing a runner can pass? which categories?), adds the good ones to the project's own list (`vocab_local.json`) and takes out words that keep being wrong; the shared list in the repo
changes only when someone exports those proposals and commits them. The model is a function argument `ask(prompts) -> answers`, so everything here runs without one in the tests."""
import json
import os
import re
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
VOCAB_FILE = os.path.join(HERE, 'vocab.json')
SEED_FILE = os.path.join(HERE, 'vocab_stats_seed.json')
MIN_SUGGEST = 3                 # times a label must be seen to be reviewed, in at least MIN_CLIPS clips
MIN_CLIPS = 2
WEAK_N = 8                      # a word is demoted after this many boxes when fewer than WEAK_PRECISION of them were right
WEAK_PRECISION = 0.25
TRUST_N = 20                    # a word is trusted (its box needs no label from the labelling model) after this many boxes when at least TRUST_PRECISION of them were right
TRUST_PRECISION = 0.9
TRUST_CONF = 0.4                # ... and only for boxes the detector is at least this sure of
AUDIT_EVERY = 10                # one trusted box in this many is labelled anyway, so the numbers keep coming and a word that goes wrong is noticed
RULES = {'forest': 'forest_trail', 'trail': 'forest_trail', 'town': 'town_village', 'building': 'town_village', 'field': 'farm_rural', 'river': 'water', 'road': 'road_traffic', 'aid_station': 'aid_station', 'start_finish': 'race_event',
         'mountain': 'moor', 'indoor': 'indoor'}
TAG_RULES = [(r'marathon|race|spectator|crowd|starting|finish|runners|event', 'race_event'), (r'aid station|checkpoint|refreshment|food', 'aid_station'), (r'city|urban|tram|shop', 'urban'), (r'dam|weir|pylon|power line|turbine|railway|tunnel', 'infrastructure'),
             (r'moor|heath|boardwalk|plateau', 'moor'), (r'deer|fox|squirrel|rabbit|wildlife', 'wildlife'), (r'river|stream|lake|waterfall|rapids|rushing water', 'water'), (r'farm|cow|sheep|goat|chicken|barn|pasture', 'farm_rural')]
FILLER = {'and', 'or', 'a', 'an', 'the', 'to', 'at', 'from', 'is', 'are'}
MODIFIERS = {'a', 'an', 'the', 'two', 'three', 'four', 'several', 'some', 'small', 'large', 'big', 'tiny', 'tall', 'short', 'long', 'old', 'new', 'white', 'black', 'brown', 'green', 'grey', 'gray', 'red', 'blue', 'yellow', 'orange',
             'dark', 'wooden', 'metal', 'stone', 'concrete', 'plastic', 'rusty', 'bare', 'little', 'distant', 'baby'}


def load(path=None, local=None):
    """The shared wordlists, with the project's own additions and removals (`local`, see apply) laid over them."""
    v = json.load(open(path or VOCAB_FILE))
    if local:
        for cat, words in (local.get('add') or {}).items():
            c = v['categories'].setdefault(cat, dict(about='', words=[])); c['words'] = c['words'] + [w for w in words if w not in c['words']]
        gone = set(local.get('remove') or [])
        v['categories'] = {k: dict(c, words=[w for w in c['words'] if w not in gone]) for k, c in v['categories'].items()}
        v['always'] = {k: [w for w in ws if w not in gone] for k, ws in v['always'].items()}
    return v


def words_for(categories, vocab=None, cap=None):
    """The words to give the detector for a clip: `always`, then each chosen category in turn, without repeats, at most `cap` (default the file's)."""
    v = vocab or load(); out = []
    for ws in list(v['always'].values()) + [v['categories'][c]['words'] for c in categories if c in v['categories']]:
        for w in ws:
            if w not in out and w not in v.get('retired', {}): out.append(w)
    return out[:cap or v.get('cap', 80)]


def _singular(w):
    if w == 'leaves': return 'leaf'
    if len(w) > 4 and w.endswith('ies'): return w[:-3] + 'y'
    if len(w) > 4 and w.endswith(('ches', 'shes', 'xes', 'sses', 'zes')): return w[:-2]
    return w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith(('ss', 'us', 'is')) else w


def normalise_label(label, vocab=None):
    """A label as a word to count: lower case, without numbers, colours, sizes and materials, singular; the thing before "on/in/with" and after "of"; the last word when that is already a word of the lists, else the last two
    ("two white ducks" -> "duck", "sign on fence post" -> "sign", "mossy retaining wall" -> "wall", "street lights" -> "street light", "lamp post" -> "lamp post")."""
    text = re.split(r'\b(?:on|in|with|near|by|under|beside|next to)\b', str(label).lower())[0]; text = text.split(' of ', 1)[1] if ' of ' in text else text
    ws = [w for w in re.findall(r"[a-z]+", text) if w not in MODIFIERS and w not in FILLER]
    if not ws: return ''
    ws[-1] = _singular(ws[-1])
    if len(ws) == 1: return ws[0]
    v = vocab or load(); known = {w for ws_ in v['always'].values() for w in ws_} | {w for c in v['categories'].values() for w in c['words']} | set(v.get('retired', {}))
    return ' '.join(ws[-2:]) if ' '.join(ws[-2:]) in known else ws[-1] if ws[-1] in known else ' '.join(ws[-2:])


def kind_of_label(label, vocab=None):
    """'stop' (not worth reporting: a body part, the ground, the sky, "unclear"), 'scenery' (trees and hills: real but filler) or 'feature'."""
    v = vocab or load(); words = set(re.findall(r'[a-z]+', str(label).lower())); text = str(label).lower()
    if any((s in text if ' ' in s else s in words) or s == text for s in v.get('stoplist', [])): return 'stop'
    if any(s in text for s in v.get('scenery', [])): return 'scenery'
    return 'feature'


def agrees(word, label, vocab=None):
    """Whether a label from the labelling model is the same kind of thing as the detector's word (the word's `accepts` list, else the word itself)."""
    v = vocab or load(); text = str(label).lower()
    return any(a in text for a in v.get('accepts', {}).get(word, [word])) or word in text


class StatsBook:
    """What happened to each word, and which labels turn up that no word covers."""
    def __init__(self, data=None):
        d = data or {}; self.words = {w: dict(fired=x.get('fired', 0), agreed=x.get('agreed', 0), false_positive=x.get('false_positive', 0), mislabels=Counter(x.get('mislabels', {}))) for w, x in (d.get('words') or {}).items()}
        self.suggest = {l: dict(count=x.get('count', 0), clips=Counter(x.get('clips', {})), examples=list(x.get('examples', []))) for l, x in (d.get('suggest') or {}).items()}
        self.cats = {c: dict(uses=x.get('uses', 0), fired=x.get('fired', 0), agreed=x.get('agreed', 0)) for c, x in (d.get('categories') or {}).items()}
        self.sources = list(d.get('sources', [])); self.updated = d.get('updated')

    @classmethod
    def read(cls, path):
        try: return cls(json.load(open(path)))
        except (OSError, ValueError): return cls()

    def to_json(self):
        return dict(schema=1, sources=self.sources, updated=self.updated, categories=dict(sorted(self.cats.items())), words={w: dict(x, mislabels=dict(x['mislabels'].most_common(8))) for w, x in sorted(self.words.items())},
                    suggest={l: dict(count=x['count'], clips=dict(x['clips']), examples=x['examples'][:3]) for l, x in sorted(self.suggest.items(), key=lambda kv: -kv[1]['count'])[:300]})

    def write(self, path):
        self.updated = time.strftime('%Y-%m-%dT%H:%M:%S'); os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True); tmp = f'{path}.{os.getpid()}.tmp'
        json.dump(self.to_json(), open(tmp, 'w'), indent=1); os.replace(tmp, path)

    def use_category(self, category):
        """A clip's detector was given the words of this category."""
        self.cats.setdefault(category, dict(uses=0, fired=0, agreed=0))['uses'] += 1

    def record_named(self, word, label, vocab=None, categories=()):
        """The detector named a box `word` and the labelling model called it `label`; `categories` are the ones that were in use (their numbers move with the word's)."""
        x = self.words.setdefault(word, dict(fired=0, agreed=0, false_positive=0, mislabels=Counter())); x['fired'] += 1
        for c in categories:
            y = self.cats.setdefault(c, dict(uses=0, fired=0, agreed=0)); y['fired'] += 1; y['agreed'] += bool(agrees(word, label, vocab))
        if kind_of_label(label, vocab) == 'stop' and not agrees(word, label, vocab): x['false_positive'] += 1
        elif agrees(word, label, vocab): x['agreed'] += 1
        else: x['mislabels'][normalise_label(label, vocab) or str(label).lower()] += 1

    def record_leftover(self, label, clip='', vocab=None, word=None):
        """The labelling model named a box the detector could not name: a candidate word, unless it is not worth reporting. `word` is the label already simplified (by canonicalise); without it the plain rules do it."""
        w = word if word is not None else normalise_label(label, vocab)
        if not w or kind_of_label(w if word is not None else label, vocab) != 'feature': return
        x = self.suggest.setdefault(w, dict(count=0, clips=Counter(), examples=[])); x['count'] += 1; x['clips'][clip] += 1
        if str(label) not in x['examples']: x['examples'].append(str(label))

    def merge(self, other):
        for w, y in other.words.items():
            x = self.words.setdefault(w, dict(fired=0, agreed=0, false_positive=0, mislabels=Counter()))
            for k in ('fired', 'agreed', 'false_positive'): x[k] += y[k]
            x['mislabels'].update(y['mislabels'])
        for l, y in other.suggest.items():
            x = self.suggest.setdefault(l, dict(count=0, clips=Counter(), examples=[])); x['count'] += y['count']; x['clips'].update(y['clips']); x['examples'] += [e for e in y['examples'] if e not in x['examples']]
        for c, y in other.cats.items():
            x = self.cats.setdefault(c, dict(uses=0, fired=0, agreed=0))
            for k in ('uses', 'fired', 'agreed'): x[k] += y[k]
        self.sources += [s for s in other.sources if s not in self.sources]

    def report(self, min_n=1):
        """Rows (word, fired, agreed, precision, false_positive, top mislabels), the weakest first."""
        rows = [(w, x['fired'], x['agreed'], x['agreed'] / x['fired'], x['false_positive'], [l for l, _ in x['mislabels'].most_common(3)]) for w, x in self.words.items() if x['fired'] >= min_n]
        return sorted(rows, key=lambda r: (r[3], -r[1]))

    def weak(self, vocab=None, min_n=WEAK_N, max_precision=WEAK_PRECISION):
        """Words that have fired at least `min_n` times and been right on fewer than `max_precision` of them."""
        return [r[0] for r in self.report(min_n) if r[3] < max_precision]

    def trusted(self, word, min_n=TRUST_N, min_precision=TRUST_PRECISION):
        """Whether the numbers say the detector's name for this word can be taken as it is: enough boxes, nearly all agreed with the labelling model, hardly any junk."""
        x = self.words.get(word)
        return bool(x) and x['fired'] >= min_n and x['agreed'] / x['fired'] >= min_precision and x['false_positive'] / x['fired'] <= 1 - min_precision

    def route(self, word, conf, vocab=None, rng=None):
        """What to do with a box the detector named `word`: 'accept' (keep the name, no model call), 'audit' (a trusted word, labelled anyway this time to keep the numbers honest), or 'label' (ask the labelling model).
        A word the lists retired is always labelled; so is any box the detector is not sure of."""
        v = vocab or load()
        if word in v.get('retired', {}) or conf < TRUST_CONF or not self.trusted(word): return 'label'
        import random
        return 'audit' if (rng or random).random() < 1.0 / AUDIT_EVERY else 'accept'

    def suggestions(self, vocab=None, min_count=MIN_SUGGEST, min_clips=MIN_CLIPS):
        """Labels seen often enough, in enough clips, that are not already a word (or retired)."""
        v = vocab or load(); known = set(v.get('retired', {})) | set(v['always']['people_gear']) | {w for ws in v['always'].values() for w in ws} | {w for c in v['categories'].values() for w in c['words']}
        return [l for l, x in sorted(self.suggest.items(), key=lambda kv: -kv[1]['count']) if l not in known and x['count'] >= min_count and len(x['clips']) >= min_clips]


# ---- the model's part: categories for a clip, and a review of suggested words ---------------------------------------------------------------------------------------------------------------
def parse_json(text):
    m = re.search(r'(\{.*\}|\[.*\])', str(text), re.S)
    if not m: return None
    try: return json.loads(m.group(1))
    except ValueError: return None


def scene_text(block):
    """A summary block of scenes.json (summary.front or summary.rear) as the lines the model reads."""
    b = block or {}; f = lambda d: ', '.join(f'{k} ({n})' if isinstance(n, int) else str(k) for k, n in (d.items() if isinstance(d, dict) else [(x, None) for x in d or []]))
    return f"settings: {f(b.get('settings'))}; weather: {f(b.get('weather'))}; lighting: {f(b.get('lighting'))}; crowd: {f(b.get('crowd'))}; tags: {f(b.get('tags'))}"


def rule_categories(block, vocab=None):
    """The categories a summary block implies by plain rules (the setting names, snow in the weather): the fallback when no model answers, and added to what it says."""
    v = vocab or load(); b = block or {}; out = []
    for s in (b.get('settings') or {}):
        c = RULES.get(s)
        if c and c not in out and c in v['categories']: out.append(c)
    tags = ' '.join(str(t) for t in (b.get('tags') or [])).lower()
    if any(k != 'puddle' for k in (b.get('water') or {})) and 'water' in v['categories'] and 'water' not in out: out.append('water')       # the model saw a river, stream or lake (a puddle on a wet road is not water)
    if (b.get('ground_snow') or 0) >= 0.3 and 'snow' not in out: out.append('snow')
    for rx, c in TAG_RULES:
        if c in v['categories'] and c not in out and re.search(rx, tags): out.append(c)
    if 'snow' in (b.get('weather') or {}) or 'snow' in tags.split():
        if 'snow' not in out: out.append('snow')
    if 'aid_station' in out and 'race_event' not in out: out.append('race_event')
    return out


def blocks_of(scenes_doc):
    """{'front': block, 'rear': block} from a scenes.json: the summary's own blocks, or (files from before they existed) built from the answered items of each view."""
    sm = (scenes_doc or {}).get('summary') or {}
    if sm.get('front') is not None and 'answered' in sm['front']: return dict(front=sm['front'], rear=sm.get('rear'))
    out = {}
    for view in ('front', 'rear'):
        its = [i for i in (scenes_doc or {}).get('items') or [] if i.get('view') == view and i.get('ok')]
        if not its: out[view] = None; continue
        top = lambda k, n=4: dict(Counter(i[k] for i in its if i.get(k) and i[k] != 'unknown').most_common(n))
        out[view] = dict(answered=len(its), settings=top('setting'), weather=top('weather', 3), lighting=top('lighting', 3), crowd=top('crowd', 3), tags=[t for t, _ in Counter(t for i in its for t in (i.get('tags') or []) if isinstance(t, str)).most_common(10)])
    return out


def categorise(block, ask=None, vocab=None):
    """The categories (most relevant first, at most 5) for one direction of a clip, from its scene labels: the model's answer plus the rules."""
    v = vocab or load(); names = list(v['categories']); rules = rule_categories(block, v)
    if ask is None or not block: return rules[:5]
    menu = '\n'.join(f"- {n}: {v['categories'][n]['about']}" for n in names)
    prompt = (f"A vision model labelled stretches of running footage. Labels for one view: {scene_text(block)}.\nWhich of these categories describe what a runner passes here? Pick 0 to 4, the most relevant first.\n{menu}\n"
              'Answer with a JSON list of category names only, for example ["forest_trail", "water"].')
    got = parse_json(ask([prompt])[0]); got = [c for c in got if c in names] if isinstance(got, list) else []
    out = []
    for c in got + rules:
        if c not in out: out.append(c)
    return out[:5]


def canonicalise(labels, ask, vocab=None, batch=40):
    """{label: simple word} for odd labels from the labelling model ("mossy retaining wall" -> "wall", "white plastic jug" -> "jug"): the model picks a word from the lists when one fits, otherwise the plain common noun, or says skip
    (None) for ground, sky, body parts and anything that is not a distinct thing. Labels it does not answer for fall back to normalise_label."""
    v = vocab or load(); known = sorted({w for ws in v['always'].values() for w in ws} | {w for c in v['categories'].values() for w in c['words']}); out = {}; labels = list(dict.fromkeys(str(l) for l in labels)); prompts = []
    for i in range(0, len(labels), batch):
        chunk = labels[i:i + batch]
        prompts.append("Simplify these labels given to crops from running footage. For each, answer only the plain singular common noun for the main thing: one or two words, the thing itself with no describing word at all (no colour, size, material, number, condition such as mossy, wet or broken). Use a word from this list when it fits: "
                       f"{', '.join(known)}.\nAnswer \"skip\" for ground, sky, grass, snow, water, a body part, worn gear, a person or anything that is not a distinct thing.\nLabels (one per line):\n" + '\n'.join(chunk) + '\nAnswer with a JSON object mapping each label to its word or "skip", nothing else.')
    for chunk_i, ans in enumerate(ask(prompts) if prompts else []):
        got = parse_json(ans); got = got if isinstance(got, dict) else {}
        for l in labels[chunk_i * batch:(chunk_i + 1) * batch]:
            w = got.get(l)
            w = None if isinstance(w, str) and w.strip().lower() in ('skip', 'none', '') else (normalise_label(w, v) if isinstance(w, str) else normalise_label(l, v))
            out[l] = w if w and kind_of_label(w, v) != 'stop' else None                                    # the simplified word is what the stop-list judges
    return out


def review(book, ask, vocab=None, min_count=MIN_SUGGEST, min_clips=MIN_CLIPS):
    """Ask the model about each suggested word: [dict(word, add, categories, why)] for those it accepts as distinct things a runner can pass."""
    v = vocab or load(); cands = book.suggestions(v, min_count, min_clips)
    if not cands: return []
    names = list(v['categories']); menu = ', '.join(names); prompts = []
    for w in cands:
        x = book.suggest[w]
        prompts.append(f"A vision model labelled {x['count']} crops from running footage (in {len(x['clips'])} clips) as \"{w}\" (e.g. {', '.join(x['examples'][:3])}).\nShould \"{w}\" be a word an object detector looks for? Yes only if it is a distinct physical thing a runner can "
                       f"pass or see (a sign, an animal, a building, a vehicle, a structure), and no if it is terrain, weather, ground clutter, a body part, worn gear or text.\nIf yes, give the singular word (one or two words) and its categories from: {menu}.\n"
                       'Answer with JSON only: {"add": true or false, "word": "...", "categories": ["..."]}')
    out = []
    for w, ans in zip(cands, ask(prompts)):
        a = parse_json(ans)
        if not isinstance(a, dict) or a.get('add') is not True: continue
        word = normalise_label(a.get('word') or w, v) or w; cats = [c for c in (a.get('categories') or []) if c in names]
        if cats and word not in v.get('retired', {}): out.append(dict(word=word, categories=cats, from_label=w))
    return out


def apply(local, proposals, demote=()):
    """The project's own additions and removals, `local`, with accepted proposals added and weak words removed."""
    local = dict(local or {}); add = {c: list(ws) for c, ws in (local.get('add') or {}).items()}
    for p in proposals:
        for c in p['categories']:
            if p['word'] not in add.setdefault(c, []): add[c].append(p['word'])
    local['add'] = add; local['remove'] = sorted(set(local.get('remove') or []) | set(demote)); return local


def project_paths(root):
    d = os.path.join(root, 'strata360'); return dict(stats=os.path.join(d, 'vocab_stats.json'), local=os.path.join(d, 'vocab_local.json'))


def collect(root, write=True):
    """The project's StatsBook rebuilt from the repo's seed and the numbers each clip's objects.json recorded (clips are processed in parallel, so each keeps its own; this is the one place they are added up). Written to the
    project's vocab_stats.json unless `write` is False."""
    import glob
    book = StatsBook.read(SEED_FILE); book.sources = list(book.sources)
    for fn in sorted(glob.glob(os.path.join(root, 'strata360', 'clips', '*', 'objects.json'))):
        try: doc = json.load(open(fn))
        except (OSError, ValueError): continue
        if doc.get('stats'): book.merge(StatsBook(doc['stats'])); book.sources.append(os.path.basename(os.path.dirname(fn)))
    if write: book.write(project_paths(root)['stats'])
    return book


def stats_for(root):
    """What the stage routes by: the repo's seed plus the project's own numbers (as last collected)."""
    book = StatsBook.read(SEED_FILE); mine = project_paths(root)['stats']
    if os.path.exists(mine): book.merge(StatsBook.read(mine))
    return book


def update(root, ask, vocab=None):
    """Review the project's suggestions with the model, write the accepted words and the demotions to its local list; returns (proposals, demoted)."""
    pp = project_paths(root); book = collect(root); local = json.load(open(pp['local'])) if os.path.exists(pp['local']) else {}
    v = load(local=local) if vocab is None else vocab; props = review(book, ask, v); weak = [w for w in book.weak(v) if w not in (local.get('remove') or [])]
    new = apply(local, props, weak); os.makedirs(os.path.dirname(pp['local']), exist_ok=True); json.dump(new, open(pp['local'], 'w'), indent=1); return props, weak


def ask_with_runner(prompts, models=None):
    """The real model: the prompts through analysis/vocab_llm.py (a local Qwen in `.venv-vision`), answers in the same order."""
    import subprocess, tempfile
    py = os.environ.get('STRATA_VISION_PYTHON') or os.path.join(HERE, '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(HERE, '..', '..'); d = tempfile.mkdtemp(prefix='s360voc_'); rq, rs = os.path.join(d, 'q.json'), os.path.join(d, 'a.json')
    json.dump(prompts, open(rq, 'w')); subprocess.run([py, '-m', 'strata360.analysis.vocab_llm', rq, rs] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    return json.load(open(rs))


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 2 and a[0] == 'categorise':
        d = a[1]; bl = blocks_of(json.load(open(os.path.join(d, 'scenes.json')))); v = load(); out = {}
        for view in ('front', 'rear'):
            out[view] = categorise(bl.get(view), ask_with_runner, v)
        allc = list(dict.fromkeys(out['front'] + out['rear'])); print(json.dumps(dict(front=out['front'], rear=out['rear'], words=len(words_for(allc, v))))); return
    if len(a) >= 2 and a[0] == 'update':
        props, weak = update(a[1], ask_with_runner); print(json.dumps(dict(added=props, demoted=weak), indent=1)); return
    if len(a) >= 2 and a[0] == 'report':
        for w, n, ag, pr, fp, ml in StatsBook.read(project_paths(a[1])['stats']).report(): print(f'{w:16} fired {n:3d}  right {pr:4.0%}  junk {fp:2d}  called instead: {", ".join(ml)}')
        return
    print('usage: python -m strata360.analysis.vocab categorise CLIP_DIR | update PROJECT_ROOT | report PROJECT_ROOT')


if __name__ == '__main__':
    main()
