"""An Insta360 X3 recording end to end: discovery of the .insv pair, ingest, telemetry, lens calibration, the audio and exposure stages, and a proxy render, on synthetic files built with ffmpeg
(tests/utils/integration_insv.py: two 128-px H.264 lens files, the rear one with AAC audio and the metadata trailer). No footage, no models. The format is in docs/progress/2026-10-insta360.md."""
import json, os, pathlib, subprocess
import numpy as np
import pytest
import integration_insv as S
from conftest import STAGES
from strata360.osv import calib, insta360, meta, telemetry
from strata360.pipeline import clips

CLIP = 'VID_20240720_195607_001'
REAR, FRONT, LRV = S.names('20240720195607', 1)
FRAMES = 44                                                  # the rear file has 45 frames, the front 44: the shorter decides


def load(path): return json.load(open(path))


@pytest.fixture
def rear(insta360_library): return os.path.join(insta360_library, REAR)


class TestDiscovery:
    def test_a_pair_is_one_clip_named_after_its_start_with_its_proxy(self, insta360_library):
        found, _ = clips.discover(insta360_library); c = found[0]
        assert [x.id for x in found] == [CLIP, 'VID_20240720_195707_002']
        assert os.path.basename(c.osv) == REAR and os.path.basename(c.lrf) == LRV and c.filename_time == '2024-07-20T19:56:07'
        assert found[1].lrf is None

    def test_a_lens_file_without_its_partner_is_reported_not_ingested(self, insta360_library):
        _, other = clips.discover(insta360_library)
        assert [os.path.basename(p) for p, r in other if 'partner' in r] == [S.names('20240720195807', 3)[1]]


class TestTelemetry:
    def test_the_header_comes_from_the_trailer(self, rear):
        h = meta.header(rear)
        assert (h['device'], h['serial'], h['firmware'], h['calibration_slots'], h['colour_mode']) == ('Insta360 X3', 'SYNX3001', 'v1.0.0', 2, 'normal')

    def test_both_lenses_give_the_shorter_frame_count(self, rear):
        a, b = telemetry.video_pts(rear, 0), telemetry.video_pts(rear, 1)
        assert len(a) == len(b) == FRAMES and np.allclose(np.diff(a), 1 / S.FPS, atol=1e-3)

    def test_frames_are_on_the_camera_clock_from_the_first_video_frame(self, rear):
        fr = telemetry.read_frames(rear); ts = fr['ts_us'] / 1e6
        assert len(ts) == FRAMES and ts[0] == pytest.approx(S.first_frame_clock(), abs=1e-5)
        assert np.allclose(np.diff(ts), 1 / S.FPS, atol=1e-3)

    def test_the_orientation_starts_level_and_follows_the_turn(self, rear):
        from scipy.spatial.transform import Rotation as Rot
        q = telemetry.read_frames(rear)['quat']; R = Rot.from_quat(q[:, [1, 2, 3, 0]])
        up = R.apply([0.0, 0.0, 1.0])                                                       # body up in the world: the camera stays upright through the turn
        assert np.allclose(up, [0, 0, 1], atol=1e-3)
        yaw = np.degrees(np.unwrap(R.as_euler('zyx')[:, 0]))
        assert abs(yaw[0]) < 0.5 and abs(yaw[-1] - yaw[0]) == pytest.approx(S.TURN_DEG, abs=1.5)
        t = np.arange(FRAMES) / S.FPS; still = t < S.TURN_AT_S - 0.05
        assert np.abs(yaw[still]).max() < 0.5                                                 # nothing moves before the turn

    def test_acceleration_is_gravity_up_in_metres_per_second_squared(self, rear):
        acc = telemetry.read_frames(rear)['acc']
        assert np.allclose(acc, [0.0, 0.0, 9.80665], atol=1e-3)

    def test_exposure_has_the_iso_and_shutter_of_every_frame(self, rear):
        e = telemetry.read_exposure(rear)
        for k in ('djmd3', 'djmd4'):
            assert len(e[k]['iso']) == FRAMES and set(e[k]['iso']) == {S.ISO} and set(e[k]['shutter_den']) == {round(1 / S.EXPOSURE_S)} and set(e[k]['ct']) == {0}


class TestCalibration:
    def test_the_two_lenses_are_in_the_videos_own_pixels(self, rear):
        sl = calib.read_slots(rear)
        assert set(sl) == {1, 2}
        for s in sl.values():
            assert s[10] == s[11] == 128 and abs(s[3] - 64) < 2 and abs(s[4] - 64) < 2 and 30 < s[1] < 40

    def test_each_lens_looks_its_own_way_and_the_offsets_are_the_identity(self, rear):
        sl = calib.read_slots(rear); front, back = calib.Lens(sl[2]), calib.Lens(sl[1])
        u, v, th = front.project(np.array([[0.0, 1.0, 0.0]])); assert abs(u[0] - 64) < 2 and abs(v[0] - 64) < 2 and np.degrees(th[0]) < 2      # +Y: the front lens's axis (1.2 degrees off: the X3 correction)
        u, v, th = back.project(np.array([[0.0, -1.0, 0.0]])); assert abs(u[0] - 64) < 1 and abs(v[0] - 64) < 1 and th[0] < 1e-6
        assert 55 < front.rim_radius() < 64
        A, B = calib.imu_offsets(rear); assert np.allclose(A, np.eye(3)) and np.allclose(B, np.eye(3))


