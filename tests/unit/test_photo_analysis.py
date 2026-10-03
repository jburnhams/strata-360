"""analysis/photo_analysis.py: the clip stages that make sense for a still photo, run over the project's photos."""
import io, json, os
import numpy as np
import pytest
from PIL import Image

from strata360 import photos as PH
from strata360.analysis import photo_analysis as PA


def jpeg_bytes(colour=(120, 140, 160), size=(64, 48), local='2026:02:20 14:12:17', noise=False):
    ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = local; ex.get_ifd(0x8769)[0x9011] = '+01:00'; arr = np.full((size[1], size[0], 3), colour, np.uint8)
    if noise: arr = np.random.default_rng(1).integers(0, 255, arr.shape, dtype=np.uint8)
    b = io.BytesIO(); Image.fromarray(arr).save(b, 'JPEG', exif=ex, quality=95); return b.getvalue() + b'\0' * 200


class TestMeasures:
    def test_exposure_calls_a_dark_a_bright_and_a_normal_photo(self):
        dark = np.full((40, 40, 3), 6, np.uint8); bright = np.full((40, 40, 3), 252, np.uint8); mid = np.full((40, 40, 3), 120, np.uint8)
        assert PA.exposure(dark)['verdict'] == 'dark' and PA.exposure(bright)['verdict'] == 'bright' and PA.exposure(mid)['verdict'] == 'ok' and PA.exposure(dark)['clip_lo'] == 1.0
        half = np.zeros((40, 40, 3), np.uint8); half[:, 20:] = 255; e = PA.exposure(half); assert e['clip_hi'] == 0.5 and e['clip_lo'] == 0.5 and e['range_stops'] > 5

    def test_quality_separates_a_sharp_a_blurred_and_a_featureless_picture(self):
        import cv2
        rng = np.random.default_rng(3); sharp = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8); blurred = cv2.GaussianBlur(sharp, (0, 0), 6); flat = np.full((120, 160, 3), 128, np.uint8)
        assert PA.quality(sharp)['verdict'] == 'ok' and PA.quality(blurred)['verdict'] in ('blurry', 'featureless') and PA.quality(flat)['verdict'] == 'featureless'
        assert PA.quality(sharp)['fine'] > PA.quality(blurred)['fine'] and set(PA.quality(sharp)) >= {'fine', 'mid', 'blur', 'tex', 'dark', 'contrast', 'sat', 'clip_hi', 'clip_lo', 'luma', 'verdict'}

    def test_places_uses_the_photos_position_and_says_when_it_has_none(self, tmp_path):
        calls = []
        rev = lambda la, lo, d: calls.append(('rev', la, lo)) or dict(display_name='x', village='Nadrin', county='Luxembourg', road='Rue 1'); near = lambda la, lo, d: [dict(name='Ourthe', kind='waterway=river', distance_m=80)]
        p = PA.places(dict(loc=dict(lat=50.1, lon=5.2, source='photo gps')), str(tmp_path), 'km 12', rev, near); assert p['covered'] and p['summary']['text'] == 'Nadrin (Luxembourg)' and p['nearby'][0]['name'] == 'Ourthe' and p['race'] == 'km 12' and calls == [('rev', 50.1, 5.2)]
        n = PA.places(dict(loc=None), str(tmp_path), None, rev, near); assert n['covered'] is False and 'no position' in n['note'] and len(calls) == 1


