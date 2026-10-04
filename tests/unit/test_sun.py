"""gps/sun.py: the one place the sun's height becomes a label, the per-clip field, and what reads it (the clip card, the scene labels)."""
import json

import numpy as np
import pytest
from overlay_fakes import race_track

from strata360.analysis import scenes as S
from strata360.gps import clock as CK, series, sun as SUN

NOON = 1771588800.0                      # 2026-02-20 12:00:00 UTC; Brussels is at 50.8 N, 4.4 E
BRUSSELS = dict(lat0=50.8, lon0=4.4)


def clip(start=NOON, seconds=60, fps=25.0):
    from datetime import datetime, timezone
    return dict(time=dict(start_utc=datetime.fromtimestamp(start, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')), video=dict(source_frames=int(seconds * fps), nominal_fps=fps))


def track(start=NOON - 3600, n=40000):
    return race_track(n=n, t0=start, **BRUSSELS)


@pytest.mark.parametrize('elev, label', [(30, 'day'), (6.1, 'day'), (6.0, 'golden hour'), (0.1, 'golden hour'), (0.0, 'twilight'), (-11.9, 'twilight'), (-12.0, 'night'), (-40, 'night')])
def test_the_sun_elevation_becomes_a_label_with_the_boundaries_the_clip_card_has_always_used(elev, label):
    assert SUN.daylight(elev) == label


def test_daylight_at_a_place_and_time_is_the_label_of_the_computed_elevation_and_none_when_something_is_unknown():
    assert SUN.daylight_at(50.8, 4.4, NOON) == 'day' and SUN.daylight_at(50.8, 4.4, NOON + 8 * 3600) == 'night'
    assert SUN.daylight_at(50.8, 4.4, NOON + 3000) == SUN.daylight(float(CK.sun_elevation_deg(50.8, 4.4, NOON + 3000)))
    assert SUN.daylight_at(None, 4.4, NOON) is None and SUN.daylight_at(50.8, None, NOON) is None and SUN.daylight_at(50.8, 4.4, None) is None


def test_a_clip_gets_the_sun_at_its_start_middle_and_end_and_whether_the_label_changes():
    s = SUN.analyse(clip(NOON, 60), track()); assert s['covered'] and s['daylight'] == 'day' and s['elevation_deg'] == s['mid']['elevation_deg'] and 15 < s['elevation_deg'] < 40 and not s['changes']
    assert s['start']['local'].endswith('13:00') and set(s['start']) == {'t_utc', 'local', 'lat', 'lon', 'elevation_deg', 'daylight'} and s['duration_s'] == 60.0
    dusk = SUN.analyse(clip(NOON + 4.5 * 3600, 3600), track(NOON, 40000)); assert dusk['start']['elevation_deg'] > dusk['end']['elevation_deg'] and dusk['lowest_deg'] == dusk['end']['elevation_deg'] and dusk['highest_deg'] == dusk['start']['elevation_deg']
    assert SUN.analyse(clip(NOON + 7.5 * 3600, 600), track(NOON, 40000))['daylight'] == 'night'


def test_a_clip_the_track_does_not_reach_is_not_covered():
    t = track(NOON - 3600, 600)
    for start in (NOON - 7200, NOON + 36000):
        s = SUN.analyse(clip(start, 60), t); assert s == dict(schema=1, covered=False, note=s['note'], duration_s=60.0) and 'outside' in s['note']
    nan = dict(t, lat=np.full(600, np.nan)); assert SUN.analyse(clip(NOON - 3000, 60), nan)['covered'] is False


def test_the_field_is_read_back_from_the_clip_folder_and_its_elevation_is_interpolated_across_the_clip(tmp_path):
    assert SUN.load(str(tmp_path)) is None and SUN.elevation_in_clip(None, 5) is None and SUN.elevation_in_clip(dict(covered=False), 5) is None
    doc = SUN.analyse(clip(NOON, 600), track()); json.dump(doc, open(tmp_path / 'sun.json', 'w')); got = SUN.load(str(tmp_path)); assert got == doc
    fake = dict(covered=True, duration_s=100.0, start=dict(elevation_deg=10.0), mid=dict(elevation_deg=4.0), end=dict(elevation_deg=-2.0))
    assert SUN.elevation_in_clip(fake, 0) == 10.0 and SUN.elevation_in_clip(fake, 25) == pytest.approx(7.0) and SUN.elevation_in_clip(fake, 100) == -2.0 and SUN.elevation_in_clip(fake, 500) == -2.0
    (tmp_path / 'sun.json').write_text('not json'); assert SUN.load(str(tmp_path)) is None


def test_the_clip_card_takes_the_stored_sun_field_when_there_is_one_and_works_it_out_when_there_is_not():
    t = track(); spans = [dict(id='a', t0=NOON, t1=NOON + 60), dict(id='b', t0=NOON + 600, t1=NOON + 660)]
    plain = series.clips(t, spans); assert plain[0]['facts']['daylight'] == 'day' and plain[1]['facts']['daylight'] == 'day'
    stored = dict(covered=True, daylight='twilight', elevation_deg=-3.5)
    got = series.clips(t, spans, sun_of=lambda cid: stored if cid == 'a' else None); assert got[0]['facts']['daylight'] == 'twilight' and 'twilight' in got[0]['facts']['text'] and got[1]['facts']['daylight'] == 'day'
    assert series.clips(t, spans, sun_of=lambda cid: dict(covered=False))[0]['facts']['daylight'] == 'day'


def _doc(lighting, times=(0.0, 30.0, 60.0)):
    items = [dict(frame=i, t_s=t, view='front', ok=True, lighting=lg, setting='road', tags=[]) for i, (t, lg) in enumerate(zip(times, lighting))]
    return dict(items=items, summary=S.summarise(items))


def test_a_picture_called_overcast_or_bright_while_the_sun_is_in_twilight_becomes_dusk_and_the_model_keeps_its_answer():
    sun = SUN.analyse(clip(NOON + 4.9 * 3600, 3600), track(NOON, 40000)); assert sun['start']['daylight'] in ('golden hour', 'twilight') and sun['end']['daylight'] in ('twilight', 'night')
    doc = S.apply_sun(_doc(['overcast', 'bright', 'headlamp'], (0.0, 1800.0, 3500.0)), sun); lg = [i['lighting'] for i in doc['items']]
    assert all('sun_elevation_deg' in i for i in doc['items']) and doc['summary']['sun'] == dict(elevation_deg=sun['elevation_deg'], daylight=sun['daylight'])
    changed = [i for i in doc['items'] if 'lighting_model' in i]; assert changed and all(i['lighting'] == 'dusk' and i['lighting_model'] in ('overcast', 'bright') for i in changed) and doc['items'][2]['lighting'] == 'headlamp'
    assert 'dusk' in doc['summary']['lighting'] and S.apply_sun(doc, sun)['items'] == doc['items']                  # repeating changes nothing more


def test_in_daylight_or_without_a_sun_field_the_labels_stay_as_the_model_gave_them():
    day = SUN.analyse(clip(NOON, 600), track()); doc = S.apply_sun(_doc(['overcast', 'bright', 'overcast']), day); assert [i['lighting'] for i in doc['items']] == ['overcast', 'bright', 'overcast'] and not any('lighting_model' in i for i in doc['items'])
    assert 'sun' in doc['summary'] and S.apply_sun(_doc(['overcast']), None)['items'][0]['lighting'] == 'overcast' and 'sun' not in S.apply_sun(_doc(['overcast']), dict(covered=False))['summary']


def test_a_picture_taken_indoors_keeps_the_models_lighting_in_twilight():
    sun = SUN.analyse(clip(NOON + 4.9 * 3600, 3600), track(NOON, 40000)); doc = _doc(['bright', 'bright'], (1800.0, 3500.0)); doc['items'][0]['setting'] = 'indoor'
    S.apply_sun(doc, sun); assert doc['items'][0]['lighting'] == 'bright' and 'lighting_model' not in doc['items'][0] and doc['items'][1]['lighting'] == 'dusk'
