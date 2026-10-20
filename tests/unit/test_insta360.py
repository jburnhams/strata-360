"""Insta360 adapter: trailer parsing, clip pairing, lens conversion and orientation filter on synthetic data (no footage needed)."""
import os, struct
import pytest
import numpy as np
from strata360.osv import insta360 as I, source
from strata360.pipeline import clips

CAL = ('2_1.948170_4637.250_4637.080_2980.600_2993.490_-0.171_-0.284_90.064_0.000000_0.000000_0.000000_0.42028457_1.03285277_-3.47208929_0.00084204_0.00139114_11904_5952_71_'
       '1.948170_4645.630_4645.130_8924.460_2988.160_-0.107_-0.283_91.229_0.000288_-0.000136_-0.026685_0.40457988_1.20917737_-3.86310482_0.00031331_0.00040798_11904_5952_71_199424')


def varint(v):
    out = b''
    while True:
        c = v & 0x7f; v >>= 7
        if v: out += bytes([c | 0x80])
        else: return out + bytes([c])


def pb(field, val): return varint(field << 3 | 2) + varint(len(val)) + val


def make_insv(path, n_imu=2000, imu_us=None):
    extra = pb(1, b'SER123') + pb(2, b'Insta360 X3') + pb(3, b'v1') + pb(54, CAL.encode())
    imu_us = [1_000_000 + i * 1000 for i in range(n_imu)] if imu_us is None else imu_us
    imu = b''.join(struct.pack('<Q6H', t, 32768, 32768 - 1000, 32768, 32768, 32768, 32768) for t in imu_us)
    exp = b''.join(struct.pack('<Qd', 4_000_000 + i * 33333, 0.01) for i in range(5))
    body = b''
    aaa = b''.join(struct.pack('<IffII7I', 1000 * i, 0.0, 10.0, 0, (((1600 >> 0) << 19) if i else 0), *([0] * 7)) for i in range(6))                   # iso = 100 * 1600 >> 6 = 2500
    for rid, d in ((0xa00, b'x' * 5), (0x101, extra), (0x300, imu), (0x400, exp), (0x900, aaa)): body += d + struct.pack('<HI', rid, len(d))      # data, then (id, length): read backwards
    with open(path, 'wb') as f:
        f.write(b'\0' * 100 + body + b'\0' * 32 + struct.pack('<II', len(body) + 72, 3) + I.MAGIC)


def test_trailer_records_and_extra(tmp_path):
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p)
    rec = I.read_trailer(str(p)); assert {0x101, 0x300, 0x400} <= set(rec)
    x = I.extra(str(p)); assert x['model'] == 'Insta360 X3' and x['serial'] == 'SER123'


def test_imu_and_exposure_decode(tmp_path):
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p, 300)
    t, g, a = I.read_imu(str(p)); assert len(t) == 300 and abs(t[1] - t[0] - 0.001) < 1e-9 and a[0, 1] == -1000
    ets, ex = I.read_exposure_records(str(p)); assert len(ets) == 5 and abs(ex[0] - 0.01) < 1e-12


def test_imu_samples_written_twice_are_dropped(tmp_path):
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; us = [1_000_000 + i * 1000 for i in range(100)]
    make_insv(p, imu_us=us[:60] + us[46:])                                                            # the camera wrote 14 ms of samples again (5 of 885 real X3 clips)
    t, g, a = I.read_imu(str(p)); assert len(t) == len(g) == len(a) == 100 and (np.diff(t) > 0).all()


def test_calibration_converts_to_kb_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'lens_size', lambda path: 2880)
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p)
    s = I.slots(str(p)); assert set(s) == {1, 2}
    for slot in s.values():
        assert abs(slot[3] - 1440) < 25 and abs(slot[4] - 1440) < 25 and 600 < slot[1] < 1000 and len(slot['poly_x']) == 0
    L = I.parse_calibration(CAL); f, k, cx, cy, err = I._fit_kb(L[0]); assert err < 1.0


def test_orientation_is_level_and_follows_a_turn():
    n = 4000; dt = np.full(n, 0.001); up = np.tile([0.0, 0.0, 1.0], (n, 1)) * 1000.0
    q, _, _ = I.fuse(dt, np.zeros((n, 3)), up); assert np.allclose(q[-1], [1, 0, 0, 0], atol=1e-6)
    w = np.tile([0.0, 0.0, np.radians(90)], (n, 1)); q, _, _ = I.fuse(dt, w, up)                  # 90 deg/s about the up axis for 4 s = 360 deg
    yaw = 2 * np.arctan2(q[-1, 3], q[-1, 0]); assert abs(abs(np.degrees(yaw)) % 360) < 3 or abs(abs(np.degrees(yaw)) % 360 - 360) < 3


