import numpy as np
import pytest
from strata360.gps.context import daylight, context_at, describe

class TestDaylight:
    def test_daylight_ranges(self):
        assert daylight(10.0) == 'day'
        assert daylight(7.0) == 'day'
        assert daylight(3.0) == 'golden hour'
        assert daylight(0.5) == 'golden hour'
        assert daylight(-5.0) == 'twilight'
        assert daylight(-11.0) == 'twilight'
        assert daylight(-13.0) == 'night'
        assert daylight(-90.0) == 'night'

class TestContextAt:
    def make_track(self):
        n = 200
        # times from 1000 to 1199
        t = np.arange(1000.0, 1200.0)
        # 0.0 at 1000 to 20.0 at 1200
        lat = np.linspace(50.0, 50.1, n)
        lon = np.linspace(4.0, 4.1, n)
        alt = np.linspace(100.0, 200.0, n)
        speed = np.ones(n) * 3.0 # 10.8 km/h, 5:33 min/km
        hr = np.ones(n) * 140.0
        cadence = np.ones(n) * 80.0 # 160 spm
        dist = np.linspace(0, 1000.0, n)
        return dict(t=t, lat=lat, lon=lon, alt=alt, speed=speed, hr=hr, cadence=cadence, dist=dist)

    def test_out_of_bounds(self):
        tr = self.make_track()
        res = context_at(tr, 800.0, 900.0)
        assert res['covered'] is False
        assert 'outside the race track' in res['note']

        res2 = context_at(tr, 1300.0, 1400.0)
        assert res2['covered'] is False

    def test_happy_path(self):
        tr = self.make_track()
        # t0=1050, t1=1150, mid=1100
        # mid is exactly halfway through the race
        res = context_at(tr, 1050.0, 1150.0, tz='UTC')
        assert res['covered'] is True
        assert res['lat'] == 50.05025
        assert res['lon'] == 4.05025
        assert res['altitude_m'] == 150.0
        assert res['speed_kmh'] == 10.8
        assert res['pace_min_per_km'] == 5.56
        assert res['moving'] is True
        assert res['heart_rate'] == 140.0
        assert res['cadence_spm'] == 160.0
        assert res['distance_km'] == 0.5
        assert res['race_total_km'] == 1.0
        # distance goes from 0 to 1000m uniformly over 199 segments? It goes over 200 points.
        # point 0 is at 0m. point 199 is at 1000m.
        # mid is at t=1100.
        assert np.isclose(res['percent_of_distance'], 50.3, atol=0.1)
        # duration is 199s, mid is 100s in. 100/199 = ~50.25%
        assert np.isclose(res['percent_of_time'], 50.3, atol=0.1)
        assert res['elapsed_h'] == 0.03
        assert res['race_day'] == 1
        # timestamp 1100 UTC -> 1970-01-01 00:18:20
        assert res['local_time'] == '00:18'
        assert '1970' not in res['local_date'] # format is '%a %d %b' e.g. Thu 01 Jan
        assert 'Jan' in res['local_date']

    def test_gradient_calculation(self):
        tr = self.make_track()
        # distance goes 0 to 1000m, altitude goes 100 to 200m.
        # climb is 100m over 1000m -> 10%
        res = context_at(tr, 1050.0, 1150.0)
        assert res['gradient_pct'] == 10.0

    def test_handles_nans_and_missing_fields(self):
        tr = self.make_track()
        n = len(tr['t'])
        nan = np.full(n, np.nan)
        tr['alt'] = nan
        tr['dist'] = nan
        tr['hr'] = nan
        tr['cadence'] = nan
        tr['speed'] = nan

        res = context_at(tr, 1050.0, 1150.0)
        assert res['altitude_m'] is None
        assert res['distance_km'] is None
        assert res['race_total_km'] is None
        assert res['heart_rate'] is None
        assert res['cadence_spm'] is None
        assert res['speed_kmh'] is None
        assert res['pace_min_per_km'] is None
        assert res['moving'] is False
        assert res['gradient_pct'] is None

class TestDescribe:
    def test_describe_not_covered(self):
        assert describe({'covered': False}) == 'no track data'
        assert describe({'covered': False, 'note': 'foo'}) == 'foo'

    def test_describe_happy_path(self):
        c = {
            'covered': True,
            'local_date': 'Sat 21 Feb',
            'local_time': '12:00',
            'daylight': 'day',
            'race_day': 2,
            'elapsed_h': 24.5,
            'distance_km': 150.2,
            'race_total_km': 300.0,
            'percent_of_distance': 50.1,
            'pace_min_per_km': 5.5,
            'speed_kmh': 10.9,
            'moving': True,
            'gradient_pct': 5.0,
            'altitude_m': 2000.0,
            'heart_rate': 145.0
        }
        res = describe(c)
        assert 'Sat 21 Feb 12:00 local (day), race day 2, 24.5 h in' in res
        assert 'km 150.2 of 300.0 (50% of the distance)' in res
        # 5.5 min/km -> 5 min + 0.5 * 60 = 5:30
        assert 'pace 5:30 min/km (10.9 km/h)' in res
        assert 'climbing (+5%)' in res
        assert '2000 m altitude' in res
        assert 'heart rate 145.0' in res

    def test_describe_not_moving(self):
        c = {
            'covered': True,
            'local_date': 'Sat 21 Feb',
            'local_time': '12:00',
            'daylight': 'night',
            'race_day': 2,
            'elapsed_h': 24.5,
            'moving': False
        }
        res = describe(c)
        assert 'stopped or walking very slowly' in res

    def test_describe_descending_and_flat(self):
        c = {
            'covered': True,
            'local_date': 'Sat',
            'local_time': '12',
            'daylight': 'day',
            'race_day': 1,
            'elapsed_h': 1.0,
            'gradient_pct': -5.0
        }
        assert 'descending (-5%)' in describe(c)

        c['gradient_pct'] = 1.0
        assert 'flat (+1%)' in describe(c)
