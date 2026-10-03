"""Which street view sections are worth showing, which overlap, what was chosen (and its label), and the range of clip lengths each can make."""
import json, os
import pytest

from strata360 import streetview as SV


def sec(i, provider='mapillary', km0=1.0, km1=1.3, frames=60, spacing=5.0, seq='s', **kw):
    d = dict(id=i, provider=provider, stretch='R1', kind='2d', km0=km0, km1=km1, length_m=int(round((km1 - km0) * 1000)), frames=frames, spacing_m=spacing, years=[2024], camera=None, size=None, seq=seq, angles=None, items=[])
    d.update(kw); return d


def doc(*sections): return dict(sections=list(sections))


class TestJudge:
    def test_enough_pictures_close_together_over_enough_road(self):
        assert SV.judge(sec('M1')) == (True, '')
        assert SV.judge(sec('M1', frames=20)) == (False, 'only 20 pictures (needs 30)')
        assert SV.judge(sec('M1', km1=1.1, length_m=100)) == (False, 'only 100 m long (needs 150 m)')
        assert SV.judge(sec('M1', spacing=15.0)) == (False, 'pictures 15.0 m apart (needs 10 m or less)')
        assert SV.judge(sec('M1', spacing=None))[0] is False

    def test_google_is_offered_like_the_others(self):
        ok, why = SV.judge(sec('G1', provider='google')); assert ok is True


def test_how_well_the_camera_can_be_steadied_depends_on_the_pictures():
    assert SV.steadying(sec('M1', kind='360')) == 'exact' and SV.steadying(sec('P1', provider='panoramax', kind='360')) == 'estimated' and SV.steadying(sec('M2', kind='2d')) == 'by matching only'


def test_a_clip_can_be_as_short_as_any_clip_and_as_long_as_its_slowest_smooth_speed():
    assert SV.clip_range(sec('M1', frames=62)) == (2.0, 15.5) and SV.clip_range(sec('M1', frames=10)) == (2.0, 2.5)           # (no fastest speed: pictures are skipped)


def test_sections_over_the_same_road_overlap_when_they_share_enough_of_the_shorter():
    a = sec('M1', km0=1.0, km1=1.4); b = sec('P1', provider='panoramax', km0=1.3, km1=1.5); c = sec('M2', km0=1.38, km1=1.9); d = sec('M3', km0=3.0, km1=3.3)
    assert SV.overlaps([a, b, c, d]) == {'M1': ['P1'], 'P1': ['M1', 'M2'], 'M2': ['P1'], 'M3': []}                              # (M1 and M2 share only 20 m of 400: not enough)


class TestChoices:
    def test_a_choice_is_kept_and_a_chosen_section_gets_a_label_for_good(self, tmp_path):
        rd = str(tmp_path); assert SV.choices(rd) == {}
        SV.set_choice(rd, 'a', 'possible'); SV.set_choice(rd, 'b', 'must'); SV.set_choice(rd, 'a', 'none'); SV.set_choice(rd, 'a', 'must')
        assert SV.choices(rd) == {'b': 'must', 'a': 'must'} and json.load(open(tmp_path / 'streetview' / 'choices.json'))['labels'] == {'a': 1, 'b': 2}              # (a keeps V1 although it was cleared and chosen again)

    def test_only_possible_and_must_are_choices(self, tmp_path):
        with pytest.raises(ValueError, match='possible, must or none'): SV.set_choice(str(tmp_path), 'a', 'maybe')

    def test_the_sections_come_with_the_judgement_the_overlaps_the_choice_and_the_label(self, tmp_path):
        rd = str(tmp_path); a = sec('M1', km0=1.0, km1=1.3); b = sec('P1', provider='panoramax', km0=1.1, km1=1.4, frames=10, seq='c'); docs = {'mapillary': doc(a), 'panoramax': doc(b), 'google': None}
        SV.set_choice(rd, SV.section_key(a), 'must'); out = {s['id']: s for s in SV.annotate(rd, docs)}
        assert out['M1']['key'] == 'mapillary:s:1.00' and out['M1']['plausible'] and out['M1']['choice'] == 'must' and out['M1']['label'] == 'V1' and out['M1']['overlaps'] == ['P1'] and (out['M1']['min_s'], out['M1']['max_s']) == (2.0, 15.0)
        assert out['M1']['play_s'] == 4.0 and out['M1']['speed_ms'] == 75.0 and out['P1']['plausible'] is False and out['P1']['choice'] is None and out['P1']['label'] is None
        assert [s['id'] for s in SV.annotate(rd, docs)] == ['M1', 'P1'] and [s['label'] for s in SV.chosen(rd, docs)] == ['V1']

    def test_a_chosen_section_that_is_not_plausible_is_still_passed_on_because_it_is_the_users_call(self, tmp_path):
        rd = str(tmp_path); b = sec('P1', provider='panoramax', frames=10); SV.set_choice(rd, SV.section_key(b), 'must'); assert [x['id'] for x in SV.chosen(rd, {'panoramax': doc(b)})] == ['P1']


