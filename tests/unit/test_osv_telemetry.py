import pytest
import struct
import numpy as np
from osv import build_varint, encode_field
from strata360.osv.telemetry import read_frames, video_pts, read_exposure



def test_read_frames(fake_run, monkeypatch):
    import strata360.osv.telemetry

    # We want to yield a mocked packet via packets()
    # Or we can just mock ffmpeg/ffprobe like we did in pbdump.
    # packets() uses ffprobe for sizes and ffmpeg for data.

    # Construct a packet
    # fm = field 3 w=2
    # d = field 1 w=2 -> device microsec (field 2 w=0)
    # b = field 2 w=2 -> quat (field 9 w=2), acc (field 10 w=2)
    # quat inner -> fields 1..4 w=5
    # acc inner -> fields 2..4 w=5

    dev_ts = encode_field(2, 0, 1000000)
    d = encode_field(1, 2, dev_ts)

    q_inner = encode_field(1, 5, 1.0) + encode_field(2, 5, 0.0) + encode_field(3, 5, 0.0) + encode_field(4, 5, 0.0)
    qq = encode_field(9, 2, q_inner)

    a_inner = encode_field(2, 5, 0.0) + encode_field(3, 5, 0.0) + encode_field(4, 5, -9.81)
    aa = encode_field(10, 2, a_inner)

    b = encode_field(2, 2, qq + aa)

    fm = encode_field(3, 2, d + b)

    # to mock packets we can mock ffprobe to return size of fm, and ffmpeg to return fm
    fake_run.returns['ffprobe'] = str(len(fm)).encode() + b'\n'
    fake_run.returns['ffmpeg'] = fm

    frames = read_frames('test.osv')
    assert len(frames['ts_us']) == 1
    assert frames['ts_us'][0] == 1000000
    np.testing.assert_array_almost_equal(frames['quat'][0], [1.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_almost_equal(frames['acc'][0], [0.0, 0.0, -9.81])

def test_video_pts(fake_run):
    fake_run.returns['ffprobe'] = b'0.0\n0.033\n0.066\n'
    pts = video_pts('test.osv')
    assert len(pts) == 3
    assert pts[0] == 0.0
    assert pts[1] == pytest.approx(0.033)
    assert pts[2] == pytest.approx(0.066)

def test_read_exposure(fake_run):
    # fm = field 3 w=2
    # b = field 2 w=2 -> e = field 2 w=2
    # e = ISO(3 w=5), shut(4 w=2), ct(6 w=0/5/etc, assume 0 for K)

    # Shutter is a varint preceded by a 0x01 tag
    shut_inner = b'\x01' + build_varint(100) # 1/100s

    iso = encode_field(3, 2, encode_field(1, 5, 400.0))
    shut = encode_field(4, 2, encode_field(1, 2, shut_inner))
    ct = encode_field(6, 2, encode_field(1, 0, 5000))

    b = encode_field(2, 2, iso + shut + ct)
    fm = encode_field(3, 2, b)

    # read_exposure reads djmd3 and djmd4, so we need two packets (or we can just supply one that loops over both)
    # mock will supply the same for both streams
    fake_run.returns['ffprobe'] = str(len(fm)).encode() + b'\n'
    fake_run.returns['ffmpeg'] = fm

    exp = read_exposure('test.osv')

    assert 'djmd3' in exp
    assert 'djmd4' in exp

    assert len(exp['djmd3']['iso']) == 1
    assert exp['djmd3']['iso'][0] == pytest.approx(400.0)
    assert exp['djmd3']['shutter_den'][0] == 100
    assert exp['djmd3']['ct'][0] == 5000
