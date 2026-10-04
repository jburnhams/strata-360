"""analysis/scenes.py: the scenes stage keeps the general answers of an earlier run for the same sampling (asking again only for the ones it lacks), always runs the scenery prompt, and summarises both, front and rear apart."""
import os
import re

import numpy as np
import pytest
from strata360.analysis import scenes as S

LOG = dict(setting='trail', description='a trail', people=0, crowd='none', lighting='dusk', weather='fog', water='stream', ground_snow=False, scenic=0.4, energy=0.3, lens_problems='none', tags=['trees'])
REAR = dict(LOG, setting='town', people=1, crowd='few', tags=['wall', 'runner'], water='none', ground_snow=True)
VIEWS = ((0, 0), (0, 180), (150, 0))                      # (frame, yaw): the image files are named by the view's yaw, and the model script reports that number as `view`


class Calls(list):
    def __init__(self): super().__init__(); self.seen = []; self.sizes = []


@pytest.fixture
def fake(monkeypatch, tmp_path):
    calls = Calls(); seen = calls.seen; sizes = calls.sizes                     # calls: (prompt, the image files it was asked about); seen: the `times` each image-writing call was given
    monkeypatch.setattr(S, 'video_pts', lambda osv, k: np.arange(0, 300) / 30.0)
    monkeypatch.setattr(S.V, 'proxy_available', lambda p: True)
    def write(proxy, osv, tmp, every=1, yaws=(0, 180), px=0, times=None, fov=None):
        seen.append(times); sizes.append((px, fov))
        for f, v in VIEWS: open(os.path.join(tmp, f's{f:05d}_v{v:03d}.jpg'), 'w').write('x')
    monkeypatch.setattr(S.V, 'write_stab_views_proxy', write)
    def vlm(py, src, tmp, out, models, prompt):
        files = sorted(n for n in os.listdir(tmp) if n.endswith('.jpg')); calls.append((prompt, files)); keys = [tuple(int(x) for x in re.findall(r'\d+', n)) for n in files]
        if prompt == 'scenery':
            ans = {(0, 0): dict(score=7, clarity=4, reason='open'), (0, 180): dict(score=3, clarity=2, reason='fog'), (150, 0): None}
            return dict(model='m', seconds=1.0, items=[dict(frame=f, view=v, answer=ans[(f, v)]) for f, v in keys])
        return dict(model='m', seconds=2.0, items=[dict(frame=f, view=v, answer=dict(REAR if v == 180 else LOG)) for f, v in keys])
    monkeypatch.setattr(S, '_vlm', vlm); return calls


def test_a_first_run_asks_both_prompts_and_keeps_the_front_and_rear_answers_apart(fake, tmp_path):
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0); assert [c[0] for c in fake] == ['scenery', 'log'] and r['schema'] == 3 and len(fake[1][1]) == 3
    f, rear, bad = r['items']; assert f['scenery'] == 7.0 and f['clarity'] == 4.0 and f['scenery_why'] == 'open' and f['setting'] == 'trail' and rear['view'] == 'rear' and rear['clarity'] == 2.0
    assert rear['ok'] is True and rear['setting'] == 'town' and rear['tags'] == ['wall', 'runner']                  # the rear answers are there, and are the rear's own
    assert bad['ok'] is True and bad['scenery'] is None and r['summary']['scenery_front'] == 7.0 and r['summary']['scenery_rear'] == 3.0 and r['summary']['clarity_front'] == 4.0
    s = r['summary']; assert s['front']['settings'] == {'trail': 2} and s['rear']['settings'] == {'town': 1} and s['front']['tags'] == ['trees'] and s['rear']['tags'] == ['wall', 'runner']
    assert s['front']['answered'] == 2 and s['rear']['answered'] == 1 and s['rear']['crowd'] == {'few': 1} and s['rear']['people'] == 1.0 and s['front']['scenery'] == 7.0 and s['rear']['clarity'] == 2.0


def test_an_earlier_run_for_the_same_sampling_is_not_asked_again_front_or_rear(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); fake.clear()
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=prev); assert [c[0] for c in fake] == ['scenery']
    assert r['items'][0]['setting'] == 'trail' and r['items'][0]['scenery'] == 7.0 and r['items'][1]['view'] == 'rear' and r['items'][1]['setting'] == 'town' and r['summary']['rear']['answered'] == 1     # the rear answer survives the reuse


def test_the_rear_answers_an_old_file_lacks_are_asked_for_and_only_those(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0)
    for i in prev['items']:                                                                               # the shape of the files written before the fix: every rear general answer empty
        if i['view'] == 'rear': i.update(ok=False, setting=None, tags=None, crowd=None, people=None)
    fake.clear(); r = S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=prev)
    assert [c[0] for c in fake] == ['scenery', 'log'] and fake[1][1] == ['s00000_v180.jpg']                  # the general prompt is run on the one missing image
    assert r['items'][1]['ok'] is True and r['items'][1]['setting'] == 'town' and r['items'][0]['setting'] == 'trail' and r['summary']['rear']['answered'] == 1


def test_another_sampling_or_no_earlier_run_means_the_general_prompt_runs_again(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=10.0, previous=prev); assert [c[0] for c in fake] == ['scenery', 'log'] and len(fake[1][1]) == 3
    assert S.reusable(None, 5.0) == {} and S.reusable(dict(sample_every_s=5.0, items=[]), 5.0) == {}


