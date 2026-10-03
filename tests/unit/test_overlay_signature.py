"""What the overlay shows besides the track and the clip, as one identity: when it changes the thumbnails with the overlay and the film preview are out of date."""
import json, os

from strata360 import overlay
from strata360.gps import tracks
from strata360.pipeline import config


def test_the_signature_changes_with_the_manifest_the_overlay_settings_and_the_time_zone_and_only_then(make_project):
    pr = make_project(config=True); f = pr.folder; a = overlay.inputs_signature(f); assert overlay.inputs_signature(f) == a and len(a) == 12
    json.dump(dict(tracks=[], cutoffs={'cp:1': {'text': '2h'}}), open(os.path.join(pr.race_dir, tracks.MANIFEST), 'w')); b = overlay.inputs_signature(f); assert b != a                          # a cut-off
    cfg = json.load(open(os.path.join(pr.race_dir, 'race.json'))); cfg['overlay'] = {'enabled': False}; json.dump(cfg, open(os.path.join(pr.race_dir, 'race.json'), 'w')); c = overlay.inputs_signature(f); assert c != b      # a setting
    cfg['timezone'] = 'Europe/London'; json.dump(cfg, open(os.path.join(pr.race_dir, 'race.json'), 'w')); assert overlay.inputs_signature(f) != c


def test_the_film_preview_is_out_of_date_when_the_overlay_inputs_change(make_project):
    from strata360.render import preview
    pr = make_project(config=True); plan = dict(segments=[]); a = preview.plan_key(pr.folder, plan); assert preview.plan_key(pr.folder, plan) == a
    json.dump(dict(tracks=[], cutoffs={'finish': {'text': '9h'}}), open(os.path.join(pr.race_dir, tracks.MANIFEST), 'w')); assert preview.plan_key(pr.folder, plan) != a


def test_the_thumbnail_overlay_stage_is_out_of_date_when_the_overlay_inputs_change(make_project):
    import numpy as np
    from strata360.pipeline import runner
    pr = make_project(config=True); tp = os.path.join(pr.race_dir, 'track.gpx'); open(tp, 'w').write('<gpx/>'); n = 5; nan = np.full(n, np.nan)
    np.savez_compressed(tp + '.npz', t=np.arange(n) + 1e9, lat=np.full(n, 50.0), lon=np.full(n, 5.0), alt=nan, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)
    cfg = config.load(pr.folder); st = runner.STAGES['thumb_overlay']; clip = type('C', (), {'id': 'c', 'fingerprint': 'f'})(); state = {d: {'status': 'ok', 'key': 'k'} for d in st.deps}
    key = lambda: runner._cached(pr.folder, st, clip, cfg, state, pr.race_dir)[1]; a = key(); assert a and key() == a
    json.dump(dict(tracks=[], cutoffs={'finish': {'text': '9h'}}), open(os.path.join(pr.race_dir, tracks.MANIFEST), 'w')); assert key() != a
    other = runner.STAGES['places']; k2 = lambda: runner._cached(pr.folder, other, clip, cfg, {d: {'status': 'ok', 'key': 'k'} for d in other.deps}, pr.race_dir)[1]; before = k2()
    json.dump(dict(tracks=[], cutoffs={'finish': {'text': '10h'}}), open(os.path.join(pr.race_dir, tracks.MANIFEST), 'w')); assert k2() == before                       # (a stage that does not draw the overlay is not redone)
