"""analysis/objects.py: from the detector's boxes to the objects of a clip (gates, candidates, de-duplication, memory, routing by the word statistics, the labelling model's part), with the detector, the labelling model and the lens frames faked."""
import json
import os

import numpy as np
import pytest
from strata360.analysis import objects as O, regions as R, vocab as VOC

TILE = O.TILES.index((15, 0.0))               # a tile looking ahead and a little up
MID = [472, 472, 552, 552]                     # a box in the middle of a tile picture


def test_a_box_in_the_middle_of_a_tile_is_in_the_tiles_direction():
    lo, la = O.direction(TILE, MID); assert abs(lo) < 0.5 and abs(la - 15) < 0.5
    lo2, _ = O.direction(O.TILES.index((15, 360 / 7 * 2)), MID); assert abs(lo2 - 360 / 7 * 2) < 0.5


def test_a_clip_is_dark_only_when_the_sun_is_low_and_the_picture_dim():
    frames = lambda v: dict(frames=[dict(t_s=float(i), sphere=dict(mean_lin=v)) for i in range(5)])
    sun = lambda e: dict(covered=True, elevation_deg=e)
    assert 'night' in O.clip_is_dark(sun(-36), frames(0.002)) and O.clip_is_dark(sun(-15), frames(0.29)) is None            # a lit indoor aid station at night is not dark
    assert O.clip_is_dark(sun(10), frames(0.001)) is None and O.clip_is_dark(None, frames(0.0)) is None and O.clip_is_dark(dict(covered=False), None) is None and O.clip_is_dark(sun(-30), None) is None


def test_a_black_moment_is_found_from_the_nearest_exposure_frame():
    ex = dict(frames=[dict(t_s=0.0, sphere=dict(mean_lin=0.001)), dict(t_s=2.0, sphere=dict(mean_lin=0.3))])
    assert O.black_at(ex, 0.4) and not O.black_at(ex, 1.9) and not O.black_at(None, 0) and not O.black_at(dict(frames=[]), 0) and not O.black_at(dict(frames=[dict(t_s=0.0, sphere=dict(mean_lin=0.0))]), 30.0)


def test_the_wearers_direction_comes_from_the_samples_around_the_moment():
    foc = [dict(t=0.0, yaw=350.0, pitch=-20, height=60), dict(t=1.0, yaw=10.0, pitch=-30), dict(t=9.0, yaw=0, pitch=0)]
    assert O.wearer_dirs(foc, 0.5) == [(-10.0, -20, 60.0), (10.0, -30, 40.0)] and O.wearer_dirs(foc, 5.0) == [] and O.wearer_dirs(None, 1.0) == []


def test_candidates_leave_out_people_worn_gear_big_scenery_tiny_boxes_and_anything_already_named():
    named = [('person', 0.9, MID), ('tree', 0.8, [0, 0, 100, 400]), ('sign', 0.6, [100, 100, 160, 160]), ('sign', 0.1, [300, 300, 360, 360]), ('chicken', 0.12, [600, 600, 660, 660]), ('car', 0.9, [10, 10, 14, 14]), ('house', 0.9, [0, 0, 1024, 900])]
    pf = [('thing', 0.5, [700, 100, 780, 180]), ('thing', 0.2, [700, 300, 780, 380]), ('hand', 0.9, [800, 800, 860, 860]), ('post', 0.9, [105, 105, 155, 155])]
    c, people = O.tile_candidates(TILE, named, pf, low_words={'chicken'})
    assert sorted((x['kind'], x['yoloe']) for x in c) == [('named', 'chicken'), ('named', 'sign'), ('other', 'thing')]       # the low-confidence sign, tiny car, huge house, hand and the post inside the sign are out
    assert len(people) == 1 and people[0]['deg'] == pytest.approx(80 / O.PPD)
    assert O.areas_of(named) == {'tree': 0.8}