class TestWhoIsInIt:
    prof = dict(centroid=np.array([1.0, 0, 0] + [0] * 509, np.float32), samples=np.array([[1.0, 0, 0] + [0] * 509], np.float32), threshold=0.5)
    emb = lambda self, *v: np.array([list(x) + [0] * (512 - len(x)) for x in v], np.float16)

    def det(self, faces, people=()):
        return dict(w=100, h=100, people=[dict(box=b, conf=c, kp=[]) for b, c in people], faces=faces)

    def test_the_wearer_is_the_face_that_matches_the_profile_and_the_others_are_counted(self):
        e = self.emb((1.0, 0.0), (0.0, 1.0))                                                                                          # the first face is the wearer, the second someone else
        det = self.det([dict(box=[10, 10, 30, 30], score=0.9, pose=[-10.0, 5.0, 0.0], emb=0), dict(box=[60, 10, 80, 30], score=0.9, pose=[0, 0, 0], emb=1)], [([0, 0, 40, 90], 0.9), ([50, 0, 90, 90], 0.8), ([95, 0, 99, 20], 0.2)])
        r = PA.identity(det, e, self.prof); assert r['me']['face'] == 0 and r['me']['sim'] > 0.99 and r['n_people'] == 2 and r['others'] == 1
        fv = PA.face_view(det, r); assert fv == dict(found=True, clear=True, score=1.0, pitch=-10.0, yaw=5.0)

    def test_nobody_matching_means_the_wearer_is_not_in_the_photo(self):
        det = self.det([dict(box=[10, 10, 30, 30], score=0.9, pose=[0, 0, 0], emb=0)], [([0, 0, 40, 90], 0.9)]); r = PA.identity(det, self.emb((0.0, 1.0)), self.prof)
        assert r['me'] is None and r['n_people'] == 1 and r['others'] == 1 and PA.face_view(det, r) == dict(found=False, clear=False, score=0.0, pitch=None, yaw=None)

    def test_a_face_turned_away_or_looking_down_is_not_clear(self):
        det = self.det([dict(box=[10, 10, 30, 30], score=0.9, pose=[-70.0, 0.0, 0.0], emb=0)]); r = PA.identity(det, self.emb((1.0, 0.0)), self.prof); assert PA.face_view(det, r)['clear'] is False
        det2 = self.det([dict(box=[10, 10, 30, 30], score=0.9, pose=[0.0, 80.0, 0.0], emb=0)]); assert PA.face_view(det2, PA.identity(det2, self.emb((1.0, 0.0)), self.prof))['clear'] is False

    def test_a_face_found_twice_inside_a_person_is_one_person(self):
        det = self.det([dict(box=[10, 10, 30, 30], score=0.9, pose=[0, 0, 0], emb=0), dict(box=[200, 10, 230, 30], score=0.9, pose=[0, 0, 0], emb=1)], [([0, 0, 40, 90], 0.9)])
        assert PA.identity(det, self.emb((0.0, 1.0), (0.0, 1.0)), self.prof)['n_people'] == 2                                       # the person with a face inside, and a face with no body


