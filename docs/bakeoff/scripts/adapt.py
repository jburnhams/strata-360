import sys, os, json, math, time, re, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanlib as L
from strata360.analysis import views as VW
S = L.S; CLIPS = ['0013', '0018', '0021']; OUT = S + '/adapt'; os.makedirs(OUT, exist_ok=True)
EXTRA = ['platform', 'container', 'hedge', 'signpost', 'street light', 'overhead wire', 'church', 'steeple', 'chimney', 'tractor', 'truck', 'van', 'bus', 'motorcycle', 'bicycle', 'boat', 'bench', 'bin', 'tent', 'banner', 'flag', 'gate', 'stairs', 'statue', 'tower', 'weir', 'waterfall', 'cabin', 'shed', 'barn', 'toilet', 'table', 'log', 'tree stump', 'boulder', 'cairn', 'puddle', 'railing']
SMALL = L.NAMED + EXTRA
def foc_of(c): return json.load(open(L.clip_dir(c) + '/focus.json'))['samples']
def frame_at(c, t):
    cap = cv2.VideoCapture(L.clip_dir(c) + '/proxy.mp4'); cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * cap.get(cv2.CAP_PROP_FPS)))); ok, eq = cap.read(); return eq
def scan_phase(kind):
    from ultralytics import YOLOE
    tx = YOLOE(S + '/yw/yoloe-26s-seg.pt'); tx.set_classes(SMALL, tx.get_text_pe(SMALL)); pf = YOLOE(S + '/yw/yoloe-26s-seg-pf.pt'); res = {}; t0 = time.time()
    for c in CLIPS:
        cr = VW.CropRenderer(L.osv_of(c)); foc = foc_of(c); sel, info = L.select_frames(c)
        if kind == 'dense': dt = 2.0 if info['dur'] < 15 else 2.5; times = [round(x, 2) for x in np.arange(1.0, info['dur'] - 0.5, dt)]
        else: times = [max(t, 1.0) for t in sel]; times = sorted(set(times))
        frames = []; thumbs = []
        for t in times:
            cands, people = L.scan_moment(cr, t, tx, pf, foc)
            frames.append(dict(t=t, cands=[dict(c2, tile=list(c2['tile'])) for c2 in cands], n_people=len(people)))
            if kind == 'adapt': eq = frame_at(c, t); thumbs.append(np.stack([L.tile_thumb(eq, la, lo) for la, lo in L.TILES]))
            print(kind, c, t, len(cands), f'({time.time()-t0:.0f}s)', flush=True)
        res[c] = dict(info=info, frames=frames)
        if kind == 'adapt': np.save(f'{OUT}/thumbs_{c}.npy', np.stack(thumbs))
        json.dump(res, open(f'{OUT}/{kind}.json', 'w'))
    print('done', kind, round(time.time() - t0))
STOP = ('person', 'man', 'woman', 'people', 'leg', 'hand', 'foot', 'feet', 'shoe', 'boot', 'jacket', 'hood', 'headlamp', 'lamp on', 'bottle', 'pole', 'backpack', 'glove', 'hat', 'sleeve', 'arm', 'finger', 'face',
        'road', 'asphalt', 'path', 'ground', 'grass', 'snow', 'sky', 'cloud', 'water', 'fog', 'dirt', 'gravel', 'mud', 'track', 'lichen', 'moss', 'unclear', 'leaves', 'leaf')
def stoplisted(lab): l = lab.lower(); return any(s in l for s in STOP)
def tiles_scanned(thumbs, tm, tp):
    """Policy: a tile is scanned when it was never scanned, or its thumbnail differs from the one at its last scan (mean difference > tm or the 99th percentile > tp). Returns [set of tile indexes per frame]."""
    last = {}; out = []
    for j in range(len(thumbs)):
        s = set()
        for k in range(thumbs.shape[1]):
            if k not in last: s.add(k)
            else:
                d = np.abs(thumbs[j, k].astype(np.int16) - last[k].astype(np.int16))
                if d.mean() > tm or np.percentile(d, 99) > tp: s.add(k)
        for k in s: last[k] = thumbs[j, k]
        out.append(s)
    return out
def remember(frames_cands, match_deg=2.0):
    """Object memory: a candidate within `match_deg` (or 0.6 of its size) of a known object of similar size is that object again (its position follows it); anything else is new."""
    mem = []; new_flags = []
    for t, cands in frames_cands:
        flags = []
        for c in cands:
            hit = None
            for m in mem:
                r = c['deg'] / max(m['deg'], 1e-3)
                if 0.4 <= r <= 2.5 and L.angdist((c['lon'], c['lat']), (m['lon'], m['lat'])) < max(match_deg, 0.6 * max(c['deg'], m['deg'])): hit = m; break
            if hit: hit['sight'].append((t, c['lon'], c['lat'])); hit['lon'], hit['lat'], hit['deg'] = c['lon'], c['lat'], c['deg']; flags.append(False)
            else: mem.append(dict(lon=c['lon'], lat=c['lat'], deg=c['deg'], kind=c['kind'], yoloe=c['yoloe'], t0=t, sight=[(t, c['lon'], c['lat'])])); flags.append(True)
        new_flags.append(flags)
    return mem, new_flags
if __name__ == '__main__':
    ph = sys.argv[1]
    if ph in ('dense', 'adapt'): scan_phase(ph)
