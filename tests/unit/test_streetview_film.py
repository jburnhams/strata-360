"""Street view in the film: the script pack and prompt, the streetview item, the plan, and the clip a chosen section becomes."""
import os

import pytest

import test_script_plan as TSP
from overlay_fakes import race_track, T0
from strata360 import streetview as SV
from strata360.edit import script_draft as SD, script_pack as SP, script_plan as SPL, streetview_clip as SVC, synthetic as SY

ITEMS = [dict(id='m%d' % i, km=1.0 + i * 0.01, lat=50.13 + i * 0.0001, lon=5.79, a=0, b=0, t=1_700_000_000 + i) for i in range(40)]
SECTION = dict(id='M1', provider='mapillary', stretch='R1', kind='360', km0=1.0, km1=1.39, length_m=390, frames=40, spacing_m=10.0, years=[2024], camera='GoPro Max', size=[5760, 2880], seq='s1', angles=None, items=ITEMS)


def sv_clip(label='V1', must=False, start='2026-02-22T10:01:30Z', **facts):
    f = dict(source='mapillary', camera='a 360 camera', km0=1.0, km1=1.39, length_m=390, pictures=40, spacing_m=10.0, min_s=2.0, max_s=10.0, years=[2024], captured='Thu 07 Mar 2024 18:44', captured_light='day', race_light='day', same_road=[]); f.update(facts)
    return dict(label=label, clip=label, start_utc=start, duration_s=4.0, usable_s=10.0, usable=[(2.0, 10.0)], synthetic=True, streetview=True, race_s=300.0, speedup=75.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0,
                settings=dict(kind=None, mode=None, seconds=None, must=must), planned=None, sv_facts=f, km=1.0, local='2026-02-22 10:01', track='km 1.0 of the run')


class TestPack:
    def test_a_chosen_section_is_a_pack_clip_with_where_how_and_in_what_light(self, project):
        rd = project.race_dir; roads = dict(schema=1, id='r', stretches=[], run=[], total_km=3)
        SV._save(rd, 'roads', roads); other = dict(SECTION, id='P1', provider='panoramax', seq='c', km0=1.1, km1=1.3, length_m=200, items=ITEMS[10:30], frames=20, spacing_m=8.0)
        SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [SECTION], roads)); SV._save(rd, 'panoramax', SV.provider_doc('panoramax', [dict(other, frames=40)], roads))
        SV.set_choice(rd, SV.section_key(SECTION), 'must'); tr = race_track(n=2000, speed=3.0, lat0=50.129)
        out = SP.streetview_clips(project.folder, tr, 'Europe/Brussels'); assert [c['label'] for c in out] == ['V1']
        c = out[0]; f = c['sv_facts']
        assert c['synthetic'] and c['streetview'] and c['settings']['must'] is True and c['duration_s'] == 2.7 and c['usable_s'] == 10.0 and c['race_s'] == pytest.approx(130.0, abs=2) and c['speedup'] == pytest.approx(48.1, abs=1)
        assert f['camera'] == 'a 360 camera' and (f['min_s'], f['max_s']) == (2.0, 10.0) and f['pictures'] == 40 and f['captured'] and f['race_light'] and 'km' in c['track'] and f['same_road'] == []
        assert SP.streetview_clips(project.folder, None, 'UTC') == []

    def test_nothing_chosen_means_no_street_view_clips(self, project): assert SP.streetview_clips(project.folder, race_track(), 'UTC') == []

    def test_the_prompt_describes_the_view_its_length_range_and_the_light(self):
        text = SP.render(dict(race={}, clips=[sv_clip(), sv_clip('V2', must=True, captured_light='day', race_light='night', same_road=['V1'], camera='a flat camera facing forward')], music=None), with_usable=False) if False else SP.render(dict(race={}, clips=[sv_clip(), sv_clip('V2', must=True, captured_light='day', race_light='night', same_road=['V1'])], music=None))
        assert '=== STREET VIEW V1: 4.0 s long' in text and 'NO FOOTAGE: a steady view along the road' in text and 'streetview item of 2 to 10 s' in text and 'filmed in day; the runner passes it in day.' in text
        v1, v2 = text.split('=== STREET VIEW V2')[0], text.split('=== STREET VIEW V2')[1]
        assert 'MUST INCLUDE' not in v1 and 'THE RUNNER WANTS THIS IN THE FILM (MUST INCLUDE)' in v2 and 'USE IT ONLY IF THAT FITS THE STORY' in v2 and 'covers the same road as V1: use at most one' in v2 and 'the runner says nothing' not in text