import datetime as dt


def utc(*a): return dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp()


class TestLight:
    DAY = utc(2024, 3, 7, 12)

    def section(self, t=None): return sec('M1', items=[dict(id='a', km=1.0, lat=50.13, lon=5.79, t=t or self.DAY), dict(id='b', km=1.2, lat=50.13, lon=5.79, t=(t or self.DAY) + 5), dict(id='c', km=1.3, lat=50.13, lon=5.79, t=(t or self.DAY) + 9)])

    def track(self, t0):
        import numpy as np
        n = 3000; d = 3.0 * np.arange(n); return dict(t=t0 + np.arange(n), lat=50.13 + d / 111195.0, lon=np.full(n, 5.79), dist=d)

    def test_a_view_in_the_sun_for_a_stretch_run_in_the_dark_is_warned_about_with_both_heights(self):
        out = SV.light(self.section(), self.track(utc(2024, 9, 15, 22)))                                                  # filmed at noon, run at midnight local time
        assert out['captured'] == 'day' and out['race'] == 'night' and out['captured_sun'] > 20 and out['race_sun'] < -20 and 'the sun' in out['warning'] and 'above the horizon (daylight)' in out['warning'] and 'below the horizon (dark)' in out['warning'] and out['warning'].endswith('it would look wrong in the film.')

    def test_the_time_of_year_counts_the_same_clock_time_is_dark_in_february_and_fine_in_july(self):
        filmed = utc(2024, 3, 7, 16, 44)                                                                                  # 17:44 local on 7 March: the sun about 6 degrees up
        feb = SV.light(self.section(filmed), self.track(utc(2026, 2, 20, 17, 58) - 1000 / 3.0)); assert 5 < feb['captured_sun'] < 7 and feb['race_sun'] < -8 and 'below the horizon (dark)' in feb['warning']
        july = SV.light(self.section(filmed), self.track(utc(2026, 7, 20, 16, 58) - 1000 / 3.0)); assert july['race_sun'] > 15 and july['warning'] is None and july['race'] == 'day'                       # 18:58 in July: broad daylight

    def test_dusk_and_dawn_fit_either_way_and_unknown_times_give_no_warning(self):
        dusk = SV.light(self.section(utc(2024, 3, 7, 12)), self.track(utc(2026, 2, 20, 17, 25) - 1000 / 3.0)); assert -6 <= dusk['race_sun'] < 6 and dusk['warning'] is None                       # 18:25 in February: the sun just set, still light enough
        undated = sec('M1', items=[dict(id='a', km=1.0, lat=50.13, lon=5.79), dict(id='b', km=1.3, lat=50.13, lon=5.79)]); out = SV.light(undated, self.track(utc(2024, 9, 15, 22))); assert out['captured'] is None and out['captured_sun'] is None and out['warning'] is None

    def test_a_view_in_the_dark_for_a_stretch_run_in_the_sun_is_warned_about(self):
        out = SV.light(self.section(utc(2024, 3, 7, 0)), self.track(utc(2024, 9, 15, 11))); assert out['captured'] == 'night' and 'below the horizon (dark)' in out['warning'].split('but')[0] and 'above the horizon' in out['warning'].split('but')[1]

    def test_annotate_adds_the_light_when_it_has_the_track(self, tmp_path):
        docs = {'mapillary': doc(self.section())}; assert SV.annotate(str(tmp_path), docs)[0]['light'] is None
        assert SV.annotate(str(tmp_path), docs, self.track(utc(2024, 9, 15, 22)))[0]['light']['warning']

    def test_the_sun_in_words(self):
        assert SV.sun_phrase(22.8) == 'the sun 23° above the horizon (daylight)' and SV.sun_phrase(3.0) == 'the sun 3° above the horizon (golden-hour light)' and SV.sun_phrase(-3.0) == 'the sun 3° below the horizon (dusk or dawn)' and SV.sun_phrase(-9.5) == 'the sun 10° below the horizon (dark)'


