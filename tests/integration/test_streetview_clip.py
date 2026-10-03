"""Street view clips with real ffmpeg: the camera renders a section's pictures to a video of the wanted length; a streetview item in the script becomes a planned clip."""
import json, os, subprocess

import cv2
import numpy as np
import pytest

from strata360 import streetview as SV
from strata360.edit import project as PJ, script_draft as SD, streetview_cam as CAM, streetview_clip as SVC, synthetic as SY, voiceover as VO

A, B = 'CAM_20260222100100_0001_D', 'CAM_20260222100200_0002_D'


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=width,height,nb_read_frames', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip().split(','); return int(r[0]), int(r[1]), int(r[2])


def texture(w, h, seed):
    rng = np.random.default_rng(seed); g = cv2.GaussianBlur((rng.random((h, w)) * 255).astype(np.uint8), (0, 0), 3); return cv2.cvtColor(cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)


def section(tmp_path, kind, provider, n=12):
    """A section of n pictures along a meridian, 6 m apart, with the pictures saved where the camera looks for them."""
    rd = str(tmp_path); items = []; meta = {}; sec = dict(id='M1' if provider == 'mapillary' else 'P1', provider=provider, stretch='R1', kind=kind, km0=1.0, km1=1.0 + 6 * (n - 1) / 1000.0, length_m=6 * (n - 1), frames=n, spacing_m=6.0, years=[2024], camera=None, size=None, seq='s', angles=None if kind == '360' else {'forward': n}, items=items)
    os.makedirs(CAM.src_dir(rd, sec), exist_ok=True); base = texture(720, 360, 1) if kind == '360' else texture(400, 300, 1)
    for i in range(n):
        it = dict(id=f'x{i}', km=1.0 + 6 * i / 1000.0, lat=50.0 + 6 * i / 111320.0, lon=5.0, a=0 if kind != '360' else None, b=0, c=0.0); items.append(it)
        cv2.imwrite(CAM.src_path(rd, sec, it['id']), np.roll(base, 3 * i, axis=1))
        meta[it['id']] = dict(computed_rotation=cv2.Rodrigues(np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float))[0].ravel().tolist(), computed_geometry=dict(coordinates=[5.0, 50.0 + 6 * i / 111320.0]), compass_angle=0.0)
    json.dump(meta, open(CAM.meta_path(rd, sec), 'w')); return rd, sec


@pytest.mark.parametrize('kind,provider', [('360', 'mapillary'), ('360', 'panoramax'), ('2d', 'mapillary')])
def test_a_section_is_rendered_to_a_clip_of_the_wanted_length_and_size(tmp_path, monkeypatch, kind, provider):
    rd, sec = section(tmp_path, kind, provider); out = str(tmp_path / 'out.mp4'); road = dict(line=[[50.0 + i * 1e-4, 5.0] for i in range(12)], km0=0.99)
    monkeypatch.setattr(CAM, 'estimate_up', lambda img: np.array([0.0, 1.0, 0.0]))                                                       # (the search for 'up' is tested on its own)
    info = CAM.render(rd, sec, 2.0, out, road=road, size=(160, 90), encode_size=(320, 180)); w, h, n = probe(out)
    assert (w, h) == (320, 180) and abs(n - 60) <= 1 and info['pictures'] == 12 and info['per_s'] == 6.0 and not os.path.exists(out + '.part.mp4')


def test_too_few_pictures_facing_forward_are_refused(tmp_path):
    rd, sec = section(tmp_path, '2d', 'mapillary'); sec['items'] = [dict(it, a=120) for it in sec['items']]
    with pytest.raises(ValueError, match='only 0 pictures face'): CAM.render(rd, sec, 2.0, str(tmp_path / 'o.mp4'), size=(160, 90))


