"""analysis/vocab.py: the wordlists by category, the numbers kept against each word, and the model's part (categories for a clip, reviewing suggested words, simplifying labels), with the model replaced by a function."""
import json

import pytest
from strata360.analysis import vocab as V


def test_the_shipped_wordlists_are_consistent():
    v = V.load(); allw = [w for ws in v['always'].values() for w in ws] + [w for c in v['categories'].values() for w in c['words']]
    for name, c in v['categories'].items(): assert c['about'] and len(set(c['words'])) == len(c['words']), name
    assert not (set(allw) & set(v['retired'])) and set(v['accepts']) <= set(allw) | set(v['retired']) and all(isinstance(w, str) and w == w.lower() for w in allw)
    assert len(V.words_for(list(v['categories']), v)) <= v['cap'] and V.words_for([], v)[:6] == v['always']['people_gear']
    seed = V.StatsBook.read(V.SEED_FILE); assert seed.words and seed.sources and 'sheep' in seed.weak(v)


def test_words_for_is_always_then_the_union_of_the_categories_in_order_without_repeats_retired_words_or_more_than_the_cap():
    v = dict(cap=6, always=dict(people_gear=['person'], core=['tree']), retired={'bad': 'x'}, categories=dict(a=dict(about='', words=['x', 'bad', 'y']), b=dict(about='', words=['y', 'z', 'w'])))
    assert V.words_for(['a', 'b'], v) == ['person', 'tree', 'x', 'y', 'z', 'w'] and V.words_for(['b', 'a', 'nope'], v, cap=4) == ['person', 'tree', 'y', 'z']


@pytest.mark.parametrize('label, word', [('two white ducks', 'duck'), ('wooden platform', 'platform'), ('street lights', 'street light'), ('Brown Chicken', 'chicken'), ('glass', 'glass'), ('a', ''), ('moss', 'moss'), ('bare tree branches', 'tree branch'),
                                         ('black and white dog', 'dog'), ('sign on fence post', 'sign'), ('pile of logs', 'log'), ('mossy retaining wall', 'wall'), ('light pole', 'pole'), ('street light', 'street light'), ('boxes', 'box'), ('berries', 'berry'), ('fallen leaves', 'fallen leaf')])
def test_a_label_is_reduced_to_its_plain_noun(label, word):
    assert V.normalise_label(label) == word


def test_labels_are_judged_as_not_worth_reporting_filler_or_a_feature():
    v = V.load()
    for stop in ('patch of snow', 'person running', 'unclear', "person's legs", 'white fungus', 'sky', 'orange running pole', 'ski pole'): assert V.kind_of_label(stop, v) == 'stop', stop
    for stop in ('muddy puddle', 'white patches', 'white plastic sheet'): assert V.kind_of_label(stop, v) == 'stop', stop
    for filler in ('rock', 'large rock', 'ceiling light fixture', 'tall tree trunk', 'bare tree', 'distant hills', 'tree branch', 'small twig'): assert V.kind_of_label(filler, v) == 'scenery', filler
    for vague in ('red object', 'object', 'a thing'): assert V.kind_of_label(vague, v) == 'stop', vague
    for feat in ('yellow sign', 'church steeple', 'brown chicken', 'utility pole', 'concrete pole'): assert V.kind_of_label(feat, v) == 'feature', feat
    assert V.agrees('chicken', 'small brown bird', v) and V.agrees('car', 'grey car', v) and not V.agrees('house', 'blue sign', v) and V.agrees('tower', 'weather vane on a steeple', v) is True


def test_the_book_counts_agreement_mislabels_and_false_positives_and_ranks_the_weakest_first():
    v = V.load(); b = V.StatsBook()
    for lab in ('grey car', 'white car', 'black car'): b.record_named('car', lab, v)
    for lab in ('goose', 'goose', 'bird', 'sheep', 'patch of snow', 'unclear'): b.record_named('sheep', lab, v)
    c, s = b.words['car'], b.words['sheep']; assert (c['fired'], c['agreed'], c['false_positive']) == (3, 3, 0) and (s['fired'], s['agreed'], s['false_positive']) == (6, 1, 2) and s['mislabels'] == {'goose': 2, 'bird': 1}
    rows = b.report(); assert [r[0] for r in rows] == ['sheep', 'car'] and rows[0][3] == pytest.approx(1 / 6) and rows[0][5][0] == 'goose'
    assert b.weak(v, min_n=6, max_precision=0.25) == ['sheep'] and b.weak(v, min_n=7) == []


