"""Spherical video metadata (render/spherical.py) on hand-built MP4 box trees: the V1 and V2 boxes in the video track only, sizes kept consistent, chunk offsets moved when the moov is before the media, marking twice is marking once."""
import struct

import pytest

from strata360.render import spherical as SP


def sample_table(kind, offsets):
    entry = SP.box(kind, b'\x00' * SP.SAMPLE_ENTRY_HEADER + SP.box('hvcC' if kind == 'hvc1' else 'esds', b'cfg'))
    stsd = SP.box('stsd', struct.pack('>II', 0, 1) + entry); stco = SP.box('stco', struct.pack('>II', 0, len(offsets)) + b''.join(struct.pack('>I', o) for o in offsets))
    return SP.box('stbl', stsd + stco)


def trak(handler, kind, offsets):
    hdlr = SP.box('hdlr', b'\x00' * 8 + handler + b'\x00' * 12)
    return SP.box('trak', SP.box('tkhd', b'\x00' * 84) + SP.box('mdia', SP.box('mdhd', b'\x00' * 24) + hdlr + SP.box('minf', sample_table(kind, offsets))))


def mp4(path, faststart):
    ftyp = SP.box('ftyp', b'isom\x00\x00\x02\x00'); mdat = SP.box('mdat', b'V' * 40 + b'A' * 40)
    def moov(base): return SP.box('moov', SP.box('mvhd', b'\x00' * 100) + trak(b'vide', 'hvc1', [base + 8]) + trak(b'soun', 'mp4a', [base + 48]))
    size = len(moov(0))
    data = ftyp + moov(len(ftyp) + size) + mdat if faststart else ftyp + mdat + moov(len(ftyp))
    path.write_bytes(data); return path


def media(path):
    """{track handler: the 4 bytes at its chunk offset} read through the file's own tables."""
    buf = path.read_bytes(); top = SP.parse(buf); moov = next(b for b in top if b.typ == 'moov'); out = {}
    for t in moov.find('trak'):
        md = t.find('mdia')[0]; h = md.find('hdlr')[0].data[8:12]; stco = md.find('minf')[0].find('stbl')[0].find('stco')[0]; off = struct.unpack('>I', stco.data[8:12])[0]; out[h] = buf[off:off + 4]
    return out


@pytest.mark.parametrize('faststart', [True, False])
def test_the_video_track_is_marked_and_the_media_still_found(tmp_path, faststart):
    f = mp4(tmp_path / 'a.mp4', faststart); before = media(f)
    assert before == {b'vide': b'VVVV', b'soun': b'AAAA'} and not SP.is_marked(str(f))
    SP.inject(str(f))
    assert SP.is_marked(str(f)) and media(f) == before
    moov = next(b for b in SP.parse(f.read_bytes()) if b.typ == 'moov'); video, audio = moov.find('trak')
    assert [k.typ for k in video.kids][-1] == 'uuid' and SP.V1_UUID in video.kids[-1].data and b'equirectangular' in video.kids[-1].data
    entry = video.find('mdia')[0].find('minf')[0].find('stbl')[0].find('stsd')[0].kids[0]
    assert [k.typ for k in entry.kids] == ['hvcC', 'st3d', 'sv3d']
    assert not any(k.typ == 'uuid' for k in audio.kids)


def test_marking_twice_is_marking_once(tmp_path):
    f = mp4(tmp_path / 'a.mp4', True); SP.inject(str(f)); once = f.read_bytes(); SP.inject(str(f))
    assert f.read_bytes() == once


def test_the_v2_boxes_say_mono_equirectangular():
    st3d, sv3d = SP.parse(SP.v2_boxes())
    assert st3d.data == b'\x00' * 4 + b'\x00'
    svhd, proj = sv3d.kids; prhd, equi = proj.kids
    assert svhd.data[4:] == b'Strata 360\x00' and (prhd.typ, equi.typ) == ('prhd', 'equi') and equi.data == b'\x00' * 20


@pytest.mark.parametrize('data, match', [(b'', 'no moov'), (SP.box('ftyp', b'isom') + SP.box('moov', SP.box('mvhd', b'\x00' * 10)), 'no video track')])
def test_a_file_without_a_video_track_is_refused(tmp_path, data, match):
    f = tmp_path / 'x.mp4'; f.write_bytes(data)
    with pytest.raises(ValueError, match=match): SP.inject(str(f))


def test_a_broken_box_is_refused():
    with pytest.raises(ValueError, match='broken'): SP.parse(struct.pack('>I4s', 100, b'moov') + b'\x00' * 10)