def test_a_missing_picture_and_a_panoramax_section_without_a_road_are_explained(tmp_path):
    rd, sec = section(tmp_path, '360', 'mapillary'); os.remove(CAM.src_path(rd, sec, 'x3'))
    with pytest.raises(RuntimeError, match='x3 has not been fetched'): CAM.render(rd, sec, 2.0, str(tmp_path / 'o.mp4'), size=(160, 90))
    rd2, sec2 = section(tmp_path / 'p', '360', 'panoramax')
    with pytest.raises(ValueError, match='needs the road'): CAM.render(rd2, sec2, 2.0, str(tmp_path / 'o.mp4'), size=(160, 90))


def test_fetch_downloads_each_picture_once_and_keeps_the_reconstruction_data(tmp_path):
    rd = str(tmp_path); sec = dict(id='M1', provider='mapillary', seq='s', km0=1.0, items=[dict(id='a'), dict(id='b')]); calls = []
    def get(url, params): calls.append(url); return dict(thumb_original_url='https://cdn/' + url.rsplit('/', 1)[1], computed_rotation=[0, 0, 1], computed_geometry=dict(coordinates=[5, 50]), compass_angle=10.0)
    def download(url): calls.append(url); return b'jpeg'
    CAM.fetch(rd, sec, 'tok', get=get, download=download, log=lambda *_: None); n = len(calls); CAM.fetch(rd, sec, 'tok', get=get, download=download, log=lambda *_: None)
    assert open(CAM.src_path(rd, sec, 'a'), 'rb').read() == b'jpeg' and json.load(open(CAM.meta_path(rd, sec)))['b']['computed_rotation'] == [0, 0, 1] and len(calls) == n + 2           # (the second fetch asks again for the data, not for the pictures)
    px = dict(id='P1', provider='panoramax', seq='c', km0=2.0, items=[dict(id='z', u='https://p/sd.jpg', h='https://p/full.jpg', c=33.0), dict(id='y', u='https://p/y/sd.jpg', c=44.0)]); got = []
    CAM.fetch(rd, px, None, get=get, download=lambda url: got.append(url) or b'x', log=lambda *_: None); assert got == ['https://p/full.jpg', 'https://p/y/sd.jpg'] and json.load(open(CAM.meta_path(rd, px)))['z']['compass_angle'] == 33.0
    with pytest.raises(RuntimeError, match='no picture to fetch'): CAM.fetch(rd, dict(px, items=[dict(id='q')]), None, get=get, download=download, log=lambda *_: None)


@pytest.fixture
def folder(make_project):
    pr = make_project(config=True); from test_script_plan_project import cand, words
    pr.add_clip(A, start_utc='2026-02-22T10:01:00+00:00', source_frames=1800, fps=30.0, candidates=dict(candidates=[cand(A, 0, 0, 60)], unusable=[]), transcript=dict(segments=[]))
    pr.add_clip(B, start_utc='2026-02-22T10:04:00+00:00', source_frames=900, fps=30.0, candidates=dict(candidates=[cand(B, 0, 0, 30)], unusable=[]))
    n = 720; t0 = 1_771_754_400.0 - 3600; d = 3.0 * 10.0 * np.arange(n); nan = np.full(n, np.nan); tp = os.path.join(pr.race_dir, 'track.gpx'); open(tp, 'w').write('<gpx/>')
    np.savez_compressed(tp + '.npz', t=t0 + 10.0 * np.arange(n), lat=50.0 + d * 8.98e-6, lon=np.full(n, 5.0), alt=100 + np.arange(n) * 0.2, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)       # a run north at 3 m/s from 09:00; the GPX has no distance
    return pr


def chosen_section(folder, choice='possible'):
    rd = folder.race_dir; items = [dict(id=f'm{i}', km=11.1 + 0.005 * i, lat=50.1, lon=5.0, a=None, b=0, t=1_700_000_000 + i) for i in range(60)]
    sec = dict(id='M1', provider='mapillary', stretch='R1', kind='360', km0=11.1, km1=11.395, length_m=295, frames=60, spacing_m=5.0, years=[2024], camera='GoPro Max', size=[5760, 2880], seq='s', angles=None, items=items)
    roads = dict(schema=1, id='r', stretches=[], run=[], total_km=21); SV._save(rd, 'roads', roads); SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [sec], roads)); SV.set_choice(rd, SV.section_key(sec), choice); return sec


