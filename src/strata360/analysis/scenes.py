"""`scenes` stage: what is in each part of a clip, from a local VLM (analysis/scenes_vlm.py in `.venv-vision`) on two body-frame views every few seconds: the front lens (what the
runner sees ahead) and the rear lens (the wearer and what follows). Output `scenes.json`: per sample the answers, plus clip-level summaries (settings, tags, scenic and energy averages,
lens problems) the candidate builder and the optimiser use."""
import json, os, shutil, subprocess, tempfile
from collections import Counter
import numpy as np
from strata360.analysis import views as V
from strata360.osv.telemetry import video_pts

SCHEMA_VERSION = 2                # 2: each item also has `scenery` (1 to 10, people ignored), `clarity` (1 to 5) and `scenery_why`; the general description is as in 1


LOG_KEYS = ('setting', 'description', 'people', 'crowd', 'lighting', 'weather', 'activity', 'mood', 'scenic', 'energy', 'lens_problems', 'tags')


def reusable(previous, every_s):
    """The general-description answers of an earlier scenes.json when they were made for the same sampling (same spacing), as {(frame, view): answer}; {} when there are none to reuse: that pass is the slow one and its answers do not
    change when only the scenery prompt does."""
    if not previous or previous.get('sample_every_s') != every_s or not previous.get('items'): return {}
    return {(i['frame'], 0 if i['view'] == 'front' else 1): {k: i.get(k) for k in LOG_KEYS} for i in previous['items'] if i.get('ok')}


def _vlm(py, src, tmp, out, models, prompt):
    subprocess.run([py, '-m', 'strata360.analysis.scenes_vlm', tmp, out, '--prompt', prompt] + (['--model', models] if models else []), check=True, env={**os.environ, 'PYTHONPATH': src, 'PYTHONWARNINGS': 'ignore'}, stdout=subprocess.PIPE)
    return json.load(open(out))


def analyse(osv, work_dir, every_s=5.0, models=None, px=768, previous=None):
    pts = video_pts(osv, 0); fps = (len(pts) - 1) / max(pts[-1] - pts[0], 1e-6); every = max(int(round(every_s * fps)), 1); tmp = tempfile.mkdtemp(prefix='s360scn_', dir=work_dir)
    try:
        proxy = os.path.join(work_dir, 'proxy.mp4')
        if V.proxy_available(proxy): V.write_stab_views_proxy(proxy, osv, tmp, every=every, yaws=(0, 180), px=px)
        else: V.write_stab_views(osv, tmp, every=every, yaws=(0, 180), px=px)
        py = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.venv-vision', 'bin', 'python'); src = os.path.join(os.path.dirname(__file__), '..', '..'); out = os.path.join(tmp, 'vlm.json')
        old = reusable(previous, every_s); scen = _vlm(py, src, tmp, os.path.join(tmp, 'scenery.json'), models, 'scenery')                 # the scenery prompt is always run (it is the new part)
        raw = _vlm(py, src, tmp, out, models, 'log') if not old else dict(model=scen['model'], seconds=scen['seconds'], items=[dict(frame=i['frame'], view=i['view'], answer=old.get((i['frame'], i['view']))) for i in scen['items']])
        by = {(i['frame'], i['view']): i['answer'] or {} for i in scen['items']}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    items = []
    for it in raw['items']:
        a = it['answer'] or {}; sc = by.get((it['frame'], it['view']), {}); score, clar = sc.get('score'), sc.get('clarity')
        items.append(dict(frame=it['frame'], t_s=round(float(pts[min(it['frame'], len(pts) - 1)] - pts[0]), 2), view='front' if it['view'] == 0 else 'rear', ok=bool(it['answer']), **{k: a.get(k) for k in LOG_KEYS},
                          scenery=float(score) if isinstance(score, (int, float)) else None, clarity=float(clar) if isinstance(clar, (int, float)) else None, scenery_why=sc.get('reason')))
    def num(k, view=None):
        v = [float(i[k]) for i in items if (i['ok'] or k in ('scenery', 'clarity')) and (view is None or i['view'] == view) and isinstance(i.get(k), (int, float))]; return round(float(np.mean(v)), 3) if v else None
    tags = Counter(t for i in items for t in (i.get('tags') or []) if isinstance(t, str)); settings = Counter(i['setting'] for i in items if i.get('setting'))
    summary = dict(settings=dict(settings.most_common(4)), tags=[t for t, _ in tags.most_common(10)], scenic_front=num('scenic', 'front'), scenery_front=num('scenery', 'front'), scenery_rear=num('scenery', 'rear'), clarity_front=num('clarity', 'front'), clarity_rear=num('clarity', 'rear'), energy_front=num('energy', 'front'), people_front=num('people', 'front'),
                   lens_problems=dict(Counter(i['lens_problems'] for i in items if i.get('lens_problems') not in (None, 'none'))), lighting=dict(Counter(i['lighting'] for i in items if i.get('lighting')).most_common(3)),
                   answered=sum(1 for i in items if i['ok']), images=len(items))
    return dict(schema=SCHEMA_VERSION, model=raw['model'], sample_every_s=every_s, seconds_model=raw['seconds'], items=items, summary=summary)
