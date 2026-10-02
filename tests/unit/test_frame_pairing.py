"""Frames are found by their timestamps and every frame of a damaged lens stream is kept (render/flat.py `frame_at`, `decode_args`, osv/telemetry.py `has_dropped_frames`)."""
import numpy as np
from strata360.osv import telemetry as TL
from strata360.render import flat


def pts_with_gap(n=100, gap_at=28, lost=9): p = np.arange(n) * 0.02; p[gap_at:] += lost * 0.02; return p


def test_the_frame_at_a_time_comes_from_the_timestamps_not_from_time_times_fps():
    p = pts_with_gap(); assert flat.frame_at(p, 0.0) == 0 and flat.frame_at(p, 0.40) == 20 and flat.frame_at(p, p[50] - p[0]) == 50 and flat.frame_at(p, 1.0) == 41          # 1.0 s is frame 41, not 50: nine frames were lost
    assert flat.frame_at(p, 999.0) == 99 and flat.frame_at(p, -1.0) == 0                                              # held at the ends
    assert flat.frame_at(np.arange(10) * 0.02, [0.04, 0.1]).tolist() == [2, 5]                                       # even timestamps: as time x 50


def test_a_clip_that_dropped_frames_is_decoded_in_software_keeping_the_damaged_frames_and_others_as_before(monkeypatch):
    monkeypatch.setattr(TL, 'read_frames', lambda osv: dict(ts_us=(pts_with_gap() * 1e6).astype(np.int64)))
    assert TL.has_dropped_frames('x') is True
    args, damaged = flat.decode_args('x'); assert damaged and args == ['-flags', '+output_corrupt'] and '-hwaccel' not in args
    monkeypatch.setattr(TL, 'read_frames', lambda osv: dict(ts_us=(np.arange(100) * 20000).astype(np.int64)))
    assert TL.has_dropped_frames('x') is False and flat.decode_args('x', hw=False) == ([], False)
    monkeypatch.setattr(flat.hwmod, 'hwaccel_args', lambda: ['-hwaccel', 'videotoolbox']); assert flat.decode_args('x')[0] == ['-hwaccel', 'videotoolbox']
