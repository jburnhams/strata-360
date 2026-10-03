"""The maths of the street view camera: no pictures of roads, just known answers."""
import math

import cv2
import numpy as np
import pytest

from strata360.edit import streetview_cam as CAM


def equirect(w=720, h=360):
    """A sphere picture whose colour tells the direction: red grows with longitude, green with latitude."""
    x = np.tile(np.linspace(0, 255, w), (h, 1)); y = np.tile(np.linspace(255, 0, h)[:, None], (1, w)); return np.stack([np.zeros_like(x), y, x], -1).astype(np.uint8)


class TestReproject:
    def test_looking_straight_ahead_shows_the_centre_of_the_picture(self):
        v = CAM.reproject(equirect(), np.eye(3), 60.0, (64, 36)); assert abs(int(v[18, 32, 2]) - 127) <= 3 and abs(int(v[18, 32, 1]) - 127) <= 3

    def test_turning_right_shows_what_is_to_the_right_in_the_picture(self):
        right = CAM.reproject(equirect(), CAM.Ry(math.radians(90)), 60.0, (64, 36)); assert abs(int(right[18, 32, 2]) - 191) <= 3          # a quarter of the way round: three quarters of the colour range
        left = CAM.reproject(equirect(), CAM.Ry(math.radians(-90)), 60.0, (64, 36)); assert abs(int(left[18, 32, 2]) - 64) <= 3

    def test_looking_up_shows_the_upper_part(self):
        up = CAM.reproject(equirect(), CAM.Rx(math.radians(-45)), 60.0, (64, 36)); assert int(up[18, 32, 1]) > 180


class TestEquirect:
    def test_no_turn_gives_the_picture_back(self):
        src = equirect(); out = CAM.reproject_equirect(src, np.eye(3), (360, 180)); ref = cv2.resize(src, (360, 180), interpolation=cv2.INTER_AREA)
        assert np.abs(out.astype(int) - ref.astype(int)).mean() < 3

    def test_turning_right_a_quarter_brings_the_right_of_the_picture_to_the_centre(self):
        out = CAM.reproject_equirect(equirect(), CAM.Ry(math.radians(90)), (360, 180)); assert abs(int(out[90, 180, 2]) - 191) <= 4          # the centre column now shows what was a quarter of the way round

    def test_an_upward_tilt_shows_the_upper_part_in_the_centre(self):
        out = CAM.reproject_equirect(equirect(), CAM.Rx(math.radians(-45)), (360, 180)); assert int(out[90, 180, 1]) > 180


class TestOrientation:
    def test_a_level_view_looks_along_the_compass_heading_with_up_up(self):
        V = CAM.level_view(90.0, 0.0); assert np.allclose(V[:, 2], [1, 0, 0]) and np.allclose(V[:, 1], [0, 0, 1]) and np.allclose(V[:, 0], [0, -1, 0])          # east, up; right of east is south
        assert np.allclose(CAM.level_view(0.0, 0.0)[:, 2], [0, 1, 0]) and CAM.level_view(0.0, -2.0)[2, 2] < 0                # a negative pitch looks down

    def test_mapillarys_rotation_turns_the_camera_into_the_world(self):
        R = CAM.sfm_to_world([0.0, 0.0, 0.0]); assert np.allclose(R, np.eye(3))
        R = CAM.sfm_to_world(np.array([1, 0, 0]) * math.pi / 2); assert np.allclose(R @ [0, 0, 1], np.linalg.inv(cv2.Rodrigues(np.array([math.pi / 2, 0, 0]))[0]) @ [0, 0, 1])

    def test_the_view_through_a_level_picture_matches_the_view_of_the_world(self):
        # a camera facing north, level, as Mapillary reports it (x right, y down, z forward = north): rotation world -> camera
        R_wc = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float); rvec, _ = cv2.Rodrigues(R_wc); Rcw = CAM.sfm_to_world(rvec.ravel())
        assert np.allclose(Rcw @ [0, 0, 1], [0, 1, 0], atol=1e-9)                                                               # forward is north
        assert np.allclose(CAM.FLIP @ Rcw.T @ CAM.level_view(0.0, 0.0), np.eye(3), atol=1e-9)                                  # so a level view due north is straight ahead in the picture

    def test_up_rotation_takes_y_to_the_given_vector(self):
        u = np.array([0.2, 0.9, 0.1]); u /= np.linalg.norm(u); assert np.allclose(CAM.up_rotation(u) @ [0, 1, 0], u) and np.allclose(CAM.up_rotation(np.array([0, 1.0, 0])), np.eye(3))
        Q = CAM.up_rotation(u); assert np.allclose(Q @ Q.T, np.eye(3))

    def test_a_level_view_of_a_tilted_picture_looks_at_the_heading_with_the_horizon_level(self):
        u = np.array([0.0, math.cos(0.2), math.sin(0.2)]); R = CAM.view_in_picture(u, 90.0, 90.0, pitch=0.0)
        assert np.allclose(R[:, 1], u) and np.allclose(R.T @ R, np.eye(3)) and abs(R[:, 2] @ u) < 1e-9                       # up is up, forward is horizontal
        R2 = CAM.view_in_picture(np.array([0, 1.0, 0]), 90.0, 180.0, pitch=0.0); assert np.allclose(R2[:, 2], [math.sin(math.radians(90)), 0, math.cos(math.radians(90))], atol=1e-9)        # a quarter turn right of the centre column