class TestRun:
    def project_with_photos(self, project, n=2):
        for i in range(n): PH.add(project.race_dir, f'IMG_{i}.jpg', jpeg_bytes(noise=bool(i), local=f'2026:02:20 14:{10 + i}:00'))
        return [p['id'] for p in PH.load(project.race_dir)['photos']]

    def fakes(self, calls):
        def detect(images, tmp):
            calls.append(('detect', sorted(images))); dets = {k: dict(w=64, h=48, people=[dict(box=[0, 0, 30, 40], conf=0.9, kp=[])], faces=[dict(box=[5, 5, 20, 20], score=0.9, pose=[-5.0, 3.0, 0.0], emb=i)]) for i, k in enumerate(sorted(images))}
            return dets, np.array([[1.0] + [0] * 511] * len(images), np.float16)
        def vlm(images, tmp, models=None):
            calls.append(('vlm', sorted(images))); return {k: (dict(setting='trail', description='a path', people=1, tags=['trees', 'path'], lighting='overcast', weather='cloud', scenic=0.4, energy=0.3), dict(score=6, clarity=4, reason='ok')) for k in images}
        return detect, vlm

    def test_all_the_stages_run_once_and_a_second_run_does_nothing(self, project, monkeypatch, tmp_path):
        ids = self.project_with_photos(project); monkeypatch.chdir(tmp_path); os.makedirs('profiles'); np.savez('profiles/me.npz', centroid=np.array([1.0] + [0] * 511, np.float32), samples=np.array([[1.0] + [0] * 511], np.float32), threshold=0.5)
        calls = []; detect, vlm = self.fakes(calls); rev = lambda la, lo, d: dict(village='Nadrin'); near = lambda la, lo, d: []
        done = PA.run(project.folder, detect=detect, vlm=vlm, reverse=rev, nearby=near)
        assert {s: sorted(v) for s, v in done.items()} == {s: sorted(ids) for s in PA.ORDER} and [c[0] for c in calls] == ['detect', 'vlm']                              # the models are loaded once for all the photos
        doc = PA.load_doc(project.race_dir, ids[0]); assert doc['identity']['me']['face'] == 0 and doc['face_view']['clear'] is True and doc['scenes']['scenery'] == 6.0 and doc['scenes']['tags'] == ['trees', 'path'] and doc['exposure']['verdict'] == 'ok'
        assert doc['places']['covered'] is False and doc['thumb_overlay']['made'] is False and os.path.exists(os.path.join(PA.adir(project.race_dir), f'{ids[0]}.npy')) and set(doc['stages']) == set(PA.ORDER)      # (no GPS and no track here)
        again = PA.run(project.folder, detect=detect, vlm=vlm, reverse=rev, nearby=near); assert all(v == [] for v in again.values()) and len(calls) == 2
        s = PA.summary(doc); assert s['scenery'] == 6.0 and s['me'] is True and s['people'] == 1 and s['face_clear'] is True and s['tags'] == ['trees', 'path'] and s['stages'] == sorted(PA.ORDER)

    def test_a_changed_photo_or_force_redoes_what_depends_on_it(self, project, monkeypatch, tmp_path):
        ids = self.project_with_photos(project, 1); calls = []; detect, vlm = self.fakes(calls); kw = dict(stages=['exposure', 'quality', 'people', 'scenes'], detect=detect, vlm=vlm)
        PA.run(project.folder, **kw); PA.run(project.folder, **kw); assert len(calls) == 2
        p = os.path.join(project.race_dir, PH.load(project.race_dir)['photos'][0]['file']); Image.new('RGB', (64, 48), (200, 10, 10)).save(p, 'JPEG'); os.utime(p, (os.path.getmtime(p) + 10,) * 2)
        done = PA.run(project.folder, **kw); assert done['exposure'] == ids and len(calls) == 4
        PA.run(project.folder, force=True, only={ids[0]}, **kw); assert len(calls) == 6

    def test_a_stage_that_cannot_run_is_reported_loudly_while_the_others_still_run(self, project, monkeypatch, tmp_path):
        ids = self.project_with_photos(project, 1); monkeypatch.chdir(tmp_path); calls = []; detect, vlm = self.fakes(calls)                              # no profiles/me.npz here
        with pytest.raises(RuntimeError, match='identity: RuntimeError: no wearer profile'): PA.run(project.folder, stages=['exposure', 'people', 'identity', 'face_view'], detect=detect, vlm=vlm)
        doc = PA.load_doc(project.race_dir, ids[0]); assert 'exposure' in doc and 'people' in doc and 'identity' not in doc and 'face_view' not in doc

    def test_unknown_stages_and_nothing_to_do(self, project):
        with pytest.raises(ValueError, match='unknown photo stage'): PA.run(project.folder, stages=['audio'])
        assert PA.run(project.folder, stages=['exposure']) == {'exposure': []}
        assert 'ingest' in PA.NOT_APPLICABLE and not set(PA.ORDER) & set(PA.NOT_APPLICABLE)

    def test_the_overlay_is_drawn_on_a_photo_taken_during_the_run(self, project, monkeypatch):
        import sys, types
        PH.add(project.race_dir, 'IMG_0.jpg', jpeg_bytes()); drawn = []
        class Fake:
            def apply(self, rgb, t): drawn.append((rgb.shape, t)); rgb[:5] = 255
        monkeypatch.setattr('strata360.overlay.for_project', lambda folder, size: Fake())
        real = PH.located
        monkeypatch.setattr(PH, 'located', lambda e, run: dict(real(e, run), track=dict(lat=50.0, lon=5.0, elapsed_s=10, km=0.1)))                       # (as if the run covered the time)
        done = PA.run(project.folder, stages=['thumb_overlay']); doc = PA.load_doc(project.race_dir, 'p1')
        assert done == {'thumb_overlay': ['p1']} and doc['thumb_overlay'] == dict(made=True, file='photos/analysis/p1-overlay.jpg') and drawn and drawn[0][1] == PH.load(project.race_dir)['photos'][0]['taken_utc']
        out = Image.open(os.path.join(project.race_dir, doc['thumb_overlay']['file'])); assert out.format == 'JPEG' and out.size == (64, 48)
