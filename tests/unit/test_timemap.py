"""render/timemap.py and the frame rate of the final film (implementation plan A2)."""
import json
import pytest
from strata360.render import final as FN, film as FL, timemap as TM


def seg(k, start, dur, clip='A', s0=10.0, utc='2026-02-19T17:00:10.000Z', tr=None, synthetic=None):
    g = dict(id=f'w{k}', clip=clip, film_start_s=start, dur_s=dur, clip_start_s=s0, utc_start=utc, transition=tr or dict(type='cut', dur_s=0.0))
    if synthetic: g.update(synthetic=synthetic, utc_start=None)
    return g


def plan():
    return dict(segments=[seg(0, 0.0, 4.0), seg(1, 4.0, 3.0, 'B', 20.0, '2026-02-19T18:30:20.000Z', tr=dict(type='dissolve', dur_s=1.0)), seg(2, 7.0, 2.5, 'B', 30.0, '2026-02-19T18:30:30.000Z', tr=dict(type='cut', dur_s=0.0)),
                         seg(3, 9.5, 2.0, 'G1', 0.0, tr=dict(type='dip', dur_s=0.5), synthetic='/x/g1.mp4')])


@pytest.mark.parametrize('fps', [25.0, 50.0, 29.97])
def test_windows_tile_the_film_once_and_transitions_lie_on_their_cuts(fps):
    tm = TM.build(plan(), fps); w = tm['windows']
    assert w[0]['film_in'] == 0 and all(a['film_out'] == b['film_in'] for a, b in zip(w, w[1:])) and tm['frames'] == w[-1]['film_out'] == round(11.5 * fps)
    pieces = FL.pieces(plan()['segments'], fps); assert sum(p['frames'] for p in pieces) == tm['frames']                      # the renderer cuts the same frames
    assert [t['index'] for t in tm['transitions']] == [1, 3]
    for t in tm['transitions']: cut = w[t['index']]['film_in']; assert t['film_in'] < cut < t['film_out'] and cut - t['film_in'] == t['film_out'] - cut


def test_a_transition_carries_both_windows_utc_and_a_generated_clip_has_none():
    tm = TM.build(plan(), 50.0); t = tm['transitions'][0]
    assert t['outgoing']['clip'] == 'A' and t['incoming']['clip'] == 'B' and t['film_out'] - t['film_in'] == 50
    assert t['outgoing']['utc_in'] < t['outgoing']['utc_out'] and t['incoming']['utc_in'] == '2026-02-19T18:30:19.500Z' and t['incoming']['utc_out'] == '2026-02-19T18:30:20.500Z'      # the incoming window is shown half a second early
    assert tm['windows'][3]['clip'] is None and tm['windows'][3]['synthetic'] and tm['windows'][3]['utc_in'] is None


def test_utc_at_follows_the_clock_inside_a_window_and_is_none_for_a_generated_clip():
    tm = TM.build(plan(), 50.0)
    assert TM.utc_at(tm, 0) == '2026-02-19T17:00:10.000Z' and TM.utc_at(tm, 50) == '2026-02-19T17:00:11.000Z'
    assert TM.utc_at(tm, 200) == '2026-02-19T18:30:20.000Z' and TM.utc_at(tm, 10 ** 6) is None and TM.utc_at(tm, 11 * 50 + 20) is None


def test_the_files_are_written(tmp_path):
    tm = TM.write(plan(), 25.0, str(tmp_path)); d = json.load(open(tmp_path / 'timemap.json')); assert d['frames'] == tm['frames'] == round(11.5 * 25)
    rows = (tmp_path / 'timemap.csv').read_text().splitlines(); assert rows[0].startswith('kind,index,film_in') and len(rows) == 1 + 4 + 2 * 2 and rows[1].startswith('window,0,0,100,A,')


def test_ffmpeg_rates_are_exact_rationals():
    assert [FN.ffmpeg_rate(x) for x in (25.0, 50, 29.97, 59.94, 23.976)] == ['25', '50', '30000/1001', '60000/1001', '24000/1001']


def project(tmp_path, rates):
    rd = tmp_path / 'strata360' / 'clips'
    for c, r in rates.items():
        (rd / c).mkdir(parents=True); json.dump(dict(video=dict(nominal_fps=r)), open(rd / c / 'clip.json', 'w'))
    return str(tmp_path)


def test_the_film_takes_the_footages_rate_the_majority_by_seconds_played(tmp_path):
    f = project(tmp_path, {'A': 25.0, 'B': 50.0, 'C': 50.0})
    mixed = dict(segments=[dict(clip='A', dur_s=10.0), dict(clip='B', dur_s=4.0), dict(clip='C', dur_s=3.0), dict(clip='G1', dur_s=99.0, synthetic='/g.mp4')])
    assert FN.source_fps(f, mixed) == 25.0 and FN.source_fps(f, dict(segments=[dict(clip='B', dur_s=1.0)])) == 50.0 and FN.source_fps(f, dict(segments=[])) == 50.0
    assert FN.resolve_fps(f, mixed) == 25.0 and FN.resolve_fps(f, mixed, 30.0) == 30.0 and FN.resolve_fps(f, mixed, 0.0, True) == 12.5 and FN.resolve_fps(f, dict(segments=[dict(clip='B', dur_s=1.0)]), 0.0, True) == 25.0
