"""The camera readers on real recordings, not synthetic ones. Opt-in: set STRATA_REAL_FOOTAGE to the folder that holds the race folders (the owner's footage drive, e.g. D:/Insta360);
without it every test here is skipped, so CI is unaffected. A test whose clip is not under that folder is skipped too.

The clips are short ones from the owner's library, picked by the October 2026 sweep of all 885 Insta360 X3 recordings (42 trips, 8 firmware versions) and the DJI folders:
an ordinary X3 clip, the X3 clip whose IMU clock steps back, cut-short recordings of both cameras, and an ordinary Osmo 360 clip. Expected numbers were read from those files.

The stitched-frame check compares against a golden kept beside the footage (`<STRATA_REAL_FOOTAGE>/.strata360-test-goldens/`), never in this public repository: the first run writes it and
skips; delete the file to accept a deliberate change."""
import copy, os
import numpy as np
import pytest

ROOT = os.environ.get('STRATA_REAL_FOOTAGE')
pytestmark = pytest.mark.skipif(not ROOT, reason='set STRATA_REAL_FOOTAGE to the footage folder to run the real-file tests')

X3 = '2024-07-20 - Crossing Switzerland/VID_20240723_150136_00_039.insv'                 # 5.1 s, firmware v1.0.90, daylight
X3_IMU_STEPS_BACK = '2023-09-09 - White Horse 100/VID_20230912_114415_00_023.insv'      # the IMU clock steps back 14 ms once (5 of 885 clips do this)
X3_CUT_SHORT = '2022-12-06 - Art Birth/VID_20221002_145905_00_224.insv'                 # no moov box: the recording was cut short
X3_IMU_HOLE = '2023-09-24 - Kidical Mass/VID_20230924_122851_00_033.insv'             # 0.6 s with no IMU samples about a second into the video (56 of 881 clips have such a hole)
DJI = '2026-02-19 - Legends/CAM_20260221120007_0019_D.OSV'                              # 4.8 s
DJI_CUT_SHORT = '2026-07-25 - Beacons 100/CAM_20260726113908_0056_D.OSV'


def real(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p): pytest.skip(f'{rel} is not under {ROOT}')
    return p


def clip_for(path):
    from strata360.pipeline import clips as C
    cl, _ = C.discover(os.path.dirname(path))
    return next(c for c in cl if os.path.normpath(c.osv) == os.path.normpath(path))


def ingest(path):
    from strata360.pipeline import config, ingest as I
    return I.ingest_clip(clip_for(path), copy.deepcopy(config.DEFAULTS))


