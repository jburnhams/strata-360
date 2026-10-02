"""Orientation rows are read from the row `frames lost` earlier in a clip where the camera dropped frames (osv/telemetry.py `align_to_frames`)."""
import numpy as np
from strata360.osv import telemetry as TL


def rows(n=40, gaps=((10, 3),)):                      # gaps: (after row i, frames lost); 20 ms steps
    ts = np.cumsum(np.full(n, 20000)); ts = ts - ts[0]; ts = ts.astype(np.int64)
    for i, lost in gaps: ts[i + 1:] += lost * 20000
    return dict(ts_us=ts, quat=np.arange(n * 4, dtype=float).reshape(n, 4), acc=np.arange(n * 3, dtype=float).reshape(n, 3))


def test_frames_lost_are_counted_from_the_timestamp_jumps():
    assert TL.missing_frames(rows(40, ())['ts_us']).tolist() == [0] * 40
    lost = TL.missing_frames(rows(40, ((10, 3), (25, 1)))['ts_us']); assert lost[:11].tolist() == [0] * 11 and set(lost[11:26]) == {3} and set(lost[26:]) == {4}
    assert TL.missing_frames(np.array([0, 20000])).tolist() == [0, 0]


def test_a_clip_with_even_timestamps_is_unchanged_and_one_with_gaps_reads_earlier_rows_after_them():
    even = rows(40, ()); assert TL.align_to_frames(even) is even
    T = rows(40, ((10, 3),)); A = TL.align_to_frames(T)
    assert np.array_equal(A['quat'][:11], T['quat'][:11]) and np.array_equal(A['quat'][11], T['quat'][8]) and np.array_equal(A['quat'][39], T['quat'][36]) and np.array_equal(A['acc'][20], T['acc'][17])
    assert np.array_equal(A['ts_us'], T['ts_us'])                                           # the timestamps stay as the camera wrote them
    short = rows(6, ((1, 5),)); assert TL.align_to_frames(short)['quat'][2].tolist() == short['quat'][0].tolist()          # never before the first row
