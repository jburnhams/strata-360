import struct
import pytest
from strata360.osv.pbdump import varint, parse, try_msg, show, first_packet, packets
from osv import build_varint, encode_field



def test_varint():
    assert varint(b'\x00', 0) == (0, 1)
    assert varint(b'\x01', 0) == (1, 1)
    assert varint(b'\x7f', 0) == (127, 1)
    assert varint(b'\x81\x01', 0) == (129, 2)
    assert varint(build_varint(300), 0) == (300, 2)
    assert varint(b'\x80\x80\x01', 0) == (16384, 3)

    with pytest.raises(ValueError, match="eof"):
        varint(b'', 0)
    with pytest.raises(ValueError, match="eof"):
        varint(b'\x81', 0)
    with pytest.raises(ValueError, match="varint"):
        varint(b'\x80' * 11, 0)

def test_parse():
    b = encode_field(1, 0, 150)
    assert parse(b) == [(1, 0, 150)]

    b = encode_field(2, 1, 3.14159)
    res = parse(b)
    assert res[0][0] == 2
    assert res[0][1] == 1
    assert struct.unpack('<d', res[0][2])[0] == pytest.approx(3.14159)

    b = encode_field(3, 5, 2.718)
    res = parse(b)
    assert res[0][0] == 3
    assert res[0][1] == 5
    assert struct.unpack('<f', res[0][2])[0] == pytest.approx(2.718)

    b = encode_field(4, 2, b'hello')
    assert parse(b) == [(4, 2, b'hello')]

    b = encode_field(1, 0, 10) + encode_field(2, 2, b'world')
    assert parse(b) == [(1, 0, 10), (2, 2, b'world')]

    with pytest.raises(ValueError, match="field"):
        parse(encode_field(0, 0, 1))
    with pytest.raises(ValueError, match="field"):
        parse(encode_field(4001, 0, 1))

    with pytest.raises(ValueError, match="trunc"):
        parse(bytes([ (1<<3)|1, 0, 0, 0 ])) # w=1 expects 8 bytes
    with pytest.raises(ValueError, match="trunc"):
        parse(bytes([ (1<<3)|5, 0, 0 ])) # w=5 expects 4 bytes
    with pytest.raises(ValueError, match="trunc"):
        parse(bytes([ (1<<3)|2, 5, 1, 2, 3 ])) # w=2 length 5, but 3 given

    with pytest.raises(ValueError, match="wire"):
        parse(bytes([ (1<<3)|3 ])) # Invalid wire type

def test_try_msg():
    b = encode_field(1, 0, 10)
    assert try_msg(b) == [(1, 0, 10)]
    assert try_msg(b'\x00') is None # ValueError on parse
    assert try_msg(b'A') is None # too short < 2

def test_show():
    # w=0
    b = encode_field(1, 0, 150)
    assert show(b) == ["1: 150"]

    # w=5 (f32)
    b = encode_field(2, 5, struct.unpack('<f', struct.pack('<i', 42))[0])
    lines = show(b)
    assert "2: f32" in lines[0]

    # w=1 (f64)
    b = encode_field(3, 1, 3.14159)
    assert "3: f64 3.14159" in show(b)[0]

    # w=2 string
    b = encode_field(4, 2, b'hello')
    assert show(b) == ["4: 'hello'"]

    # w=2 nested msg
    inner = encode_field(1, 0, 42)
    b = encode_field(5, 2, inner)
    assert show(b) == ["5: msg(2)", "  1: 42"]

    # maxd limit
    assert show(b, ind=0, maxd=0) == ["5: bytes(2) 082a"]

    # w=2 packed f64
    packed_d = struct.pack('<16d', *[float(i) for i in range(16)])
    b = encode_field(6, 2, packed_d)
    assert "6: packed f64[16]" in show(b)[0]

    # w=2 packed f32
    packed_f = struct.pack('<10f', *[123.456 + i for i in range(10)])
    b = encode_field(7, 2, packed_f)
    assert "7: packed f32[10]" in show(b)[0]

def test_first_packet(fake_run):
    fake_run.returns['ffmpeg'] = b'packet_data'
    assert first_packet('test.osv', 3) == b'packet_data'
    assert fake_run.calls[0] == ['ffmpeg', '-v', 'error', '-i', 'test.osv', '-map', '0:3', '-c', 'copy', '-frames:d', '1', '-f', 'data', '-']

def test_packets(fake_run):
    fake_run.returns['ffprobe'] = b'5\n6\n'
    fake_run.returns['ffmpeg'] = b'12345abcdef'

    res = list(packets('test.osv', 3))
    assert len(res) == 2
    assert res[0] == b'12345'
    assert res[1] == b'abcdef'

    assert fake_run.calls[0][:6] == ['ffprobe', '-v', 'error', '-select_streams', '3', '-show_entries']
    assert fake_run.calls[1] == ['ffmpeg', '-v', 'error', '-i', 'test.osv', '-map', '0:3', '-c', 'copy', '-f', 'data', '-']
