"""render/chapters.py: YouTube chapter markers from the time map and the race's stages."""
import json, os
import pytest
from strata360.render import chapters as CH, timemap as TM

T0 = 1771520400.0                     # 2026-02-19T17:00:00Z


def iso(s): return TM._utc('2026-02-19T17:00:00.000Z', s)


def win(k, film_in, film_out, utc_in, utc_out):
    return dict(index=k, film_in=film_in, film_out=film_out, utc_in=utc_in if utc_in is None else iso(utc_in), utc_out=utc_out if utc_out is None else iso(utc_out))


def tmap(*wins, fps=10.0): return dict(fps=fps, frames=wins[-1]['film_out'], windows=list(wins))


SCHED = [(float('-inf'), 'Before Race'), (T0, 'At Start'), (T0 + 60, 'Stage 1'), (T0 + 3600, 'Checkpoint 1'), (T0 + 3900, 'Stage 2'), (T0 + 9000, 'At Finish'), (T0 + 9100, 'After Race')]
km = lambda u: (u - T0) / 360.0       # 10 km an hour


def test_a_chapter_starts_where_the_stage_changes_and_names_it_with_the_km_run():
    tm = tmap(win(0, 0, 150, 120, 135), win(1, 150, 300, 600, 615), win(2, 300, 450, 3950, 3965), win(3, 450, 600, 8000, 8015))
    ch = CH.build(tm, SCHED, km)
    assert [(c['t'], c['title']) for c in ch] == [(0.0, 'Stage 1, km 0'), (30.0, 'Stage 2, km 11')] and ch[1]['km'] == 11.0 and ch[1]['label'] == 'Stage 2'
    assert CH.text(ch) == '0:00 Stage 1, km 0\n0:30 Stage 2, km 11\n'


def test_a_stage_that_changes_inside_a_window_starts_its_chapter_at_that_frame():
    gap = win(1, 200, 400, 3000, 4000)                                   # a generated clip over 1000 s of race in 20 s of film
    ch = CH.build(tmap(win(0, 0, 200, 100, 120), gap, win(2, 400, 600, 4000, 4020)), SCHED, km)
    assert [(c['t'], c['label']) for c in ch] == [(0.0, 'Stage 1'), (38.0, 'Stage 2')]          # the checkpoint (3600 to 3900) is 6 s of film (32 to 38 s): too short, it joins the stage before it


def test_short_chapters_join_a_neighbour_and_the_first_takes_in_the_opening():
    tm = tmap(win(0, 0, 50, 10, 15), win(1, 50, 300, 120, 145), win(2, 300, 600, 3700, 3730), win(3, 600, 900, 4000, 4030))
    ch = CH.build(tm, SCHED, km, lead_s=4.0)
    assert [(c['t'], c['title']) for c in ch] == [(0.0, 'Stage 1, km 0'), (34.0, 'Checkpoint 1, km 10'), (64.0, 'Stage 2, km 11')]       # "Start" (5 s) joined the first stage, which now starts the film
    assert all(b['t'] - a['t'] >= CH.MIN_S for a, b in zip(ch, ch[1:]))


def test_windows_without_a_race_time_stay_in_the_chapter_before_them():
    tm = tmap(win(0, 0, 200, 120, 140), win(1, 200, 400, None, None), win(2, 400, 600, 4000, 4020))
    assert [(c['t'], c['title']) for c in CH.build(tm, SCHED, km)] == [(0.0, 'Stage 1, km 0'), (40.0, 'Stage 2, km 11')]


def test_without_routes_the_chapters_are_km_and_without_a_schedule_there_are_none():
    tm = tmap(win(0, 0, 200, 120, 140), win(1, 200, 400, 9200, 9220))
    sched = [(float('-inf'), 'Before Race'), (T0, 'At Start'), (T0 + 60, 'On Course'), (T0 + 9100, 'After Race')]
    assert [c['title'] for c in CH.build(tm, sched, km)] == ['km 0', 'After the finish'] and [c['title'] for c in CH.build(tm, sched)] == ['On course', 'After the finish']
    assert CH.build(tm, []) == [] and CH.build(tmap(win(0, 0, 200, None, None)), SCHED) == []


@pytest.mark.parametrize('label, k, want', [('Before Race', 1.0, 'Before the start'), ('At Start', 0.2, 'Start'), ('At Finish', 160.4, 'Finish'), ('After Race', None, 'After the finish'), ('Stage 3', 41.6, 'Stage 3, km 42'), ('Checkpoint 2', None, 'Checkpoint 2'), ('On Course', 12.4, 'km 12')])
def test_titles(label, k, want): assert CH.title(label, k) == want


