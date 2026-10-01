import numpy as np
from strata360.analysis import candidates as C


def vq(detail, contrast, n=3):
    d = np.full((n, 18, 36), detail, np.float16); c = np.full((n, 18, 36), contrast, np.float16); return dict(t=np.arange(n, dtype=np.float32), detail=d, contrast=c)


def test_low_fraction_counts_the_empty_part_of_the_sphere():
    assert np.allclose(C.low_fraction(vq(0.0, 0.0)), 1.0)                                      # mist all over
    assert np.allclose(C.low_fraction(vq(0.05, 0.3)), 0.0)                                     # foliage and people
    q = vq(0.05, 0.3); q['detail'][:, :9, :] = 0.0; q['contrast'][:, :9, :] = 0.0              # the northern half is empty (a clear sky): about half, weighted by area
    f = C.low_fraction(q); assert 0.4 < f[0] < 0.6
    q['detail'][:, :3, :] = np.nan; assert np.isfinite(C.low_fraction(q)).all()                  # cells that nobody covers do not count


def test_unusable_needs_both_the_vision_model_and_the_grid(tmp_path):
    from strata360.analysis import exposure as EX
    rows = [(i * 50, float(i), dict(detail=np.full((18, 36), 0.05), contrast=np.full((18, 36), 0.3), chroma=np.full((18, 36), 0.2), share=np.full((18, 36), 0.5), cover=np.ones((18, 36))),
             dict(overlap_frac=0.3, detail_share_master=0.5, master_range=0.6, slave_range=0.6)) for i in range(4)]
    EX.save_quality(str(tmp_path / 'view_quality.npz'), rows); q = EX.load_quality(str(tmp_path))
    assert q['detail'].shape == (4, 18, 36) and q['lens_detail_share_master'].shape == (4,) and EX.load_quality(str(tmp_path / 'nope')) is None
    assert np.allclose(C.low_fraction(q), 0.0)                                                 # a detailed picture: even if the vision model says "fog", it stays usable (see candidates.timeline)


def maps(detail_peak_col=None, n=3):
    rng = np.random.default_rng(0); det = rng.uniform(0.0, 0.01, (n, 18, 36)).astype(np.float32); con = rng.uniform(0.0, 0.05, (n, 18, 36)).astype(np.float32); chroma = rng.uniform(0.1, 0.2, (n, 18, 36)).astype(np.float32)
    if detail_peak_col is not None:
        cols = [(detail_peak_col + j) % 36 for j in range(-4, 5)]; det[:, 7:12, :][:, :, cols] = 0.08; con[:, 7:12, :][:, :, cols] = 0.4
    return dict(t=np.arange(n, dtype=np.float32), detail=det, contrast=con, chroma=chroma, share=np.full((n, 18, 36), 0.5, np.float32), lens_detail_share_master=np.full(n, 0.5, np.float32))


def test_the_view_turns_toward_the_detail_but_only_when_it_gains_something_clear():
    from strata360.edit import attention as A
    heading = 0.0; c0 = 18                                                                       # the column of the heading (lon 0)
    r = A.best_yaw_offset(maps(c0 + 4), 0.0, 2.0, heading); assert 20 <= r['offset_deg'] <= 50, r        # the detail is 40 deg to the right
    r = A.best_yaw_offset(maps(c0 - 4), 0.0, 2.0, heading); assert -50 <= r['offset_deg'] <= -20, r
    r = A.best_yaw_offset(maps(c0), 0.0, 2.0, heading); assert r['offset_deg'] == 0.0, r                  # it is straight ahead already
    r = A.best_yaw_offset(maps(None), 0.0, 2.0, heading); assert abs(r['offset_deg']) <= 10 or r['gain'] < 0.2     # random texture everywhere: no strong reason to move


def test_a_foggier_lens_is_looked_away_from():
    from strata360.edit import attention as A
    q = maps(None); q['detail'][:, 7:12, 24:30] = 0.08; q['contrast'][:, 7:12, 24:30] = 0.4          # something to see on the right, 30 to 80 deg
    free = A.best_yaw_offset(q, 0.0, 2.0, 0.0)['offset_deg']
    q['share'][:, :, 20:36] = 0.9; q['lens_detail_share_master'][:] = 0.2                            # but that side is the master lens, which holds far less detail (fog)
    fog = A.best_yaw_offset(q, 0.0, 2.0, 0.0)['offset_deg']
    assert fog < free


def test_clarity_samples_follow_the_detail_around_the_whole_sphere():
    from strata360.edit import attention as A
    s = A.clarity_samples(maps(30)); assert len(s) == 3 and all(abs(((x['yaw'] - 305.0 + 180) % 360) - 180) < 30 for x in s), s          # column 30 is lon +125 .. yaw about 305: it finds it behind, not only near the heading
    assert all(x['pitch'] in (-20.0, 0.0, 20.0) and 0 <= x['yaw'] < 360 for x in s)
