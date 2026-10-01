"""Offline tests for the view geometry, duplicate merging and identity clustering (no models needed). Run: .venv/bin/python tests/test_people.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src'))
import numpy as np
from strata360.analysis.people import merge
from strata360.analysis import identity
from strata360.analysis.people_detect import pixel_dir


def test_pixel_dir_centres_match_view_axes():
    for y in (0, 60, 120, 180, 240, 300):
        yaw, pitch = pixel_dir(y, 512, 512, 1024, 100.0)
        assert abs(((yaw - y + 180) % 360) - 180) < 0.2 and abs(pitch) < 0.2, (y, yaw, pitch)
    yaw, pitch = pixel_dir(0, 512, 100, 1024, 100.0); assert pitch > 30 and abs(yaw) < 1 or abs(yaw - 360) < 1


def test_merge_removes_duplicates_across_views_and_keeps_the_face():
    a = dict(frame=0, view=60, yaw=90.0, pitch=-10.0, conf=0.6, face=None); b = dict(frame=0, view=120, yaw=94.0, pitch=-11.0, conf=0.9, face=dict(emb=0, score=0.8, size_px=50))
    c = dict(frame=0, view=180, yaw=200.0, pitch=-20.0, conf=0.7, face=None); d = dict(frame=50, view=60, yaw=92.0, pitch=-10.0, conf=0.5, face=None)
    out = merge([a, b, c, d]); assert len(out) == 3 and sum(1 for p in out if p['frame'] == 0) == 2
    assert [p for p in out if p['frame'] == 0 and p['yaw'] < 150][0]['face']['emb'] == 0


def test_identity_clusters_separate_people():
    rng = np.random.default_rng(0); base = rng.normal(size=(3, 512)); E = np.vstack([b + 0.15 * rng.normal(size=(40, 512)) for b in base])
    lab = identity.cluster(E); assert len(set(lab)) == 3 and all(len(set(lab[i * 40:(i + 1) * 40])) == 1 for i in range(3))


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
