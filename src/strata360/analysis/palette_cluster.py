"""Project colour schemes: a few schemes for the whole film instead of one per clip, so the titles do not jump about.

The per-clip palettes (analysis/palette.py) are each the best scheme for their own footage, but neighbouring clips of one night or one forest then get slightly different colours. Fewer schemes mean a steadier film; fewer schemes also mean each clip is further from its best. That is an
optimisation (uncapacitated facility location): choose a set S of schemes and assign every clip to one of them so as to minimise

    total = sum over clips c of loss(c, scheme of c)  +  COST * |S|

  loss(c, s)  = hue     how far the scheme's hue is from the clip's, in quarter turns, weighted by how colourful the clip is (a grey night clip barely has a hue to get wrong)
              + tone    how different the lightness of the footage the scheme was made for is (lightness of the bright and dark parts of the footage, 0 to 1)
              + read    how much worse the scheme's best swatch reads on this clip's footage than the clip's own best does (contrast against its bright and dark parts, 0 to 1)
  COST        what one more scheme costs, in the same units: 2.0 means a new scheme must save more than 2.0 of loss over all the clips it takes (a clip moved a quarter turn of hue away costs about 1). `sweep` shows what other costs give.

The day/night split is not what separates schemes: every scheme carries pale and deep swatches and each word picks per area (title_design.style_from_palette), so footage of any brightness can use any scheme. The hue family is what differs.

Solved by greedy opening of schemes and then add/drop/swap passes over the candidates (every clip's own scheme), then each group is REFIT (its colours merged, its hue taken over the whole group, made to read on the group's typical footage) and the clips are assigned again, until nothing changes. N is the number of
clips (tens to hundreds): this is instant.

Output `<project>/strata360/palette_schemes.json`; `for_clip(folder, clip)` gives a clip its project scheme as a palette document (the same shape as the clip's own palette.json), or the clip's own palette when there is no file or the clip is not in it."""
import json, math, os
import numpy as np

from strata360.analysis import palette as P
from strata360.render import titles as TT

FILE = 'palette_schemes.json'
COST = 2.0                          # on the project this was tuned on (61 clips of one race): 3 schemes from 2.0 to 3.5, 2 above 5, 10 at 0.35; see `sweep`
MAX_K = 12
HUE_WEIGHT_C = 30.0                 # a clip whose hue has this much chroma (Lab) counts its hue in full
MIN_HUE_WEIGHT = 0.1                # a grey clip still counts its hue a little
NAMES = ((20, 'red'), (50, 'orange'), (75, 'yellow'), (165, 'green'), (195, 'teal'), (255, 'blue'), (280, 'indigo'), (310, 'violet'), (340, 'magenta'), (361, 'red'))


def _lstar(y): return 116.0 * (max(y, 0.0) ** (1.0 / 3.0)) - 16.0 if y > 0.008856 else 903.3 * y


def _hue_diff(a, b):
    d = abs(a - b) % 360.0; return min(d, 360.0 - d)


def features(doc):
    """What the loss needs of one palette document: hue, how much chroma it has, the lightness (L*, 0 to 100) of the bright and dark parts of the footage, and the two colours themselves."""
    hue, chroma, found = P.pick_hue(doc['colours']); b = doc['backgrounds']; light, dark = TT.hex_rgb(b['light']), TT.hex_rgb(b['dark'])
    return dict(hue=hue, chroma=chroma if found else 0.0, found=found, light=light, dark=dark, L=(_lstar(TT.luminance(light)) + _lstar(TT.luminance(dark))) / 2.0, swatches=[x['hex'] for x in doc['scheme']['swatches']], scheme_hue=doc['scheme']['hue'])


def best_read(swatches, backs):
    """The contrast of the swatch that does best against the worst of `backs` (colours as 0..1 triples)."""
    return max(min(TT.contrast(TT.hex_rgb(h), b) for b in backs) for h in swatches)


def loss(c, s):
    """What using scheme `s` (a features dict of the scheme) costs the clip with features `c`. Each term is about 0 to 1."""
    w = float(np.clip(c['chroma'] / HUE_WEIGHT_C, MIN_HUE_WEIGHT, 1.0)); hue = w * min(_hue_diff(c['hue'], s['hue']) / 90.0, 2.0) if (c['found'] or s['found']) else 0.0
    tone = abs(c['L'] - s['L']) / 100.0 * 2.0
    own = best_read(c['swatches'], [c['light'], c['dark']]); mine = best_read(s['swatches'], [c['light'], c['dark']]); read = float(np.clip(1.0 - mine / max(own, 1e-6), 0.0, 1.0))
    return hue + tone + read