class TestQualityStage:
    def setup_docs(self, rd):
        a = sec('M1', km0=1.0, km1=1.3, frames=60, seq='a'); b = sec('P1', provider='panoramax', km0=2.0, km1=2.3, frames=60, seq='b'); c = sec('M2', km0=3.0, km1=3.3, frames=10, seq='c'); g = sec('G1', provider='google', km0=4.0, km1=4.3, frames=60, seq='g')
        roads = dict(schema=1, id='r', stretches=[dict(id='R1', km0=0.5, km1=5.0, length_m=4500, highways=[], names=[], line=[[1, 1], [1, 2]])], run=[], total_km=6)
        SV._save(rd, 'roads', roads); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [a, c], roads)); SV._save(rd, 'panoramax', SV.provider_doc('panoramax', [b], roads)); SV._save(rd, 'google', SV.provider_doc('google', [g], roads)); return roads

    def test_only_plausible_open_sections_are_scored_each_once_and_what_is_found_is_kept(self, tmp_path, monkeypatch):
        rd = str(tmp_path); roads = self.setup_docs(rd); monkeypatch.setattr(SV, '_key', lambda n: 'tok'); fetched = []; measured = []; log = []
        def fetch(rd_, sec_, token=None, log=print, preview=False): fetched.append((sec_['id'], preview, token))
        def measure(rd_, sec_, road=None): measured.append((sec_['id'], road['km0'])); return dict(psnr=15.0, jerk=0.3, roll=0.2, score=70 if sec_['id'] == 'M1' else 20)
        assert SV.run(rd, {}, ['quality'], measure=measure, fetch=fetch, log=log.append) == ['quality']
        assert fetched == [('M1', True, 'tok'), ('P1', True, 'tok'), ('G1', True, 'tok')] and measured == [('M1', 0.5), ('P1', 0.5), ('G1', 0.5)] and len(log) == 3
        q = SV.quality_of(rd); assert q['mapillary:a:1.00']['grade'] == 'good' and q['panoramax:b:2.00']['grade'] == 'poor' and q['mapillary:a:1.00']['frames'] == 60 and set(q) == {'mapillary:a:1.00', 'panoramax:b:2.00', 'google:g:4.00'}
        assert SV.run(rd, {}, ['quality'], measure=measure, fetch=fetch) == [] and len(measured) == 3                                  # nothing new to score
        assert SV.run(rd, {}, ['quality'], force=True, measure=measure, fetch=fetch) == ['quality'] and len(measured) == 6
        out = {s['id']: s for s in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})}; assert out['M1']['quality']['score'] == 70 and out['M1']['quality']['grade'] == 'good' and out['M2']['quality'] is None and out['G1']['quality']['score'] == 20
        assert SV.status(rd)['quality'] == dict(done=True, scored=3, km=0) and 'quality' in SV.STAGES

    def test_a_section_whose_pictures_changed_is_scored_again(self, tmp_path, monkeypatch):
        rd = str(tmp_path); roads = self.setup_docs(rd); monkeypatch.setattr(SV, '_key', lambda n: 'tok'); measure = lambda rd_, s_, road=None: dict(psnr=1, jerk=1, roll=1, score=50); fetch = lambda *a, **k: None
        SV.run(rd, {}, ['quality'], measure=measure, fetch=fetch); a = sec('M1', km0=1.0, km1=1.3, frames=70, seq='a'); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [a], roads))
        out = SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}); assert out[0]['quality'] is None                                  # the old score is for other pictures
        assert SV.run(rd, {}, ['quality'], measure=measure, fetch=fetch) == ['quality'] and SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})[0]['quality']['score'] == 50

    def test_a_section_that_cannot_be_measured_is_recorded_and_the_rest_go_on(self, tmp_path, monkeypatch):
        rd = str(tmp_path); self.setup_docs(rd); monkeypatch.setattr(SV, '_key', lambda n: 'tok')
        def measure(rd_, s_, road=None):
            if s_['id'] == 'M1': raise RuntimeError('picture x1 has not been fetched')
            return dict(psnr=15.0, jerk=0.3, roll=0.2, score=60)
        SV.run(rd, {}, ['quality'], measure=measure, fetch=lambda *a, **k: None); out = {s['id']: s for s in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})}
        assert out['M1']['quality']['score'] is None and 'has not been fetched' in out['M1']['quality']['error'] and out['P1']['quality']['score'] == 60 and SV.status(rd)['quality']['scored'] == 2

    def test_the_quality_stage_needs_the_roads_and_mapillary_needs_its_token(self, tmp_path, monkeypatch):
        with pytest.raises(RuntimeError, match='roads stage first'): SV.run(str(tmp_path), {}, ['quality'])
        rd = str(tmp_path / 'p'); self.setup_docs(rd); monkeypatch.setattr(SV, '_key', lambda n: None); SV.run(rd, {}, ['quality'], measure=lambda *a, **k: dict(score=50, psnr=1, jerk=1, roll=1), fetch=lambda *a, **k: None)
        assert 'MAPILLARY_TOKEN' in SV.quality_of(rd)['mapillary:a:1.00']['error']


