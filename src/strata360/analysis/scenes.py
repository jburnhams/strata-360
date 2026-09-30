"""`scenes` stage: what is in each part of a clip, from a local VLM (analysis/scenes_vlm.py in `.venv-vision`) on two body-frame views every few seconds: the front lens (what the
runner sees ahead) and the rear lens (the wearer and what follows). Output `scenes.json`: per sample the answers, plus clip-level summaries (settings, tags, scenic and energy averages,
lens problems) the candidate builder and the optimiser use."""
import json, os, shutil, subprocess, tempfile
from collections import Counter
import numpy as np
from strata360.analysis import views as V
from strata360.osv.telemetry import video_pts

SCHEMA_VERSION = 1


def analyse(osv, work_dir, every_s=5.0, models=None, px=768):
    pts = video_pts(osv, 0); fps = (len(pts) - 1) / max(pts[-1] - pts[0], 1e-6); every = max(int(round(every_s * fps)), 1); tmp = tempfile.mkdtemp(prefix='s360scn_', dir=work_dir)
    try:
        V.write_stab_views(osv, tmp, every=every, yaws=(0, 180), px=px)
        py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..'); out = os.path.join(tmp, 'vlm.json')
        subprocess.run([py, '-m', 'strata360.analysis.scenes_vlm', tmp, out] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
        raw = json.load(open(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    items = []
    for it in raw['items']:
        a = it['answer'] or {}
        items.append(dict(frame=it['frame'], t_s=round(float(pts[min(it['frame'], len(pts) - 1)] - pts[0]), 2), view='front' if it['view'] == 0 else 'rear', ok=bool(it['answer']), **{k: a.get(k) for k in
                          ('setting', 'description', 'people', 'crowd', 'lighting', 'weather', 'activity', 'mood', 'scenic', 'energy', 'lens_problems', 'tags')}))
    def num(k, view=None):
        v = [float(i[k]) for i in items if i['ok'] and (view is None or i['view'] == view) and isinstance(i.get(k), (int, float))]; return round(float(np.mean(v)), 3) if v else None
    tags = Counter(t for i in items for t in (i.get('tags') or []) if isinstance(t, str)); settings = Counter(i['setting'] for i in items if i.get('setting'))
    summary = dict(settings=dict(settings.most_common(4)), tags=[t for t, _ in tags.most_common(10)], scenic_front=num('scenic', 'front'), energy_front=num('energy', 'front'), people_front=num('people', 'front'),
                   lens_problems=dict(Counter(i['lens_problems'] for i in items if i.get('lens_problems') not in (None, 'none'))), lighting=dict(Counter(i['lighting'] for i in items if i.get('lighting')).most_common(3)),
                   answered=sum(1 for i in items if i['ok']), images=len(items))
    return dict(schema=SCHEMA_VERSION, model=raw['model'], sample_every_s=every_s, seconds_model=raw['seconds'], items=items, summary=summary)
