import json, sys, re, collections
def parse(a):
    t = re.sub(r'^```(?:json)?|```$', '', a.strip(), flags=re.M).strip()
    try: return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S)
        try: return json.loads(m.group(0)) if m else None
        except Exception: return None
def flat(v):
    out = []
    for x in (v if isinstance(v, list) else [v]):
        if isinstance(x, dict): out.append(' '.join(str(z) for z in x.values()))
        elif x: out.append(str(x))
    return out
for name in sys.argv[2:]:
    r = json.load(open(f'{sys.argv[1]}/res_{name}.json')); bad = 0; per = collections.defaultdict(lambda: dict(n=0, animals=0, water=0, an=collections.Counter(), wt=collections.Counter()))
    for x in r:
        c = x['file'].split('/')[0]; j = parse(x['answer']); p = per[c]; p['n'] += 1
        if not isinstance(j, dict): bad += 1; continue
        an = flat(j.get('animals')); w = ' '.join(re.findall(r'river|stream|lake|pond|sea|waterfall|creek|canal|ocean|puddle|rapids|dam|reservoir|water|weir|brook', str(j.get('water', 'none')).lower())) or 'none'
        if an: p['animals'] += 1; [p['an'].update([re.sub(r'\d+|\W', ' ', a).strip()[:18]]) for a in an]
        if w not in ('none', '', 'n/a', 'null', '[]', 'no'): p['water'] += 1; p['wt'][w[:22]] += 1
    print(f'## {name}: {len(r)} answers, unparsed {bad}')
    for c, p in sorted(per.items()): print(f"  {c}: animal views {p['animals']}/{p['n']} {dict(p['an'].most_common(4))} | water views {p['water']} {dict(p['wt'].most_common(3))}")
