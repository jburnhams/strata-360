"""Recordings cut short (no moov: the battery or card ran out) rebuilt by `strata360 recover` (osv/recover.py) and then used by the pipeline in place of the original, which is only read.
The cut-short files are made from the synthetic Insta360 pair (tests/utils/integration_insv.py): the media data kept, the index and trailer dropped, the mdat size left at 0 as the camera leaves it."""
import hashlib, json, os
import pytest
import integration_insv as S
from strata360.osv import insta360, mp4, recover as R, telemetry
from strata360.pipeline import clips

GOOD, CUT = 'VID_20240720_195607_001', 'VID_20240720_195707_002'


def cut_short(path):
    """Overwrite `path` with what a camera leaves when it stops mid-recording: everything before the index, the mdat size 0."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        md = next(b for b in mp4._boxes(f, 0, size) if b[0] == 'mdat'); f.seek(0); data = bytearray(f.read(md[2]))
    data[md[1] - 8:md[1] - 4] = b'\0\0\0\0'
    with open(path, 'wb') as f: f.write(bytes(data))


def sha(path): return hashlib.sha1(open(path, 'rb').read()).hexdigest()


@pytest.fixture
def library(tmp_path):
    """A footage folder with a good X3 recording (the template) and one cut short (both lenses and its proxy); returns (folder, {name: the uncut file's copy})."""
    d = str(tmp_path / 'trip'); S.build_insv(d, frames=60, number=1); S.build_insv(d, frames=90, name_time='20240720195707', number=2)
    whole = {}
    for n in S.names('20240720195707', 2):
        p = os.path.join(d, n); keep = str(tmp_path / ('whole_' + n)); open(keep, 'wb').write(open(p, 'rb').read()); whole[n] = keep; cut_short(p)
    return d, whole


def test_a_cut_short_recording_is_reported_until_it_is_recovered(library, cli):
    d, whole = library
    found, other = clips.discover(d)
    assert [c.id for c in found] == [GOOD] and sum(r == clips.NO_INDEX for _, r in other) == 2
    before = {n: sha(os.path.join(d, n)) for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))}
    out = cli('recover', d).stdout
    assert '3 rebuilt' in out and 'originals are unchanged' in out
    assert {n: sha(os.path.join(d, n)) for n in before} == before                                       # the originals are only read
    found, other = clips.discover(d); c = next(x for x in found if x.id == CUT)
    assert c.recovered and os.path.dirname(c.osv) == R.recovered_dir(d) and os.path.basename(c.lrf).startswith('LRV_') and os.path.dirname(c.lrf) == R.recovered_dir(d)
    assert not any(r == clips.NO_INDEX for _, r in other)
    assert 'already rebuilt' in cli('recover', d).stdout


def test_the_rebuilt_index_is_the_one_the_camera_would_have_written(library, cli):
    d, whole = library; cli('recover', d)
    for n in S.names('20240720195707', 2):
        a, b = R.Template(whole[n]), R.Template(os.path.join(R.recovered_dir(d), n))
        assert a.kinds == b.kinds
        for ta, tb in zip(a.traks, b.traks):
            (oa, za), (ob, zb) = R._samples(ta), R._samples(tb)
            assert len(ob) and (oa[:len(ob)] == ob).all() and (za[:len(zb)] == zb).all() and len(oa) - len(ob) <= 1   # every whole sample, at the same place (the audio frame after the last video frame is left out)


def test_a_recovered_x3_is_ingested_held_upright(library, cli):
    d, _ = library; cli('recover', d); cli('open', d, '--no-run'); cli('run', d, '--stages', 'ingest')
    j = json.load(open(os.path.join(d, 'strata360', 'clips', CUT, 'clip.json')))
    assert j['time']['start_utc'] == '2024-07-20T19:57:07Z' and j['video']['source_frames'] in (89, 90) and j['camera']['model'] == 'Insta360 X3'
    assert any('rebuilt from a recording cut short' in n for n in j['notes']) and any('held upright' in n for n in j['notes'])
    rear = j['source_files']['osv']; assert not insta360.has_motion(rear)
    f = telemetry.read_frames(rear); assert (f['quat'] == [1, 0, 0, 0]).all() and len(f['quat']) == len(telemetry.video_pts(rear, 0))
