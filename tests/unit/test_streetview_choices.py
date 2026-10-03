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
