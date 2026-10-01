import pytest
import struct
import numpy as np
from strata360.osv import telemetry
from pbdump_fakes import pack_msg, pack_varint

def test_read_frames(monkeypatch):
    def fake_packets(osv, stream):
        pk1_d1 = pack_msg(2, 0, 1000) # ts_us = 1000

        q_msg = b''
        for f, v in [(1, 1.0), (2, 0.0), (3, 0.0), (4, 0.0)]:
            q_msg += pack_msg(f, 5, struct.pack('<f', v))

        acc_msg = b''
        for f, v in [(2, 0.0), (3, 0.0), (4, 9.8)]:
            acc_msg += pack_msg(f, 5, struct.pack('<f', v))

        pk1_d2 = pack_msg(9, 2, q_msg) + pack_msg(10, 2, acc_msg)

        d1_msg = pack_msg(1, 2, pk1_d1)
        d2_msg = pack_msg(2, 2, pk1_d2)
        fm = pack_msg(3, 2, d1_msg + d2_msg)
        yield fm

    monkeypatch.setattr(telemetry, 'packets', fake_packets)

    out = telemetry.read_frames('test.osv')
    np.testing.assert_allclose(out['ts_us'], [1000])
    np.testing.assert_allclose(out['quat'], [[1.0, 0.0, 0.0, 0.0]])
    np.testing.assert_allclose(out['acc'], [[0.0, 0.0, 9.8]])


def test_video_pts(fake_run):
    fake_run.returns['ffprobe'] = b'0.1\n0.0\n0.2\n'
    pts = telemetry.video_pts('test.osv', 5)

    np.testing.assert_allclose(pts, [0.0, 0.1, 0.2])
    assert fake_run.calls[0] == ['ffprobe', '-v', 'error', '-select_streams', 'v:5', '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', 'test.osv']

def test_read_exposure(monkeypatch):
    def fake_packets(osv, stream):
        iso_inner = pack_msg(1, 5, struct.pack('<f', 100.0))
        iso_msg = pack_msg(3, 2, iso_inner)

        inner_val = b'\x01' + pack_varint(240)
        e4_val = pack_msg(1, 2, inner_val)
        shutter_msg = pack_msg(4, 2, e4_val)

        # e[6] w=2 is parsed in code: ct.append([v for f, w, v in parse(e[6])][0])
        # So e[6] is a message containing some field (let's say field 1) with varint value
        ct_inner = pack_msg(1, 0, 5600)
        ct_msg = pack_msg(6, 2, ct_inner)

        e_msg = iso_msg + shutter_msg + ct_msg
        b2_msg = pack_msg(2, 2, e_msg)
        fm = pack_msg(3, 2, b2_msg)

        yield fm

    monkeypatch.setattr(telemetry, 'packets', fake_packets)

    out = telemetry.read_exposure('test.osv')

    assert 'djmd3' in out
    assert 'djmd4' in out

    for name in ['djmd3', 'djmd4']:
        np.testing.assert_allclose(out[name]['iso'], [100.0])
        np.testing.assert_allclose(out[name]['shutter_den'], [240])
        np.testing.assert_allclose(out[name]['ct'], [5600])
