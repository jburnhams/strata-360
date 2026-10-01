import numpy as np
from strata360.osv import telemetry as T


def test_parsed_telemetry_is_read_once_per_file_and_again_when_the_file_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('STRATA_CACHE', str(tmp_path / 'cache')); f = tmp_path / 'a.osv'; f.write_bytes(b'x' * 100); calls = []
    def make(): calls.append(1); return dict(q=np.arange(6.0).reshape(2, 3))
    a = T._cached(str(f), 'frames3', make); b = T._cached(str(f), 'frames3', make)
    assert len(calls) == 1 and np.array_equal(a['q'], b['q'])                                                  # the second call came from the cache
    T._cached(str(f), 'exposure', make); assert len(calls) == 2                                               # another kind of result is kept apart
    f.write_bytes(b'x' * 200); T._cached(str(f), 'frames3', make); assert len(calls) == 3                      # a changed file (size, time) is read again


def test_video_pts_falls_back_to_the_packet_scan_when_the_index_reader_fails(monkeypatch):
    import subprocess
    from strata360.osv import mp4
    monkeypatch.setattr(mp4, 'video_sample_times', lambda p: (_ for _ in ()).throw(ValueError('no moov box')))
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: b'0.04\n0.00\n0.02\n')
    assert list(T.video_pts('x.osv', 0)) == [0.0, 0.02, 0.04]