class TestTimesAndVideo:
    def section(self, **kw): return sec('M1', km0=1.0, km1=1.3, items=[dict(id='a', km=1.0, lat=50.13, lon=5.79, t=1_709_812_800), dict(id='b', km=1.3, lat=50.13, lon=5.79, t=1_709_812_830)], **kw)

    def track(self, t0=1_726_401_600):
        import numpy as np
        n = 3000; d = 3.0 * np.arange(n); return dict(t=t0 + np.arange(n), lat=50.13 + d / 111195.0, lon=np.full(n, 5.79), dist=d)

    def test_each_section_has_when_it_was_filmed_and_when_the_runner_passed_it(self, tmp_path):
        out = SV.annotate(str(tmp_path), {'mapillary': doc(self.section())}, self.track())[0]
        assert out['filmed'] == [1_709_812_800, 1_709_812_830] and out['passed'] == [pytest.approx(1_726_401_600 + 1000 / 3.0), pytest.approx(1_726_401_600 + 1300 / 3.0)]
        bare = SV.annotate(str(tmp_path), {'mapillary': doc(sec('M1'))})[0]; assert bare['filmed'] is None and bare['passed'] is None

    def test_the_preview_video_of_a_section_is_named_by_what_it_is_made_from(self, tmp_path):
        rd = str(tmp_path); a = SV.annotate(rd, {'mapillary': doc(self.section())})[0]; p = SV.video_path(rd, a)
        assert p.endswith('.mp4') and os.path.join('streetview', 'video', 'M1-') in p and SV.video_path(rd, a) == p and a['has_video'] is False
        assert SV.video_path(rd, dict(a, frames=a['frames'] + 1)) != p and SV.video_path(rd, dict(a, key='other')) != p
        os.makedirs(os.path.dirname(p)); open(p, 'wb').write(b'x'); assert SV.annotate(rd, {'mapillary': doc(self.section())})[0]['has_video'] is True

    def test_the_preview_is_the_stretch_at_road_speed_held_to_what_the_section_can_play(self):
        assert SV.default_seconds(sec('M1', km0=1.0, km1=1.4, length_m=400, frames=80)) == 16.0 and SV.default_seconds(sec('M1', length_m=100, frames=80)) == 4.0
        assert SV.default_seconds(sec('M1', length_m=2000, frames=40)) == 10.0 and SV.default_seconds(sec('M1', length_m=10, frames=80)) == 2.0

    def test_making_the_video_fetches_the_small_pictures_renders_once_and_(self, tmp_path, monkeypatch):
        from strata360.edit import streetview_cam as CAM
        rd = str(tmp_path); roads = dict(schema=1, id='r', stretches=[dict(id='R1', km0=0.5, km1=3.0, length_m=2500, highways=[], names=[], line=[[1, 1], [1, 2]])], run=[], total_km=4)
        SV._save(rd, 'roads', roads); a = SV.annotate(rd, {'mapillary': doc(self.section())})[0]; calls = []
        monkeypatch.setattr(SV, '_key', lambda n: 'tok')
        monkeypatch.setattr(CAM, 'fetch', lambda rd_, s_, token=None, log=print, preview=False: calls.append(('fetch', s_['id'], token, preview)))
        def render(rd_, s_, seconds, out, road=None, size=None, preview=False, log=print): calls.append(('render', seconds, road, size, preview)); open(out, 'wb').write(b'mp4')
        monkeypatch.setattr(CAM, 'render', render)
        out = SV.make_video(rd, a); assert os.path.exists(out) and calls == [('fetch', 'M1', 'tok', True), ('render', SV.default_seconds(a), dict(line=[[1, 1], [1, 2]], km0=0.5), (960, 540), True)]
        assert SV.make_video(rd, a) == out and len(calls) == 2                                                                         # kept: not made again
    

