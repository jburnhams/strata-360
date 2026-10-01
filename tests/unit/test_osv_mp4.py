import pytest
import struct
import io
import numpy as np
from strata360.osv.mp4 import _boxes, _find, _u32, video_sample_times

def create_box(typ, data=b''):
    assert len(typ) == 4
    if isinstance(typ, str):
        typ = typ.encode('latin1')
    size = 8 + len(data)
    return struct.pack('>I4s', size, typ) + data

def test_boxes():
    data = create_box('moov', b'1234') + create_box('mdat', b'56789')
    f = io.BytesIO(data)
    boxes = list(_boxes(f, 0, len(data)))
    assert len(boxes) == 2
    assert boxes[0] == ('moov', 8, 12)
    assert boxes[1] == ('mdat', 20, 25)

    # test extended size
    extended_size = struct.pack('>I4sQ', 1, b'larg', 20) + b'1234'
    f = io.BytesIO(extended_size)
    boxes = list(_boxes(f, 0, len(extended_size)))
    assert len(boxes) == 1
    assert boxes[0] == ('larg', 16, 20)

    # test zero size (to end of file)
    zero_size = struct.pack('>I4s', 0, b'zero') + b'1234'
    f = io.BytesIO(zero_size)
    boxes = list(_boxes(f, 0, len(zero_size)))
    assert len(boxes) == 1
    assert boxes[0] == ('zero', 8, 12)

    # invalid size too short
    f = io.BytesIO(struct.pack('>I4s', 4, b'shor'))
    boxes = list(_boxes(f, 0, 8))
    assert len(boxes) == 0

def test_find():
    inner = create_box('in1 ', b'in') + create_box('in2 ', b'ner')
    outer = create_box('moov', create_box('trak', inner))
    f = io.BytesIO(outer)

    res = _find(f, 0, len(outer), ['moov'])
    assert res is not None
    assert res[1] - res[0] == len(outer) - 8 # contents of moov

    res = _find(f, 0, len(outer), ['moov', 'trak', 'in2 '])
    assert res is not None
    f.seek(res[0])
    assert f.read(res[1] - res[0]) == b'ner'

    res = _find(f, 0, len(outer), ['moov', 'notr'])
    assert res is None

def test_u32():
    b = struct.pack('>I', 42)
    assert _u32(b, 0) == 42
    b = b'\x00' * 10 + struct.pack('>I', 314)
    assert _u32(b, 10) == 314

def test_video_sample_times_no_moov(tmp_path):
    p = tmp_path / "test.mp4"
    p.write_bytes(create_box('mdat', b'1234'))
    with pytest.raises(ValueError, match='no moov box'):
        video_sample_times(str(p))

def test_video_sample_times_no_video_track(tmp_path):
    p = tmp_path / "test.mp4"
    hdlr = create_box('hdlr', b'\x00'*8 + b'soun' + b'\x00'*4)
    mdia = create_box('mdia', hdlr)
    trak = create_box('trak', mdia)
    moov = create_box('moov', trak)
    p.write_bytes(moov)
    with pytest.raises(ValueError, match='no video track'):
        video_sample_times(str(p))

def test_video_sample_times_valid(tmp_path):
    p = tmp_path / "test.mp4"

    hdlr = create_box('hdlr', b'\x00'*8 + b'vide' + b'\x00'*4)

    # mdhd version 0
    # timescale offset 12 in body
    mdhd_body = b'\x00' * 12 + struct.pack('>I', 30000) + b'\x00' * 4
    mdhd = create_box('mdhd', mdhd_body)

    # stts: version/flags(4), count(4), [count(4), duration(4)]
    stts_body = b'\x00'*4 + struct.pack('>I', 2) + struct.pack('>II', 10, 1000) + struct.pack('>II', 5, 2000)
    stts = create_box('stts', stts_body)

    stbl = create_box('stbl', stts)
    minf = create_box('minf', stbl)
    mdia = create_box('mdia', hdlr + mdhd + minf)
    trak = create_box('trak', mdia)
    moov = create_box('moov', trak)

    p.write_bytes(moov)

    times = video_sample_times(str(p))
    assert len(times) == 15
    assert times[0] == pytest.approx(0)
    assert times[1] == pytest.approx(1000 / 30000)
    assert times[10] == pytest.approx(10000 / 30000)
    assert times[11] == pytest.approx(12000 / 30000)
    assert times[14] == pytest.approx(18000 / 30000)

def test_video_sample_times_with_ctts(tmp_path):
    p = tmp_path / "test.mp4"

    hdlr = create_box('hdlr', b'\x00'*8 + b'vide' + b'\x00'*4)

    # mdhd version 1 (timescale at 20)
    mdhd_body = b'\x01' + b'\x00' * 19 + struct.pack('>I', 30000) + b'\x00' * 4
    mdhd = create_box('mdhd', mdhd_body)

    # 2 frames, 1000 duration each
    stts_body = b'\x00'*4 + struct.pack('>I', 1) + struct.pack('>II', 2, 1000)
    stts = create_box('stts', stts_body)

    # ctts version 1: offset is signed
    # frame 0 offset = 500, frame 1 offset = -500 (represented as 2^32 - 500)
    neg_offset = (1<<32) - 500
    ctts_body = b'\x01\x00\x00\x00' + struct.pack('>I', 2) + struct.pack('>II', 1, 500) + struct.pack('>II', 1, neg_offset)
    ctts = create_box('ctts', ctts_body)

    stbl = create_box('stbl', stts + ctts)
    minf = create_box('minf', stbl)
    mdia = create_box('mdia', hdlr + mdhd + minf)
    trak = create_box('trak', mdia)
    moov = create_box('moov', trak)

    p.write_bytes(moov)

    times = video_sample_times(str(p))
    assert len(times) == 2
    # dts: [0, 1000]
    # pts: [500, 1000 - 500] = [500, 500]
    assert times[0] == pytest.approx(500 / 30000)
    assert times[1] == pytest.approx(500 / 30000)
