"""Photos in the film: the script pack and prompt, the photo item, the plan, and the clip each photo becomes."""
import io, os
import numpy as np
import pytest
from PIL import Image

import test_script_plan as TSP
from strata360 import photos as PH
from strata360.edit import photo_clip as PCL, photo_motion as PM, script_draft as SD, script_pack as SP, script_plan as SPL, synthetic as SY
from strata360.pipeline import config


def jpeg(local='2026:02:20 14:12:17', size=(120, 80)):
    ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = local; ex.get_ifd(0x8769)[0x9011] = '+00:00'; b = io.BytesIO(); Image.new('RGB', size, (40, 90, 160)).save(b, 'JPEG', exif=ex); return b.getvalue() + b'\0' * 200


def photo_clip(label='P1', must=False, start='2026-02-20T14:12:17Z', seconds=6.0, **facts):
    return dict(label=label, clip=label, start_utc=start, duration_s=seconds, usable_s=12.0, usable=[(0.0, 12.0)], synthetic=True, photo=True, race_s=0.0, speedup=1.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0, settings=dict(kind=None, mode=None, seconds=None, must=must),
                planned=None, photo_facts=dict(name='IMG_1.jpg', camera='', **facts), km=12.3, local='2026-02-20 14:12', track='km 12.3 of the run')


class TestPack:
    def test_a_photo_is_a_pack_clip_with_what_the_analysis_found_and_whether_it_must_be_used(self, project):
        from strata360.analysis import photo_analysis as PA
        rd = project.race_dir; PH.add(rd, 'a.jpg', jpeg()); PH.add(rd, 'b.jpg', jpeg(local='2026:02:20 15:00:00')); PH.set_use(rd, 'p1', True); PH.set_must(rd, 'p2', True); PH.set_motion(rd, 'p1', seconds=4)                                                          # p1 has a length of its own; p2 follows how busy it is
        doc = PA.load_doc(rd, 'p1'); doc['scenes'] = dict(ok=True, setting='trail', description='A path in the trees.', tags=['trees'], weather='cloud', scenery=7.0, clarity=4.0); doc['identity'] = dict(me=dict(face=0), n_people=2, others=1, threshold=0.45); doc['stages'] = dict(scenes={}, identity={}); PA.save_doc(rd, doc)
        a, b = SP.photo_clips(project.folder, None, 'UTC'); assert (a['label'], b['label']) == ('P1', 'P2') and a['photo'] and a['synthetic'] and a['duration_s'] == 4.0 and a['settings'] == dict(kind=None, mode='set', seconds=4.0, must=False) and b['duration_s'] == 2.5 and b['settings']['mode'] is None and a['settings']['must'] is False and b['settings']['must'] is True and a['start_utc'] == '2026-02-20T14:12:17Z'
        assert a['photo_facts']['description'] == 'A path in the trees.' and a['photo_facts']['scenery'] == 7.0 and a['photo_facts']['people'] == 2 and a['photo_facts']['me'] is True and a['race_s'] == 0.0 and a['usable_s'] == 4.0 and b['usable_s'] == SP.MAX_PHOTO_S
        assert SP.photo_clips(str(project.folder) + '-none', None, 'UTC') == []

    def test_the_prompt_describes_a_photo_and_says_when_it_must_be_used(self):
        text = SP.render(dict(race={}, clips=[photo_clip(description='A path in the trees.', place='Nadrin', scenery=7.0, people=1, me=True, face_clear=True, tags=['trees'], objects=[dict(label='bottle', n=2)], exposure='dark'), photo_clip('P2', must=True)], music=None))
        assert '=== PHOTO P1: 6.0 s long' in text and 'A PHOTO the runner took' in text and 'photo item of 2 to 3 s' in text and 'A path in the trees.; place: Nadrin; scenery 7/10; people in it: 1, the runner among them (face clear); objects: 2 bottle; tags: trees; picture looks dark' in text
        p1, p2 = text.split('=== PHOTO P2')[0], text.split('=== PHOTO P2')[1]; assert 'MUST INCLUDE' not in p1 and 'THE RUNNER WANTS THIS PHOTO IN THE FILM (MUST INCLUDE)' in p2 and 'has not been analysed' in p2 and 'the runner says nothing' not in text


