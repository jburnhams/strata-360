import numpy as np
import pytest
from strata360.gps import context

def test_daylight():
    assert context.daylight(7.0) == 'day'
    assert context.daylight(3.0) == 'golden hour'
    assert context.daylight(-5.0) == 'twilight'
    assert context.daylight(-15.0) == 'night'

def test_context_at_outside_race():
    tr = dict(t=np.array([1000.0, 1100.0]), lat=np.array([0.0, 0.0]), lon=np.array([0.0, 0.0]))
    c = context.context_at(tr, 0.0, 500.0)
    assert not c['covered']
    assert 'outside the race track' in c['note']

    c2 = context.context_at(tr, 2000.0, 2500.0)
    assert not c2['covered']

def test_context_at_inside_race(monkeypatch):
    monkeypatch.setattr(context, 'sun_elevation_deg', lambda lat, lon, t: 45.0)

    t = np.arange(1000.0, 2000.0, 10.0)
    lat = np.full_like(t, 50.0)
    lon = np.full_like(t, 4.0)
    alt = np.linspace(100.0, 200.0, len(t))
    speed = np.full_like(t, 2.5)
    hr = np.full_like(t, 150.0)
    cadence = np.full_like(t, 85.0)
    dist = np.linspace(0.0, 2500.0, len(t))

    tr = dict(t=t, lat=lat, lon=lon, alt=alt, speed=speed, hr=hr, cadence=cadence, dist=dist)

    c = context.context_at(tr, 1500.0, 1560.0)

    assert c['covered']
    assert c['lat'] == 50.0
    assert c['lon'] == 4.0
    assert c['altitude_m'] == 154.0
    assert c['speed_kmh'] == 9.0
    assert c['pace_min_per_km'] == 6.67
    assert c['moving'] is True
    assert c['gradient_pct'] == 4.0
    assert c['heart_rate'] == 150
    assert c['cadence_spm'] == 170
    assert c['distance_km'] == 1.3
    assert c['race_total_km'] == 2.5
    assert c['percent_of_distance'] == 53.5
    assert c['daylight'] == 'day'

def test_context_at_missing_fields(monkeypatch):
    monkeypatch.setattr(context, 'sun_elevation_deg', lambda lat, lon, t: -10.0)

    t = np.arange(1000.0, 2000.0, 10.0)
    lat = np.full_like(t, 50.0)
    lon = np.full_like(t, 4.0)

    nan_array = np.full_like(t, np.nan)
    tr = dict(t=t, lat=lat, lon=lon, alt=nan_array, speed=nan_array, hr=nan_array, cadence=nan_array, dist=nan_array)

    c = context.context_at(tr, 1500.0, 1560.0)

    assert c['covered']
    assert c['altitude_m'] is None
    assert c['speed_kmh'] is None
    assert c['moving'] is False
    assert c['heart_rate'] is None
    assert c['distance_km'] is None
    assert c['daylight'] == 'twilight'

def test_describe_not_covered():
    c = dict(covered=False, note="way off")
    assert context.describe(c) == "way off"

def test_describe_full_fields():
    c = dict(
        covered=True,
        local_date="Sat 21 Feb",
        local_time="14:00",
        daylight="day",
        race_day=1,
        elapsed_h=4.5,
        distance_km=42.0,
        race_total_km=100.0,
        percent_of_distance=42.0,
        pace_min_per_km=5.5,
        moving=True,
        speed_kmh=10.9,
        gradient_pct=4.2,
        altitude_m=1200,
        heart_rate=155
    )
    desc = context.describe(c)
    assert "Sat 21 Feb 14:00 local (day)" in desc
    assert "4.5 h in" in desc
    assert "km 42.0 of 100.0 (42% of the distance)" in desc
    assert "pace 5:30 min/km (10.9 km/h)" in desc
    assert "climbing (+4%)" in desc
    assert "1200 m altitude" in desc
    assert "heart rate 155" in desc

def test_describe_missing_fields_and_stopped():
    c = dict(
        covered=True,
        local_date="Sun 22 Feb",
        local_time="02:00",
        daylight="night",
        race_day=2,
        elapsed_h=16.5,
        distance_km=None,
        pace_min_per_km=None,
        moving=False,
        gradient_pct=-5.1,
        altitude_m=None,
        heart_rate=None
    )
    desc = context.describe(c)
    assert "Sun 22 Feb 02:00 local (night)" in desc
    assert "stopped or walking very slowly" in desc
    assert "descending (-5%)" in desc
    assert "altitude" not in desc
    assert "heart rate" not in desc
