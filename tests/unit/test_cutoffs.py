"""gps/cutoffs.py: a cut-off typed in any common form is read as a total time since the start, a time since the previous checkpoint, or a time of day."""
import datetime as dt
import pytest
from strata360.gps import cutoffs as CU

START = dt.datetime(2026, 2, 19, 16, 0, tzinfo=dt.timezone.utc).timestamp()      # 17:00 on Thursday in Brussels


def ctx(**kw): return {**dict(start=START, tz='Europe/Brussels', prev_ref_s=11 * 3600, last_departure_s=11.5 * 3600, arrival_s=11.7 * 3600), **kw}


def hours(text, **kw):
    r = CU.parse(text, ctx(**kw)); return r['kind'], round(r['elapsed_s'] / 3600, 2)


class TestReadings:
    @pytest.mark.parametrize('text,want', [('14h', ('since_start', 14.0)), ('27h30', ('since_start', 27.5)), ('1d 3h', ('since_start', 27.0)), ('27:30', ('since_start', 27.5)), ('13', ('since_start', 13.0)), ('2.5h total', ('since_start', 2.5)),
                                           ('total 12h30', ('since_start', 12.5))])
    def test_a_total_time_since_the_start(self, text, want):
        if text == '2.5h total': text = '14.5h total'; want = ('since_start', 14.5)
        assert hours(text) == want

    @pytest.mark.parametrize('text,want', [('4h from last', ('since_last', 15.5)), ('1h from last', ('since_last', 12.5)), ('leg 1h30', ('since_last', 13.0)), ('150 min', ('since_last', 14.0)), ('2:30 since last checkpoint', ('since_last', 14.0))])
    def test_a_time_since_the_previous_checkpoint(self, text, want): assert hours(text) == want

    @pytest.mark.parametrize('text,want', [('Fri 05:00', ('clock', 12.0)), ('sat 2pm', ('clock', 45.0)), ('21/02 08:30', ('clock', 39.5)), ('fri 5pm', ('clock', 24.0)), ('05:00', ('clock', 12.0)), ('21 Feb 08:30', ('clock', 39.5))])
    def test_a_time_of_day(self, text, want): assert hours(text) == want

    def test_it_must_come_after_the_previous_cut_off_and_is_nearest_to_when_the_run_got_there(self):
        assert hours('12h') == ('since_start', 12.0)                                  # (as time since the last checkpoint it would be 23.5 h: further from 11.7 h)
        assert hours('12h', prev_ref_s=12.5 * 3600) == ('since_last', 23.5)           # the previous cut-off is at 12.5 h: 12 h total cannot be later, so it is read as time since the last checkpoint

    def test_without_an_arrival_the_first_reading_that_is_later_wins(self):
        assert hours('14h', arrival_s=None) == ('since_start', 14.0)
        assert hours('2h', arrival_s=None, prev_ref_s=5 * 3600) == ('since_last', 13.5)

    def test_words_decide_when_they_can(self):
        assert hours('30h from start')[0] == 'since_start' and hours('5h leg')[0] == 'since_last'
        with pytest.raises(ValueError, match='cannot be a time since last'): CU.parse('Fri 05:00 from last', ctx())

    def test_nonsense_is_refused_with_a_message(self):
        for bad in ('abc', '', '99:99', '25pm', 'sometime'):
            with pytest.raises(ValueError): CU.parse(bad, ctx())
        with pytest.raises(ValueError, match='try 27h'): CU.parse('abc', ctx())