class TestScript:
    def pack(self, must=False):
        return dict(PACK_BASE, clips=[PACK_BASE['clips'][0], photo_clip('P1', must=must, start='2026-02-22T10:01:30Z', seconds=2.5), PACK_BASE['clips'][1]])

    def check(self, items, must=False, target=20.0): return SD.check(dict(items=items), self.pack(must), target, 150.0)

    def test_a_photo_item_is_checked_for_what_it_names_and_how_long(self):
        rep, probs = self.check([dict(type='broll', clip='0001', seconds=8), dict(type='photo', clip='P1', seconds=2.5), dict(type='broll', clip='0002', seconds=9.5)])
        assert not [p for p in probs if 'item' in p] and rep['photo_s'] == 2.5 and rep['per_clip']['P1'] == 2.5
        assert any('a photo plays for 2 to 3 seconds, not 20' in p for p in self.check([dict(type='photo', clip='P1', seconds=20)])[1])
        assert any('0001 is not a photo' in p for p in self.check([dict(type='photo', clip='0001', seconds=5)])[1])
        assert any('P1 is a photo with no words: use a photo item' in p for p in self.check([dict(type='clip', clip='P1', **{'from': 'x', 'to': 'y'})])[1])

    def test_a_photo_marked_must_include_has_to_be_used(self):
        items = [dict(type='broll', clip='0001', seconds=8), dict(type='broll', clip='0002', seconds=12)]
        assert any('photo P1 is marked MUST INCLUDE but no item uses it' in p for p in self.check(items, must=True)[1]) and not any('MUST INCLUDE' in p for p in self.check(items, must=False)[1])
        assert not any('MUST INCLUDE' in p for p in self.check(items[:1] + [dict(type='photo', clip='P1', seconds=4)] + items[1:], must=True)[1])

    def test_photos_are_in_chronological_order_with_the_clips_and_narration_may_go_over_one(self):
        probs = self.check([dict(type='broll', clip='0002', seconds=8), dict(type='photo', clip='P1', seconds=4)])[1]; assert any('P1 is out of shooting order' in p for p in probs)
        rep, probs = self.check([dict(type='broll', clip='0001', seconds=8), dict(type='vo', clip='P1', text='A view I could not film.'), dict(type='broll', clip='0002', seconds=7)]); assert not [p for p in probs if p.startswith('item')]

    def test_the_instructions_describe_the_photo_item(self):
        assert '- "photo": a photo the runner took' in SD.SYSTEM and '"type": "photo", "clip": "P2"' in SD.SCHEMA


PACK_BASE = dict(race={}, clips=[
    dict(label='0001', clip='C0001', start_utc='2026-02-22T10:00:00Z', duration_s=30, usable_s=30, usable=[(0, 30)], scene={}, note='', lines=[], speech_s=0, speech_words=0),
    dict(label='0002', clip='C0002', start_utc='2026-02-22T10:05:00Z', duration_s=30, usable_s=30, usable=[(0, 30)], scene={}, note='', lines=[], speech_s=0, speech_words=0)])


class TestPlan:
    def test_a_photo_item_becomes_a_picture_only_generated_piece_no_longer_than_a_photo_may_be(self):
        pack = dict(TSP.PACK, clips=TSP.PACK['clips'] + [dict(photo_clip('P1', start='2026-02-22T10:01:30Z'), duration_s=6.0)]); draft = TSP.anchored([dict(type='broll', clip='0001', seconds=4.0), dict(type='photo', clip='P1', seconds=30.0), dict(type='broll', clip='0002', seconds=4.0)])
        ps, warn = SPL.pieces(draft, pack, {}, 150.0); p = next(x for x in ps if x['label'] == 'P1'); assert p['kind'] == 'synthetic' and p['role'] == 'broll' and p['photo'] is True and p['seconds'] == SPL.MAX_PHOTO_S
        assert SPL.flex(p) == (SPL.MIN_PHOTO_S, SPL.MAX_PHOTO_S) and SPL.MIN_PHOTO_S == 2.0 and SPL.MAX_PHOTO_S == 3.0                      # a photo is fitted to the music between 2 and 3 s
        assert SPL.flex(dict(p, seconds=5.0, fixed=True)) is None or SPL.flex(dict(p, seconds=5.0))[1] == 5.0                                  # (one you set longer is not cut)
        draft2 = TSP.anchored([dict(type='photo', clip='0001', seconds=4.0), dict(type='gap', clip='P1', seconds=4.0)]); ps2, warn2 = SPL.pieces(draft2, pack, {}, 150.0); assert any('0001 is not a photo' in w for w in warn2) and any('P1 is a photo, not a gap' in w for w in warn2)

    def test_a_photo_marked_must_is_added_in_its_place_when_the_script_leaves_it_out(self):
        ps = [dict(kind='broll', seconds=10.0, n=0, label='0001', clip='c1', text='', seg=None), dict(kind='broll', seconds=10.0, n=1, label='0002', clip='c2', text='', seg=None)]
        pack = dict(clips=[dict(label='0001', start_utc='2026-02-22T10:01:00Z'), photo_clip('P1', must=True, start='2026-02-22T10:30:00Z', seconds=2.5), photo_clip('P2', start='2026-02-22T10:40:00Z'), dict(label='0002', start_utc='2026-02-22T12:00:00Z')])
        warn = []; added = SPL.force_gaps(ps, pack, warn); assert added == ['P1'] and [p['label'] for p in ps] == ['0001', 'P1', '0002'] and ps[1]['photo'] and ps[1]['seconds'] == 2.5 and SPL.flex(ps[1]) == (2.0, 3.0) and any('P1' in w for w in warn)