def test_reusable_answers_are_keyed_by_the_view_number_in_the_file_names(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); keys = set(S.reusable(prev, 5.0)); assert keys == {(0, 0), (0, 180), (150, 0)}


def test_adaptive_times_go_to_the_image_writer_and_answers_are_only_reused_for_the_same_kind_of_sampling(fake, tmp_path):
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0, times=[1.0, 7.5]); assert fake.seen == [[1.0, 7.5]] and r['sampling'] == 'adaptive'
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=r); assert [c[0] for c in fake] == ['scenery', 'log']                # an adaptive run is not reused by a fixed one
    fake.clear(); again = S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=r, times=[1.0, 7.5]); assert [c[0] for c in fake] == ['scenery'] and again['sampling'] == 'adaptive'
    assert S.reusable(r, 5.0) == {} and set(S.reusable(r, 5.0, 'adaptive')) == {(0, 0), (0, 180), (150, 0)}
    assert S.analyse('x.osv', str(tmp_path), every_s=5.0)['sampling'] == 'fixed'


def test_answers_from_pictures_of_another_size_or_field_of_view_are_not_reused(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0, px=768, fov=100.0); assert prev['px'] == 768 and prev['fov'] == 100.0 and fake.sizes[-1] == (768, 100.0)
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, px=512, fov=100.0, previous=prev); assert [c[0] for c in fake] == ['scenery', 'log'] and fake.sizes[-1] == (512, 100.0)
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, px=768, fov=120.0, previous=prev); assert [c[0] for c in fake] == ['scenery', 'log']
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, px=768, fov=100.0, previous=prev); assert [c[0] for c in fake] == ['scenery']
    old = dict(prev); old.pop('px'); old.pop('fov'); fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, px=768, fov=100.0, previous=old); assert [c[0] for c in fake] == ['scenery']                  # files from before these were recorded were made at 768 and 100


def test_answers_made_by_another_model_are_not_reused(fake, tmp_path):
    prev = S.analyse('x.osv', str(tmp_path), every_s=5.0); assert prev['model'] == 'm'
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=dict(prev, model='older')); assert [c[0] for c in fake] == ['scenery', 'log']
    fake.clear(); S.analyse('x.osv', str(tmp_path), every_s=5.0, previous=prev); assert [c[0] for c in fake] == ['scenery'] and S.reusable(prev, 5.0) != {} and S.reusable(prev, 5.0, model='other') == {}


def test_a_foggy_scene_is_not_recorded_as_a_fogged_lens():
    assert S.item(dict(LOG, weather='fog', lens_problems='fog'), None)['lens_problems'] == 'none' and S.item(dict(LOG, weather='unknown', lens_problems='fog'), None)['lens_problems'] == 'fog'
    assert S.item(dict(LOG, weather='fog', lens_problems='blocked'), None)['lens_problems'] == 'blocked' and S.item(None, None)['ok'] is False


def test_the_summary_says_where_there_is_water_and_snow_on_the_ground_for_each_direction(fake, tmp_path):
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0); s = r['summary']
    assert s['front']['water'] == {'stream': 2} and s['rear']['water'] == {} and s['front']['ground_snow'] == 0.0 and s['rear']['ground_snow'] == 1.0
    assert r['items'][0]['water'] == 'stream' and r['items'][1]['ground_snow'] is True and 'mood' not in r['items'][0] and r['px'] == 512 and r['fov'] == 120.0


def test_a_run_with_the_sun_field_records_the_sun_in_the_summary_and_a_finished_file_can_be_patched_without_the_model(fake, tmp_path):
    import json
    from strata360.gps import sun as SUN
    sun = dict(covered=True, duration_s=60.0, start=dict(elevation_deg=-3.0), mid=dict(elevation_deg=-3.5), end=dict(elevation_deg=-4.0), elevation_deg=-3.5, daylight='twilight')
    r = S.analyse('x.osv', str(tmp_path), every_s=5.0, sun=sun); assert r['summary']['sun'] == dict(elevation_deg=-3.5, daylight='twilight') and r['items'][0]['lighting'] == 'dusk' and 'lighting_model' not in r['items'][0]            # the model already said dusk: nothing to correct
    plain = S.analyse('x.osv', str(tmp_path), every_s=5.0); assert 'sun' not in plain['summary'] and plain['items'][0]['lighting'] == 'dusk'
    plain['items'][0]['lighting'] = 'overcast'; plain['items'][1]['lighting'] = 'overcast'; d = tmp_path / 'clip'; d.mkdir(); json.dump(plain, open(d / 'scenes.json', 'w'))
    assert S.patch_sun(str(d)) is False                                                                  # no sun field yet: nothing to do
    json.dump(sun, open(d / SUN.FILE, 'w')); assert S.patch_sun(str(d)) is True; got = json.load(open(d / 'scenes.json')); assert got['items'][0]['lighting'] == 'dusk' and got['items'][0]['lighting_model'] == 'overcast' and got['summary']['sun']['daylight'] == 'twilight'
    assert S.patch_sun(str(d)) is False and S.patch_sun(str(tmp_path / 'none')) is False
