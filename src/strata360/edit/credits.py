"""The credits a film made from a project needs to carry where it is shown (map tiles, imagery, terrain): listed here, never drawn into the picture. `strata360 credits FOLDER` prints them and `--write` saves `<project>/credits.txt`, to be added
with the film's distribution.

What counts: the map styles the overlay uses (the whole-route map and the close-up map, `race.json` overlay settings) when the overlay is on and there is a race track, and the generated clips of the plan: a 2D map clip uses the overlay's map style, a 3D flyover its imagery and the terrain data. The music and the footage are the
film maker's own business and are not listed."""
import os

from strata360.pipeline import config


def needed(folder):
    """[(what, credit text)] for this project: see the module docstring."""
    from strata360.edit import project as PJ
    from strata360.overlay import layout as LY, mapclip as MC, tiles as TL
    cfg = config.load(folder); st = LY.settings(cfg.get('overlay')); out = []; seen = set()
    def add(what, text):
        if text not in seen: seen.add(text); out.append((what, text))
    if st['enabled'] and config.track_path(folder, cfg):
        els = {n: {**LY.ELEMENTS[n], **st['layout'].get(n, {})} for n in st['elements'] if n in LY.ELEMENTS}
        for n, e in els.items():
            if e['kind'] in ('route_map', 'local_map'): style = st.get('style') or e.get('style'); add(f"the {n.replace('_', ' ')} on the overlay ({style})", TL.STYLES[style]['credit'])
    plan = (PJ.load(folder).get('plan') or {}).get('segments') or []; kinds = {}
    from strata360.edit import synthetic as SY
    docs = {c['id']: c for c in SY.load(folder)['clips']}
    for g in plan:
        if g.get('synthetic') and g['clip'] in docs: kinds[g['clip']] = docs[g['clip']]
    for cid, c in sorted(kinds.items()):
        if c['kind'] == 'flyover':
            from strata360.overlay import flyover as FO
            imagery = (c.get('style') or {}).get('imagery') or FO.DEFAULT_IMAGERY; add(f'the 3D flyover {cid}', FO.IMAGERY[imagery][3] + ' · ' + FO.TERRAIN_CREDIT)
        else:
            style = (c.get('style') or {}).get('map') or MC.DEFAULT_STYLE; add(f'the 2D map {cid} ({style})', TL.STYLES[style]['credit'])
    return out


def text(folder):
    rows = needed(folder)
    return 'Credits to carry with the film:\n' + ''.join(f'  {t}   [{what}]\n' for what, t in rows) if rows else 'No credits are needed for this project (no maps or imagery in the film).\n'


def write(folder):
    p = os.path.join(config.race_dir(folder), 'credits.txt'); open(p, 'w').write(text(folder)); return p
