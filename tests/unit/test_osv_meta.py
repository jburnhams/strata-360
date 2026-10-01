import pytest
import struct
import numpy as np
from tests.utils.osv import build_varint, encode_field
from strata360.osv.meta import header, frame_gaps, COLOUR_MODES



def test_header(fake_run, monkeypatch):
    import strata360.osv.meta
    # disable read_slots just for testing standard fields, we test it below properly if needed
    monkeypatch.setattr(strata360.osv.meta, 'read_slots', lambda o, s: {0: {1: 1}, 1: {}})

    # top 1 (Device block), outer 1, h 1/10/6/5
    h = encode_field(1, 2, b'PROTO') + encode_field(10, 2, b'DEV1') + encode_field(6, 2, b'V1.0') + encode_field(5, 2, b'SN123')
    outer = encode_field(1, 2, h)
    f1 = encode_field(1, 2, outer)

    # top 2 (StreamMeta), field 4
    # raw colour mode = 19 (DLOGM) inside a nested message
    inner = encode_field(1, 0, 19)
    sm = encode_field(4, 2, inner)
    f2 = encode_field(2, 2, sm)

    fake_run.returns['ffmpeg'] = f1 + f2

    out = header('test.osv')
    assert out['proto'] == 'PROTO'
    assert out['device'] == 'DEV1'
    assert out['firmware'] == 'V1.0'
    assert out['serial'] == 'SN123'
    assert out['colour_mode_raw'] == 19
    assert out['colour_mode'] == 'dlogm'
    assert out['calibration_slots'] == 1

def test_header_fallback(fake_run):
    # Empty packet
    fake_run.returns['ffmpeg'] = b''
    out = header('test.osv')
    assert out['device'] is None
    assert out['colour_mode'] == 'unknown'
    assert out['colour_mode_raw'] is None
    assert out['calibration_slots'] == 0

def test_header_w0_colour(fake_run):
    # Test flat varint for colour mode
    sm = encode_field(4, 0, 9) # 9 = hlg
    f2 = encode_field(2, 2, sm)
    fake_run.returns['ffmpeg'] = f2
    out = header('test.osv')
    assert out['colour_mode'] == 'hlg'
    assert out['colour_mode_raw'] == 9

def test_frame_gaps():
    pts = [0.0, 0.1, 0.2, 0.4, 0.5] # gap between 0.2 and 0.4 (nominal 0.1)
    gaps, nominal = frame_gaps(pts)
    assert nominal == pytest.approx(0.1)
    assert len(gaps) == 1
    assert gaps[0] == (2, 0.2, 1) # index 2 is pts=0.2, missing 1 frame before next

    pts = [0.0, 0.033, 0.066, 0.099, 0.132, 0.231] # nominal 0.033, gap of ~3 frames
    gaps, nominal = frame_gaps(pts)
    assert nominal == pytest.approx(0.033)
    assert len(gaps) == 1
    assert gaps[0] == (4, 0.132, 2) # dt is ~0.099, which is 3 nominal, so 2 missing
