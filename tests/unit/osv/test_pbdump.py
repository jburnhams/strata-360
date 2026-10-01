import pytest
import struct
from strata360.osv import pbdump

def test_varint():
    assert pbdump.varint(b'\x00', 0) == (0, 1)
    assert pbdump.varint(b'\x01', 0) == (1, 1)
    assert pbdump.varint(b'\x7f', 0) == (127, 1)
    assert pbdump.varint(b'\x80\x01', 0) == (128, 2)
    assert pbdump.varint(b'\xac\x02', 0) == (300, 2)

    with pytest.raises(ValueError, match="eof"):
        pbdump.varint(b'\x80', 0)

    with pytest.raises(ValueError, match="varint"):
        pbdump.varint(b'\x80' * 11 + b'\x00', 0)


def test_parse_success():
    assert pbdump.parse(b'\x08\x96\x01') == [(1, 0, 150)]
    assert pbdump.parse(b'\x11\x00\x00\x00\x00\x00\x00\xf0?') == [(2, 1, b'\x00\x00\x00\x00\x00\x00\xf0?')]
    assert pbdump.parse(b'\x1d\x00\x00\x80?') == [(3, 5, b'\x00\x00\x80?')]
    assert pbdump.parse(b'\x22\x03abc') == [(4, 2, b'abc')]


def test_parse_errors():
    with pytest.raises(ValueError, match="field"):
        pbdump.parse(b'\x00') # field 0

    with pytest.raises(ValueError, match="eof"):
        pbdump.parse(b'\x80\xfa\x01') # truncated field 4000

    with pytest.raises(ValueError, match="wire"):
        pbdump.parse(b'\x0b') # field 1, type 3 (deprecated groups)

    with pytest.raises(ValueError, match="trunc"):
        pbdump.parse(b'\x11\x00\x00\x00') # w=1 but only 4 bytes

    with pytest.raises(ValueError, match="trunc"):
        pbdump.parse(b'\x1d\x00\x00') # w=5 but only 3 bytes

    with pytest.raises(ValueError, match="trunc"):
        pbdump.parse(b'\x22\x03ab') # w=2 len 3 but only 2 bytes


def test_try_msg():
    assert pbdump.try_msg(b'\x08\x01') == [(1, 0, 1)]
    assert pbdump.try_msg(b'\x00') is None # invalid msg
    assert pbdump.try_msg(b'a') is None # too short


def test_show():
    b = b'\x08\x96\x01'
    b += b'\x11' + struct.pack('<d', 1.0)
    b += b'\x1d' + struct.pack('<f', 2.0)
    b += b'\x22\x05hello'

    sub = b'\x08\x02'
    b += b'\x2a' + struct.pack('B', len(sub)) + sub

    p32 = struct.pack('<3f', 1.0, 2.0, 3.0)
    b += b'\x32' + struct.pack('B', len(p32)) + p32

    p64 = struct.pack('<2d', 1.0, 2.0)
    b += b'\x3a' + struct.pack('B', len(p64)) + p64

    b += b'\x42\x04\xff\xff\xff\xff'

    lines = pbdump.show(b)

    assert lines == [
        '1: 150',
        '2: f64 1',
        '3: f32 2  (i32 1073741824)',
        "4: 'hello'",
        '5: msg(2)',
        '  1: 2',
        '6: packed f32[3] 1 2 3',
        '7: packed f64[2] 1 2',
        '8: bytes(4) ffffffff'
    ]

def test_first_packet(fake_run):
    fake_run.returns['ffmpeg'] = b'packet1'
    assert pbdump.first_packet('test.osv', 3) == b'packet1'
    assert fake_run.calls[0] == ['ffmpeg', '-v', 'error', '-i', 'test.osv', '-map', '0:3', '-c', 'copy', '-frames:d', '1', '-f', 'data', '-']

def test_packets(fake_run):
    fake_run.returns['ffprobe'] = b'4\n5\n'
    fake_run.returns['ffmpeg'] = b'1234abcde'

    p = list(pbdump.packets('test.osv', 3))

    assert p == [b'1234', b'abcde']

    assert fake_run.calls[0] == ['ffprobe', '-v', 'error', '-select_streams', '3', '-show_entries', 'packet=size', '-of', 'csv=p=0', 'test.osv']
    assert fake_run.calls[1] == ['ffmpeg', '-v', 'error', '-i', 'test.osv', '-map', '0:3', '-c', 'copy', '-f', 'data', '-']
