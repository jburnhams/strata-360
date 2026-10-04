import numpy as np
import pytest

from strata360.edit import pointcam as PC

LAT0, LON0 = 50.0, 5.0
M_LAT = 1 / PC.EARTH                      # degrees of latitude in a metre
M_LON = 1 / (PC.EARTH * np.cos(np.radians(LAT0)))


def straight(n=121, speed=3.0, bearing_east=True):
    """A run heading due east at `speed` m/s, one fix a second, starting at (LAT0, LON0) and time 1000."""
    t = 1000.0 + np.arange(n); x = speed * np.arange(n)
    return PC.poly(np.full(n, LAT0), LON0 + x * M_LON, t)


def point(east_m, north_m): return LAT0 + north_m * M_LAT, LON0 + east_m * M_LON


def cam(**kw):
    lat, lon = point(180.0, 20.0)          # 20 m to the left (north) of a run heading east, 180 m along (60 s in)
    return dict(PC.DEFAULTS, id='C1', label='C1', source=dict(kind='clip', clip='c1'), lat=lat, lon=lon, t_pass=1060.0, **kw)


def test_closest_approach_is_the_nearest_point_of_the_line_not_the_nearest_fix():
    p = straight(n=61, speed=10.0)                                   # fixes 10 m apart
    c = PC.closest(p, *point(155.0, 12.0))
    assert c['dist_m'] == pytest.approx(12.0, abs=0.2) and c['t'] == pytest.approx(1015.5, abs=0.05) and c['along_m'] == pytest.approx(155.0, abs=0.5)


def test_closest_can_be_held_to_a_stretch_of_time():
    p = straight(); lat, lon = point(180.0, 20.0)
    assert PC.closest(p, lat, lon, 1000, 1030)['t'] == pytest.approx(1030.0, abs=0.01)         # only the first 30 s are looked at: the end of that is the nearest
    assert PC.closest(straight(1), lat, lon) is None


def test_the_window_is_the_metres_either_side_of_the_pass():
    p = straight(speed=3.0)
    t0, t1 = PC.window(p, 1060.0, 30.0, 60.0)
    assert (t0, t1) == pytest.approx((1050.0, 1080.0), abs=0.1)                       # 30 m before is 10 s, 60 m after is 20 s at 3 m/s
    assert PC.window(p, 1060.0, 400.0, 400.0, 1040.0, 1090.0) == pytest.approx((1040.0, 1090.0))        # held to what the source covers
    t0, t1 = PC.window(p, 1060.0, 1.0, 1.0)
    assert t1 - t0 == pytest.approx(PC.MIN_S, abs=0.01) and t0 < 1060.0 < t1         # too short: widened round the pass
    t0, t1 = PC.window(straight(n=400, speed=3.0), 1100.0, 400.0, 400.0)
    assert t1 - t0 <= PC.MAX_S + 1e-6 and t0 < 1100.0 < t1                          # too long: trimmed round the pass


def test_a_shorter_shot_is_trimmed_round_the_closest_approach():
    c = cam(); t0, t1 = 1040.0, 1090.0
    a, b = PC.shrink(None, c, t0, t1, 10.0)
    assert (b - a) == pytest.approx(10.0) and a < c['t_pass'] < b and (c['t_pass'] - a) / (b - c['t_pass']) == pytest.approx(20 / 30)       # the same share each side as before
    assert PC.shrink(None, c, t0, t1, 80.0) == (t0, t1)                               # longer than the window: unchanged


def test_the_camera_looks_at_the_point_and_swings_round_as_it_passes():
    p = straight(); c = cam(smooth_s=0.0)
    sm = PC.samples(p, c, 1030.0, 1090.0)
    # heading east: the point 90 m ahead and 20 m to the left (north) is 12.5 degrees to the left at first, and swings to 90 degrees left and then behind as it is passed
    assert sm['rel'][0] == pytest.approx(-np.degrees(np.arctan2(20.0, 90.0)), abs=1.0)
    mid = int(np.argmin(np.abs(sm['t'] - 1060.0))); assert sm['rel'][mid] == pytest.approx(-90.0, abs=2.0) and sm['dist'][mid] == pytest.approx(20.0, abs=1.0)
    assert sm['rel'][-1] < -150.0 and np.all(np.diff(sm['rel']) < 0.05)                 # always turning the same way, to behind the runner
    assert sm['dist'].min() == pytest.approx(20.0, abs=1.0) and sm['dist'][0] == pytest.approx(np.hypot(90.0, 20.0), abs=1.5)


def test_smoothing_limits_how_fast_the_view_swings():
    p = straight(); sharp = PC.facts(PC.samples(p, cam(smooth_s=0.0), 1030.0, 1090.0)); soft = PC.facts(PC.samples(p, cam(smooth_s=2.0), 1030.0, 1090.0))
    assert soft['max_pan_deg_s'] < sharp['max_pan_deg_s']


def test_the_zoom_follows_the_distance_from_wide_when_close_to_tight_when_far():
    p = straight(); c = cam(fov_near=100.0, fov_far=50.0, smooth_s=0.0); sm = PC.samples(p, c, 1030.0, 1090.0)
    mid = int(np.argmin(sm['dist']))
    assert sm['fov'][mid] == pytest.approx(100.0, abs=0.5) and sm['fov'][0] == pytest.approx(50.0, abs=8.0) and sm['fov'].min() >= 50.0 - 1e-6 and sm['fov'].max() <= 100.0 + 1e-6
    far = PC.samples(p, dict(c, fov_near=70.0, fov_far=70.0), 1030.0, 1090.0); assert np.allclose(far['fov'], 70.0)


