"""Editing the word-art cards by hand (edit/film_text_edit.py): list, save (edit and create), delete, and the pictures."""
import json, os
import numpy as np
import pytest

from strata360.edit import film_text_edit as FE
from strata360.render import preview as PVW

PLAN = dict(film=dict(length_s=100.0), segments=[])


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(FE.config, 'race_dir', lambda f: str(tmp_path)); monkeypatch.setattr(PVW, 'plan_key', lambda f, p: 'k1'); return 'proj'


def _spec(text='HALFWAY'): return dict(elements=[dict(text=text, font='anton', size=0.2, x=0.5, y=0.4, fill=dict(type='solid', c1='#ffffff'))], timing=dict(start_s=0.2, end_s=3.0), lines=[dict(role='title', text=text)], why='loud')


def _doc(folder, tmp_path, *cards): json.dump(dict(schema=1, plan_key='k1', cards=list(cards)), open(os.path.join(str(tmp_path), 'film_text.json'), 'w'))


def test_the_listing_is_in_film_order_with_ids_the_editor_choices_and_a_stale_flag(folder, tmp_path):
    _doc(folder, tmp_path, dict(t=50.0, dur_s=3.0, type='progress', lines=[dict(role='title', text='B')], spec=_spec('B')), dict(t=5.0, dur_s=3.0, type='quote', lines=[dict(role='title', text='A')], spec=_spec('A'), id='o9'))
    got = FE.listing(folder, PLAN); assert [c['lines'][0]['text'] for c in got['cards']] == ['A', 'B'] and got['cards'][0]['id'] == 'o9' and got['cards'][1]['id'].startswith('c') and not got['stale'] and got['length_s'] == 100.0
    assert 'anton' in [f['id'] for f in got['fonts']] and 'rise' in got['presets_in'] and got['has_preview'] is False
    json.dump(dict(plan_key='older', cards=[]), open(os.path.join(str(tmp_path), 'film_text.json'), 'w')); assert FE.listing(folder, PLAN)['stale'] is True


def test_a_card_is_made_from_plain_words_with_safe_defaults(folder):
    c = FE.save(folder, PLAN, dict(t=12.0, dur_s=3.0, texts=['LOADS OF IT', 'just down the side', '']))
    assert c['id'].startswith('u') and c['user'] and c['t'] == 12.0 and [e['text'] for e in c['elements']] == ['LOADS OF IT', 'just down the side'] and c['elements'][0]['font'] == 'anton' and c['lines'][1]['role'] == 'meta'
    again = FE.listing(folder, PLAN); assert len(again['cards']) == 1 and json.load(open(FE._file(folder)))['plan_key'] == 'k1'


def test_a_save_changes_the_times_and_words_and_keeps_what_the_models_noted(folder, tmp_path):
    _doc(folder, tmp_path, dict(id='o1', t=40.0, dur_s=3.0, type='progress', lines=[dict(role='title', text='HALFWAY')], spec=_spec(), score=9.0, shot=dict(verdict='ok'), blocking=dict(score=2.0, what='x')))
    c = FE.save(folder, PLAN, dict(id='o1', t=41.234, dur_s=4.0, start_s=0.5, elements=[dict(_spec('MIDWAY')['elements'][0], size=9.0, x=-3, rot=700)]))
    assert c['t'] == 41.23 and c['dur_s'] == 4.0 and c['start_s'] == 0.5 and c['elements'][0]['text'] == 'MIDWAY' and c['score'] == 9.0 and c['blocking'] is None                    # (what was measured for the old words no longer holds)
    el = c['elements'][0]; assert el['size'] <= 0.42 and 0.06 <= el['x'] <= 0.94 and abs(el['rot']) <= 360                                                                       # out-of-range values are made safe, not refused
    stored = json.load(open(FE._file(folder)))['cards'][0]; assert stored['spec']['timing'] == dict(start_s=0.5, end_s=4.0) and stored['spec']['lines'][0]['text'] == 'MIDWAY' and stored['spec']['why'] == 'loud' and stored['by'] == 'hand'