def matrix(fs):
    """[i][j]: the loss of clip i when it uses the scheme that was made for clip j."""
    return np.array([[loss(c, s) if i != j else 0.0 for j, s in enumerate(fs)] for i, c in enumerate(fs)])


def solve(D, cost=COST, max_k=MAX_K):
    """The set of facilities (columns of D) and the assignment minimising sum of D[i, assigned] + cost * |set|. Greedy add, then add/drop/swap until no move helps. Returns (facilities, assignment, total)."""
    n = D.shape[0]; cost = float(cost)
    def total(S): return D[:, sorted(S)].min(1).sum() + cost * len(S)
    S = {int(np.argmin(D.sum(0)))}; best = total(S)
    for _ in range(4 * n):
        moves = []
        for j in range(n):
            if j not in S and len(S) < max_k: moves.append((total(S | {j}), S | {j}))
        for j in S:
            if len(S) > 1: moves.append((total(S - {j}), S - {j}))
            for k in range(n):
                if k not in S: moves.append((total((S - {j}) | {k}), (S - {j}) | {k}))
        if not moves: break
        t, S2 = min(moves, key=lambda m: m[0])
        if t < best - 1e-9: best, S = t, S2
        else: break
    fac = sorted(S); assign = [fac[int(np.argmin(D[i, fac]))] for i in range(n)]; return fac, assign, best


def name_of(hue, found):
    if not found: return 'neutral'
    h = hue % 360.0
    return next(n for lim, n in NAMES if h < lim)


def merged_hue(docs):
    """(hue, chroma, found) of a group of clips: the colourful clusters of every member by share times chroma, the hue taken from the 60 degree window of the circle that holds most weight (its weighted circular mean)."""
    pts = [(c['h'], c['share'] * c['C'], c['C']) for d in docs for c in d['colours'] if c['C'] >= P.MIN_CHROMA and P.MAX_WEIGHT_L[0] <= c['L'] <= P.MAX_WEIGHT_L[1]]
    if not pts: return P.FALLBACK_HUE, 0.0, False
    h = np.array([p[0] for p in pts]); w = np.array([p[1] for p in pts]); ch = np.array([p[2] for p in pts])
    centre = max(range(0, 360, 5), key=lambda a: w[[_hue_diff(x, a) <= 30 for x in h]].sum()); inside = np.array([_hue_diff(x, centre) <= 30 for x in h])
    ang = np.radians(h[inside]); mean = math.degrees(math.atan2((w[inside] * np.sin(ang)).sum(), (w[inside] * np.cos(ang)).sum())) % 360.0
    return float(mean), float((w[inside] * ch[inside]).sum() / w[inside].sum()), True


