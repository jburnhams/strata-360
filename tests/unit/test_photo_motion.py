"""edit/photo_motion.py: pan and zoom paths for still photos."""
import math
import numpy as np
import pytest

from strata360.edit import photo_motion as PM


def doc(me_box=(300, 100, 380, 200), size=(1600, 1200), others=()):
    faces = [dict(box=list(me_box), score=0.9, pose=[0, 0, 0], emb=0)] + [dict(box=list(b), score=0.9, pose=[0, 0, 0], emb=i + 1) for i, b in enumerate(others)]
    return dict(people=dict(w=size[0], h=size[1], people=[], faces=faces), identity=dict(me=dict(face=0, sim=0.9, box=list(me_box))))


class TestGeometry:
    def test_the_window_is_the_largest_16_by_9_that_fits_and_zoom_narrows_it(self):
        assert PM.base_window(1600, 1200) == (1600, 900) and PM.base_window(3000, 1000) == pytest.approx((1777.78, 1000.0), abs=0.01) and PM.base_window(1000, 3000)[0] == 1000
        pl = dict(size=[1600, 1200], aspect=PM.ASPECT, keys=[dict(t=0, cx=0.5, cy=0.5, z=1.0), dict(t=2, cx=0.5, cy=0.5, z=2.0)]); assert PM.crop_at(pl, 0) == (0.0, 150.0, 1600.0, 900.0)
        x0, y0, ww, wh = PM.crop_at(pl, 2); assert (ww, wh) == (800.0, 450.0) and (x0, y0) == (400.0, 375.0)

    def test_the_window_never_leaves_the_photo_or_zooms_past_the_pixels(self):
        k = PM.clamp_key(dict(cx=0.99, cy=0.01, z=9.0), 1600, 1200, PM.ASPECT, 2.0); assert k['z'] == 2.0 and k['cx'] <= 1 - 0.25 and k['cy'] >= (450 / 1200) / 2 - 1e-9
        assert PM.max_zoom(1600, 1200, 1920) == pytest.approx(1600 / (1920 / 1.5)) and PM.max_zoom(800, 450, 1920) == 1.0                  # a small photo cannot be zoomed at all

    def test_easing_starts_and_ends_gently(self):
        assert PM.ease(0) == 0 and PM.ease(1) == 1 and PM.ease(0.5) == 0.5 and PM.ease(0.1) < 0.1 and PM.ease(0.9) > 0.9 and PM.ease(-1) == 0 and PM.ease(2) == 1


class TestFocals:
    def test_the_wearers_face_comes_first_then_other_faces_and_thefrom_the_rest(self):
        f = PM.focals(doc(others=[(1000, 300, 1060, 380)])); assert [x['label'] for x in f[:2]] == ['you', 'face'] and f[0]['cx'] == pytest.approx(340 / 1600) and f[0]['w'] == pytest.approx(80 * 2.6 / 1600) and f[-1]['label'] == 'thirds'

    def test_objects_count_unless_they_are_tiny(self):
        d = doc(); d['objects'] = dict(w=800, h=600, objects=[dict(label='bicycle', conf=0.9, box=[400, 300, 700, 500]), dict(label='bottle', conf=0.9, box=[10, 10, 20, 30])])
        labels = [x['label'] for x in PM.focals(d)]; assert 'bicycle' in labels and 'bottle' not in labels

    def test_the_most_detailed_part_of_a_picture_is_found(self):
        img = np.full((240, 320, 3), 128, np.uint8); img[40:120, 200:300] = np.random.default_rng(2).integers(0, 255, (80, 100, 3), dtype=np.uint8)
        s = PM.saliency(img); assert s and s[0] > 0.6 and s[1] < 0.5
        assert PM.focals(None, img)[0]['label'] == 'detail' and PM.focals(None)[0]['label'] == 'thirds'

    def test_a_flat_picture_has_nothing_to_find(self): assert PM.saliency(np.full((60, 80, 3), 90, np.uint8)) is None or PM.saliency(np.full((60, 80, 3), 90, np.uint8))[4] >= 0