class TestClip:
    def fake_render(self, monkeypatch, calls):
        def write(path, img, pl, size, fps=25.0, crf=20): calls.append((pl['style'], pl['duration_s'], size, fps)); open(path, 'wb').write(b'mp4'); return 1
        monkeypatch.setattr(PM, 'write_video', write)

    def test_the_photo_clip_is_rendered_once_per_length_and_move(self, project, monkeypatch):
        rd = project.race_dir; PH.add(rd, 'a.jpg', jpeg(size=(1600, 900))); calls = []; self.fake_render(monkeypatch, calls)
        made = PCL.sync(project.folder, [dict(clip='P1', seconds=5.0)]); c = made[0]
        assert c['id'] == 'P1' and c['kind'] == 'photo' and c['seconds'] == 5.0 and c['t0'] == c['t1'] == '2026-02-20T14:12:17Z' and c['file'] == os.path.join('synthetic', 'P1.mp4') and c['size'] == '3840x2160' and calls == [(calls[0][0], 5.0, (3840, 2160), 30.0)] and os.path.exists(os.path.join(rd, c['file']))
        assert [x['id'] for x in SY.load(project.folder)['clips']] == ['P1']
        PCL.sync(project.folder, [dict(clip='P1', seconds=5.0)]); assert len(calls) == 1                                                  # nothing changed: kept
        PCL.sync(project.folder, [dict(clip='P1', seconds=7.0)]); assert len(calls) == 2 and SY.load(project.folder)['clips'][0]['seconds'] == 7.0
        PH.set_motion(rd, 'p1', style='pan'); PCL.sync(project.folder, [dict(clip='P1', seconds=7.0)]); assert len(calls) == 3 and calls[-1][0] == 'pan'

    def test_gap_specs_and_removed_photos_are_left_alone(self, project, monkeypatch):
        calls = []; self.fake_render(monkeypatch, calls); logs = []
        assert PCL.sync(project.folder, [dict(clip='G03', seconds=8.0), dict(clip='P9', seconds=5.0)], logs.append) == [] and calls == [] and any('not in the project any more' in l for l in logs)
        assert PCL.is_photo_label('P12') and not PCL.is_photo_label('G01') and not PCL.is_photo_label('PX')


def test_only_photos_ticked_to_use_are_options_a_must_photo_is_used_and_unticking_clears_must(project):
    rd = project.race_dir; PH.add(rd, 'a.jpg', jpeg()); PH.add(rd, 'b.jpg', jpeg(local='2026:02:20 15:00:00'))
    assert SP.photo_clips(project.folder, None, 'UTC') == [] and not PH.is_used(PH.load(rd)['photos'][0])
    PH.set_use(rd, 'p1', True); assert [c['label'] for c in SP.photo_clips(project.folder, None, 'UTC')] == ['P1']
    PH.set_must(rd, 'p2', True); assert PH.is_used(PH.load(rd)['photos'][1]) and [c['label'] for c in SP.photo_clips(project.folder, None, 'UTC')] == ['P1', 'P2']
    PH.set_use(rd, 'p2', False); e = PH.load(rd)['photos'][1]; assert not PH.is_used(e) and 'must' not in e