@pytest.mark.parametrize('s, want', [(0, '0:00'), (65.9, '1:05'), (600, '10:00'), (3723, '1:02:03')])
def test_stamps_are_youtubes_form(s, want): assert CH.stamp(s) == want


def test_write_and_for_film_put_the_files_beside_the_film(tmp_path, monkeypatch):
    monkeypatch.setattr(CH, 'race', lambda folder: (SCHED, km)); seen = []
    d = tmp_path / 'strata360' / 'final' / 'abc'; d.mkdir(parents=True)
    tm = tmap(win(0, 0, 300, 120, 150), win(1, 300, 600, 3700, 3730), win(2, 600, 900, 4000, 4030)); json.dump(tm, open(d / 'timemap.json', 'w'))
    (d / 'bookend-intro-1234.mov').write_bytes(b''); (d / 'film.mp4').write_bytes(b'')
    monkeypatch.setattr(CH, '_duration', lambda p: seen.append(os.path.basename(p)) or {'bookend-intro-1234.mov': 6.0, 'film.mp4': 100.0}[os.path.basename(p)])
    out, res = CH.for_film(str(tmp_path))
    assert out == str(d) and res['youtube'] and res['lead_s'] == 6.0 and seen == ['bookend-intro-1234.mov', 'film.mp4']
    assert (d / 'chapters.txt').read_text() == '0:00 Stage 1, km 0\n0:36 Checkpoint 1, km 10\n1:06 Stage 2, km 11\n' and json.load(open(d / 'chapters.json'))['chapters'][2]['t'] == 66.0


def test_for_film_without_a_film_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match='no final film'): CH.for_film(str(tmp_path))


def test_the_race_comes_from_the_projects_run(tmp_path, monkeypatch):
    import numpy as np
    from strata360.gps import tracks as TKS
    assert CH.race(str(tmp_path)) == ([], None)
    lat = np.linspace(45.0, 45.09, 10)                                    # about 10 km north in 10 samples
    monkeypatch.setattr(TKS, 'current_path', lambda rd: 'run.fit'); monkeypatch.setattr(TKS, 'stage_schedule', lambda rd: SCHED)
    monkeypatch.setattr(TKS, 'read', lambda p: dict(t=T0 + np.arange(10.0) * 100, lat=lat, lon=np.full(10, 6.0)))
    sched, k = CH.race(str(tmp_path)); assert sched == SCHED and k(T0) == 0.0 and k(T0 + 900) == pytest.approx(10.0, abs=0.05) and k(T0 + 450) == pytest.approx(5.0, abs=0.05)


def test_a_generated_clip_is_timed_as_the_renderer_plays_it():
    gap = dict(win(1, 200, 300, 3000, 4000), synthetic_seconds=20.0, source_in_s=0.0)          # 1000 s of race in a 20 s clip, of which the window plays the first 10 s
    ch = CH.build(tmap(win(0, 0, 200, 100, 120), gap, win(2, 300, 500, 4000, 4020)), SCHED, km)
    assert [(c['t'], c['label']) for c in ch] == [(0.0, 'Stage 1'), (30.0, 'Stage 2')]          # the checkpoint (3600) is 12 s into the clip: past the window's end, never on screen
    late = dict(gap, source_in_s=10.0)                                                          # the window plays the clip's second half: it opens at 3500 and the checkpoint comes 2 s in
    ch = CH.build(tmap(win(0, 0, 200, 100, 120), late, win(2, 300, 500, 4000, 4020)), SCHED, km, min_s=0)
    assert [(c['t'], c['label']) for c in ch] == [(0.0, 'Stage 1'), (22.0, 'Checkpoint 1'), (28.0, 'Stage 2')]


def test_a_speed_ramp_window_starts_its_chapter_where_the_ramp_reaches_the_stage():
    from strata360.edit import hyperlapse as HL
    rp = dict(dur_s=20.0, lead_s=2.0, ramp_s=2.0, tail_s=2.0, speed=10.0); src = float(HL.offsets(rp, 20.0))
    ramp = dict(win(1, 200, 400, 3500, 3500 + src), ramp=rp)                                         # 20 s of film racing through about 150 s of the clip
    ch = CH.build(tmap(win(0, 0, 200, 100, 120), ramp, win(2, 400, 600, 4000, 4020)), SCHED, km, min_s=0)
    cp = next(c for c in ch if c['label'] == 'Checkpoint 1'); t = cp['t'] - 20.0
    assert 2.0 < t < 18.0 and float(HL.offsets(rp, t)) == pytest.approx(100.0, abs=0.2)             # the frame where the ramp's clock reaches the checkpoint (100 s into the clip), not 100 / 150 of the way
