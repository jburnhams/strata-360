"""Who is who: cluster the faces found by the `people` stage across a whole race, show them to the user once so they can say which one is them, and keep that
as a reusable profile (`profiles/<label>.npz`, gitignored: it is biometric data). Later runs score every face against the profile.

    ./strata360 who RACE                 # clusters faces, writes races/RACE/people/clusters.png and clusters.json, suggests the wearer
    ./strata360 who RACE --me 3          # saves cluster 3 as profiles/me.npz
"""
import glob, json, os
import numpy as np, cv2
from scipy.cluster.hierarchy import linkage, fcluster

MIN_SCORE, MIN_SIZE = 0.6, 40.0
THRESHOLD = 0.55            # cosine distance for "same person" on ArcFace embeddings: conservative, so one person may split in two (harmless) rather than two merge


def collect(race_dir):
    E, T, meta = [], [], []
    for f in sorted(glob.glob(os.path.join(race_dir, 'clips', '*', 'people.json'))):
        d = os.path.dirname(f); cid = os.path.basename(d)
        try: emb = np.load(os.path.join(d, 'faces.npy')).astype(np.float32); th = np.load(os.path.join(d, 'faces_thumbs.npy')); doc = json.load(open(f))
        except OSError: continue
        for p in doc['people']:
            fc = p.get('face')
            if not fc or fc['score'] < MIN_SCORE or fc['size_px'] < MIN_SIZE: continue
            E.append(emb[fc['emb']]); T.append(th[fc['emb']]); meta.append(dict(clip=cid, frame=p['frame'], yaw=p['yaw'], size=fc['size_px'], score=fc['score']))
    return np.array(E).reshape(-1, 512), (np.array(T) if T else np.zeros((0, 96, 96, 3), np.uint8)), meta


def cluster(E):
    if len(E) < 2: return np.ones(len(E), int)
    E = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    return fcluster(linkage(E, 'average', metric='cosine'), THRESHOLD, 'distance')


def summarise(E, T, meta, lab, top=14, per=12):
    out = []
    for c in sorted(set(lab), key=lambda c: -(lab == c).sum())[:top]:
        idx = np.flatnonzero(lab == c); yaws = np.array([meta[i]['yaw'] for i in idx]); rear = float(np.mean(np.abs((yaws - 180 + 180) % 360 - 180) < 45))
        sizes = np.array([meta[i]['size'] for i in idx]); cen = E[idx].mean(0); cen /= np.linalg.norm(cen)
        pick = idx[np.argsort(-np.array([meta[i]['size'] * meta[i]['score'] for i in idx]))[:per]]
        out.append(dict(cluster=int(c), n=int(len(idx)), clips=len({meta[i]['clip'] for i in idx}), rear_fraction=round(rear, 2), median_size_px=round(float(np.median(sizes)), 1), sample=[int(i) for i in pick]))
    return out