def test_the_same_thing_in_two_tiles_is_one_candidate_and_the_wearers_is_marked():
    c = lambda lo, la, cf: dict(kind='named', yoloe='sign', conf=cf, lon=lo, lat=la, deg=3.0)
    out = O.merge_moment([c(10, 5, 0.5), c(10.5, 5, 0.7), c(120, 0, 0.6), c(-170, -40, 0.6)], [], [(-170, -35, 40)])
    assert [(x['lon'], x['wearer']) for x in out] == [(10.5, False), (120, False), (-170, False)]
    assert O.merge_moment([c(0, 0, 0.5)], [dict(lon=1, lat=0, deg=5)], [])[0]['wearer'] is True and O.merge_moment([c(0, 0, 0.5)], [dict(lon=2.5, lat=0, deg=5)], [])[0]['wearer'] is False       # a named box 2.5 degrees from a 5 degree person is a chair beside them
    assert O.merge_moment([dict(c(0, 0, 0.5), kind='other')], [dict(lon=2.5, lat=0, deg=5)], [])[0]['wearer'] is True
    named, other = c(-170, -40, 0.6), dict(c(-170, -40, 0.6), kind='other'); assert O.merge_moment([named], [], [(-170, -35, 40)])[0]['wearer'] is False and O.merge_moment([other], [], [(-170, -35, 40)])[0]['wearer'] is True     # a named thing next to the wearer is kept
    assert O.merge_moment([dict(other, lon=-170 + 25)], [], [(-170, -35, 40)])[0]['wearer'] is False                                                                                                                           # outside the wearer's own size


def test_an_object_seen_again_is_the_same_object_unless_it_is_elsewhere_or_another_size():
    m = O.Memory(); c = lambda lo, la, d, cf=0.5: dict(kind='named', yoloe='sign', conf=cf, lon=lo, lat=la, deg=d)
    a, new = m.see(c(10, 0, 3), 1.0); assert new
    b, new = m.see(c(10.8, 0.3, 3, 0.9), 2.0); assert not new and b is a and a['seen'] == [1.0, 2.0] and a['conf'] == 0.9 and a['best_t'] == 2.0
    assert m.see(c(40, 0, 3), 3.0)[1] and m.see(c(10, 0, 30), 3.5)[1] and len(m.objects) == 3
    assert O.crop_fov(1.0) == 10.0 and O.crop_fov(100.0) == 60.0 and O.crop_fov(10.0) == pytest.approx(18.0)


# ---- the whole run, with fakes ------------------------------------------------------------------------------------------------------------------------------------------------------
class Lens:
    def __init__(self): self.calls = []
    def crop(self, t, lon, lat, fov, px=448):
        self.calls.append((t, round(float(np.degrees(lon)), 1), round(float(np.degrees(lat)), 1), fov, px)); return np.full((px, px, 3), 120, np.uint8)


def fakes(named_by_moment, labels, pf_by_moment=None):
    """A detector that finds the given named boxes in tile TILE of each moment, and a labelling model that answers `labels` (by object number) for the crops it is given."""
    seen = dict(detect=[], label=[])
    def detect(images, words, out):
        seen['detect'].append((sorted(os.listdir(images))[:1], list(words))); files = {}
        for name in sorted(os.listdir(images)):
            if not name.endswith('.jpg'): continue
            m, k = int(name[1:4]), int(name[6:8]); files[name] = dict(named=named_by_moment.get(m, []) if k == TILE else [], pf=(pf_by_moment or {}).get(m, []) if k == TILE else [])
        return dict(files=files)
    def label(images, out):
        names = sorted(os.listdir(images)); seen['label'].append(names); return dict(model='fake-vlm', seconds=1.5, labels={n: labels[int(n[1:4])] for n in names})
    return detect, label, seen


def run(tmp_path, detect, label, times=(1.0, 2.0), stats=None, **kw):
    v = VOC.load(); words = VOC.words_for(['farm_rural'], v)
    return O.analyse('x.osv', str(tmp_path), list(times), words, stats=stats or VOC.StatsBook(), vocab=v, categories=['farm_rural'], detect=detect, label=label, renderer=Lens(), clip='CAM_0013', crops_to=str(tmp_path / 'objects'), **kw)


