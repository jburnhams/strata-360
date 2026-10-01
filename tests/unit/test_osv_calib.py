import pytest
import struct
import numpy as np
from osv import build_varint, encode_field
from strata360.osv.calib import read_slots, quat_to_R, Lens, imu_offsets



def test_read_slots(fake_run):
    # build a slot message
    # slot format: 1=fx(5), 2=fy(5), 3=cx(5), 4=cy(5)
    # k: 5=k1, 6=k2, 7=k3, 8=k4, 15=k5 (all w=5)
    # q: 28=msg(w=2) -> fields 1..4=w=5 (w, x, y, z)
    # poly: 22=poly_x(w=2, len 56), 23=poly_y(w=2, len 56) -> packed 14 floats

    s = b''
    for i in range(1, 9):
        s += encode_field(i, 5, float(i))
    s += encode_field(15, 5, 15.0)

    q_msg = encode_field(1, 5, 1.0) + encode_field(2, 5, 0.0) + encode_field(3, 5, 0.0) + encode_field(4, 5, 0.0)
    s += encode_field(28, 2, q_msg)

    poly_x = struct.pack('<14f', *[float(i) for i in range(14)])
    s += encode_field(22, 2, poly_x)
    poly_y = struct.pack('<14f', *[float(10+i) for i in range(14)])
    s += encode_field(23, 2, poly_y)

    # Must be 264 bytes long
    pad_len = 264 - len(s) - 2
    pad_len -= 1; s += encode_field(100, 2, b'\x00' * pad_len)
    assert len(s) == 264

    # StreamMeta.6
    # f6 = encode_field(X, 2, s) for slot X
    f6 = encode_field(1, 2, s)
    sm = encode_field(6, 2, f6)

    # packet
    # StreamMeta is field 2 of the top packet
    pk = encode_field(2, 2, sm)

    fake_run.returns['ffmpeg'] = pk

    slots = read_slots('test.osv')
    assert len(slots) == 1
    d = slots[1]
    assert d[1] == 1.0
    assert d[15] == 15.0
    np.testing.assert_array_almost_equal(d['q'], [1.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_almost_equal(d['poly_x'], np.arange(14, dtype=np.float32))

def test_quat_to_R():
    # Identity
    R = quat_to_R([1, 0, 0, 0])
    np.testing.assert_array_almost_equal(R, np.eye(3))

    # Rotation by 180 degrees around X axis
    R = quat_to_R([0, 1, 0, 0])
    np.testing.assert_array_almost_equal(R, [[1, 0, 0], [0, -1, 0], [0, 0, -1]])

    # Non-normalized quat
    R2 = quat_to_R([0, 2, 0, 0])
    np.testing.assert_array_almost_equal(R2, [[1, 0, 0], [0, -1, 0], [0, 0, -1]])

def test_lens():
    slot = {
        1: 500.0, 2: 500.0, 3: 1920.0, 4: 1920.0,
        5: 0.1, 6: 0.0, 7: 0.0, 8: 0.0, 15: 0.0,
        'q': [1, 0, 0, 0]
    }
    lens = Lens(slot)

    # test project
    d_body = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    u, v, th = lens.project(d_body)

    assert len(u) == 2
    assert len(v) == 2
    assert len(th) == 2

    # test rim_radius
    r = lens.rim_radius(90)
    assert r > 0

    # test edge_theta
    th, r = lens.edge_theta()
    assert len(th) == 4000
    assert len(r) > 0

def test_imu_offsets(monkeypatch):
    import numpy as np
    import strata360.osv.calib
    mock_data = np.array([np.eye(3), np.eye(3)])
    monkeypatch.setattr(np, "load", lambda path: mock_data)
    offsets = imu_offsets()
    assert len(offsets) == 2
    assert offsets[0].shape == (3, 3)
