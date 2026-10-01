import pytest
import numpy as np
from strata360.osv import meta
from pbdump_fakes import pack_msg

def test_frame_gaps():
    pts = [0.0, 0.1, 0.2, 0.4, 0.5] # nominal 0.1, gap at idx 2
    gaps, nom = meta.frame_gaps(pts)
    assert np.isclose(nom, 0.1)
    assert gaps == [(2, 0.2, 1)] # at frame 2, missing 1 frame

def test_header_basic(monkeypatch):
    def fake_first(osv, stream):
        # Empty message
        return b''

    monkeypatch.setattr(meta, 'first_packet', fake_first)

    # Should handle missing fields gracefully
    out = meta.header('test.osv')
    assert out['device'] is None
    assert out['colour_mode'] == 'unknown'
    assert out['calibration_slots'] == 0

def test_header_full(monkeypatch):
    # Construct a valid first packet
    # Field 1 (header message)
    #   Field 1 (outer)
    #     Field 1 (h)
    #       proto (1) = b'proto'
    #       serial (5) = b'serial'
    #       firmware (6) = b'fw'
    #       device (10) = b'dev'
    h_msg = pack_msg(1, 2, b'proto') + pack_msg(5, 2, b'serial') + pack_msg(6, 2, b'fw') + pack_msg(10, 2, b'dev')
    outer_msg = pack_msg(1, 2, h_msg)
    top_field_1 = pack_msg(1, 2, outer_msg)

    # Field 2 (StreamMeta)
    #   Field 4 (colour mode)
    #     as varint (w=0), e.g. 9 for hlg
    sm_msg = pack_msg(4, 0, 9)
    top_field_2 = pack_msg(2, 2, sm_msg)

    def fake_first(osv, stream):
        return top_field_1 + top_field_2

    def fake_read_slots(osv, stream):
        return {1: {1: 1.0}, 2: {1: 0}, 3: {}}

    monkeypatch.setattr(meta, 'first_packet', fake_first)
    monkeypatch.setattr(meta, 'read_slots', fake_read_slots)

    out = meta.header('test.osv')
    assert out['proto'] == 'proto'
    assert out['serial'] == 'serial'
    assert out['firmware'] == 'fw'
    assert out['device'] == 'dev'
    assert out['colour_mode'] == 'hlg'
    assert out['colour_mode_raw'] == 9
    assert out['calibration_slots'] == 1 # only slot 1 has non-zero field 1

def test_header_colour_modes(monkeypatch):
    def fake_first(osv, stream):
        # colour mode 19 as varint
        return pack_msg(2, 2, pack_msg(4, 0, 19))
    monkeypatch.setattr(meta, 'first_packet', fake_first)
    monkeypatch.setattr(meta, 'read_slots', lambda o, s: {})
    out = meta.header('test.osv')
    assert out['colour_mode'] == 'dlogm'

    # Nested colour mode format (w=2)
    def fake_first_nested(osv, stream):
        # field 4 w=2 -> inner msg with varint field ? (next(iv for _, iw, iv in inner if iw == 0))
        # let's say field 1 w=0 value 0 (normal)
        inner = pack_msg(1, 0, 0)
        return pack_msg(2, 2, pack_msg(4, 2, inner))
    monkeypatch.setattr(meta, 'first_packet', fake_first_nested)
    out = meta.header('test.osv')
    assert out['colour_mode'] == 'normal'

    # Missing field 4 inside StreamMeta (default normal)
    def fake_first_empty_sm(osv, stream):
        return pack_msg(2, 2, b'')
    monkeypatch.setattr(meta, 'first_packet', fake_first_empty_sm)
    out = meta.header('test.osv')
    assert out['colour_mode'] == 'normal'