@pytest.mark.parametrize('body, what', [(dict(t=500.0, texts=['x']), 'inside the film'), (dict(t='abc', texts=['x']), 'number'), (dict(t=5.0, dur_s='long', texts=['x']), 'number'), (dict(t=5.0, texts=['  ']), 'at least one word'), (dict(t=5.0, elements='no'), 'list')])
def test_a_card_that_cannot_be_made_says_why(folder, body, what):
    with pytest.raises(FE.Invalid, match=what): FE.save(folder, PLAN, body)


def test_the_length_is_kept_within_what_a_card_can_be_and_an_unknown_card_is_not_found(folder):
    assert FE.save(folder, PLAN, dict(t=1.0, dur_s=0.1, texts=['A']))['dur_s'] == FE.MIN_DUR and FE.save(folder, PLAN, dict(t=2.0, dur_s=99.0, texts=['B']))['dur_s'] == FE.MAX_DUR
    with pytest.raises(KeyError): FE.save(folder, PLAN, dict(id='nope', t=1.0))
    with pytest.raises(KeyError): FE.delete(folder, PLAN, 'nope')


def test_a_card_can_be_deleted(folder, tmp_path):
    _doc(folder, tmp_path, dict(id='o1', t=4.0, dur_s=3.0, lines=[], spec=_spec()), dict(id='o2', t=9.0, dur_s=3.0, lines=[], spec=_spec('B'))); FE.delete(folder, PLAN, 'o1'); assert [c['id'] for c in FE.listing(folder, PLAN)['cards']] == ['o2']


def test_a_picture_of_a_card_is_drawn_once_on_the_frame_or_alone_and_again_when_the_card_changes(folder, tmp_path, monkeypatch):
    frames = []; monkeypatch.setattr(FE, 'frame_at', lambda f, p, t: frames.append(t) or np.full((540, 960, 3), 90, np.uint8)); src = tmp_path / 'base.mp4'; src.write_bytes(b'x'); monkeypatch.setattr(FE, 'base_source', lambda f, p=None: str(src))
    card = dict(id='o1', t=10.0, dur_s=3.0, spec=_spec())
    a = FE.picture(folder, PLAN, card, 'still', 480); assert a[:4] == b'\x89PNG' and len(frames) == 1 and abs(frames[0] - 11.86) < 1e-6
    assert FE.picture(folder, PLAN, card, 'still', 480) == a and len(frames) == 1                                            # the same card and frame: the picture kept
    t = FE.picture(folder, PLAN, card, 'text', 480); assert t[:4] == b'\x89PNG' and t != a and len(frames) == 1                 # alone: no frame needed
    FE.picture(folder, PLAN, dict(card, spec=_spec('OTHER')), 'still', 480); assert len(frames) == 2
    monkeypatch.setattr(FE, 'base_source', lambda f, p=None: None)
    with pytest.raises(FileNotFoundError): FE.picture(folder, PLAN, dict(card, t=11.0), 'still')


def test_the_overlay_sheet_has_every_frame_over_transparency_and_is_kept(folder, tmp_path):
    import cv2
    card = dict(id='o1', t=10.0, dur_s=1.0, spec=_spec('GO')); png = FE.sheet(folder, card); n = FE.sheet_frames(1.0); assert n == 20 and png == FE.sheet(folder, card)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED); W = FE.SHEET_W; H = W * 9 // 16
    assert img.shape == (2 * H, FE.SHEET_COLS * W, 4) and img[..., 3].max() > 200                                                          # 20 frames in 2 rows; the words are opaque
    assert img[H:2 * H, :W, 3].max() > 0                                                                                                    # frame 10 (the first of row 2): the word is on
    assert np.count_nonzero(img[..., 3] == 0) > 0.9 * img[..., 3].size                                                                     # and almost everything else is clear


def test_the_boxes_of_a_card_are_where_its_words_are(folder):
    spec = _spec('GO'); spec['elements'].append(dict(spec['elements'][0], text='AND LATER', y=0.8, size=0.08)); b = FE.boxes_of(dict(id='o1', t=1.0, dur_s=3.0, spec=spec))
    assert len(b) == 2 and all(0.0 <= v <= 1.0 for box in b for v in box) and b[0][1] < b[1][1] and b[0][2] > b[0][0] and FE.boxes_of(dict(id='x', t=0, dur_s=1.0, spec={})) == []
    assert FE.public(dict(id='o1', t=1.0, dur_s=3.0, spec=spec))['boxes'] == b