def refit(docs):
    """One scheme for a group of palette documents: the merged hue, made to read on the group's typical footage (the member whose bright part is the median brightness, and the one whose dark part is). Returns a palette-document-shaped dict."""
    hue, chroma, found = merged_hue(docs); lum = lambda d, k: TT.luminance(TT.hex_rgb(d['backgrounds'][k]))
    by_light = sorted(docs, key=lambda d: lum(d, 'light')); by_dark = sorted(docs, key=lambda d: lum(d, 'dark')); light_q = TT.hex_rgb(by_light[len(docs) // 2]['backgrounds']['light']); dark_q = TT.hex_rgb(by_dark[len(docs) // 2]['backgrounds']['dark'])
    colours = sorted([dict(c) for d in docs for c in d['colours']], key=lambda c: -c['share'] * c['C'])[:6]
    colours = [dict(c, share=round(c['share'] / len(docs), 3)) for c in colours]
    from strata360.analysis.palette import build_scheme
    forced = [dict(hex='#808080', share=1.0, L=50.0, C=chroma if found else 0.0, h=hue)]                    # build_scheme takes the hue from the colours: one entry that stands for the group's
    scheme = build_scheme(forced if found else [], light_q, dark_q)
    if found: scheme['hue'] = round(hue, 1)
    return dict(colours=colours, backgrounds=dict(light=P.to_hex(light_q), dark=P.to_hex(dark_q)), mood=P.mood(forced if found else [], light_q, dark_q, scheme), scheme=scheme)


def cluster(docs, cost=COST, max_k=MAX_K, rounds=6):
    """{ids: [clip ids], schemes: [palette document of each group + label, members], assignment: {clip id: scheme index}, cost, k, loss_total, loss_mean, own_loss_mean} for the palette documents `docs` ({clip id: palette.json}). Raises ValueError without documents."""
    if not docs: raise ValueError('no clip has a palette yet: run the palette stage')
    ids = sorted(docs); fs = [features(docs[i]) for i in ids]; D = matrix(fs); fac, assign, _ = solve(D, cost, max_k)
    groups = {f: [i for i, a in enumerate(assign) if a == f] for f in fac}; schemes = [refit([docs[ids[i]] for i in m]) for m in groups.values()]; members = list(groups.values())
    for _ in range(rounds):                                                                                     # reassign to the refit schemes, refit, until nothing moves
        sf = [features(s) for s in schemes]; L = np.array([[loss(c, s) for s in sf] for c in fs]); new = [int(np.argmin(L[i])) for i in range(len(ids))]
        groups2 = [[i for i, a in enumerate(new) if a == k] for k in range(len(schemes))]; keep = [k for k, m in enumerate(groups2) if m]
        if len(keep) < len(schemes) or groups2 != members: schemes = [refit([docs[ids[i]] for i in groups2[k]]) for k in keep]; members = [groups2[k] for k in keep]
        else: break
    sf = [features(s) for s in schemes]; L = np.array([[loss(c, s) for s in sf] for c in fs]); asg = [int(np.argmin(L[i])) for i in range(len(ids))]
    for k, s in enumerate(schemes):
        mem = [ids[i] for i, a in enumerate(asg) if a == k]; s['members'] = mem; s['label'] = name_of(s['scheme']['hue'], s['scheme']['found'])
        s['mean_loss'] = round(float(np.mean([L[ids.index(m), k] for m in mem])), 3) if mem else 0.0
    seen = {}
    for s in schemes: seen.setdefault(s['label'], []).append(s)
    for label, same in seen.items():                                                                              # two schemes of one hue family get their hue in degrees, so every label is unique
        if len(same) > 1:
            for k, s in enumerate(sorted(same, key=lambda x: x['scheme']['hue'])): s['label'] = f"{label} {round(s['scheme']['hue'])}" + (f' #{k + 1}' if len({round(x['scheme']['hue']) for x in same}) < len(same) else '')
    schemes = [s for s in schemes if s['members']]; remap = {old: new for new, old in enumerate(sorted({a for a in asg}))}; asg = [remap[a] for a in asg]
    lt = float(sum(L[i, asg[i]] for i in range(len(ids))))
    return dict(cost=cost, k=len(schemes), loss_total=round(lt, 3), loss_mean=round(lt / len(ids), 3), schemes=schemes, assignment={ids[i]: asg[i] for i in range(len(ids))})


def sweep(docs, costs=(0.1, 0.35, 0.75, 1.5, 2.0, 3.5, 5.0, 10.0, 20.0)):
    """[(cost, k, mean loss)] for a range of costs: what a steadier film costs in accuracy."""
    out = []
    for c in costs: r = cluster(docs, c); out.append((c, r['k'], r['loss_mean']))
    return out


def load_docs(folder):
    """{clip id: palette.json} of the project's clips that have one."""
    from strata360.pipeline import config
    rd = os.path.join(config.race_dir(folder), 'clips'); out = {}
    for c in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        d = P.load(os.path.join(rd, c))
        if d: out[c] = d
    return out


def run(folder, cost=COST):
    """Cluster the project's clip palettes and write palette_schemes.json. Returns the result."""
    from strata360.pipeline import config
    docs = load_docs(folder); res = cluster(docs, cost); path = os.path.join(config.race_dir(folder), FILE); tmp = path + '.tmp'
    json.dump(res, open(tmp, 'w'), indent=1); os.replace(tmp, path); return res


def load(folder):
    from strata360.pipeline import config
    try: return json.load(open(os.path.join(config.race_dir(folder), FILE)))
    except (OSError, ValueError): return None


def for_clip(folder, clip):
    """The palette document a clip's titles use: its project scheme (`cluster`, `label` added) when palette_schemes.json has the clip, else the clip's own palette.json, else None."""
    from strata360.pipeline import config
    doc = load(folder); i = (doc or {}).get('assignment', {}).get(clip)
    if i is not None and i < len(doc['schemes']): s = doc['schemes'][i]; return dict(colours=s['colours'], backgrounds=s['backgrounds'], mood=s['mood'], scheme=s['scheme'], cluster=i, label=s['label'])
    return P.load(os.path.join(config.race_dir(folder), 'clips', clip))
