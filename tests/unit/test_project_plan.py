

def _w(i, clip, start, dur, span=None): return dict(id=i, clip=clip, clip_start_s=start, dur_s=dur, in_s=start, utc_start='2026-02-20T06:00:00.000Z', utc_end='2026-02-20T06:00:04.000Z', voice_span=span)


def test_a_window_never_goes_back_over_footage_the_one_before_it_played():
    from strata360.edit import project as PJ
    segs = [_w('a', 'c', 10.0, 4.0, [0.0, 4.0]), _w('b', 'c', 13.84, 4.0, [0.0, 4.0]), _w('c', 'd', 5.0, 4.0), _w('d', 'd', 7.0, 4.0), _w('e', 'd', 3.0, 4.0)]
    moved = PJ.no_replay(segs, {'c': 60.0, 'd': 60.0})
    assert moved == [('b', 0.16), ('d', 2.0)]                                         # b picks up where a ended, d where c ended; e starts earlier in its clip than d: the script's own order, left
    assert segs[1]['clip_start_s'] == 14.0 and segs[1]['in_s'] == 14.0 and segs[1]['voice_span'] == [0.0, 3.84] and segs[1]['utc_start'] == '2026-02-20T06:00:00.160Z'
    assert segs[4]['clip_start_s'] == 3.0 and segs[0]['clip_start_s'] == 10.0
    near_end = [_w('a', 'c', 50.0, 8.0), _w('b', 'c', 54.0, 5.0)]; assert PJ.no_replay(near_end, {'c': 60.0}) == [('b', 1.0)]          # the clip has only 1 s left: as far as it goes
