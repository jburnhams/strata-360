import pytest
import io
import struct
import numpy as np
from strata360.osv import mp4

def make_box(typ, payload):
    btyp = typ.encode('latin1')
    return struct.pack('>I4s', len(payload) + 8, btyp) + payload

def make_large_box(typ, payload):
    btyp = typ.encode('latin1')
    return struct.pack('>I4sQ', 1, btyp, len(payload) + 16) + payload

def make_until_eof_box(typ, payload):
    btyp = typ.encode('latin1')
    return struct.pack('>I4s', 0, btyp) + payload

def test_boxes():
    data = make_box('ftyp', b'iso5') + make_large_box('mdat', b'1234') + make_until_eof_box('moov', b'abcd')
    f = io.BytesIO(data)
    boxes = list(mp4._boxes(f, 0, len(data)))
    assert boxes == [
        ('ftyp', 8, 12),
        ('mdat', 28, 32), # 12 + 16 = 28
        ('moov', 40, 44)  # 32 + 8 = 40
    ]

    # Error cases: truncated
    f = io.BytesIO(b'\x00\x00\x00\x08ft') # only 6 bytes
    assert list(mp4._boxes(f, 0, 6)) == []

    f = io.BytesIO(b'\x00\x00\x00\x05ftyp') # length < hdr_len
    assert list(mp4._boxes(f, 0, 8)) == []


def test_find():
    moov_payload = make_box('trak', make_box('tkhd', b'a') + make_box('mdia', make_box('mdhd', b'b')))
    data = make_box('mdat', b'x') + make_box('moov', moov_payload)

    f = io.BytesIO(data)
    assert mp4._find(f, 0, len(data), ['moov']) == (9 + 8, len(data))

    moov_s = 17
    assert mp4._find(f, 0, len(data), ['moov', 'trak']) == (moov_s + 8, moov_s + 8 + len(moov_payload) - 8)
    assert mp4._find(f, 0, len(data), ['moov', 'trak', 'mdia', 'mdhd']) is not None
    assert mp4._find(f, 0, len(data), ['moov', 'nope']) is None


def test_u32():
    assert mp4._u32(b'\x00\x00\x00\x00', 0) == 0
    assert mp4._u32(b'\x00\x00\x01\x00', 0) == 256
    assert mp4._u32(b'\xff\xff\xff\xff', 0) == 4294967295


def write_video(tmp_path, timescale=1000, version=0, ctts_version=None, empty_stts=False):
    if version == 0:
        mdhd_payload = b'\x00\x00\x00\x00' + b'\x00\x00\x00\x00' + b'\x00\x00\x00\x00' + struct.pack('>I', timescale) + b'\x00' * 8
    else:
        mdhd_payload = b'\x01\x00\x00\x00' + b'\x00\x00\x00\x00\x00\x00\x00\x00' + b'\x00\x00\x00\x00\x00\x00\x00\x00' + struct.pack('>I', timescale) + b'\x00' * 8

    if empty_stts:
        stts_payload = b'\x00\x00\x00\x00' + struct.pack('>I', 0)
    else:
        stts_payload = b'\x00\x00\x00\x00' + struct.pack('>I', 1) + struct.pack('>II', 3, 100)

    if ctts_version is not None:
        if ctts_version == 0:
            ctts_payload = b'\x00\x00\x00\x00' + struct.pack('>I', 2) + struct.pack('>II', 1, 50) + struct.pack('>II', 2, 0)
        else:
            ctts_payload = b'\x01\x00\x00\x00' + struct.pack('>I', 2) + struct.pack('>II', 1, 2**32 - 50) + struct.pack('>II', 2, 0)
    else:
        ctts_payload = b''

    stbl_payload = make_box('stts', stts_payload)
    if ctts_payload: stbl_payload += make_box('ctts', ctts_payload)

    minf_payload = make_box('stbl', stbl_payload)

    hdlr_payload = b'\x00' * 8 + b'vide' + b'\x00' * 12
    mdia_payload = make_box('mdhd', mdhd_payload) + make_box('hdlr', hdlr_payload) + make_box('minf', minf_payload)
    trak_payload = make_box('mdia', mdia_payload)

    hdlr_audio_payload = b'\x00' * 8 + b'soun' + b'\x00' * 12
    trak_audio_payload = make_box('mdia', make_box('hdlr', hdlr_audio_payload))

    moov_payload = make_box('trak', trak_audio_payload) + make_box('trak', trak_payload)

    p = tmp_path / "test.mp4"
    p.write_bytes(make_box('moov', moov_payload))
    return p

def test_video_sample_times_basic(tmp_path):
    p = write_video(tmp_path, timescale=1000)
    pts = mp4.video_sample_times(str(p))
    np.testing.assert_allclose(pts, [0.0, 0.1, 0.2])

def test_video_sample_times_v1(tmp_path):
    p = write_video(tmp_path, timescale=1000, version=1)
    pts = mp4.video_sample_times(str(p))
    np.testing.assert_allclose(pts, [0.0, 0.1, 0.2])

def test_video_sample_times_ctts_v0(tmp_path):
    p = write_video(tmp_path, timescale=1000, ctts_version=0)
    pts = mp4.video_sample_times(str(p))
    np.testing.assert_allclose(pts, [0.05, 0.1, 0.2])

def test_video_sample_times_ctts_v1(tmp_path):
    p = write_video(tmp_path, timescale=1000, ctts_version=1)
    pts = mp4.video_sample_times(str(p))
    np.testing.assert_allclose(pts, [-0.05, 0.1, 0.2])

def test_video_sample_times_empty_stts(tmp_path):
    p = write_video(tmp_path, empty_stts=True)
    pts = mp4.video_sample_times(str(p))
    assert len(pts) == 0

def test_video_sample_times_errors(tmp_path):
    p = tmp_path / "bad.mp4"
    p.write_bytes(b'moov is missing')
    with pytest.raises(ValueError, match="no moov box"):
        mp4.video_sample_times(str(p))

    p.write_bytes(make_box('moov', make_box('notrak', b'')))
    with pytest.raises(ValueError, match="no video track"):
        mp4.video_sample_times(str(p))