def test_the_pitch_aims_at_the_height_of_the_point():
    p = straight()
    ground = PC.samples(p, cam(height_m=0.0, smooth_s=0.0), 1050.0, 1070.0); tower = PC.samples(p, cam(height_m=20.0, smooth_s=0.0), 1050.0, 1070.0)
    i = int(np.argmin(ground['dist'])); assert ground['pitch'][i] == pytest.approx(-np.degrees(np.arctan2(PC.CAM_H, 20.0)), abs=0.5)         # a little down to the ground 20 m away
    assert tower['pitch'][i] == pytest.approx(np.degrees(np.arctan2(20.0 - PC.CAM_H, 20.0)), abs=0.5)           # up to the top of a 20 m tower


def test_the_course_is_the_direction_of_travel_and_a_gps_jitter_does_not_swing_the_view():
    rng = np.random.default_rng(1); p = straight(); p['lat'] = p['lat'] + rng.normal(0, 2.0, len(p['lat'])) * M_LAT                  # 2 m of noise on a 3 m/s run
    sm = PC.samples(p, cam(smooth_s=0.0), 1030.0, 1090.0)
    assert np.all(np.abs(sm['course'] - 90.0) < 25.0)
    clean = PC.samples(straight(), cam(smooth_s=0.0), 1030.0, 1090.0); assert np.max(np.abs(sm['rel'] - clean['rel'])) < 25.0


def test_facts_warn_about_a_fast_pan_and_a_point_on_the_path():
    p = straight(speed=6.0); lat, lon = point(360.0, 3.0)
    near = dict(cam(smooth_s=0.0), lat=lat, lon=lon, t_pass=1060.0); f = PC.facts(PC.samples(p, near, 1050.0, 1070.0))
    assert f['min_dist_m'] < 4.0 and any('within 4 m' in w for w in f['warnings']) and any('degrees a second' in w for w in f['warnings'])
    ok = PC.facts(PC.samples(straight(), dict(cam(smooth_s=1.0), lat=point(180.0, 80.0)[0], lon=point(180.0, 80.0)[1]), 1030.0, 1090.0)); assert ok['warnings'] == [] and ok['seconds'] == 60.0


def test_the_keyframes_are_world_yaw_from_the_bearing_and_the_calibration():
    p = straight(); sm = PC.samples(p, cam(smooth_s=0.0), 1050.0, 1070.0); kf = PC.keyframes(sm, 1050.0, north_offset=10.0)
    assert kf[0]['t'] == 0.0 and kf[-1]['t'] == 20.0 and all(k['ease'] == 'linear' for k in kf)
    assert kf[0]['yaw'] == pytest.approx(sm['bearing'][0] - 10.0, abs=0.01) and np.all(np.abs(np.diff([k['yaw'] for k in kf])) < 180)                   # (unwrapped: no jump over north)
    assert PC.keyframes(dict(sm, bearing=np.array([359.0, 1.0] + [1.0] * (len(sm['t']) - 2))), 1050.0)[1]['yaw'] == pytest.approx(361.0)


def test_the_calibration_is_the_circular_mean_of_the_course_minus_the_heading():
    assert PC.north_offset([90, 91, 89], [0, 1, -1]) == pytest.approx(90.0, abs=0.01)
    assert PC.north_offset([359, 1], [0, 0]) == pytest.approx(0.0, abs=0.01)                    # across north
    assert PC.north_offset([], []) == 0.0 and PC.north_offset([np.nan], [3.0]) == 0.0


def test_records_are_created_numbered_checked_updated_and_deleted(tmp_path):
    rd = str(tmp_path); a = PC.create(rd, dict(kind='clip', clip='c1'), 50.1, 5.2, 1060.0); b = PC.create(rd, dict(kind='streetview', key='google:s:1.0'), 50.1, 5.2, 1070.0, fov_far=300, before_m=1)
    assert (a['id'], b['id']) == ('C1', 'C2') and a['use'] == '' and b['fov_far'] == PC.LIMITS['fov_far'][1] and b['before_m'] == PC.LIMITS['before_m'][0]          # held to the limits
    assert PC.update(rd, 'c1', use='must', height_m=25)['use'] == 'must' and PC.get(rd, 'C1')['height_m'] == 25.0
    with pytest.raises(ValueError, match='use'): PC.update(rd, 'C1', use='sometimes')
    with pytest.raises(ValueError, match='number'): PC.update(rd, 'C1', fov_near='wide')
    with pytest.raises(ValueError, match='unknown'): PC.update(rd, 'C1', colour='red')
    with pytest.raises(KeyError): PC.update(rd, 'C9', use='')
    assert PC.delete(rd, 'C1') and not PC.delete(rd, 'C1') and [c['id'] for c in PC.load(rd)['cams']] == ['C2']
    assert PC.create(rd, dict(kind='clip', clip='c1'), 50.1, 5.2, 1.0)['id'] == 'C3'          # a label is never used twice
    assert PC.is_camera_label('c12') and not PC.is_camera_label('G12') and not PC.is_camera_label('C')