class TestIngest:
    def test_clip_facts_come_from_both_lens_files_and_the_trailer(self, insta360_processed):
        c = load(f'{insta360_processed}/strata360/clips/{CLIP}/clip.json'); v = c['video']
        assert {k: os.path.basename(p) for k, p in c['source_files'].items()} == dict(osv=REAR, lrf=LRV, front=FRONT)
        assert c['camera'] == dict(model='Insta360 X3', serial='SYNX3001', firmware='v1.0.0', proto='insta360-trailer-v3') and c['calibration_slots'] == 2
        assert (v['streams'], v['width'], v['codec'], v['pix_fmt'], v['nominal_fps'], v['source_frames'], v['dropped_frames']) == (2, 128, 'h264', 'yuvj420p', 29.97, FRAMES, 0)
        assert c['audio']['present'] and c['audio']['channels'] == 2 and c['duration_s'] == pytest.approx(FRAMES / S.FPS, abs=0.01)
        assert any('differ in length (45 rear, 44 front' in n for n in c['notes'])

    def test_the_start_is_the_file_name_not_the_early_container_time(self, insta360_processed):
        t = load(f'{insta360_processed}/strata360/clips/{CLIP}/clip.json')['time']
        assert (t['start_utc'], t['utc_source'], t['container_creation_time']) == ('2024-07-20T19:56:07Z', 'filename', '2024-07-20T19:55:57Z')
        assert load(f'{insta360_processed}/strata360/clips/VID_20240720_195707_002/clip.json')['time']['start_utc'] == '2024-07-20T19:57:07Z'

    def test_audio_and_exposure_are_tied_to_the_clip_by_its_time_hash(self, insta360_processed):
        d = f'{insta360_processed}/strata360/clips/{CLIP}'; h = load(f'{d}/clip.json')['time']['utc_hash']
        au, ex = load(f'{d}/audio.json'), load(f'{d}/exposure.json')
        assert au['utc_hash'] == ex['utc_hash'] == h and au['summary']['channels'] == 2 and au['summary']['integrated_lufs'] < 0
        f = ex['frames'][0]['camera']; assert f['iso'] == [S.ISO, S.ISO] and f['shutter_den'] == [250, 250]
        assert ex['sampling']['source_frames'] == FRAMES and ex['frames'][0]['sphere']['coverage'] > 0.9

    def test_exposure_names_the_camera_that_made_the_clip(self, insta360_processed):
        ex = load(f'{insta360_processed}/strata360/clips/{CLIP}/exposure.json')
        assert (ex['source']['camera'], ex['source']['colour_mode']) == ('insta360_x3', 'normal')

    def test_unchanged_work_is_not_redone(self, insta360_processed, cli):
        assert 'nothing left to do' in cli('run', insta360_processed, '--stages', STAGES).stdout

    def test_status_lists_each_clip_without_failures(self, insta360_processed, cli):
        st = cli('status', insta360_processed).stdout
        assert CLIP in st and 'VID_20240720_195707_002' in st and 'FAIL' not in st, st


def _frames(path, w, h):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(float)


def _shift(a, b):
    """Columns by which equirect picture `b` is `a` turned (circularly), from the cross-correlation of their column profiles."""
    pa, pb = a.mean(0) - a.mean(), b.mean(0) - b.mean()
    c = np.fft.ifft(np.fft.fft(pb) * np.conj(np.fft.fft(pa))).real; k = int(np.argmax(c))
    return k if k <= len(c) // 2 else k - len(c)


def test_the_proxy_stage_renders_an_upright_view_that_turns_with_the_camera(insta360_processed, cli):
    p = pathlib.Path(insta360_processed, 'strata360', 'race.json'); cfg = load(p)
    cfg['proxy'] = dict(size='128x64', every_frames=1, bitrate='1M', encoder='h264'); json.dump(cfg, open(p, 'w'))
    assert 'proxy: ok' in cli('run', insta360_processed, '--stages', 'proxy', '--clips', CLIP).stdout
    d = pathlib.Path(insta360_processed, 'strata360', 'clips', CLIP); side = load(d / 'proxy.json')
    assert side['size'] == [128, 64] and [f['source_frame'] for f in side['frames']] == list(range(FRAMES))
    img = _frames(d / 'proxy.mp4', 128, 64); assert len(img) == FRAMES
    assert (img[0] > 16).mean() > 0.9                                                               # the two lenses cover the sphere
    assert abs(_shift(img[0], img[1])) <= 1                                                         # still before the turn
    assert abs(_shift(img[0], img[-1])) == pytest.approx(128 * S.TURN_DEG / 360, abs=2)            # 45 degrees of yaw = 16 of 128 columns