def sheet(T, summary, path, per=12):
    rows = []
    for s in summary:
        strip = np.zeros((96, 96 * per + 130, 3), np.uint8)
        for j, i in enumerate(s['sample'][:per]): strip[:, 130 + j * 96:130 + (j + 1) * 96] = T[i]
        cv2.putText(strip, f"#{s['cluster']}", (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2); cv2.putText(strip, f"n={s['n']}", (6, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(strip, f"rear {s['rear_fraction']:.0%}", (6, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1); rows.append(strip)
    cv2.imwrite(path, np.vstack(rows)[:, :, ::-1])            # thumbnails are RGB, OpenCV writes BGR


def suggest_wearer(E, lab, S, merge_cos=0.4):
    """Who is the wearer? The person whose face is nearly always straight in front of the rear lens (the selfie stick), seen in several clips. The same person from other
    head angles splits into extra clusters, so every cluster whose centroid is within `merge_cos` cosine of the seed (and mostly in front of the rear lens) is added.
    Returns dict(clusters=[ids], confident=bool, why=str, stats)."""
    def score(s): return s['rear_fraction'] * np.log1p(s['n']) * min(s['clips'], 6)
    cands = [s for s in S if s['rear_fraction'] >= 0.85 and s['clips'] >= 3]
    if not cands: return dict(clusters=[max(S, key=score)['cluster']], confident=False, why='no cluster is both mostly behind the rear lens and seen in 3+ clips', stats={})
    seed = max(cands, key=score); En = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9); cen = {}
    for s_ in S:
        v = En[lab == s_['cluster']].mean(0); cen[s_['cluster']] = v / np.linalg.norm(v)
    ids = [seed['cluster']] + [s_['cluster'] for s_ in S if s_['cluster'] != seed['cluster'] and cen[s_['cluster']] @ cen[seed['cluster']] >= merge_cos and s_['rear_fraction'] >= 0.5]
    rest = sorted([float(cen[s_['cluster']] @ cen[seed['cluster']]) for s_ in S if s_['cluster'] not in ids], reverse=True); gap = (rest[0] if rest else 0.0)
    rivals = [s_ for s_ in cands if s_['cluster'] not in ids]
    confident = seed['n'] >= 40 and seed['clips'] >= 5 and seed['rear_fraction'] >= 0.9 and gap < 0.3 and not any(score(r) > 0.5 * score(seed) for r in rivals)
    return dict(clusters=ids, confident=bool(confident), why=f"seed #{seed['cluster']}: {seed['n']} faces in {seed['clips']} clips, {seed['rear_fraction']:.0%} behind the rear lens; merged {ids[1:]} (cosine >= {merge_cos}); nearest other person {gap:.2f}",
                stats=dict(gap=round(gap, 2)))


def run(race_dir, me=None, profiles_dir='profiles', label='me', auto=False):
    E, T, meta = collect(race_dir)
    if not len(E): raise SystemExit('no faces yet: run the people stage first (./strata360 run RACE --stages people)')
    lab = cluster(E); S = summarise(E, T, meta, lab); out = os.path.join(race_dir, 'people'); os.makedirs(out, exist_ok=True)
    sheet(T, S, os.path.join(out, 'clusters.png')); sug = suggest_wearer(E, lab, S)
    if auto and me is None and sug['confident']: me = ','.join(str(c) for c in sug['clusters'])
    json.dump(dict(threshold=THRESHOLD, clusters=S, suggested_wearer=sug, members=[dict(meta[i], cluster=int(lab[i])) for i in range(len(E))]), open(os.path.join(out, 'clusters.json'), 'w'))
    if me is not None:                                                    # one cluster, or several (the same person from different angles often splits): 101,103
        ids = [int(x) for x in str(me).split(',')]; idx = np.flatnonzero(np.isin(lab, ids))
        if not len(idx): raise SystemExit(f'no cluster {me}')
        os.makedirs(profiles_dir, exist_ok=True); En = E[idx] / np.linalg.norm(E[idx], axis=1, keepdims=True); cen = En.mean(0); cen /= np.linalg.norm(cen)
        np.savez(os.path.join(profiles_dir, f'{label}.npz'), centroid=cen, samples=En[:200].astype(np.float16), thumbs=T[idx][:24], threshold=0.45)
        print(f'saved profiles/{label}.npz from cluster {me} ({len(idx)} faces)')
    return S, sug


def load_profile(path):
    z = np.load(path); return dict(centroid=z['centroid'].astype(np.float32), samples=z['samples'].astype(np.float32), threshold=float(z['threshold']) if 'threshold' in z.files else 0.45)


def score_faces(emb, prof):
    """Similarity of each face embedding to the wearer profile: the better of the centroid and the mean of the 3 closest stored samples (poses differ)."""
    E = emb.astype(np.float32); E = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    if not len(E): return np.zeros(0)
    c = E @ prof['centroid']; top = np.sort(E @ prof['samples'].T, axis=1)[:, -3:].mean(1)
    return np.maximum(c, top)


VIEW_PX = 1024.0; VIEW_FOV = 100.0        # the views people_detect looks at: 1024 px square, 100 degrees


def head_up(p):
    """Degrees the TOP OF THE HEAD is above the centre of the person's box (the pitch the detections carry): from the face when one was found (its box is the face itself, so the hair is added), else the top of
    the person's box; None when the box is cut off at the top of the view or there is nothing to go on."""
    box = p.get('box'); fb = (p.get('face') or {}).get('box')
    if fb: top = fb[1] - 0.35 * (fb[3] - fb[1])
    elif box and box[1] > 4: top = box[1]                                                  # a box cut off at the top of the view has no known top
    else: return None
    cy = (box[1] + box[3]) / 2 if box else (fb[1] + fb[3]) / 2
    return round((cy - top) / VIEW_PX * VIEW_FOV, 1)


def analyse_clip(people_doc, emb, prof, thr=None):
    """identity.json body for one clip: per sampled frame, which detected person is the wearer (by face; else the large person straight behind the rear lens with no other
    face claiming to be someone else), and who else is in shot. Yaw is degrees from the front lens (180 = the rear lens)."""
    thr = thr or prof['threshold']; sims = score_faces(emb, prof); frames = {}
    for p in people_doc['people']:
        frames.setdefault(p['frame'], []).append(p)
    out = []
    for k in sorted(frames):
        ps = frames[k]; me = None; how = None
        for p in ps:
            if p.get('face') and sims[p['face']['emb']] >= thr and (me is None or sims[p['face']['emb']] > me['sim']): me = dict(p=p, sim=float(sims[p['face']['emb']])); how = 'face'
        if me is None:                                                                              # no recognisable face: the biggest person behind the rear lens, if nobody there is a different known face
            rear = [p for p in ps if p.get('box') and abs((p['yaw'] - 180 + 180) % 360 - 180) < 40 and (p['height_deg'] or 0) > 35 and (p['conf'] or 0) > 0.5
                    and not (p.get('face') and sims[p['face']['emb']] < 0.2)]
            if rear: p = max(rear, key=lambda p: p['height_deg']); me = dict(p=p, sim=None); how = 'position'
        others = [p for p in ps if (me is None or p is not me['p']) and ((p.get('conf') or 0) > 0.5 or p.get('face')) and (p['height_deg'] or 0) > 8 or (p.get('face') and me and p is not me['p'])]
        rec = dict(frame=int(k), t_s=ps[0]['t_s'], n_people=len(others) + (1 if me else 0), me=None,
                   others=[dict(yaw=p['yaw'], pitch=p['pitch'], height_deg=p['height_deg'], head_up=head_up(p), face=bool(p.get('face'))) for p in sorted(others, key=lambda p: -(p['height_deg'] or 0))[:6]])
        if me:
            p = me['p']; rec['me'] = dict(how=how, sim=None if me['sim'] is None else round(me['sim'], 3), yaw=p['yaw'], pitch=p['pitch'], height_deg=p['height_deg'], head_up=head_up(p), box=p.get('box'), view=p['view'],
                                          face_box=(p['face'] or {}).get('box') if p.get('face') else None)
        out.append(rec)
    n = max(len(out), 1)
    return dict(schema=1, threshold=thr, samples=out, summary=dict(frames=len(out), me_fraction=round(sum(1 for r in out if r['me']) / n, 3), me_by_face=round(sum(1 for r in out if r['me'] and r['me']['how'] == 'face') / n, 3),
                                                                     median_people=float(np.median([r['n_people'] for r in out])) if out else 0.0, max_people=max([r['n_people'] for r in out], default=0)))