class TestPlan:
    size = (1600, 1200)

    def subj(self, cx=0.25, cy=0.3): return [dict(cx=cx, cy=cy, w=0.1, h=0.12, weight=1.0, label='you'), dict(cx=0.75, cy=0.6, w=0.1, h=0.1, weight=0.6, label='person')]

    def test_a_push_in_starts_wide_and_ends_on_the_subject(self):
        p = PM.plan(self.size, 6, 'push_in', self.subj()); a, b = p['keys']; assert p['style'] == 'push_in' and a['z'] == 1.0 and b['z'] > 1.2 and abs(b['cx'] - 0.25) < 0.16 and abs(b['cy'] - 0.3) < 0.2 and b['t'] == 6.0                                       # (as near as the window can get to it without leaving the photo)
        w, h = self.size; x0, y0, ww, wh = PM.crop_at(p, 6); assert x0 <= 0.25 * w <= x0 + ww and y0 <= 0.3 * h <= y0 + wh                  # the subject is in the final window

    def test_a_pull_out_is_a_push_in_the_other_way_round(self):
        a, b = PM.plan(self.size, 6, 'pull_out', self.subj())['keys']; assert a['z'] > 1.2 and b['z'] == 1.0 and abs(a['cx'] - 0.25) < 0.16

    def test_a_wide_photo_pans_along_its_length_and_ends_on_the_side_of_the_subject(self):
        p = PM.plan((4000, 1000), 8, 'pan', self.subj(cx=0.8)); a, b = p['keys']; assert a['z'] == b['z'] == 1.0 and a['cx'] < 0.5 < b['cx'] and b['cx'] > a['cx']          # clamped so the window stays inside
        q = PM.plan((4000, 1000), 8, 'pan', self.subj(cx=0.15)); assert q['keys'][0]['cx'] > q['keys'][1]['cx']
        t = PM.plan((900, 3000), 8, 'pan', self.subj(cx=0.5, cy=0.9)); assert t['keys'][0]['cy'] < t['keys'][1]['cy'] and t['keys'][0]['cx'] == t['keys'][1]['cx']              # a tall one pans down

    def test_a_photo_with_no_room_to_pan_is_zoomed_in_first(self):
        p = PM.plan((1600, 900), 6, 'pan', self.subj(cx=0.8)); a, b = p['keys']; assert a['z'] == b['z'] == pytest.approx(PM.max_zoom(1600, 900, 1920)) and a['cx'] < b['cx'] and b['cx'] - a['cx'] >= 0.19                  # (as far in as the photo's pixels allow, up to 1.4)
        q = PM.plan((6400, 3600), 6, 'pan', self.subj(cx=0.8)); assert q['keys'][0]['z'] == pytest.approx(1.4)
        x = PM.plan((1280, 720), 6, 'pan', self.subj()); assert x['keys'][0] == {**x['keys'][1], 't': 0.0} or x['zmax'] == 1.0                                              # too small to zoom: nothing to pan across

    def test_drift_and_reveal_move_between_two_points_of_interest(self):
        d = PM.plan(self.size, 6, 'drift', self.subj()); assert d['keys'][0]['cx'] < d['keys'][1]['cx'] and d['keys'][1]['z'] > d['keys'][0]['z']
        r = PM.plan(self.size, 6, 'reveal', self.subj()); assert r['keys'][0]['z'] > r['keys'][1]['z'] and r['keys'][0]['cx'] < r['keys'][1]['cx']

    def test_hold_breathes_a_little(self):
        a, b = PM.plan(self.size, 5, 'hold')['keys']; assert (a['cx'], a['cy'], a['z']) == (0.5, 0.5, 1.0) and 1.0 < b['z'] <= 1.06

    def test_auto_chooses_by_the_photo_and_the_seed_and_the_same_seed_gives_the_same_move(self):
        assert PM.plan((4000, 1000), 6, 'auto', self.subj())['style'] == 'pan' and PM.plan((900, 3000), 6, 'auto', self.subj())['style'] == 'pan'
        seen = {PM.plan(self.size, 6, 'auto', self.subj(), seed=s)['style'] for s in range(20)}; assert seen <= {'push_in', 'pull_out', 'drift', 'reveal'} and len(seen) >= 2
        assert PM.plan(self.size, 6, 'auto', self.subj(), seed=4) == PM.plan(self.size, 6, 'auto', self.subj(), seed=4)
        assert PM.plan(self.size, 6, 'auto', [dict(cx=0.5, cy=0.5, w=0.3, h=0.3, weight=0.1, label='thirds')], seed=1)['style'] in ('drift', 'push_in', 'hold')

    def test_a_small_photo_cannot_zoom_but_still_moves_a_little_or_holds(self):
        p = PM.plan((1280, 720), 5, 'push_in', self.subj()); assert p['zmax'] == 1.0 and all(k['z'] == 1.0 for k in p['keys'])

    def test_what_is_not_allowed_is_refused(self):
        with pytest.raises(ValueError, match='style'): PM.plan(self.size, 5, 'spin')
        with pytest.raises(ValueError, match='more than zero'): PM.plan(self.size, 0)

    def test_the_zoom_is_eased_in_its_logarithm_so_it_feels_even(self):
        p = dict(size=[1600, 1200], aspect=PM.ASPECT, keys=[dict(t=0, cx=0.5, cy=0.5, z=1.0), dict(t=4, cx=0.5, cy=0.5, z=1.44)])
        assert PM.key_at(p, 2)['z'] == pytest.approx(1.2) and PM.key_at(p, -1)['z'] == 1.0 and PM.key_at(p, 9)['z'] == pytest.approx(1.44)