def test_a_clip_run_names_each_thing_once_with_the_labelling_model_and_records_how_the_detector_did(tmp_path):
    named = {0: [('goat', 0.5, MID)], 1: [('goat', 0.6, [470, 470, 554, 554])]}                 # the same goat at both moments
    detect, label, seen = fakes(named, {0: 'black goat'}, pf_by_moment={0: [('thing', 0.5, [700, 100, 780, 180])]}); label_1 = label
    seen_labels = {0: 'black goat', 1: 'street light'}; detect, label, seen = fakes(named, seen_labels, pf_by_moment={0: [('thing', 0.5, [700, 100, 780, 180])]})
    doc = run(tmp_path, detect, label)
    assert doc['schema'] == 1 and doc['model'] == 'fake-vlm' and doc['counts']['tiles'] == 2 * len(O.TILES) and len(seen['detect']) == 1 and 'goat' in seen['detect'][0][1]
    goat, other = doc['objects']; assert goat['yoloe'] == 'goat' and goat['label'] == 'black goat' and goat['word'] == 'goat' and goat['seen'] == [1.0, 2.0] and goat['source'] == 'vlm' and goat['conf'] == 0.6
    assert other['kind'] == 'other' and other['label'] == 'street light' and other['word'] == 'street light' and seen['label'] == [['o000.jpg', 'o001.jpg']]
    st = VOC.StatsBook(doc['stats']); assert st.words['goat']['fired'] == 1 and st.words['goat']['agreed'] == 1 and st.suggest['street light']['count'] == 1 and st.cats['farm_rural']['uses'] == 1
    assert sorted(os.listdir(tmp_path / 'objects')) == ['o000.jpg', 'o001.jpg'] and not [d for d in os.listdir(tmp_path) if d.startswith('s360obj_')]       # the crops are kept, the work folder is gone


def test_a_trusted_word_keeps_the_detectors_name_and_the_labelling_model_is_not_asked(tmp_path):
    book = VOC.StatsBook(dict(words=dict(sign=dict(fired=40, agreed=40, false_positive=0, mislabels={}))))
    detect, label, seen = fakes({0: [('sign', 0.8, MID)]}, {}); doc = run(tmp_path, detect, label, times=(1.0,), stats=book, rng=type('R', (), {'random': lambda self: 0.99})())
    o, = doc['objects']; assert o['route'] == 'accept' and o['source'] == 'detector' and o['label'] == 'sign' and o['word'] == 'sign' and seen['label'] == [] and doc['model'] is None
    detect, label, seen = fakes({0: [('sign', 0.8, MID)]}, {0: 'blue sign'}); doc = run(tmp_path, detect, label, times=(1.0,), stats=book, rng=type('R', (), {'random': lambda self: 0.0})())      # the audit: asked anyway
    assert doc['objects'][0]['route'] == 'audit' and doc['objects'][0]['label'] == 'blue sign' and VOC.StatsBook(doc['stats']).words['sign']['fired'] == 1


def test_labels_that_are_not_things_are_dropped_and_counted(tmp_path):
    detect, label, seen = fakes({0: [('goat', 0.5, MID)], 1: []}, {0: 'unclear'}); doc = run(tmp_path, detect, label)
    assert doc['objects'] == [] and doc['dropped_by_stoplist'] == 1 and VOC.StatsBook(doc['stats']).words['goat']['false_positive'] == 1


def test_big_scenery_words_are_counted_per_clip_not_labelled(tmp_path):
    detect, label, seen = fakes({0: [('snow', 0.7, [0, 0, 600, 600]), ('river', 0.4, [0, 0, 300, 300])]}, {}); doc = run(tmp_path, detect, label, times=(1.0,))
    assert doc['objects'] == [] and doc['areas'] == {'snow': dict(boxes=1, max_conf=0.7), 'river': dict(boxes=1, max_conf=0.4)} and seen['label'] == []


