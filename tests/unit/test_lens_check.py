import numpy as np
from strata360.analysis import lens_check as LC

S = LC.SIZE


def textured(seed=0):
    rng = np.random.default_rng(seed); img = rng.integers(60, 200, (S, S, 3)).astype(np.uint8); return img


def test_a_textured_scene_has_nothing_over_the_lens():
    cover, flat, dark, glare, soft = LC.measure(textured())
    assert cover < 0.02 and flat < 0.02 and glare < 0.01


def test_a_smooth_patch_is_a_covered_part_of_the_lens():
    img = textured(); img[:, : S // 3] = (90, 110, 150)                       # a hand: smooth, warm, a third of the picture
    cover, flat, *_ = LC.measure(img)
    assert 0.15 < cover < 0.5 and flat >= cover


def test_fog_over_the_whole_lens_is_nearly_all_cover():
    assert LC.measure(np.full((S, S, 3), (150, 150, 150), np.uint8))[0] > 0.9


def test_a_plain_blue_sky_is_not_a_covered_lens():
    sky = np.zeros((S, S, 3), np.uint8); sky[:] = (230, 180, 120)             # BGR: bright and bluer than red
    assert LC.measure(sky)[0] == 0.0


def test_blocked_signal_rises_with_cover_and_takes_the_worse_lens():
    doc = dict(hz=1.0, lenses=dict(front=[[0.0] * 5, [0.0] * 5, [0.0] * 5], rear=[[0.0] * 5, [0.3] * 5, [0.9, 0, 0, 0, 0]]))
    b = LC.blocked(doc, [0.5, 1.5, 2.5])
    assert b[0] == 0.0 and 0.3 < b[1] < 0.7 and b[2] == 1.0
    assert (LC.blocked(None, [0.5, 1.5]) == 0).all()

