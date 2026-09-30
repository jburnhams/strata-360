"""Who is speaking: separate the wearer's own voice (the cameraman talking to the camera) from chatter around them.

Per clip (`speakers` stage): a speaker embedding (ECAPA-TDNN, local, `.venv-vision`) and level statistics for each transcribed speech segment (`speakers.json`, `speakers.npy`).
Per race (`strata360 voice RACE`): the embeddings are clustered across all clips; the wearer's voice is the cluster present in the most clips (the wearer talks to the camera all race; a companion or
an interviewee dominates only a few clips). It is suggested automatically and confirmed once (the choice is stored in `profiles/me_voice.npz`, reused in
later races); every segment is then labelled `wearer` or `other` by similarity to that profile (`speakers.json` `label`)."""
import glob, json, os, shutil, subprocess, tempfile
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster

SCHEMA_VERSION = 1
THRESHOLD = 0.6            # cosine distance for "same speaker" when clustering (similarity 0.4)
MATCH = 0.45               # similarity to the wearer profile that counts as "the wearer"


def analyse(osv, transcript, work_dir, models=None):
    segs = [dict(i=i, t0=s['t0'], t1=s['t1'], text=s['text'], text_en=s.get('text_en'), lang=s.get('lang')) for i, s in enumerate(transcript['segments'])
            if s.get('text', '').strip() and not s.get('flags') and not s.get('suspect') and s['t1'] - s['t0'] >= 0.8]
    tmp = tempfile.mkdtemp(prefix='s360voice_', dir=work_dir)
    try:
        sj, npy, oj = os.path.join(tmp, 'segs.json'), os.path.join(tmp, 'emb.npy'), os.path.join(tmp, 'stats.json'); json.dump(segs, open(sj, 'w'))
        py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..')
        subprocess.run([py, '-m', 'strata360.analysis.voices_embed', osv, sj, npy, oj] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        emb = np.load(npy); stats = json.load(open(oj))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for s, st in zip(segs, stats): s.update(st)
    return dict(schema=SCHEMA_VERSION, model='speechbrain ecapa-tdnn (voxceleb)', segments=segs), emb


def collect(race_dir):
    E, meta = [], []
    for f in sorted(glob.glob(os.path.join(race_dir, 'clips', '*', 'speakers.json'))):
        d = os.path.dirname(f)
        try: doc = json.load(open(f)); emb = np.load(os.path.join(d, 'speakers.npy')).astype(np.float32)
        except OSError: continue
        for k, s in enumerate(doc['segments']):
            E.append(emb[k]); meta.append(dict(clip=os.path.basename(d), k=k, **{x: s[x] for x in ('t0', 't1', 'text', 'rms_db', 'peak_db', 'spread_db')}))
    return (np.array(E).reshape(-1, 192), meta)


def cluster(E):
    if len(E) < 2: return np.ones(len(E), int)
    En = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9); return fcluster(linkage(En, 'average', metric='cosine'), THRESHOLD, 'distance')


def summarise(E, meta, lab, top=12):
    out = []
    for c in sorted(set(lab), key=lambda c: -(lab == c).sum())[:top]:
        idx = np.flatnonzero(lab == c); rms = np.array([meta[i]['rms_db'] for i in idx]); dur = sum(meta[i]['t1'] - meta[i]['t0'] for i in idx)
        pick = sorted(idx, key=lambda i: -(meta[i]['t1'] - meta[i]['t0']))[:4]
        out.append(dict(cluster=int(c), n=int(len(idx)), clips=len({meta[i]['clip'] for i in idx}), seconds=round(float(dur), 1), median_rms_db=round(float(np.median(rms)), 1), samples=[meta[i]['text'] for i in pick]))
    return out


def suggest_wearer(S):
    """The wearer talks to the camera throughout the race, so their voice is the cluster present in the most clips (loudness is not used: a wearer talking quietly to the camera is often
    quieter than a guest right next to the stick, and a long conversation with one companion gives a big cluster in only a few clips). Confident when it spans 5+ clips and
    clearly more clips than the runner-up (at least 1.5 times)."""
    cands = sorted([s for s in S if s['n'] >= 5], key=lambda s: (-s['clips'], -s['n']))
    if not cands: return dict(cluster=(S[0]['cluster'] if S else None), confident=False, why='no voice cluster with 5+ segments')
    top = cands[0]; nxt = cands[1]['clips'] if len(cands) > 1 else 0
    return dict(cluster=top['cluster'], confident=bool(top['clips'] >= 5 and top['clips'] >= 1.5 * max(nxt, 1)), clips_next=nxt,
                why=f"cluster {top['cluster']}: {top['n']} segments in {top['clips']} clips (next most widespread voice: {nxt} clips), median level {top['median_rms_db']} dBFS")


def save_profile(E, lab, ids, path='profiles/me_voice.npz'):
    idx = np.flatnonzero(np.isin(lab, ids)); En = E[idx] / np.linalg.norm(E[idx], axis=1, keepdims=True); c = En.mean(0); c /= np.linalg.norm(c)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True); np.savez(path, centroid=c, samples=En[:300].astype(np.float16), threshold=MATCH); return int(len(idx))


def label(emb, prof_path='profiles/me_voice.npz'):
    """'wearer' / 'other' and the similarity for each embedding row."""
    z = np.load(prof_path); E = emb.astype(np.float32); E = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    sim = E @ z['centroid'].astype(np.float32) if len(E) else np.zeros(0); thr = float(z['threshold']) if 'threshold' in z.files else MATCH
    return ['wearer' if s >= thr else 'other' for s in sim], [round(float(s), 3) for s in sim]