def test_orientation_is_held_across_a_hole_in_the_imu_and_levelled_again():
    n = 2000; dt = np.full(n, 0.001); dt[1000:1005] = 0.12                                         # one 5-sample block spans 0.6 s with no samples
    w = np.zeros((n, 3)); w[1000:1005] = [np.radians(200), 0.0, 0.0]                                 # the last rate before the hole: carried across it, that is 120 degrees of roll
    tilt = np.radians(10); up = np.tile([0.0, 0.0, 1000.0], (n, 1)); up[1005:] = [0.0, -np.sin(tilt) * 1000, np.cos(tilt) * 1000]   # the camera was leaning 10 degrees when the samples resume
    q, _, _ = I.fuse(dt, w, up)
    i = 1005 // 5; qw, qx, qy, qz = q[i]; vy, vz = 2 * (qy * qz + qw * qx), qw * qw - qx * qx - qy * qy + qz * qz      # world up seen from the body just after the hole
    assert np.degrees(np.arctan2(-vy, vz)) == pytest.approx(10, abs=0.5)
    assert np.allclose(q[1000 // 5 - 1], [1, 0, 0, 0], atol=1e-6)


def test_cut_short_recordings_are_reported_not_paired(tmp_path):
    ftyp = struct.pack('>I4s', 16, b'ftyp') + b'avc1\0\0\0\0'; mdat = struct.pack('>I4s', 1000, b'mdat') + b'\0' * 992; moov = struct.pack('>I4s', 8, b'moov')
    for n, body in (('VID_20221002_145905_00_224.insv', ftyp + mdat), ('VID_20221002_145905_10_224.insv', ftyp + mdat),
                    ('VID_20221002_150000_00_225.insv', ftyp + mdat + moov), ('VID_20221002_150000_10_225.insv', ftyp + mdat + moov), ('CAM_20260726113908_0056_D.OSV', ftyp + mdat[:500])):
        (tmp_path / n).write_bytes(body)
    cl, other = clips.discover(str(tmp_path)); why = {os.path.basename(f): r for f, r in other}
    assert [c.id for c in cl] == ['VID_20221002_150000_225']
    assert why['VID_20221002_145905_00_224.insv'] == why['VID_20221002_145905_10_224.insv'] == why['CAM_20260726113908_0056_D.OSV'] == clips.NO_INDEX


def test_pairing_and_filename_time(tmp_path):
    for n in ('VID_20240720_195607_00_001.insv', 'VID_20240720_195607_10_001.insv', 'LRV_20240720_195607_11_001.lrv', 'VID_20240720_202857_00_002.insv'):
        (tmp_path / n).write_bytes(b'x' * 10)
    cl, other = clips.discover(str(tmp_path))
    assert [c.id for c in cl] == ['VID_20240720_195607_001'] and cl[0].lrf.endswith('.lrv') and cl[0].filename_time == '2024-07-20T19:56:07' and cl[0].osv.endswith('_00_001.insv')
    assert any('partner' in r for _, r in other)


def test_lens_files_and_input(tmp_path):
    p = str(tmp_path / 'VID_20240720_195607_00_001.insv')
    assert I.lens_file(p, 0) == p and I.lens_file(p, 1).endswith('_10_001.insv')
    assert source.lens_input(p, 1)[-2:] == ['-map', '0:v:0'] and source.lens_input('a.osv', 1)[-1] == '0:v:1'
    assert source.full_frame_filter('a.osv', True) == [] and source.full_frame_filter(p) == []                  # nothing is resized
    assert 'in_range=full' in source.full_frame_filter(p, True)[0] and '3840' not in source.full_frame_filter(p, True)[0]


def test_video_pts_agree_between_lenses(tmp_path, monkeypatch):
    from strata360.osv import mp4, telemetry
    p = str(tmp_path / 'VID_20240720_195607_00_001.insv')
    monkeypatch.setattr(mp4, 'video_sample_times', lambda f: np.arange(479 if '_00_' in f else 478) / 29.97)
    assert len(telemetry.video_pts(p, 0)) == 478 and len(telemetry.video_pts(p, 1)) == 478


def test_x3_front_lens_gets_the_measured_correction_and_others_do_not(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'lens_size', lambda path: 2880)
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p)
    q = I.slots(str(p))[2]['q']
    from strata360.osv.calib import quat_to_R
    R = quat_to_R(q); assert not np.allclose(R, I._R_FRONT, atol=1e-6) and np.allclose(R, I._R_FRONT, atol=0.03)          # about 1.2 degrees off the nominal flip
    assert np.allclose(I._front_rotation('Insta360 X4'), I._R_FRONT)


def test_lens_pixels_follow_the_video_size(tmp_path, monkeypatch):
    """Calibration coordinates are in the lens video's own pixels: the centre sits at half the size, whatever the size."""
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p)
    for size in (2880, 2400):
        monkeypatch.setattr(I, 'lens_size', lambda path, size=size: size)
        for slot in I.slots(str(p)).values(): assert abs(slot[3] - size / 2) < 25 and slot[10] == size


def test_iso_comes_from_the_auto_exposure_table(tmp_path):
    p = tmp_path / 'VID_20240720_195607_00_001.insv'; make_insv(p)
    ts, iso = I.read_aaa(str(p)); assert len(ts) == 5 and np.all(iso == 2500)
    e = I.exposure_frames(str(p), np.arange(4) / 29.97)['djmd3']; assert np.all(e['iso'] == 2500) and e['shutter_den'][0] == 100
