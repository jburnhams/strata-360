"""Which street view sections are worth showing, which overlap, what was chosen (and its label), and the range of clip lengths each can make."""
import json
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

    def test_google_is_never_offered(self):
        ok, why = SV.judge(sec('G1', provider='google')); assert ok is False and 'terms' in why


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

    def test_a_chosen_section_that_is_not_plausible_is_not_passed_on(self, tmp_path):
        rd = str(tmp_path); b = sec('P1', provider='panoramax', frames=10); SV.set_choice(rd, SV.section_key(b), 'must'); assert SV.chosen(rd, {'panoramax': doc(b)}) == []


import datetime as dt


def utc(*a): return dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp()


class TestLight:
    DAY = utc(2024, 3, 7, 12)

    def section(self): return sec('M1', items=[dict(id='a', km=1.0, lat=50.13, lon=5.79, t=self.DAY), dict(id='b', km=1.2, lat=50.13, lon=5.79, t=self.DAY + 5), dict(id='c', km=1.3, lat=50.13, lon=5.79, t=self.DAY + 9)])

    def track(self, t0):
        import numpy as np
        n = 3000; d = 3.0 * np.arange(n); return dict(t=t0 + np.arange(n), lat=50.13 + d / 111195.0, lon=np.full(n, 5.79), dist=d)

    def test_a_daytime_view_for_a_stretch_run_in_the_dark_is_warned_about(self):
        out = SV.light(self.section(), self.track(utc(2024, 9, 15, 22)))            # the run is at midnight local time, a kilometre in
        assert out['captured'] == 'day' and out['race'] == 'night' and out['warning'] == 'Filmed in daylight, but the runner passes here at night: it would look wrong in the film.'

    def test_no_warning_when_the_light_fits_or_is_unknown(self):
        noon = SV.light(self.section(), self.track(utc(2024, 9, 15, 11))); assert noon['race'] in ('day', 'golden hour') and noon['warning'] is None
        undated = sec('M1', items=[dict(id='a', km=1.0, lat=50.13, lon=5.79), dict(id='b', km=1.3, lat=50.13, lon=5.79)]); assert SV.light(undated, self.track(utc(2024, 9, 15, 11)))['captured'] is None and SV.light(undated, self.track(utc(2024, 9, 15, 22)))['warning'] is None

    def test_a_night_view_for_a_stretch_run_in_the_day_is_warned_about(self):
        s = self.section(); s['items'] = [dict(i, t=utc(2024, 3, 7, 0)) for i in s['items']]                    # filmed at midnight
        out = SV.light(s, self.track(utc(2024, 9, 15, 11))); assert out['captured'] == 'night' and out['warning'] == 'Filmed at night, but the runner passes here in daylight: it would look wrong in the film.'

    def test_annotate_adds_the_light_when_it_has_the_track(self, tmp_path):
        docs = {'mapillary': doc(self.section())}; assert SV.annotate(str(tmp_path), docs)[0]['light'] is None
        assert SV.annotate(str(tmp_path), docs, self.track(utc(2024, 9, 15, 22)))[0]['light']['warning']


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
        assert fetched == [('M1', True, 'tok'), ('P1', True, 'tok')] and measured == [('M1', 0.5), ('P1', 0.5)] and len(log) == 2
        q = SV.quality_of(rd); assert q['mapillary:a:1.00']['grade'] == 'good' and q['panoramax:b:2.00']['grade'] == 'poor' and q['mapillary:a:1.00']['frames'] == 60 and set(q) == {'mapillary:a:1.00', 'panoramax:b:2.00'}
        assert SV.run(rd, {}, ['quality'], measure=measure, fetch=fetch) == [] and len(measured) == 2                                  # nothing new to score
        assert SV.run(rd, {}, ['quality'], force=True, measure=measure, fetch=fetch) == ['quality'] and len(measured) == 4
        out = {s['id']: s for s in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})}; assert out['M1']['quality']['score'] == 70 and out['M1']['quality']['grade'] == 'good' and out['M2']['quality'] is None and out['G1']['quality'] is None
        assert SV.status(rd)['quality'] == dict(done=True, scored=2, km=0) and 'quality' in SV.STAGES

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
        assert out['M1']['quality']['score'] is None and 'has not been fetched' in out['M1']['quality']['error'] and out['P1']['quality']['score'] == 60 and SV.status(rd)['quality']['scored'] == 1

    def test_the_quality_stage_needs_the_roads_and_mapillary_needs_its_token(self, tmp_path, monkeypatch):
        with pytest.raises(RuntimeError, match='roads stage first'): SV.run(str(tmp_path), {}, ['quality'])
        rd = str(tmp_path / 'p'); self.setup_docs(rd); monkeypatch.setattr(SV, '_key', lambda n: None); SV.run(rd, {}, ['quality'], measure=lambda *a, **k: dict(score=50, psnr=1, jerk=1, roll=1), fetch=lambda *a, **k: None)
        assert 'MAPILLARY_TOKEN' in SV.quality_of(rd)['mapillary:a:1.00']['error']
