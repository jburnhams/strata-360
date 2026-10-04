import json, glob, collections, re
D = "/Volumes/Expansion/2026-02-19 - Legends/strata360/clips"; S = "$S".replace('$S', __import__('os').path.dirname(__file__))
V = [json.loads(l) for l in open(f'{S}/vocab_cats.jsonl')]
CORE = ['cow','sheep','horse','pig','chicken','goat','dog','deer','bird','duck','car','bicycle','bus','truck','van','tractor','house','barn','fence','gate','bench','road sign','bridge','boat','tent','flag','banner','trash can','traffic light','church','statue','power line']
SET = {'town': ['town_village', 'road_traffic'], 'trail': ['forest_trail'], 'forest': ['forest_trail'], 'field': ['rural_farm'], 'river': ['water_inland'], 'road': ['road_traffic'], 'aid_station': ['race_event', 'town_village'], 'indoor': [], 'night_scene': []}
KW = {'mountain_snow': r'snow|mountain|hill|alp|ridge', 'rural_farm': r'fence|animal|rural|farm|field|cow|sheep|pasture', 'water_inland': r'river|stream|water|bridge|dam|lake|waterfall', 'town_village': r'building|church|village|town|house|street|brick|historic', 'urban': r'city|urban|skyline|traffic|tram', 'coast_sea': r'beach|sea|coast|ocean|harbou?r', 'race_event': r'spectator|aid station|race|marathon|crowd|checkpoint|banner', 'wildlife': r'animal|bird|deer|wildlife'}
def cats_for(n):
    d = glob.glob(f'{D}/CAM_*_{n}_D')[0]; s = json.load(open(d + '/scenes.json'))['items']; c = collections.Counter()
    for i in s:
        for k in SET.get(i.get('setting'), []): c[k] += 1
        txt = ' '.join(i.get('tags') or [])
        for k, rx in KW.items():
            if re.search(rx, txt, re.I): c[k] += 1
    base = {'forest_trail'} if n in ('0006', '0023') else set()
    keep = {k for k, v in c.items() if v >= max(1, 0.2 * len(s))} | base
    return sorted(keep)
packs = {}
for n in ['0002', '0004', '0006', '0009', '0013', '0014', '0016', '0018', '0023']:
    cs = cats_for(n); sc = []
    for x in V:
        if x['y'] < 0.5: continue
        m = max([x['cats'][c] for c in cs] or [0])
        if m >= 0.8: sc.append((m * x['y'], x['tag']))
    terms = [t for _, t in sorted(sc, reverse=True)][:45]
    for t in CORE:
        if t not in terms: terms.append(t)
    packs[n] = dict(cats=cs, terms=terms)
    print(n, cs, len(sc), '->', len(terms)); print('   ', terms[:45])
json.dump(packs, open(f'{S}/packs.json', 'w'), indent=1)
