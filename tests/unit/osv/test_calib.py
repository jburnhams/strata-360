import pytest
import struct
import numpy as np
from strata360.osv import calib
from pbdump_fakes import pack_msg, pack_varint

def test_read_slots(monkeypatch):
    # Construct a valid slot (264 bytes)
    # Fields to populate (ww=5 is i32/f32):
    # 1,2,3,4: fx, fy, cx, cy
    # 5,6,7,8,15: k1..k5
    # 22, 23: poly_x, poly_y (56 bytes each, ww=2)
    # 28: q (ww=2) -> fields 1..4 (ww=5)

    slot_data = b''
    for f, v in [(1, 1000.0), (2, 1000.0), (3, 500.0), (4, 500.0),
                 (5, 0.1), (6, 0.2), (7, 0.3), (8, 0.4), (15, 0.5)]:
        slot_data += pack_msg(f, 5, struct.pack('<f', v))

    poly_data = struct.pack('<14f', *(float(i) for i in range(14)))
    slot_data += pack_msg(22, 2, poly_data)
    slot_data += pack_msg(23, 2, poly_data)

    q_data = b''
    for a, v in [(1, 1.0), (2, 0.0), (3, 0.0), (4, 0.0)]:
        q_data += pack_msg(a, 5, struct.pack('<f', v))
    slot_data += pack_msg(28, 2, q_data)

    # Pad to exactly 264 bytes
    pad_len = 264 - len(slot_data)
    if pad_len > 0:
        # We can add a dummy field (e.g. field 99, w=2) that will take pad_len bytes
        # wire 2 header is 1 varint for key, 1 varint for len.
        # let's just make it a raw byte buffer, not properly formatted, wait, it must parse!
        # key = 99 << 3 | 2 = 794. Varint is 2 bytes.
        # Length varint is 1-2 bytes.
        # Let's manually construct a w=2 field to pad.
        key = pack_varint((99 << 3) | 2)
        val_len = pad_len - len(key) - 1 # assuming 1 byte varint for len
        if val_len > 127:
            val_len = pad_len - len(key) - 2
        slot_data += key + pack_varint(val_len) + (b'\x00' * val_len)

    assert len(slot_data) == 264

    f6_inner = pack_msg(1, 2, slot_data) # slot 1
    sm = pack_msg(6, 2, f6_inner)
    top = pack_msg(2, 2, sm)

    monkeypatch.setattr(calib, 'first_packet', lambda o, s: top)

    slots = calib.read_slots('test.osv')
    assert 1 in slots
    s = slots[1]
    assert s[1] == 1000.0
    assert s[15] == 0.5
    np.testing.assert_allclose(s['poly_x'], np.arange(14))
    np.testing.assert_allclose(s['q'], [1.0, 0.0, 0.0, 0.0])

def test_quat_to_R():
    # Identity
    R = calib.quat_to_R([1, 0, 0, 0])
    np.testing.assert_allclose(R, np.eye(3))

    # 90 deg around Z -> w = cos(45), z = sin(45)
    w = np.cos(np.pi/4)
    z = np.sin(np.pi/4)
    R = calib.quat_to_R([w, 0, 0, z])
    expected = np.array([
        [0, -1, 0],
        [1,  0, 0],
        [0,  0, 1]
    ])
    np.testing.assert_allclose(R, expected, atol=1e-7)

def test_imu_offsets():
    # Should just load the file successfully
    m = calib.imu_offsets()
    assert m.shape[0] == 2 # (P, B) typically

def test_lens():
    slot = {
        1: 1000.0, 2: 1000.0, 3: 500.0, 4: 500.0,
        5: 0.0, 6: 0.0, 7: 0.0, 8: 0.0, 15: 0.0, # no distortion for easy test
        'q': np.array([1.0, 0.0, 0.0, 0.0])
    }
    lens = calib.Lens(slot)

    assert lens.fx == 1000.0
    np.testing.assert_allclose(lens.k, np.zeros(5))

    # Project a point
    d_body = np.array([[0.0, 0.0, 1.0]]) # Looks straight ahead (Z axis).
    # wait, the code uses th = np.arccos(d[:, 2]), phi = np.arctan2(d[:, 1], d[:, 0])
    # Z=1 -> th = 0.
    # u = cx + fx*thd*cos(phi) = 500
    # v = cy + fy*thd*sin(phi) = 500
    u, v, th = lens.project(d_body)
    np.testing.assert_allclose(u, [500.0])
    np.testing.assert_allclose(v, [500.0])
    np.testing.assert_allclose(th, [0.0])

    # Rim radius
    r = lens.rim_radius(90.0) # pi/2
    assert np.isclose(r, 1000.0 * (np.pi / 2.0))

    # Edge theta
    th_arr, r_arr = lens.edge_theta()
    assert th_arr.shape == (4000,)
    assert r_arr.shape == (4000,)