class TestInsta360X3:
    def test_header_names_the_camera(self):
        from strata360.osv import meta
        h = meta.header(real(X3))
        assert (h['device'], h['firmware'], h['proto'], h['calibration_slots']) == ('Insta360 X3', 'v1.0.90_build1', 'insta360-trailer-v3', 2) and h['serial']

    def test_lens_calibration_fits_at_the_video_size(self):
        from strata360.osv import calib, source
        p = real(X3); s = calib.read_slots(p)
        assert source.lens_size(p) == 2880
        assert [round(s[k][1], 1) for k in (1, 2)] == pytest.approx([786.5, 791.0], abs=0.2)          # focal length of the fitted Kannala-Brandt lens, rear then front
        for k in (1, 2): assert abs(s[k][3] - 1440) < 15 and abs(s[k][4] - 1440) < 15                 # centres near the middle of the 2880 px picture

    def test_ingest_takes_the_start_from_the_file_name(self):
        j = ingest(real(X3))
        assert (j['time']['start_utc'], j['time']['container_creation_time'], j['time']['utc_source']) == ('2024-07-23T15:01:36Z', '2024-07-23T15:01:26Z', 'filename')
        assert (j['video']['width'], j['video']['nominal_fps'], j['video']['source_frames'], j['video']['dropped_frames']) == (2880, 29.97, 154, 0)
        assert j['duration_s'] == pytest.approx(5.138, abs=0.01) and j['audio']['present']

    def test_imu_covers_the_video_and_gives_a_row_a_frame(self):
        from strata360.osv import insta360 as I, telemetry as T
        p = real(X3); t, gyro, acc = I.read_imu(p); pts = T.video_pts(p, 0); start = I.device_start(p)
        assert np.median(np.diff(t)) == pytest.approx(0.001, abs=1e-5)                                # 1 kHz (with a 0.4 s hole before the video starts)
        assert t[0] < start and t[-1] > start + (pts[-1] - pts[0])                                     # the IMU runs from before the first frame to after the last
        f = T.read_frames(p); q = f['quat']
        assert len(q) == len(pts) == 154 and np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-6) and (q[:, 0] >= 0).all()
        assert np.median(np.linalg.norm(f['acc'], axis=1)) == pytest.approx(9.81, abs=0.5)

    def test_exposure_reads_iso_and_shutter(self):
        from strata360.osv import telemetry as T
        e = T.read_exposure(real(X3))['djmd3']
        assert len(e['iso']) == 154 and e['iso'].min() >= 100 and e['iso'].max() <= 6400 and e['shutter_den'].min() > 30

    def test_imu_samples_written_twice_are_dropped(self):
        from strata360.osv import insta360 as I, telemetry as T
        p = real(X3_IMU_STEPS_BACK); t, _, _ = I.read_imu(p)
        assert (np.diff(t) > 0).all()
        assert len(T.read_frames(p)['quat']) == len(T.video_pts(p, 0))                                # used to fail: Slerp needs increasing times

    def test_orientation_is_held_and_relevelled_across_a_hole_in_the_imu(self):
        from scipy.spatial.transform import Rotation as Rot
        from strata360.osv import insta360 as I
        p = real(X3_IMU_HOLE); t, gyro, acc = I.read_imu(p); d = np.diff(t); i = int(np.argmax(d * (t[1:] > I.device_start(p))))
        assert 0.5 < d[i] < 0.7
        wb, ab = gyro @ I.IMU_TO_BODY.T, acc @ I.IMU_TO_BODY.T; q, dtb, _ = I.fuse(np.gradient(t), wb - np.median(wb, 0), ab)
        n = len(dtb) * 5; tb = t[:n].reshape(-1, 5).mean(1); a = ab[:n].reshape(-1, 5, 3).mean(1); a /= np.linalg.norm(a, axis=1)[:, None]
        up = Rot.from_quat(q[:, [1, 2, 3, 0]]).inv().apply([0, 0, 1]); after = (tb > t[i + 1]) & (tb < t[i + 1] + 0.5)
        assert np.median(np.degrees(np.arccos(np.clip((up * a).sum(1), -1, 1)))[after]) < 30           # 66 degrees out when the last rate was carried across the hole; 19 now

    def test_stitched_frame_matches_the_golden(self):
        from strata360.analysis import exposure as E
        from strata360.osv import telemetry as T
        p = real(X3); k = 60
        lens = {s: next(img for n, img in E.decode_stream(p, s, k) if n == k) for s in (0, 1)}
        sph, cov = E.Analyser(p).sphere(lens[1], lens[0], T.read_frames(p)['quat'][k])
        assert cov.mean() > 0.95
        img = np.clip(np.asarray(sph, np.float32), 0, 1)
        gold = os.path.join(ROOT, '.strata360-test-goldens', 'x3_039_f60_sphere.npy')
        if not os.path.exists(gold):
            os.makedirs(os.path.dirname(gold), exist_ok=True); np.save(gold, img); pytest.skip(f'golden written to {gold}: check it once, then later runs compare against it')
        ref = np.load(gold)
        assert img.shape == ref.shape and float(np.abs(img - ref).mean()) < 2e-3


class TestDjiOsmo360:
    def test_header_and_calibration(self):
        from strata360.osv import calib, meta
        p = real(DJI); h = meta.header(p); s = calib.read_slots(p)
        assert (h['device'], h['colour_mode'], h['proto']) == ('Osmo 360', 'normal', 'dvtm_oq101.proto') and h['calibration_slots'] >= 2
        assert [round(s[k][1], 1) for k in (1, 2)] == pytest.approx([1046.8, 1049.0], abs=0.2)

    def test_ingest_and_telemetry(self):
        from strata360.osv import telemetry as T
        p = real(DJI); j = ingest(p)
        assert (j['time']['start_utc'], j['video']['source_frames'], j['video']['width'], j['video']['dropped_frames']) == ('2026-02-21T12:00:07Z', 239, 3840, 2)        # this clip really has a 2-frame gap
        f = T.read_frames(p); e = T.read_exposure(p)['djmd3']
        assert len(f['quat']) == len(e['iso']) == 239 and (np.diff(f['ts_us']) > 0).all()


class TestCutShortRecordings:
    """A recording whose battery or card ran out has no MP4 index; discovery reports it instead of handing it to ingest (where ffprobe failed on it)."""

    def test_an_x3_pair_with_no_index_is_reported_not_ingested(self):
        from strata360.pipeline import clips as C
        p = real(X3_CUT_SHORT); cl, un = C.discover(os.path.dirname(p))
        assert '224' not in {c.id.rsplit('_', 1)[1] for c in cl}
        reasons = {os.path.basename(f): r for f, r in un}
        assert reasons[os.path.basename(p)] == reasons[os.path.basename(p).replace('_00_', '_10_')] == C.NO_INDEX

    def test_an_osv_with_no_index_is_reported_not_ingested(self):
        from strata360.pipeline import clips as C
        from strata360.osv.mp4 import cut_short
        p = real(DJI_CUT_SHORT); cl, un = C.discover(os.path.dirname(p))
        assert cut_short(p) and os.path.splitext(os.path.basename(p))[0] not in {c.id for c in cl}
        assert {os.path.basename(f): r for f, r in un}[os.path.basename(p)] == C.NO_INDEX