def test_the_wearer_tiny_boxes_black_moments_and_night_clips_are_never_looked_at(tmp_path):
    detect, label, seen = fakes({0: [('goat', 0.5, MID)]}, {0: 'goat'}); foc = [dict(t=1.0, yaw=0.0, pitch=15.0, height=40)]
    doc = run(tmp_path, detect, label, times=(1.0,), focus=foc); assert doc['objects'] != [] and doc['counts']['wearer'] == 0       # a named goat in the wearer's direction is kept
    detect, label, seen = fakes({}, {0: 'goat'}, pf_by_moment={0: [('thing', 0.5, MID)]}); doc = run(tmp_path, detect, label, times=(1.0,), focus=foc); assert doc['objects'] == [] and doc['counts']['wearer'] == 1 and doc['wearer_dropped'][0]['yoloe'] == 'thing'
    detect, label, seen = fakes({0: [('goat', 0.5, MID)]}, {0: 'goat'})
    detect, label, seen = fakes({0: [('goat', 0.5, [500, 500, 510, 509])]}, {0: 'goat'}); doc = run(tmp_path, detect, label, times=(1.0,)); assert doc['counts']['tiny'] == 1 and doc['objects'] == []
    detect, label, seen = fakes({0: [('goat', 0.5, MID)]}, {0: 'goat'}); ex = dict(frames=[dict(t_s=1.0, sphere=dict(mean_lin=0.001))]); doc = run(tmp_path, detect, label, times=(1.0,), exposure=ex)
    assert doc['counts']['black'] == 1 and seen['detect'] == [] and doc['objects'] == []
    sun = dict(covered=True, elevation_deg=-30.0); dark = dict(frames=[dict(t_s=1.0, sphere=dict(mean_lin=0.01))]); doc = run(tmp_path, detect, label, times=(1.0,), sun=sun, exposure=dark)
    assert 'night' in doc['skipped'] and doc['objects'] == [] and seen['detect'] == []


def test_the_moments_are_given_to_the_detector_in_batches(tmp_path):
    detect, label, seen = fakes({}, {}); run(tmp_path, detect, label, times=[float(i) for i in range(5)], batch=2); assert len(seen['detect']) == 3


def test_the_projects_statistics_are_added_up_from_the_clips_and_the_seed(tmp_path):
    for name, n in (('CAM_1', 3), ('CAM_2', 4)):
        d = tmp_path / 'strata360' / 'clips' / name; d.mkdir(parents=True); b = VOC.StatsBook()
        for _ in range(n): b.record_named('zzword', 'zzword')
        json.dump(dict(stats=b.to_json()), open(d / 'objects.json', 'w'))
    (tmp_path / 'strata360' / 'clips' / 'CAM_3').mkdir(); book = VOC.collect(str(tmp_path)); assert book.words['zzword']['fired'] == 7 and book.sources[-2:] == ['CAM_1', 'CAM_2'] and 'sheep' in book.words
    again = VOC.collect(str(tmp_path)); assert again.words['zzword']['fired'] == 7                              # rebuilt from the clips every time: running it twice does not count twice
    assert VOC.stats_for(str(tmp_path)).words['zzword']['fired'] == 7 and 'zzword' not in VOC.stats_for(str(tmp_path / 'none')).words
    assert VOC.collect(str(tmp_path / 'empty')).words == {}                                                    # nothing recorded and no file: nothing invented


def test_small_marks_on_the_ground_are_not_sent_and_scenery_labels_are_counted_apart(tmp_path):
    low = O.TILES.index((-55, 0.0)); detect, label, seen = fakes({}, {0: 'tall tree trunk'}, pf_by_moment={0: [('thing', 0.5, [472, 472, 552, 552])]})
    inner = detect
    def lower(images, words, out):                                                               # the same boxes, in a tile that looks at the ground
        d = inner(images, words, out); f = d['files']
        for n in list(f):
            if n.endswith(f't{TILE:02d}.jpg'): f[n[:-6] + f'{low:02d}.jpg'], f[n] = f[n], dict(named=[], pf=[])
        return d
    doc = run(tmp_path, lower, label, times=(1.0,)); assert doc['counts']['ground'] == 1 and doc['objects'] == [] and seen['label'] == []
    doc = run(tmp_path, detect, label, times=(1.0,)); assert doc['objects'] == [] and doc['scenery_labels'] == {'tree trunk': 1} and doc['dropped_by_stoplist'] == 0


# ---- snow and water regions ----------------------------------------------------------------------------------------------------------------------------------------------------
def scenes(*items):
    return dict(items=[dict(ok=True, t_s=t, view=v, ground_snow=sn, water=w) for t, v, sn, w in items])