def fake_render(made):
    def render(folder, sec, seconds, path, log=print):
        made.append((sec['label'], seconds)); os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc=size=320x180:rate=30:duration={seconds}', '-pix_fmt', 'yuv420p', path], check=True)
    return render


def draft(items): return dict(title='T', wpm=150, target_s=40, items=items, skipped=[])


def test_a_streetview_item_becomes_a_planned_clip_over_the_race_minutes_of_the_section(folder, monkeypatch):
    chosen_section(folder); made = []; monkeypatch.setattr(SVC, 'render', fake_render(made)); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.5 for l in lines})
    SD.save_draft(folder.folder, draft([dict(type='broll', clip='0001', seconds=4.0), dict(type='streetview', clip='V1', seconds=6.0), dict(type='broll', clip='0002', seconds=4.0)])); edit = PJ.plan_from_script(folder.folder); segs = edit['plan']['segments']
    sv = [g for g in segs if g['clip'] == 'V1']; assert len(sv) == 1 and sv[0]['role'] == 'broll' and sv[0]['synthetic'].endswith(os.path.join('synthetic', 'V1.mp4')) and os.path.exists(sv[0]['synthetic']) and made == [('V1', made[0][1])]
    clip = next(c for c in SY.load(folder.folder)['clips'] if c['id'] == 'V1'); assert clip['kind'] == 'streetview' and clip['status'] == 'ready' and abs(clip['seconds'] - sv[0]['dur_s']) < 0.02 and clip['duration_s'] == pytest.approx(98.0, abs=3) and clip['style']['provider'] == 'mapillary'
    assert not [w for w in edit['plan']['warnings'] if 'not rendered' in w]
    PJ.plan_from_script(folder.folder); assert len(made) == 1                                                                              # planned again: the finished clip is kept


def test_a_streetview_marked_must_is_planned_when_the_script_leaves_it_out_and_one_not_chosen_is_not_offered(folder, monkeypatch):
    chosen_section(folder, 'must'); made = []; monkeypatch.setattr(SVC, 'render', fake_render(made)); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.5 for l in lines})
    SD.save_draft(folder.folder, draft([dict(type='broll', clip='0001', seconds=4.0), dict(type='broll', clip='0002', seconds=4.0)])); edit = PJ.plan_from_script(folder.folder)
    assert [g['clip'] for g in edit['plan']['segments'] if g['clip'] == 'V1'] == ['V1'] and any('because you marked them to use' in w for w in edit['plan']['warnings'])
    SV.set_choice(folder.race_dir, 'mapillary:s:11.10', 'none'); made.clear(); edit = PJ.plan_from_script(folder.folder); assert not [g for g in edit['plan']['segments'] if g['clip'] == 'V1']


def test_the_credits_name_the_street_level_source(folder, monkeypatch):
    from strata360.edit import credits
    chosen_section(folder); monkeypatch.setattr(SVC, 'render', fake_render([])); monkeypatch.setattr(VO, 'line_durations', lambda f, lines, log=print: {l['seg']: 2.5 for l in lines})
    SD.save_draft(folder.folder, draft([dict(type='broll', clip='0001', seconds=4.0), dict(type='streetview', clip='V1', seconds=6.0), dict(type='broll', clip='0002', seconds=4.0)])); PJ.plan_from_script(folder.folder)
    assert any('Mapillary contributors (CC BY-SA 4.0)' in t and 'V1' in w for w, t in credits.needed(folder.folder)) and not any('2D map V1' in w for w, t in credits.needed(folder.folder))
