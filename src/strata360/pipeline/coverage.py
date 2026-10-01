"""Data completeness (overview 15.3): per clip, which artefacts of the default stages exist and which edit decisions the missing ones block.

Based on the files on disk (a stage's declared outputs), so it is cheap and needs no models. `strata360 coverage FOLDER [--json]` and `/api/coverage`."""
import os

from strata360.pipeline import clips as clipmod, config, runner
from strata360.pipeline.stages import ORDER, STAGES

# What each stage's output is needed for (a missing artefact blocks these decisions).
DECISIONS = {
    'ingest': ['clip time and order in the film'],
    'audio_extract': ['sound for the film', 'transcription'],
    'audio_clean': ['clean dialogue in the film'],
    'audio_events': ['sound roles and levels in the mix'],
    'audio': ['loudness and wind labels'],
    'motion': ['steadiness, usable footage', 'thumbnails'],
    'proxy': ['preview player', 'scene, people and thumbnail analysis'],
    'thumb': ['clip list pictures'],
    'places': ['place names in the script'],
    'transcribe': ['dialogue windows', 'script facts'],
    'align': ['exact cut points around speech'],
    'exposure': ['unusable exposure', 'grading'],
    'people': ['who is in view'],
    'identity': ['you in view'],
    'scenes': ['scene candidates', 'script facts'],
    'speakers': ['your speech vs other voices'],
    'candidates': ['planning the film from the clip'],
    'thumb_best': ['best thumbnail'],
    'thumb_overlay': ['overlay on thumbnails'],
}


def clip_coverage(race, cfg, clip_id, names, has_track):
    """{stage: 'ok' | 'missing' | 'partial' | 'waiting'} for one clip, plus the decisions blocked."""
    d = runner.clip_dir(race, clip_id); stages = {}; blocked = []
    for n in names:
        st = STAGES[n]; have = [os.path.exists(os.path.join(d, o)) for o in st.outputs]
        if all(have) and have: s = 'ok'
        elif st.needs_track and not has_track: s = 'waiting'
        elif any(have): s = 'partial'
        else: s = 'missing'
        stages[n] = s
        if s != 'ok':
            for x in DECISIONS.get(n, []):
                if x not in blocked: blocked.append(x)
    return dict(clip=clip_id, stages=stages, blocked=blocked)


def coverage(name):
    """The report for a project: per clip, per default stage; totals per stage; decisions blocked by missing data and the clips behind each."""
    cfg = config.load(name); cl, _ = clipmod.discover(cfg['library']); names = [n for n in ORDER if n in cfg['stages']]; has_track = config.track_path(name, cfg) is not None
    rows = [clip_coverage(name, cfg, c.id, names, has_track) for c in cl]
    totals = {n: sum(r['stages'][n] == 'ok' for r in rows) for n in names}; blocked = {}
    for r in rows:
        for x in r['blocked']: blocked.setdefault(x, []).append(r['clip'])
    missing = [dict(clip=r['clip'], stage=n, state=s) for r in rows for n, s in r['stages'].items() if s != 'ok']
    return dict(clips=len(rows), stages=names, rows=rows, totals=totals, blocked=blocked, missing=missing, complete=not missing)