class TestRender:
    def test_the_frames_follow_the_path_and_have_the_output_size(self):
        img = np.zeros((600, 1600, 3), np.uint8); img[:, 800:] = 255                                      # left half black, right half white (wide enough to pan along)
        p = dict(duration_s=2.0, size=[1600, 600], aspect=PM.ASPECT, zmax=2.0, keys=[dict(t=0, cx=0.0, cy=0.5, z=1.0), dict(t=2, cx=1.0, cy=0.5, z=1.0)])
        frames = list(PM.render(img, p, (160, 90), fps=10)); assert len(frames) == 20 and frames[0].shape == (90, 160, 3)
        first, last = frames[0].mean(), frames[-1].mean(); assert first < 80 and last > 170 and all(frames[i].mean() <= frames[i + 1].mean() + 1 for i in range(19))   # moving from the dark side to the light, never back
    def test_zooming_in_on_a_detail_enlarges_it(self):
        img = np.zeros((900, 1600, 3), np.uint8); img[400:500, 750:850] = 255
        p = dict(duration_s=1.0, size=[1600, 900], aspect=PM.ASPECT, zmax=4.0, keys=[dict(t=0, cx=0.5, cy=0.5, z=1.0), dict(t=1, cx=0.5, cy=0.5, z=4.0)])
        f = list(PM.render(img, p, (320, 180), fps=5)); share = lambda fr: float((fr[..., 0] > 128).mean()); assert share(f[-1]) > 4 * share(f[0])


class TestByLength:
    subj = [dict(cx=0.3, cy=0.4, w=0.1, h=0.12, weight=1.0, label='you'), dict(cx=0.7, cy=0.6, w=0.1, h=0.1, weight=0.6, label='person')]

    def test_a_short_shot_only_gets_a_gentle_style_and_a_long_one_may_have_any(self):
        short = {PM.plan((1600, 1200), 2.5, 'auto', self.subj, seed=s)['style'] for s in range(40)}; long_ = {PM.plan((1600, 1200), 8, 'auto', self.subj, seed=s)['style'] for s in range(60)}
        assert short <= {'push_in', 'pull_out', 'hold'} and {'drift', 'reveal'} & long_ and PM.plan((4000, 1000), 2.5, 'auto', self.subj)['style'] == 'pan'                    # (a very wide photo is still panned)

    def test_the_move_is_made_in_proportion_to_the_time_it_has(self):
        def travel(sec): a, b = PM.plan((1600, 1200), sec, 'push_in', self.subj)['keys']; return b['z'] / a['z']
        assert travel(2.0) < travel(4.0) < travel(6.0) == travel(10.0) and travel(2.0) > 1.0
        a, b = PM.plan((6000, 3000), 2.0, 'pan', self.subj, seed=1)['keys']; c, d = PM.plan((6000, 3000), 8.0, 'pan', self.subj, seed=1)['keys']; assert abs(b['cx'] - a['cx']) < 0.5 * abs(d['cx'] - c['cx']) + 1e-9
        h = PM.plan((1600, 1200), 2.0, 'hold')['keys']; assert h[1]['z'] == pytest.approx(1.06)                                                                       # a hold is the same at any length