class TestPaths:
    def test_headings_are_smoothed_round_the_compass(self):
        out = CAM.smooth_heading(np.array([359.0, 1.0, 359.0, 1.0, 359.0]), 1.0); assert np.all((out < 5) | (out > 355))

    def test_the_heading_of_a_path_looks_ahead(self):
        prog = np.array([0.0, 100.0, 200.0]); xy = np.array([[0.0, 0.0], [0.0, 100.0], [100.0, 100.0]])                          # north for 100 m, then east
        assert CAM.heading_along(prog, xy, 20.0, 10.0) == pytest.approx(0.0, abs=1) and CAM.heading_along(prog, xy, 150.0, 10.0) == pytest.approx(90.0, abs=1) and 0 < CAM.heading_along(prog, xy, 95.0, 20.0) < 90

    def test_a_road_line_gives_metres_along_it(self):
        prog, xy = CAM.road_xy([[50.0 + i * 0.0001, 5.0] for i in range(41)]); assert prog[-1] == pytest.approx(445.0, rel=0.08) and xy[-1, 1] > xy[0, 1] and prog[0] == 0


class TestFlat:
    def test_only_the_pictures_facing_the_way_the_runner_went_are_used(self):
        s = dict(kind='2d', items=[dict(id='a', a=0), dict(id='b', a=40), dict(id='c', a=-100), dict(id='d', a=170), dict(id='e')]); assert [i['id'] for i in CAM.forward_items(s)] == ['a', 'b']
        t = dict(kind='360', items=[dict(id='a'), dict(id='b')]); assert len(CAM.forward_items(t)) == 2

    def test_a_flat_view_is_the_wanted_shape_and_moves_with_the_shift(self):
        img = np.zeros((300, 400, 3), np.uint8); img[:, 200:] = 255; a = CAM.flat_view(img, (0, 0, 0), (160, 90)); b = CAM.flat_view(img, (40, 0, 0), (160, 90))
        assert a.shape == (90, 160, 3) and abs(int(a[:, :, 0].mean()) - 127) < 12 and b[:, :, 0].mean() < a[:, :, 0].mean()                  # shifting the picture right shows more of the dark left half

    def test_the_quick_shake_of_flat_pictures_is_found_and_taken_out(self):
        rng = np.random.default_rng(1); base = cv2.GaussianBlur((rng.random((540, 960)) * 255).astype(np.uint8), (0, 0), 3); base = cv2.cvtColor(cv2.normalize(base, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)
        shakes = [0, 12, -10, 11, -12, 10, 0]                                                                                    # a wobble sideways, in pixels
        imgs = [np.roll(base, s, axis=1) for s in shakes]; fx = CAM.far_shift(imgs[0], imgs[1]); assert fx is not None and abs(fx[0] - 12) < 3
        steady = CAM.steady_flat(imgs, sigma=1.5); resid = [s + d[0] for s, d in zip(shakes, steady)]; assert np.std(resid) < np.std(shakes) * 0.6

    def test_far_shift_gives_up_on_a_blank_picture(self):
        blank = np.full((200, 300, 3), 128, np.uint8); assert CAM.far_shift(blank, blank) is None


def test_flow_blend_moves_things_part_of_the_way():
    rng = np.random.default_rng(2); base = cv2.GaussianBlur((rng.random((180, 320)) * 255).astype(np.uint8), (0, 0), 2); A = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR); B = np.roll(A, 8, axis=1)
    mid = CAM.flow_blend(A, B, 0.5); want = np.roll(A, 4, axis=1); assert np.abs(mid.astype(int) - want.astype(int))[:, 20:-20].mean() < np.abs(cv2.addWeighted(A, .5, B, .5, 0).astype(int) - want.astype(int))[:, 20:-20].mean()     # nearer the true halfway than a cross-fade
