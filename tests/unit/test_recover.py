"""osv/recover.py: the pure parts of rebuilding a cut-short recording's index (sample boundaries, protobuf fields, the AAC split, box writing). The end-to-end run on real ffmpeg files is
tests/integration/test_recover.py; on the owner's footage, tests/integration/test_real_footage.py."""
import struct
import numpy as np
import pytest
from strata360.osv import recover as R


def nal(t, size, first=True, hevc=False):
    """A length-prefixed NAL unit of `size` payload bytes: H.264 header byte (type t, ref idc 3), or the two-byte HEVC header; then the slice's first bit (first slice / first macroblock)."""
    hdr = bytes([t << 1, 1]) if hevc else bytes([0x60 | t])
    body = bytes([0x80 if first else 0x00]) + b'\x11' * (size - 1)
    return struct.pack('>I', len(hdr) + len(body)) + hdr + body


def pb(field, payload): return bytes([field << 3 | 2, len(payload)]) + payload


def test_an_h264_frame_ends_where_the_next_picture_starts():
    b = np.frombuffer(nal(5, 50) + nal(1, 40) + b'\x21' * 8, np.uint8)
    assert R._video('h264', b, 0, len(b)) == (55, True)
    assert R._video('h264', b, 55, len(b)) == (55 + 45, False)                                   # stops at the audio byte (0x21: not a length prefix)


def test_an_hevc_frame_keeps_its_slices_and_parameter_sets_together():
    frame = nal(32, 10, hevc=True) + nal(33, 10, hevc=True) + nal(34, 10, hevc=True) + nal(19, 60, hevc=True) + nal(19, 60, first=False, hevc=True)
    nxt = nal(1, 30, hevc=True); b = np.frombuffer(frame + nxt, np.uint8)
    assert R._video('hevc', b, 0, len(b)) == (len(frame), True)
    assert R._video('hevc', b, len(frame), len(b)) == (len(b), False)


def test_a_slice_that_does_not_start_a_picture_is_not_a_frame_start():
    b = np.frombuffer(nal(1, 40, first=False), np.uint8)
    assert R._video('h264', b, 0, len(b)) is None


def test_protobuf_fields_are_counted_and_bad_ones_refused():
    b = np.frombuffer(pb(3, b'abc') + pb(1, b'xy') + bytes([0x08, 0x96, 0x01]), np.uint8)
    assert R._pb_fields(b, 0, 1) == 5 and R._pb_fields(b, 0, 2) == 9 and R._pb_fields(b, 0, 3) == 12
    assert R._pb_fields(np.frombuffer(bytes([0x07, 1]), np.uint8), 0, 1) is None                 # wire type 7 does not exist
    assert R._pb_fields(np.frombuffer(pb(3, b'abc')[:4], np.uint8), 0, 1) is None                 # runs past the end


def test_the_audio_config_is_read_from_the_esds():
    esds = b'esds' + b'\0' * 4 + bytes([3, 0x80, 0x80, 0x80, 0x22, 0, 0, 0]) + bytes([4, 0x80, 0x80, 0x80, 0x14]) + b'\x40\x15' + b'\0' * 11 + bytes([5, 0x80, 0x80, 0x80, 2, 0x11, 0x90])
    assert R._asc(b'\0' * 16 + esds) == b'\x11\x90'


class FakeTemplate:
    audio_range, audio_typical, audio_sig = (100, 1000), 300.0, 0x21


def walker(data, ok=lambda b: True):
    w = R.Walker.__new__(R.Walker); w.t, w.b, w._ok = FakeTemplate(), np.frombuffer(data, np.uint8), {}; w.aac = ok
    return w


def test_an_audio_run_is_cut_into_frames_of_the_wanted_number():
    run = b'\x21' + b'\x01' * 299 + b'\x21' + b'\x02' * 299
    assert walker(run)._split(0, 600, want=2) == [(0, 300), (300, 600)]
    assert walker(run)._split(0, 600, want=1) == [(0, 600)]
    assert walker(run)._split(0, 600, want=3) is None


def test_without_a_count_the_cut_nearest_the_typical_frame_size_wins_and_bad_frames_are_refused():
    run = b'\x21' + b'\x01' * 299 + b'\x21' + b'\x02' * 299
    assert walker(run)._split(0, 600) == [(0, 300), (300, 600)]
    assert walker(run, ok=lambda b: len(b) == 600)._split(0, 600) == [(0, 600)]                  # the decoder refuses the halves


def test_the_moov_gets_new_tables_durations_and_times():
    stsd = b'\0' * 16
    stbl = [('stsd', stsd), ('stts', struct.pack('>IIII', 0, 1, 10, 1001)), ('stss', struct.pack('>III', 0, 1, 1)), ('stsz', b''), ('stco', b'')]
    trak = [('tkhd', bytes(84)), ('mdia', [('mdhd', bytes(4) + bytes(8) + struct.pack('>II', 30000, 0) + bytes(4)), ('minf', [('stbl', stbl)])]), ('udta', b'x')]
    t = R.Template.__new__(R.Template); t.traks = [trak]; t.moov = [('mvhd', bytes(4) + bytes(8) + struct.pack('>II', 1000, 0) + bytes(80)), ('trak', trak), ('udta', b'template')]; t.hdr = {'mvhd': t.moov[0][1]}
    moov = R.build_moov(t, {0: [(48, 10), (58, 20), (78, 5)]}, {0: [True, False, True]}, when=0)
    assert moov[4:8] == b'moov' and b'udta' not in moov and b'co64' in moov
    i = moov.index(b'stsz'); assert struct.unpack('>III', moov[i + 8:i + 20]) == (0, 3, 10)
    i = moov.index(b'stss'); assert struct.unpack('>II', moov[i + 8:i + 16]) == (2, 1)
    i = moov.index(b'mvhd'); assert struct.unpack('>I', moov[i + 8:i + 12])[0] == R.MAC_EPOCH and struct.unpack('>I', moov[i + 20:i + 24])[0] == 3 * 1001 * 1000 // 30000


@pytest.mark.parametrize('name, role', [('VID_20221002_145905_00_224.insv', ('x3', '00')), ('VID_20221002_145905_10_224.insv', ('x3', '10')), ('LRV_20221002_145905_11_224.lrv', ('x3', '11')),
                                        ('CAM_20260726113908_0056_D.OSV', ('dji', 'osv')), ('CAM_20260726113908_0056_D.LRF', ('dji', 'lrf')), ('notes.txt', None)])
def test_files_are_matched_with_templates_of_their_own_kind(name, role):
    assert R._role(name) == role
