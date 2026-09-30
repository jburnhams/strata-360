"""`people` stage: detect persons and faces on body-frame views and merge duplicates from overlapping views into one list per sampled frame (`people.json`, `faces.npy`).

Views (analysis/views.py) are written to a temporary directory, detected in `.venv-vision` (analysis/people_detect.py) and merged here. The merged record per person:
frame, t_s, yaw/pitch in the body frame, height_deg (apparent size), person confidence, and the best face (score, size, embedding row in faces.npy)."""
import json, os, shutil, subprocess, sys, tempfile
import numpy as np
from strata360.analysis import views as V
from strata360.osv.telemetry import video_pts

SCHEMA_VERSION = 1


def _ang(a, b):
    dy = (a['yaw'] - b['yaw'] + 180) % 360 - 180
    return float(np.hypot(dy * np.cos(np.radians((a['pitch'] + b['pitch']) / 2)), a['pitch'] - b['pitch']))


def merge(dets, radius=9.0):
    """Suppress duplicates of one person seen in two overlapping views: within a frame, detections closer than `radius` degrees are one person;
    the survivor is the one with a face, then the highest confidence (the face and box of the others are adopted if the survivor lacks them)."""
    out = []
    for k in sorted({d['frame'] for d in dets}):
        fr = sorted([d for d in dets if d['frame'] == k], key=lambda d: (d['face'] is None, -(d['conf'] or 0)))
        kept = []
        for d in fr:
            for m in kept:
                if _ang(d, m) < radius:
                    if m['face'] is None and d['face'] is not None: m['face'] = d['face']
                    break
            else: kept.append(dict(d))
        out += kept
    return out


def analyse(osv, work_dir, every=50, models=None):
    pts = video_pts(osv, 0); t = lambda k: round(float(pts[min(k, len(pts) - 1)] - pts[0]), 3)
    tmp = tempfile.mkdtemp(prefix='s360views_', dir=work_dir)
    try:
        V.write_stab_views(osv, tmp, every=every)
        py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..')
        jf, nf = os.path.join(tmp, 'det.json'), os.path.join(tmp, 'emb.npy')
        cmd = [py, '-m', 'strata360.analysis.people_detect', tmp, jf, nf] + (['--models', models] if models else [])
        subprocess.run(cmd, check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
        raw = json.load(open(jf)); emb = np.load(nf); th = np.load(nf.replace('.npy', '_thumbs.npy'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    people = merge(raw['detections'])
    keep = sorted({p['face']['emb'] for p in people if p['face']}); remap = {e: i for i, e in enumerate(keep)}
    for p in people:
        p['t_s'] = t(p['frame']); p.pop('kp', None)
        if p['face']: p['face']['emb'] = remap[p['face']['emb']]
    doc = dict(schema=SCHEMA_VERSION, models=raw['models'], sample_every_frames=every, frames=sorted({p['frame'] for p in people}), n_raw=len(raw['detections']), people=people,
               note='yaw is degrees from the front lens (180 = the rear lens, where the wearer normally is); embeddings: faces.npy rows via face.emb')
    return doc, (emb[keep] if len(keep) else np.zeros((0, 512), np.float16)), (th[keep] if len(keep) else np.zeros((0, 96, 96, 3), np.uint8))