class TestScript:
    def pack(self, **kw): return dict(TSP.PACK, clips=TSP.PACK['clips'] + [sv_clip(**kw)])
    def check(self, items, target=20.0, **kw): return SD.check(dict(items=items), self.pack(**kw), target, 150.0)

    def test_a_streetview_item_is_checked_for_what_it_names_and_how_long(self):
        clips = [c['label'] for c in TSP.PACK['clips']]; first = clips[0]
        rep, probs = self.check([dict(type='broll', clip=first, seconds=6), dict(type='streetview', clip='V1', seconds=6)]); assert not [p for p in probs if p.startswith('item')] and rep['streetview_s'] == 6.0 and rep['per_clip']['V1'] == 6.0
        assert any('V1 plays for 2 to 10 seconds, not 30' in p for p in self.check([dict(type='streetview', clip='V1', seconds=30)])[1]) and any('V1 plays for 2 to 10 seconds, not 1' in p for p in self.check([dict(type='streetview', clip='V1', seconds=1)])[1])
        assert any(f'{first} is not a street view section' in p for p in self.check([dict(type='streetview', clip=first, seconds=5)])[1])
        assert any('V1 is a streetview with no words: use a streetview item' in p for p in self.check([dict(type='clip', clip='V1', **{'from': 'x', 'to': 'y'})])[1]) and any(f'{first} is a camera clip, not a gap' in p for p in self.check([dict(type='gap', clip=first, seconds=5)])[1])
        assert any('V1 is not a gap' in p for p in self.check([dict(type='gap', clip='V1', seconds=5)])[1])

    def test_a_streetview_marked_must_has_to_be_used_and_two_over_one_road_are_alternatives(self):
        first = TSP.PACK['clips'][0]['label']; items = [dict(type='broll', clip=first, seconds=8)]
        assert any('street view V1 is marked MUST INCLUDE but no item uses it' in p for p in self.check(items, must=True)[1]) and not any('MUST INCLUDE' in p for p in self.check(items, must=False)[1])
        assert not any('MUST INCLUDE' in p for p in self.check(items + [dict(type='streetview', clip='V1', seconds=5)], must=True)[1])
        pack = dict(TSP.PACK, clips=TSP.PACK['clips'] + [sv_clip('V1', same_road=['V2']), sv_clip('V2', same_road=['V1'], start='2026-02-22T10:01:40Z')])
        probs = SD.check(dict(items=[dict(type='streetview', clip='V1', seconds=4), dict(type='streetview', clip='V2', seconds=4)]), pack, 20.0, 150.0)[1]; assert any('V1 and V2 cover the same road' in p for p in probs)
        assert not any('same road' in p for p in SD.check(dict(items=[dict(type='streetview', clip='V1', seconds=4)]), pack, 20.0, 150.0)[1])

    def test_the_instructions_describe_the_streetview_item(self):
        assert '- "streetview": a steady view along the road' in SD.SYSTEM and '"type": "streetview", "clip": "V1"' in SD.SCHEMA and 'a view filmed in the day looks wrong in the dark' in SD.SYSTEM
        script = dict(items=[dict(type='streetview', clip='V1', seconds=6.04)]); assert SD.resolve(script, self.pack(), 150.0)['items'][0]['seconds'] == 6.0


class TestPlan:
    def test_a_streetview_item_becomes_a_picture_only_generated_piece_within_what_the_section_can_play(self):
        pack = dict(TSP.PACK, clips=TSP.PACK['clips'] + [sv_clip('V1', start='2026-02-22T10:01:30Z')]); first, second = TSP.PACK['clips'][0]['label'], TSP.PACK['clips'][1]['label']
        draft = TSP.anchored([dict(type='broll', clip=first, seconds=4.0), dict(type='streetview', clip='V1', seconds=30.0), dict(type='broll', clip=second, seconds=4.0)])
        ps, warn = SPL.pieces(draft, pack, {}, 150.0); p = next(x for x in ps if x['label'] == 'V1'); assert p['kind'] == 'synthetic' and p['role'] == 'broll' and p['streetview'] is True and p['photo'] is False and p['seconds'] == 10.0 and p['sv_range'] == (2.0, 10.0)
        assert SPL.flex(p) == (2.0, 10.0) and SPL.flex(dict(p, seconds=5.0)) == (2.0, 10.0)
        short = SPL.pieces(TSP.anchored([dict(type='streetview', clip='V1', seconds=0.5)]), pack, {}, 150.0)[0][0]; assert short['seconds'] == 2.0
        ps2, warn2 = SPL.pieces(TSP.anchored([dict(type='streetview', clip=first, seconds=4.0), dict(type='gap', clip='V1', seconds=4.0)]), pack, {}, 150.0); assert any(f'{first} is not a street view section' in w for w in warn2) and any('V1 is a street view section, not a gap' in w for w in warn2)

    def test_a_streetview_marked_must_is_added_in_its_place_when_the_script_leaves_it_out(self):
        ps = [dict(kind='broll', seconds=10.0, n=0, label='0001', clip='c1', text='', seg=None), dict(kind='broll', seconds=10.0, n=1, label='0002', clip='c2', text='', seg=None)]
        pack = dict(clips=[dict(label='0001', start_utc='2026-02-22T10:01:00Z'), sv_clip('V1', must=True, start='2026-02-22T10:30:00Z'), sv_clip('V2', start='2026-02-22T10:40:00Z'), dict(label='0002', start_utc='2026-02-22T12:00:00Z')])
        warn = []; added = SPL.force_gaps(ps, pack, warn); assert added == ['V1'] and [p['label'] for p in ps] == ['0001', 'V1', '0002'] and ps[1]['streetview'] and ps[1]['seconds'] == 4.0 and SPL.flex(ps[1]) == (2.0, 10.0) and any('V1' in w for w in warn)

    def test_a_streetview_section_is_not_added_as_an_unfilled_gap(self):
        class Music:
            beat_s = 0.5; bar_beats = 4
        gap = dict(label='G01', clip='G01', start_utc='2026-02-22T10:20:00Z', duration_s=8.0, race_s=7200.0, synthetic=True, settings={}); sv = dict(sv_clip('V1', start='2026-02-22T10:30:00Z'), race_s=7200.0)
        pack = dict(clips=[dict(label='0001', start_utc='2026-02-22T10:01:00Z'), gap, sv]); ps = [dict(kind='broll', seconds=10.0, n=0, label='0001', clip='c1', text='', seg=None)]
        assert SPL.auto_gaps(ps, pack, Music(), 120.0, []) == ['G01']