def test_only_what_the_scene_labels_say_is_there_is_asked_for():
    d = scenes((1.0, 'front', False, 'none'), (1.0, 'rear', True, 'puddle'), (30.0, 'front', False, 'river'))
    assert R.kinds_at(d, 1.0) == {'snow'} and R.kinds_at(d, 30.0) == {'water'} and R.kinds_at(d, 15.0) == set() and R.kinds_at(None, 1.0) == set()
    assert R.kinds_at(dict(items=[dict(ok=False, t_s=1.0, ground_snow=True)]), 1.0) == set()                     # a picture the model did not answer says nothing
    assert R.question(['snow']).count('(1)') == 1 and 'water' not in R.question(['snow']).replace('"snow"', '') and '(2)' in R.question(['snow', 'water'])


def test_at_most_one_moment_in_the_gap_is_looked_at_and_only_moments_with_something():
    d = scenes(*[(float(t), 'front', True, 'none') for t in range(0, 40)])
    assert R.plan(d, [1.0, 3.0, 11.0, 12.0, 22.0], gap_s=10.0) == [(1.0, ['snow']), (11.0, ['snow']), (22.0, ['snow'])] and R.plan(scenes((1.0, 'front', False, 'none')), [1.0]) == []


def test_the_models_answer_is_read_strictly():
    txt = '```json\n[{"bbox_2d": [0, 345, 998, 781], "label": "snow"}, {"bbox_2d": [10, 10, 5, 5], "label": "snow"}, {"bbox_2d": [1, 2], "label": "water"}, {"bbox_2d": [0, 0, 500, 500], "label": "water"}, {"label": "snow"}]\n```'
    assert R.parse(txt, ['snow']) == [('snow', [0.0, 0.345, 0.998, 0.781])] and [k for k, _ in R.parse(txt, ['snow', 'water'])] == ['snow', 'water'] and R.parse('nothing', ['snow']) == [] and R.parse('[not json]', ['snow']) == []


def test_a_box_in_the_middle_of_a_view_is_where_the_view_looks_and_a_wide_one_is_wide():
    b = R.to_world([0.4, 0.4, 0.6, 0.6], 120.0, -15.0); assert abs(b['lon'] - 120) < 1 and abs(b['lat'] + 15) < 1 and 20 < b['w_deg'] < 30 and len(b['polygon']) == 4
    w = R.to_world([0.0, 0.5, 1.0, 1.0], 0.0, -15.0); assert w['w_deg'] > 80 and w['lat'] < -15 and R.to_world([0.2, 0.2, 0.3, 0.3], 0.0, -15.0)['lon'] < 0     # left of the view's middle is west of it


def test_the_objects_run_adds_the_regions_of_what_the_scene_labels_gave_and_asks_nothing_when_they_give_nothing(tmp_path):
    detect, label, seen = fakes({}, {}); asked = []
    def regions_label(images, out):
        jobs = json.load(open(os.path.join(images, 'jobs.json'))); asked.append(dict(jobs)); names = sorted(jobs)
        return dict(model='fake', seconds=2.0, answers={names[0]: '[{"bbox_2d": [100, 500, 900, 900], "label": "snow"}, {"bbox_2d": [0, 0, 100, 100], "label": "water"}]', **{n: '[]' for n in names[1:]}})
    v = VOC.load(); words = VOC.words_for([], v)
    run = lambda sc: O.analyse('x.osv', str(tmp_path), [1.0, 2.0], words, stats=VOC.StatsBook(), vocab=v, detect=detect, label=label, renderer=Lens(), scenes=sc, regions_label=regions_label)
    doc = run(scenes((1.0, 'front', True, 'none'), (2.0, 'front', True, 'none')))
    assert len(asked) == 1 and len(asked[0]) == 6 and all(k == ['snow'] for k in asked[0].values())                          # one moment (1 s and 2 s are inside the gap), six views, asked about snow only
    assert [(r['kind'], r['t']) for r in doc['regions']] == [('snow', 1.0)] and doc['regions'][0]['w_deg'] > 50 and doc['regions_seconds'] == 2.0                  # the water box was not asked for, so it is dropped
    asked.clear(); doc = run(scenes((1.0, 'front', False, 'puddle'))); assert asked == [] and doc['regions'] == []