def test_leftover_labels_become_suggestions_only_when_seen_often_enough_in_enough_clips_and_not_already_words():
    v = V.load(); b = V.StatsBook()
    for clip in ('0013', '0013', '0016'): b.record_leftover('wooden platform', clip, v)
    for clip in ('0013',) * 5: b.record_leftover('brown chicken', clip, v)                          # a word already, and all in one clip
    for clip in ('0018', '0021', '0018'): b.record_leftover('white fungus', clip, v)                 # filler: not counted at all
    for clip in ('0002', '0004', '0002'): b.record_leftover('lamp post', clip, v)
    assert 'fungus' not in b.suggest and b.suggest['platform']['count'] == 3 and b.suggest['platform']['clips'] == {'0013': 2, '0016': 1}
    assert b.suggestions(v) == ['lamp post']
    assert 'chicken' not in b.suggestions(v) and 'platform' not in b.suggestions(v)                  # both are words already


def test_books_merge_and_survive_a_round_trip_through_the_file(tmp_path):
    v = V.load(); a, b = V.StatsBook(), V.StatsBook(); a.record_named('car', 'grey car', v); b.record_named('car', 'blue suv', v); b.record_leftover('weather vane', '0002', v); b.sources = ['x']
    a.merge(b); assert a.words['car']['fired'] == 2 and a.words['car']['agreed'] == 2 and 'weather vane' in a.suggest and a.sources == ['x']
    p = str(tmp_path / 'sub' / 'stats.json'); a.write(p); r = V.StatsBook.read(p); assert r.words['car']['fired'] == 2 and r.suggest['weather vane']['clips'] == {'0002': 1} and r.updated
    assert V.StatsBook.read(str(tmp_path / 'missing.json')).words == {}


def test_a_clips_categories_come_from_the_model_plus_the_plain_rules_and_from_the_rules_alone_when_it_fails():
    v = V.load(); block = dict(settings={'forest': 9, 'river': 2}, weather={'snow': 3}, lighting={'overcast': 4}, tags=['hiker', 'river'])
    assert V.rule_categories(block, v) == ['forest_trail', 'water', 'snow'] and V.categorise(block, None, v) == ['forest_trail', 'water', 'snow'] and V.categorise(None, lambda p: ['["coast"]'], v) == []
    race = dict(settings={'aid_station': 4, 'town': 2}, tags=['runners', 'spectators', 'aid station']); assert V.rule_categories(race, v) == ['aid_station', 'town_village', 'race_event']
    asked = []
    def ask(p): asked.append(p[0]); return ['Sure: ["water", "made_up", "forest_trail", "indoor"]']
    got = V.categorise(block, ask, v); assert got == ['water', 'forest_trail', 'indoor', 'snow'] and 'forest (9)' in asked[0] and 'snow (3)' in asked[0] and 'farm_rural:' in asked[0]
    assert V.categorise(block, lambda p: ['I cannot say'], v) == ['forest_trail', 'water', 'snow']


def test_suggested_words_are_reviewed_by_the_model_and_only_distinct_things_in_known_categories_are_added():
    v = V.load(); b = V.StatsBook()
    for clip in ('0013', '0016', '0016'): b.record_leftover('lamp post', clip, v); b.record_leftover('white object', clip, v); b.record_leftover('weather vane', clip, v)
    def ask(prompts):
        out = []
        for p in prompts:
            if '"post"' in p or '"lamp post"' in p: out.append('{"add": true, "word": "lamp post", "categories": ["town_village", "made_up"]}')
            elif '"weather vane"' in p: out.append('{"add": true, "word": "weather vane", "categories": []}')
            else: out.append('{"add": false, "word": "", "categories": []}')
        return out
    log = []; V.review(b, ask, v, log=log); by = {d['label']: d for d in log}; assert by['lamp post']['add'] is True and by['lamp post']['count'] == 3 and 'add' in by['lamp post']['answer'] and by['weather vane']['add'] is True
    judged = {k: dict(count=d['count']) for k, d in by.items()}; assert V.review(b, ask, v, judged=judged) == []                                                      # already judged at this count: not asked again
    assert [g['word'] for g in V.review(b, ask, v, judged=dict(judged, **{'lamp post': dict(count=1)}))] == ['lamp post']; got = V.review(b, ask, v); assert [(g['word'], g['categories']) for g in got] == [('lamp post', ['town_village'])] and V.review(V.StatsBook(), ask, v) == []


def test_odd_labels_are_simplified_in_batches_with_skips_and_a_fallback_for_what_the_model_leaves_out():
    v = V.load(); labels = [f'odd {i}' for i in range(45)] + ['mossy retaining wall', 'patch of snow', 'two white ducks']; calls = []
    def ask(prompts):
        calls.append(len(prompts)); return [json.dumps({'mossy retaining wall': 'wall', 'patch of snow': 'skip'}) if 'mossy retaining wall' in p else '{}' for p in prompts]
    got = V.canonicalise(labels, ask, v); assert calls == [2] and got['mossy retaining wall'] == 'wall' and got['patch of snow'] is None and got['two white ducks'] == 'duck' and got['odd 3'] == 'odd'
    assert V.canonicalise([], ask, v) == {}
    def ask2(prompts): return [json.dumps({'utility pole': 'pole', 'wet road': 'road', 'fallen leaves': 'leaf', 'white mushroom': 'skip'}) for _ in prompts]
    assert V.canonicalise(['utility pole', 'wet road', 'fallen leaves', 'white mushroom'], ask2, v) == {'utility pole': 'pole', 'wet road': None, 'fallen leaves': None, 'white mushroom': None}           # the word is judged, not the label