class TestClip:
    def test_the_clip_covers_the_race_minutes_of_the_section_and_changes_key_with_what_is_shown(self):
        c = dict(SECTION, label='V1', key='mapillary:s1:1.00'); a = SY.make_streetview(c, 6.0, T0, T0 + 300); assert a['id'] == 'V1' and a['kind'] == 'streetview' and a['seconds'] == 6.0 and a['duration_s'] == 300.0 and a['speedup'] == 50.0 and a['size'] == '3840x2160' and a['style']['section'] == 'mapillary:s1:1.00'
        assert SY.make_streetview(c, 6.0, T0, T0 + 300)['key'] == a['key'] and SY.make_streetview(c, 7.0, T0, T0 + 300)['key'] != a['key'] and SY.make_streetview(dict(c, frames=41), 6.0, T0, T0 + 300)['key'] != a['key']
        with pytest.raises(ValueError, match='shorter than'): SY.make_streetview(c, 1.0, T0, T0 + 300)

    def test_sync_renders_what_changed_and_keeps_what_did_not(self, project, monkeypatch):
        rd = project.race_dir; roads = dict(schema=1, id='r', stretches=[], run=[], total_km=3); SV._save(rd, 'roads', roads); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [SECTION], roads)); SV.set_choice(rd, SV.section_key(SECTION), 'possible')
        made = []
        def fake(folder, sec, seconds, path, log=print): made.append((sec['label'], seconds)); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, 'wb').write(b'mp4')
        monkeypatch.setattr(SVC, 'render', fake); monkeypatch.setattr(SVC, 'race_span', lambda folder, sec: (T0, T0 + 130))
        specs = [dict(clip='V1', seconds=4.37), dict(clip='P1', seconds=3.0), dict(clip='V9', seconds=3.0)]; log = []
        out = SVC.sync(project.folder, specs, log.append); assert [c['id'] for c in out] == ['V1'] and made == [('V1', 4.37)] and out[0]['status'] == 'ready' and any('V9' in l for l in log) and out[0]['file'] == os.path.join('synthetic', 'V1.mp4')
        SVC.sync(project.folder, specs, log.append); assert len(made) == 1                                                                              # unchanged: kept
        SVC.sync(project.folder, [dict(clip='V1', seconds=99.0)], log.append); assert made[-1] == ('V1', 10.0)                                       # the length is held to what the section can play
        SV.set_choice(rd, SV.section_key(SECTION), 'none'); assert SVC.sync(project.folder, specs, log.append) == []

    def test_a_section_with_no_race_track_is_reported(self, project, monkeypatch):
        rd = project.race_dir; roads = dict(schema=1, id='r', stretches=[], run=[], total_km=3); SV._save(rd, 'roads', roads); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [SECTION], roads)); SV.set_choice(rd, SV.section_key(SECTION), 'must')
        monkeypatch.setattr(SVC, 'race_span', lambda folder, sec: None); log = []; assert SVC.sync(project.folder, [dict(clip='V1', seconds=4.0)], log.append) == [] and any('no race track' in l for l in log)

    def test_labels(self):
        assert SVC.is_streetview_label('V2') and SVC.is_streetview_label('v10') and not SVC.is_streetview_label('P2') and not SVC.is_streetview_label('0023') and not SVC.is_streetview_label('VX')