class TestNearestClips:
    T0 = 1_726_401_600.0

    def track(self):
        import numpy as np
        n = 4000; d = 3.0 * np.arange(n); return dict(t=self.T0 + np.arange(n), lat=50.13 + d / 111195.0, lon=np.full(n, 5.79), dist=d)

    def near(self, km0, km1, clips, gaps=None):
        s = dict(sec('M1', km0=km0, km1=km1), passed=[self.T0 + km0 * 1000 / 3.0, self.T0 + km1 * 1000 / 3.0]); return SV.nearest_clips(s, clips, self.track(), gaps)

    def clip(self, label, km0, km1): return dict(label=label, t0=self.T0 + km0 * 1000 / 3.0, t1=self.T0 + km1 * 1000 / 3.0)

    def test_the_nearest_clip_each_way_with_the_time_and_the_distance_along_the_run_between(self):
        out = self.near(5.0, 5.3, [self.clip('0001', 1.0, 2.0), self.clip('0002', 3.0, 4.2), self.clip('0003', 6.0, 7.0), self.clip('0004', 9.0, 9.5)])
        assert out['before'] == dict(label='0002', seconds=round(800 / 3.0), km=0.8) and out['after'] == dict(label='0003', seconds=round(700 / 3.0), km=0.7) and out['overlaps'] == [] and out['in_gap'] is None

    def test_a_section_that_overlaps_footage_says_which_and_the_ends_are_empty_when_there_is_no_clip(self):
        out = self.near(3.5, 4.5, [self.clip('0002', 3.0, 4.0)]); assert out['overlaps'] == ['0002'] and out['before'] is None and out['after'] is None
        assert self.near(1.0, 1.2, [])['overlaps'] == [] and self.near(1.0, 1.2, [])['before'] is None and SV.nearest_clips(sec('M1'), [], self.track()) is None and SV.nearest_clips(dict(sec('M1'), passed=[1, 2]), None, self.track()) is None

    def test_a_clip_that_touches_the_section_is_zero_away_and_not_an_overlap(self):
        out = self.near(5.0, 5.3, [self.clip('0002', 4.0, 5.0), self.clip('0003', 5.3, 6.0)]); assert out['before'] == dict(label='0002', seconds=0, km=0.0) and out['after'] == dict(label='0003', seconds=0, km=0.0) and out['overlaps'] == []

    def test_the_gap_in_the_footage_that_holds_the_whole_section(self):
        gaps = [dict(id='G01', t0=self.T0 + 2000 / 3.0, t1=self.T0 + 4800 / 3.0), dict(id='G02', t0=self.T0 + 6000 / 3.0, t1=self.T0 + 9000 / 3.0)]
        assert self.near(3.0, 3.5, [], gaps)['in_gap'] == 'G01' and self.near(4.5, 5.0, [], gaps)['in_gap'] is None and self.near(7.0, 7.5, [], gaps)['in_gap'] == 'G02'                  # (the middle one sticks out of the first gap)

    def test_annotate_adds_it_when_it_has_the_track_the_clips_and_the_gaps(self, tmp_path):
        s = sec('M1', km0=5.0, km1=5.3, items=[dict(id='a', km=5.0, lat=50.2, lon=5.79, t=1), dict(id='b', km=5.3, lat=50.2, lon=5.79, t=2)])
        out = SV.annotate(str(tmp_path), {'mapillary': doc(s)}, self.track(), [self.clip('0003', 6.0, 7.0)], [])[0]['near']; assert out['after']['label'] == '0003' and out['before'] is None
        assert SV.annotate(str(tmp_path), {'mapillary': doc(s)})[0]['near'] is None


class TestLength:
    def test_a_length_is_kept_within_what_the_section_can_play_and_cleared(self, tmp_path):
        rd = str(tmp_path); a = sec('M1'); docs = {'mapillary': doc(a)}; s = SV.annotate(rd, docs)[0]
        assert SV.set_length(rd, s, 12) == 12.0 and SV.annotate(rd, docs)[0]['seconds'] == 12.0
        with pytest.raises(ValueError, match='can play'): SV.set_length(rd, s, 0.5)
        with pytest.raises(ValueError, match='number'): SV.set_length(rd, s, 'long')
        assert SV.set_length(rd, s, None) is None and SV.annotate(rd, docs)[0]['seconds'] is None