def test_update_adds_accepted_words_and_removes_weak_ones_in_the_projects_own_list_and_leaves_the_shared_list_alone(tmp_path):
    v = V.load(); b = V.StatsBook()
    for i in range(10): b.record_named('sheep', 'goose', v)
    for clip in ('0013', '0016', '0013'): b.record_leftover('lamp post', clip, v)
    pp = V.project_paths(str(tmp_path)); b.write(pp['stats'])
    props, weak = V.update(str(tmp_path), lambda ps: ['{"add": true, "word": "lamp post", "categories": ["town_village"]}'] * len(ps), vocab=v)
    assert [p['word'] for p in props] == ['lamp post'] and weak == ['sheep']; local = json.load(open(pp['local'])); assert local['add'] == {'town_village': ['lamp post']} and local['remove'] == ['sheep'] and local['reviewed']['lamp post']['add'] is True and local['reviewed']['lamp post']['count'] == 3         # what was judged is kept, so it is not asked again
    mine = V.load(local=local); assert 'lamp post' in mine['categories']['town_village']['words'] and 'lamp post' not in v['categories']['town_village']['words'] and 'lamp post' in V.words_for(['town_village'], mine)
    props, weak = V.update(str(tmp_path), lambda ps: [], vocab=None); assert props == [] and weak == []                    # nothing new the second time: the word is a word now, the weak one is already out


def test_each_category_collects_its_own_numbers_as_it_is_used():
    v = V.load(); a, b = V.StatsBook(), V.StatsBook()
    a.use_category('farm_rural'); a.use_category('farm_rural'); a.record_named('chicken', 'brown hen', v, categories=['farm_rural']); a.record_named('goat', 'dog', v, categories=['farm_rural', 'race_event'])
    b.use_category('farm_rural'); b.record_named('duck', 'white duck', v, categories=['farm_rural']); a.merge(b)
    assert a.cats['farm_rural'] == dict(uses=3, fired=3, agreed=2) and a.cats['race_event'] == dict(uses=0, fired=1, agreed=0) and a.to_json()['categories']['farm_rural']['uses'] == 3
    assert V.StatsBook(a.to_json()).cats == a.cats


def test_a_word_is_trusted_only_with_enough_boxes_nearly_all_agreed_and_a_sure_detector_and_a_trusted_box_is_still_audited_now_and_then():
    import random
    v = V.load(); b = V.StatsBook()
    for i in range(30): b.record_named('car', 'grey car' if i != 5 else 'trailer', v)                      # 29 of 30 agreed
    for i in range(30): b.record_named('sheep', 'goose', v)
    for i in range(10): b.record_named('van', 'white van', v)                                              # right every time, but too few
    for i in range(25): b.record_named('fence', 'wooden fence' if i < 21 else 'wall', v)                   # 21 of 25 = 84%
    assert b.trusted('car') and not b.trusted('sheep') and not b.trusted('van') and not b.trusted('fence') and not b.trusted('unknown') and b.trusted('van', min_n=10)
    rng = random.Random(0); got = [b.route('car', 0.8, v, rng) for _ in range(2000)]; assert set(got) == {'accept', 'audit'} and 0.07 < got.count('audit') / 2000 < 0.13
    assert b.route('car', 0.3, v) == 'label' and b.route('sheep', 0.9, v) == 'label' and b.route('van', 0.9, v) == 'label' and b.route('nothing', 0.9, v) == 'label'
    b.record_named('animal', 'person', v); assert 'animal' in v['retired'] and b.route('animal', 0.99, v) == 'label'


def test_a_seen_stream_or_snow_on_the_ground_adds_its_category_whatever_the_tags_say():
    v = V.load(); assert V.rule_categories(dict(settings={'trail': 5}, water={'stream': 3}, ground_snow=0.6, tags=['hiker']), v) == ['forest_trail', 'water', 'snow']
    assert V.rule_categories(dict(settings={'trail': 5}, water={}, ground_snow=0.1, tags=['hiker']), v) == ['forest_trail']


def test_a_puddle_on_a_wet_road_is_not_water_for_the_categories():
    v = V.load(); assert V.rule_categories(dict(settings={'road': 5}, water={'puddle': 4}, tags=['road']), v) == ['road_traffic']
