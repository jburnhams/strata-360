"""The HTTP API (server/app.py) through FastAPI's TestClient: auth, path safety, browse, the last project, notes, log, clips and starting a project. No real worker starts (fake_popen)."""
import json, os
import pytest
from projects import CLIP_ID


class TestAuth:
    def test_no_token_configured_means_open(self, client): assert client.get('/api/roots').status_code == 200

    def test_a_token_is_required_when_configured(self, make_client):
        c = make_client(token='s3cret')
        assert c.get('/api/roots').status_code == 401

    @pytest.mark.parametrize('how', ['bearer', 'query'])
    def test_token_accepted(self, make_client, how):
        c = make_client(token='s3cret')
        r = c.get('/api/roots', headers={'Authorization': 'Bearer s3cret'}) if how == 'bearer' else c.get('/api/roots?token=s3cret')
        assert r.status_code == 200

    def test_a_valid_query_token_becomes_a_cookie_for_later_requests(self, make_client):
        c = make_client(token='s3cret')
        assert 'strata360_token' in c.get('/api/roots?token=s3cret').cookies
        assert c.get('/api/roots').status_code == 200                     # the TestClient keeps the cookie

    def test_a_wrong_token_is_refused(self, make_client):
        assert make_client(token='s3cret').get('/api/roots?token=nope').status_code == 401

    def test_responses_are_never_cached(self, client): assert client.get('/api/roots').headers['cache-control'] == 'no-store'


class TestRootsAndBrowse:
    def test_roots_are_listed(self, client, tmp_path): assert client.get('/api/roots').json() == {'roots': [os.path.realpath(tmp_path)]}

    def test_browse_defaults_to_the_first_root(self, client, tmp_path, make_project):
        make_project('alpha', footage=())
        b = client.get('/api/browse').json()
        assert b['path'] == os.path.realpath(tmp_path) and b['parent'] is None and [e['name'] for e in b['entries']] == ['alpha']
        assert b['can_create'] is False                                   # a root itself is never a project

    def test_a_folder_with_camera_files_can_become_a_project(self, client, make_project):
        p = make_project('trip')
        b = client.get('/api/browse', params={'path': p.folder}).json()
        assert b['footage_here'] == 1 and b['can_create'] is True and b['is_project'] is False

    def test_an_existing_project_is_marked_and_its_subfolders_are_hidden(self, client, make_project):
        p = make_project('trip', config=True)
        os.makedirs(os.path.join(p.folder, 'day1'))
        b = client.get('/api/browse', params={'path': p.folder}).json()
        assert b['is_project'] is True and b['entries'] == [] and b['can_create'] is False

    def test_hidden_folders_are_not_offered(self, client, make_project, tmp_path):
        make_project('trip', footage=()); os.makedirs(tmp_path / '.cache')
        assert [e['name'] for e in client.get('/api/browse').json()['entries']] == ['trip']

    def test_the_results_folder_is_not_offered(self, client, make_project):
        p = make_project('trip', footage=()); os.makedirs(p.race_dir)
        assert client.get('/api/browse', params={'path': p.folder}).json()['entries'] == []

    @pytest.mark.parametrize('bad', ['/etc', '/', 'PARENT'])
    def test_paths_outside_the_roots_are_forbidden(self, client, tmp_path, bad):
        assert client.get('/api/browse', params={'path': str(tmp_path.parent) if bad == 'PARENT' else bad}).status_code == 403

    def test_an_empty_path_means_the_first_root(self, client, tmp_path): assert client.get('/api/browse', params={'path': ''}).json()['path'] == os.path.realpath(tmp_path)

    def test_a_symlink_out_of_the_roots_is_not_followed(self, make_client, tmp_path):
        root, outside = tmp_path / 'root', tmp_path / 'outside'; root.mkdir(); outside.mkdir()
        try: os.symlink(outside, root / 'escape')
        except OSError: pytest.skip('cannot create symlinks here')
        c = make_client(roots=[root])
        assert c.get('/api/browse', params={'path': str(root / 'escape')}).status_code == 403
        assert c.get('/api/browse').json()['entries'] == []


class TestLastProject:
    def test_none_before_anything_was_opened(self, client): assert client.get('/api/last').json() == {'folder': None}

    def test_open_remembers_the_project(self, client, make_project):
        p = make_project('trip', config=True)
        assert client.post('/api/open', json={'folder': p.folder}).json() == {'started': True}
        assert client.get('/api/last').json() == {'folder': p.folder}

    def test_a_project_that_vanished_is_forgotten(self, client, make_project):
        import shutil
        p = make_project('trip', config=True); client.post('/api/open', json={'folder': p.folder})
        shutil.rmtree(p.race_dir)
        assert client.get('/api/last').json() == {'folder': None}


class TestOpen:
    def test_starts_one_worker_for_the_project(self, client, make_project, fake_popen):
        p = make_project('trip', config=True)
        client.post('/api/open', json={'folder': p.folder})
        assert [w.cmd[-2:] for w in fake_popen.instances] == [['open', p.folder]]

    def test_languages_are_passed_on(self, client, make_project, fake_popen):
        p = make_project('trip', config=True); client.post('/api/open', json={'folder': p.folder, 'languages': 'en,fr'})
        assert fake_popen.instances[0].cmd[-4:] == ['open', p.folder, '--languages', 'en,fr']

    def test_a_root_is_not_a_project(self, client, tmp_path):
        r = client.post('/api/open', json={'folder': str(tmp_path)})
        assert r.status_code == 400 and 'allowed root' in r.json()['detail']

    def test_a_new_folder_without_camera_files_is_refused(self, client, make_project):
        p = make_project('empty', footage=())
        r = client.post('/api/open', json={'folder': p.folder})
        assert r.status_code == 400 and 'no camera files' in r.json()['detail']

    def test_a_folder_outside_the_roots_is_forbidden(self, client): assert client.post('/api/open', json={'folder': '/etc'}).status_code == 403


class TestNotes:
    def test_empty_by_default(self, client, project):
        assert client.get('/api/notes', params={'folder': project.folder}).json() == {'folder': '', 'clips': {}, 'updated': {}, 'vo_must': {'folder': '', 'folder_ordered': True, 'clips': {}}}

    def test_saves_the_folder_note(self, client, project):
        n = client.post('/api/notes', json={'folder': project.folder, 'text': 'a good day'}).json()
        assert n['folder'] == 'a good day' and 'folder' in n['updated']
        assert client.get('/api/notes', params={'folder': project.folder}).json()['folder'] == 'a good day'

    def test_saves_and_clears_a_clip_note(self, client, project):
        body = {'folder': project.folder, 'clip': CLIP_ID}
        assert client.post('/api/notes', json={**body, 'text': 'start line'}).json()['clips'] == {CLIP_ID: 'start line'}
        assert client.post('/api/notes', json={**body, 'text': '  '}).json()['clips'] == {}

    def test_notes_of_a_folder_outside_the_roots_are_forbidden(self, client): assert client.get('/api/notes', params={'folder': '/etc'}).status_code == 403


class TestLogAndClips:
    def test_log_is_empty_without_a_run(self, client, project): assert client.get('/api/log', params={'folder': project.folder}).json() == {'lines': []}

    def test_log_returns_the_last_40_lines(self, client, project):
        open(project.path('run.log'), 'w').write('\n'.join(f'line {i}' for i in range(100)))
        lines = client.get('/api/log', params={'folder': project.folder}).json()['lines']
        assert len(lines) == 40 and lines[0] == 'line 60' and lines[-1] == 'line 99'

    def test_a_clip_the_film_plays_is_marked_in_film(self, client, make_project):
        from strata360.edit import project as PJ
        p = make_project(config=True); p.add_clip(CLIP_ID, source_frames=300, fps=30.0)
        assert client.get('/api/clips', params={'folder': p.folder}).json()['clips'][0]['in_film'] is False                                  # no plan yet
        edit = PJ.load(p.folder); edit['plan'] = dict(segments=[dict(clip=CLIP_ID), dict(clip='G01')]); PJ.save(p.folder, edit)
        assert client.get('/api/clips', params={'folder': p.folder}).json()['clips'][0]['in_film'] is True
        edit['plan'] = dict(segments=[dict(clip='G01')]); PJ.save(p.folder, edit); assert client.get('/api/clips', params={'folder': p.folder}).json()['clips'][0]['in_film'] is False

    def test_clips_summarise_each_clip(self, client, make_project):
        p = make_project(config=True)
        p.add_clip(CLIP_ID, source_frames=300, fps=30.0, motion={'summary': {'steady': 0.8}}, candidates={'summary': {'n': 3}})
        open(os.path.join(p.clip_dir(), 'thumb.jpg'), 'wb').write(b'x')
        [c] = client.get('/api/clips', params={'folder': p.folder}).json()['clips']
        assert c == dict(id=CLIP_ID, start_utc='2026-02-21T12:00:07+00:00', duration_s=10.0, has_note=False, thumb='best', thumb_overlay=False, audio_original=False, audio_clean=False, in_film=False, steady=0.8, candidates=3)

    def test_overlay_thumbnail_when_it_matches_the_current_one(self, client, make_project):
        p = make_project(config=True); p.add_clip(CLIP_ID); d = p.clip_dir(); open(os.path.join(d, 'thumb.jpg'), 'wb').write(b'plain'); open(os.path.join(d, 'thumb_overlay.jpg'), 'wb').write(b'over')
        json.dump(dict(source='thumb.jpg', source_mtime=os.path.getmtime(os.path.join(d, 'thumb.jpg'))), open(os.path.join(d, 'thumb_overlay.json'), 'w'))
        get = lambda **kw: client.get('/api/thumb', params={'folder': p.folder, 'clip': CLIP_ID, **kw}).content
        [c] = client.get('/api/clips', params={'folder': p.folder}).json()['clips']; assert c['thumb'] == 'best' and c['thumb_overlay'] is True
        assert get(overlay=1) == b'over' and get() == b'plain'
        os.utime(os.path.join(d, 'thumb.jpg'), (1, 1))                                                   # a newer thumbnail: the overlay one is out of date until the stage redoes it
        [c] = client.get('/api/clips', params={'folder': p.folder}).json()['clips']; assert c['thumb_overlay'] is False and get(overlay=1) == b'plain'

    def test_a_clip_without_clip_json_is_skipped(self, client, project):
        os.makedirs(project.clip_dir('CAM_broken'))
        assert [c['id'] for c in client.get('/api/clips', params={'folder': project.folder}).json()['clips']] == [CLIP_ID]

    def test_a_clip_with_a_note_is_flagged(self, client, project):
        client.post('/api/notes', json={'folder': project.folder, 'clip': CLIP_ID, 'text': 'hi'})
        assert client.get('/api/clips', params={'folder': project.folder}).json()['clips'][0]['has_note'] is True


class TestMarksAndNarrationNotes:
    TR = dict(segments=[dict(t0=1.0, t1=3.0, text='we are fine', text_en='we are fine', lang='en', words=[dict(w=x, t0=1.0 + i * 0.5, t1=1.4 + i * 0.5, p=0.9) for i, x in enumerate(['we', 'are', 'fine'])])])

    def test_marking_words_shows_up_on_the_clip_transcript(self, client, project):
        project.add_clip(transcript=self.TR); q = dict(folder=project.folder, clip=CLIP_ID)
        r = client.post('/api/transcript/mark', json=dict(**q, spans=[dict(seg=0, **{'from': 1, 'to': 2})], state='never')); assert r.status_code == 200 and r.json()['marked'] == 2
        words = [w for p in client.get('/api/clip', params=q).json()['transcript'] for w in p['words']]; assert [w.get('m') for w in words] == [None, 'never', 'never']
        assert client.post('/api/transcript/mark', json=dict(**q, spans=[dict(seg=0, **{'from': 0, 'to': 2})], state='none')).json()['marked'] == 0

    def test_bad_marks_are_refused(self, client, project):
        project.add_clip(transcript=self.TR); q = dict(folder=project.folder, clip=CLIP_ID)
        assert client.post('/api/transcript/mark', json=dict(**q, spans=[], state='must')).status_code == 400
        assert client.post('/api/transcript/mark', json=dict(**q, spans=[dict(seg=0, **{'from': 0, 'to': 9})], state='must')).status_code == 404
        assert client.post('/api/transcript/mark', json=dict(**q, spans=[dict(seg=0, **{'from': 0, 'to': 1})], state='purple')).status_code == 400

    def test_the_narration_must_include_fields_save_beside_the_notes(self, client, project):
        f = project.folder
        r = client.post('/api/notes', json=dict(folder=f, kind='vo', text='One.\nTwo.', ordered=False)); assert r.json()['vo_must'] == dict(folder='One.\nTwo.', folder_ordered=False, clips={})
        client.post('/api/notes', json=dict(folder=f, kind='vo', text='In the clip.', clip=CLIP_ID)); n = client.get('/api/notes', params=dict(folder=f)).json()
        assert n['vo_must']['clips'] == {CLIP_ID: 'In the clip.'} and n['folder'] == '' and n['clips'] == {}                       # the ordinary notes are untouched
        client.post('/api/notes', json=dict(folder=f, kind='vo', text='  ', clip=CLIP_ID)); assert client.get('/api/notes', params=dict(folder=f)).json()['vo_must']['clips'] == {}


class TestScript2:
    def test_nothing_yet(self, client, project):
        r = client.get('/api/script2', params=dict(folder=project.folder)).json()
        assert r['draft'] is None and r['drafts'] == [] and r['running'] is False and r['pins'] == {} and r['used'] == []

    def test_pins_are_validated_and_saved(self, client, project):
        f = project.folder
        assert client.post('/api/script2/pins', json=dict(folder=f, vo=[dict(id='v1', text='x', mode='clip')])).status_code == 400            # a clip pin needs its clip
        assert client.post('/api/script2/pins', json=dict(folder=f, vo=[dict(id='v1', text='', mode='anywhere')])).status_code == 400
        ok = client.post('/api/script2/pins', json=dict(folder=f, include=['0019.01'], vo=[dict(id='v1', text='Say this.', mode='anywhere')])); assert ok.status_code == 200
        assert client.get('/api/script2', params=dict(folder=f)).json()['pins']['include'] == ['0019.01']

    def test_generate_starts_a_background_draft_once(self, client, project, fake_popen):
        f = project.folder; r = client.post('/api/script2/generate', json=dict(folder=f, revise=True, target_s=200, wpm=170, auto=True)); assert r.json() == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'script-draft' in cmd and '--revise' in cmd and '--target-s' in cmd and '200.0' in cmd and '--wpm' in cmd and '--auto' in cmd
        assert client.get('/api/script2', params=dict(folder=f)).json()['running'] is True and client.post('/api/script2/generate', json=dict(folder=f)).json()['started'] is False


class TestScript2Plan:
    def test_the_plan_is_reported_with_its_source(self, client, project):
        f = project.folder; assert client.get('/api/script2', params=dict(folder=f)).json()['plan'] is None
        project.write_json('project.json', dict(edit=dict(plan=dict(source='script', script='draft-1.json', film=dict(length_s=120.5), segments=[{}, {}, {}], warnings=['clip 0025: not enough free footage'], generated_at='2026-10-03T08:00:00Z'))))
        p = client.get('/api/script2', params=dict(folder=f)).json()['plan']; assert p['source'] == 'script' and p['windows'] == 3 and p['length_s'] == 120.5 and p['warnings'] == ['clip 0025: not enough free footage']

    def test_planning_starts_a_background_job_once_and_can_name_a_draft(self, client, project, fake_popen):
        f = project.folder; r = client.post('/api/script2/plan', json=dict(folder=f, draft='../../etc/draft-2.json')); assert r.json() == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'script-plan' in cmd and '--voice' in cmd and cmd[cmd.index('--draft') + 1] == 'draft-2.json'                  # only the file name is passed on
        j = client.get('/api/script2', params=dict(folder=f)).json(); assert j['plan_running'] is True and client.post('/api/script2/plan', json=dict(folder=f)).json()['started'] is False


class TestRaceMapData:
    T0 = 1_771_700_000.0

    def put_track(self, project, hours=2):
        import numpy as np
        n = int(hours * 360); t = self.T0 + 10.0 * np.arange(n); d = 3.0 * 10.0 * np.arange(n); nan = np.full(n, np.nan); p = os.path.join(project.race_dir, 'track.gpx'); os.makedirs(project.race_dir, exist_ok=True); open(p, 'w').write('<gpx/>')
        np.savez_compressed(p + '.npz', t=t, lat=50.0 + d * 5.4e-6, lon=5.0 + d * 1.119e-5, alt=100 + np.arange(n) * 0.2, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)          # track.load reads this cache, so the test needs no GPX library; like a GPX it has no speed or distance

    def iso(self, off):
        import datetime as dt
        return (dt.datetime.fromtimestamp(self.T0 + off, dt.timezone.utc)).isoformat()

    def test_without_a_track_there_is_nothing_to_draw(self, client, project):
        for path in ('series', 'line', 'clips'): assert client.get(f'/api/track/{path}', params=dict(folder=project.folder)).status_code == 404

    def test_series_gives_the_charts_their_points(self, client, project):
        self.put_track(project); s = client.get('/api/track/series', params=dict(folder=project.folder, points=150)).json()
        assert s['points'] == 150 and len(s['t']) == 150 and s['pace'][10] is not None and abs(s['pace'][10] - 1000 / 3 / 60) < 0.5 and s['distance_km'] > 15      # a GPX gets distance and pace from its positions

    def test_the_line_comes_whole_or_for_the_box_in_view(self, client, project):
        self.put_track(project); q = dict(folder=project.folder); whole = client.get('/api/track/line', params=dict(q, limit=300)).json(); assert 0 < len(whole['lat']) <= 300
        part = client.get('/api/track/line', params=dict(q, bbox='50.0,5.0,50.02,5.05', limit=5000)).json(); assert 0 < len(part['lat']) < len(whole['lat']) * 20 and max(part['lat']) < 50.05
        assert client.get('/api/track/line', params=dict(q, bbox='1,2,3')).status_code == 400 and client.get('/api/track/line', params=dict(q, bbox='a,b,c,d')).status_code == 400

    def test_every_clip_is_placed_and_marked_as_played_by_the_draft_or_not(self, client, project):
        from strata360.edit import script_draft as SD
        self.put_track(project); project.add_clip('CAM_20260222190000_0001_D', start_utc=self.iso(600), source_frames=1800, fps=30.0); project.add_clip('CAM_20260222180000_0002_D', start_utc=self.iso(-7200), source_frames=900, fps=30.0)
        SD.save_draft(project.folder, dict(items=[dict(type='clip', clip='0001', seconds=12.5, lines=[]), dict(type='vo', clip='0001', text='x', seconds=4.0)]))
        r = client.get('/api/track/clips', params=dict(folder=project.folder)).json(); by = {c['label']: c for c in r['clips']}; assert r['has_draft'] is True
        a, b = by['0001'], by['0002']; assert a['covered'] and a['used'] is True and a['used_s'] == 16.5 and a['lat'] > 50.0 and len(a['stretch']) >= 2 and a['facts']['local']
        assert b['covered'] is False and b['used'] is False and 'lat' not in b                                         # before the track starts: listed, not placed


class TestGapClipsApi(TestRaceMapData):
    def with_gap(self, project):
        self.put_track(project); project.add_clip('CAM_20260222190000_0001_D', start_utc=self.iso(0), source_frames=9000, fps=30.0); project.add_clip('CAM_20260222190000_0002_D', start_utc=self.iso(5000), source_frames=3600, fps=30.0)

    def test_the_gaps_are_listed_with_their_default_length_and_no_clips_yet(self, client, project):
        self.with_gap(project); g = client.get('/api/gaps', params=dict(folder=project.folder)).json()['gaps']
        assert [x['id'] for x in g if not x.get('final')] == ['G01'] and 4000 < g[0]['duration_s'] < 4800 and g[0]['clips'] == [] and 6 <= g[0]['default_seconds'] <= 45

    def test_a_flyover_can_be_planned_in_4k_and_the_list_says_whether_it_can_be_rendered(self, client, project, monkeypatch, tmp_path):
        from strata360.overlay import flyover as FO
        self.with_gap(project); f = project.folder; monkeypatch.delenv('MBGL_RENDER', raising=False); monkeypatch.setattr(FO, 'MBGL_DEFAULT', str(tmp_path / 'none')); monkeypatch.setattr(FO.shutil, 'which', lambda n: None)
        r = client.get('/api/gaps', params=dict(folder=f)).json()['flyover']; assert r['available'] is False and 'terrain-flyover.md' in r['note']
        exe = tmp_path / 'mbgl-render'; exe.write_text('x'); monkeypatch.setenv('MBGL_RENDER', str(exe)); assert client.get('/api/gaps', params=dict(folder=f)).json()['flyover'] == dict(available=True, note='')
        c = client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=20, kind='flyover')).json(); assert c['kind'] == 'flyover' and c['size'] == '3840x2160'
        assert client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', kind='orbit')).status_code == 400 and client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=20)).json()['kind'] == 'map'

    def test_planning_a_clip_for_a_gap_or_a_stretch_of_it(self, client, project):
        self.with_gap(project); f = project.folder; r = client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=10)).json()
        assert r['id'] == 'G01' and r['seconds'] == 10.0 and r['status'] == 'planned' and client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]['id'] == 'G01'
        g = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]; a = g['t0'] + 600
        assert client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', **{'from': a, 'to': a + 1200})).status_code == 400                                  # a stretch needs its own id
        s = client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', id='G01b', speedup=100, **{'from': a, 'to': a + 1200})).json(); assert s['id'] == 'G01b' and s['seconds'] == 12.0
        assert client.post('/api/gaps/clip', json=dict(folder=f, gap='G09')).status_code == 404 and client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=0.5)).status_code == 400

    def test_rendering_starts_a_background_job_once_and_a_missing_clip_is_refused(self, client, project, fake_popen):
        self.with_gap(project); f = project.folder; client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=10))
        assert client.post('/api/gaps/render', json=dict(folder=f, id='nope')).status_code == 404
        assert client.post('/api/gaps/render', json=dict(folder=f, id='G01')).json() == dict(started=True); cmd = fake_popen.instances[-1].cmd; assert 'gap-clip' in cmd and cmd[cmd.index('--clip') + 1] == 'G01'
        g = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]; assert g['rendering'] is True and client.post('/api/gaps/render', json=dict(folder=f, id='G01')).json()['started'] is False

    def test_no_clip_waits_for_approval_even_one_an_older_plan_left_unapproved(self, client, project, fake_popen):
        from strata360.edit import synthetic as SY
        self.with_gap(project); f = project.folder; g = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]
        SY.upsert(f, SY.make(g, seconds=10, kind='flyover', approved=False)); c = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]; assert c['approved'] is False
        assert client.post('/api/gaps/render', json=dict(folder=f, id='G01')).json() == dict(started=True) and fake_popen.instances                      # no approval step: an older plan's unapproved flyover renders when asked
        assert client.post('/api/gaps/approve', json=dict(folder=f, id='G01')).json()['approved'] is True
        assert client.post('/api/gaps/approve', json=dict(folder=f, id='nope')).status_code == 404
        client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=10, kind='flyover')); assert client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]['approved'] is True              # asking for it yourself is the approval

    def test_a_rendered_clip_can_be_played_and_removed(self, client, project):
        from strata360.edit import synthetic as SY
        self.with_gap(project); f = project.folder; c = client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=10)).json(); assert client.get('/api/gaps/video', params=dict(folder=f, id='G01')).status_code == 404
        os.makedirs(os.path.join(project.race_dir, 'synthetic'), exist_ok=True); open(os.path.join(project.race_dir, 'synthetic', 'G01.mp4'), 'wb').write(b'x' * 10)
        doc = SY.load(f); doc['clips'][0].update(status='ready', file='synthetic/G01.mp4'); SY.save(f, doc)
        assert client.get('/api/gaps/video', params=dict(folder=f, id='G01')).content == b'x' * 10 and client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]['exists'] is True
        assert client.delete('/api/gaps/clip', params=dict(folder=f, id='G01')).json() == dict(removed=True) and not os.path.exists(os.path.join(project.race_dir, 'synthetic', 'G01.mp4')) and SY.load(f)['clips'] == [] and c

    def test_progress_ignores_start_up_warnings_and_a_failure_shows_its_real_error(self, client, project, fake_popen):
        self.with_gap(project); f = project.folder; client.post('/api/gaps/clip', json=dict(folder=f, gap='G01', seconds=10)); client.post('/api/gaps/render', json=dict(folder=f, id='G01'))
        log = os.path.join(project.race_dir, 'synthetic', 'G01.log'); noise = 'ValueError: unsupported hash type blake2s\n'
        open(log, 'w').write('  G01: 40/300 frames\n' + noise); g = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]; assert g['progress'] == 'G01: 40/300 frames' and g['error'] == ''
        open(log, 'w').write(noise); assert client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]['progress'] == 'starting…'
        from strata360.server import app as A
        A.GAP_JOBS.clear(); open(log, 'w').write(noise + 'Traceback (most recent call last):\nstrata360.overlay.tiles.MissingKey: the map style tf-landscape needs a key\n' + noise)
        c = client.get('/api/gaps', params=dict(folder=f)).json()['gaps'][0]['clips'][0]; assert c['rendering'] is False and c['error'].startswith('strata360.overlay.tiles.MissingKey')


class TestRoughMixApi:
    def plan(self, project):
        project.write_json('project.json', dict(edit=dict(plan=dict(source='script', film=dict(length_s=8.0), segments=[dict(clip='X', clip_start_s=0.0, dur_s=8.0)]))))

    def test_without_a_plan_nothing_is_started(self, client, project, fake_popen):
        f = project.folder; assert client.get('/api/script2/mix', params=dict(folder=f)).json()['has_plan'] is False
        r = client.post('/api/script2/mix', json=dict(folder=f)).json(); assert r['started'] is False and 'no film plan' in r['reason'] and not fake_popen.instances

    def test_making_the_mix_runs_the_command_once_and_the_audio_is_served_when_it_exists(self, client, project, fake_popen):
        self.plan(project); f = project.folder; assert client.post('/api/script2/mix', json=dict(folder=f)).json() == dict(started=True)
        assert 'rough-mix' in fake_popen.instances[-1].cmd and client.post('/api/script2/mix', json=dict(folder=f)).json()['started'] is False
        s = client.get('/api/script2/mix', params=dict(folder=f)).json(); assert s['building'] is True and s['exists'] is False and client.get('/api/script2/mix/audio', params=dict(folder=f)).status_code == 404
        d = os.path.join(project.race_dir, 'roughmix'); open(os.path.join(d, 'mix.m4a'), 'wb').write(b'x' * 12); json.dump(dict(key='k', length_s=8.0, made_at='t'), open(os.path.join(d, 'mix.json'), 'w'))
        assert client.get('/api/script2/mix/audio', params=dict(folder=f)).content == b'x' * 12

    def test_reset_forgets_the_mix_unless_it_is_being_made(self, client, project, fake_popen):
        self.plan(project); f = project.folder; d = os.path.join(project.race_dir, 'roughmix'); os.makedirs(d, exist_ok=True); open(os.path.join(d, 'mix.m4a'), 'wb').write(b'x'); json.dump(dict(key='k', parts={}), open(os.path.join(d, 'mix.json'), 'w'))
        assert client.delete('/api/script2/mix', params=dict(folder=f)).json() == dict(reset=True) and not os.path.exists(os.path.join(d, 'mix.m4a')) and client.delete('/api/script2/mix', params=dict(folder=f)).json() == dict(reset=False)
        client.post('/api/script2/mix', json=dict(folder=f)); assert client.delete('/api/script2/mix', params=dict(folder=f)).status_code == 409

    def test_a_failed_run_shows_its_real_error_not_the_interpreters_warnings(self, client, project, fake_popen):
        self.plan(project); f = project.folder; client.post('/api/script2/mix', json=dict(folder=f)); fake_popen.instances[-1].returncode = 1
        open(os.path.join(project.race_dir, 'roughmix', 'mix.log'), 'w').write('ValueError: unsupported hash type blake2s\nTraceback (most recent call last):\n  File "x", line 1\nno voice is installed: run voice setup\n')
        s = client.get('/api/script2/mix', params=dict(folder=f)).json(); assert s['building'] is False and s['error'] == 'no voice is installed: run voice setup'


class TestMapTiles:
    @pytest.fixture(autouse=True)
    def keys(self, tmp_path, monkeypatch):
        from strata360.edit import llm_remote as L
        monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env')); monkeypatch.delenv('THUNDERFOREST_API_KEY', raising=False)

    def served(self, monkeypatch, fetch):
        from strata360.server import app as A
        monkeypatch.setattr(A, 'TILE_FETCH', fetch)

    def test_a_tile_is_fetched_once_through_the_server_and_then_comes_from_the_cache(self, client, monkeypatch):
        from overlay_fakes import TileServer
        ts = TileServer(colour=(10, 200, 30)); self.served(monkeypatch, ts)
        r = client.get('/api/tiles/osm/5/16/10'); assert r.status_code == 200 and r.headers['content-type'] == 'image/png' and r.content[:4] == b'\x89PNG'
        assert client.get('/api/tiles/osm/5/16/10').status_code == 200 and len(ts.urls) == 1

    def test_the_key_stays_on_the_server_and_is_never_in_what_the_browser_gets(self, client, monkeypatch):
        from overlay_fakes import TileServer
        monkeypatch.setenv('THUNDERFOREST_API_KEY', 'secretkey123'); ts = TileServer(); self.served(monkeypatch, ts)
        r = client.get('/api/tiles/tf-landscape/6/32/21'); assert r.status_code == 200 and 'secretkey123' in ts.urls[0] and b'secretkey123' not in r.content
        s = client.get('/api/tiles/status', params=dict(style='tf-landscape')).json(); assert s['ok'] is True and 'Thunderforest' in s['credit'] and 'secretkey123' not in str(s)

    def test_a_missing_key_is_an_error_with_the_fix_not_an_empty_map(self, client):
        s = client.get('/api/tiles/status', params=dict(style='tf-landscape')).json(); assert s['ok'] is False and 'THUNDERFOREST_API_KEY' in s['error']
        r = client.get('/api/tiles/tf-landscape/6/32/21'); assert r.status_code == 503 and 'THUNDERFOREST_API_KEY' in r.json()['detail']

    def test_unknown_styles_and_zooms_and_a_failing_service_are_refused_clearly(self, client, monkeypatch):
        import urllib.error
        assert client.get('/api/tiles/nope/5/1/1').status_code == 404 and client.get('/api/tiles/osm/40/1/1').status_code == 404
        def boom(url): raise urllib.error.HTTPError(url, 429, 'slow down', {}, None)
        self.served(monkeypatch, boom); r = client.get('/api/tiles/osm/5/3/3'); assert r.status_code == 502 and 'HTTP 429' in r.json()['detail']


class TestLyricsApi:
    def track(self, project):
        os.makedirs(os.path.join(project.race_dir, 'music'), exist_ok=True); open(os.path.join(project.race_dir, 'music', 'track.mp3'), 'wb').write(b'x'); json.dump(dict(file='music/track.mp3', sig=[1, 2]), open(os.path.join(project.race_dir, 'music.json'), 'w'))

    def record(self, project):
        from strata360.edit import lyrics as LY
        ph = lambda a, b, t: dict(t0=a, t1=b, text=t, avg_logprob=-0.4, no_speech=0.3, words=[])
        LY.build(project.folder, log=lambda m: None, transcriber=lambda p: ([ph(10.0, 14.0, 'one'), ph(14.5, 20.0, 'two')], dict(language='en', language_probability=0.9, duration_s=60.0)))

    def test_without_a_track_nothing_is_started(self, client, project, fake_popen):
        f = project.folder; assert client.get('/api/lyrics', params=dict(folder=f)).json()['has_track'] is False
        r = client.post('/api/lyrics', json=dict(folder=f)).json(); assert r['started'] is False and 'no music track' in r['reason'] and not fake_popen.instances

    def test_finding_the_lyrics_runs_the_command_once_and_a_failure_shows_its_real_error(self, client, project, fake_popen):
        self.track(project); f = project.folder; assert client.post('/api/lyrics', json=dict(folder=f)).json() == dict(started=True)
        assert 'lyrics' in fake_popen.instances[-1].cmd and client.post('/api/lyrics', json=dict(folder=f)).json()['started'] is False and client.get('/api/lyrics', params=dict(folder=f)).json()['building'] is True
        fake_popen.instances[-1].returncode = 1; open(os.path.join(project.race_dir, 'lyrics.log'), 'w').write('ValueError: unsupported hash type blake2s\nTraceback (most recent call last):\n  File "x", line 1\nModuleNotFoundError: No module named faster_whisper\n')
        s = client.get('/api/lyrics', params=dict(folder=f)).json(); assert s['building'] is False and s['error'] == 'ModuleNotFoundError: No module named faster_whisper'

    def test_the_phrases_and_sung_stretches_come_back_and_can_be_corrected_and_reset(self, client, project):
        self.track(project); self.record(project); f = project.folder; g = client.get('/api/lyrics', params=dict(folder=f)).json()
        assert g['exists'] and [p['key'] for p in g['phrases_list']] == ['10.0-14.0', '14.5-20.0'] and g['vocal_spans'] == [[9.7, 20.3]]
        r = client.post('/api/lyrics/phrase', json=dict(folder=f, key='14.5-20.0', deleted=True)).json(); assert r['deleted'] is True and client.get('/api/lyrics', params=dict(folder=f)).json()['vocal_spans'] == [[9.7, 14.3]]
        assert client.post('/api/lyrics/phrase', json=dict(folder=f, key='9.0-9.5', deleted=True)).status_code == 404
        assert client.delete('/api/lyrics', params=dict(folder=f)).json() == dict(reset=True) and client.get('/api/lyrics', params=dict(folder=f)).json()['exists'] is False


class TestClipSounds:
    def test_the_clip_audio_endpoint_serves_original_clean_and_background(self, client, make_project):
        p = make_project(config=True); p.add_clip(CLIP_ID)
        for name in ('audio_original.flac', 'audio_clean.flac', 'audio_background.flac'): open(os.path.join(p.clip_dir(), name), 'wb').write(name.encode())
        get = lambda kind: client.get('/api/clip/audio', params={'folder': p.folder, 'clip': CLIP_ID, 'kind': kind})
        assert get('original').content == b'audio_original.flac' and get('clean').content == b'audio_clean.flac' and get('background').content == b'audio_background.flac'
        os.remove(os.path.join(p.clip_dir(), 'audio_background.flac')); assert get('background').status_code == 404

    def test_the_clip_detail_says_which_sounds_exist(self, client, make_project):
        p = make_project(config=True); p.add_clip(CLIP_ID); open(os.path.join(p.clip_dir(), 'audio_background.flac'), 'wb').write(b'x')
        d = client.get('/api/clip', params={'folder': p.folder, 'clip': CLIP_ID}).json()
        assert d['audio_files'] == dict(original=False, clean=False, background=True)


def test_the_interpreters_hashlib_noise_never_reaches_a_job_log_shown_in_the_web():
    from strata360.server import app as SRV
    noisy = ['ERROR:root:code for hash blake2s was not found.', 'Traceback (most recent call last):', '  File "/x/lib/python3.13/hashlib.py", line 247, in <module>', '    globals()[__func_name] = __get_hash(__func_name)',
             '                             ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^', 'ValueError: unsupported hash type blake2s', 'writing draft 2 of 3', 'Traceback (most recent call last):', '  File "script_draft.py", line 9, in main', 'KeyError: gemini']
    assert SRV.clean_log(noisy) == ['writing draft 2 of 3', 'Traceback (most recent call last):', '  File "script_draft.py", line 9, in main', 'KeyError: gemini']      # a real traceback stays
    assert SRV.clean_log([]) == []


class TestProposeKeepsAScriptPlan:
    def test_the_beat_planner_does_not_replace_a_film_planned_from_the_script_unless_told_to(self, client, project, monkeypatch):
        from strata360.edit import project as PJ
        monkeypatch.setattr(PJ, 'load', lambda f: dict(plan=dict(source='script'))); called = []; monkeypatch.setattr(PJ, 'propose', lambda f, s=None, o=None, keep=True: called.append(1) or dict(plan=None))
        r = client.post('/api/edit/propose', json=dict(folder=project.folder)); assert r.status_code == 409 and 'planned from the script' in r.json()['detail'] and not called
        assert client.post('/api/edit/propose', json=dict(folder=project.folder, replace=True)).status_code == 200 and called


class TestTracksCollection:
    """Several tracks per project: runs merge into the race track, routes only show on the overview map."""

    def gpx(self, n=60, lat0=50.0, t0=1_770_000_000, route=False, wpt=False):
        from datetime import datetime, timezone
        tm = lambda i: '' if route else f'<time>{datetime.fromtimestamp(t0 + i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>'
        pts = ''.join(f'<trkpt lat="{lat0 + i * 1e-4}" lon="5.0"><ele>10</ele>{tm(i)}</trkpt>' for i in range(n))
        w = '<wpt lat="50.001" lon="5.0"><name>Aid 1</name></wpt>' if wpt else ''
        return f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">{w}<trk><trkseg>{pts}</trkseg></trk><!--{"x" * 100}--></gpx>'.encode()

    def test_upload_mark_merge_and_remove(self, client, project):
        q = dict(folder=project.folder); up = lambda name, data, **kw: client.post('/api/tracks', params=dict(q, filename=name, **kw), content=data)
        a = up('a.gpx', self.gpx(wpt=True)).json(); assert a['kind'] == 'run'
        b = up('b.gpx', self.gpx(lat0=50.01, t0=1_770_001_000)).json(); assert b['kind'] == 'route'
        r = client.post('/api/tracks/kind', json=dict(q, id=b['id'], kind='run')); assert r.status_code == 200 and r.json()['runs'] == 2 and r.json()['merged']['samples'] == 120
        ov = client.get('/api/track', params=q).json(); assert ov['samples'] == 120                                           # the one race track is the merged runs
        assert client.get('/api/tracks/line', params=dict(q, id='merged', limit=50)).json()['lat'] and client.get('/api/tracks/line', params=dict(q, id=a['id'])).status_code == 200
        assert [p['name'] for p in client.get('/api/tracks', params=q).json()['pois']] == ['Aid 1']
        assert client.post('/api/tracks/kind', json=dict(q, id='zzz', kind='run')).status_code == 404 and client.post('/api/tracks/kind', json=dict(q, id=a['id'], kind='x')).status_code == 400
        r = client.delete('/api/tracks', params=dict(q, id=b['id'])); assert r.json()['runs'] == 1 and r.json()['merged'] is None and client.get('/api/track', params=q).json()['samples'] == 60
        assert client.delete('/api/tracks', params=dict(q, id='zzz')).status_code == 404 and client.get('/api/tracks/line', params=dict(q, id='merged')).status_code == 404

    def test_bad_files_are_refused(self, client, project):
        q = dict(folder=project.folder)
        assert client.post('/api/tracks', params=dict(q, filename='a.txt'), content=b'x' * 300).status_code == 400
        assert client.post('/api/tracks', params=dict(q, filename='a.gpx'), content=b'<gpx>' + b'x' * 300).status_code == 400
        assert client.get('/api/tracks', params=q).json()['tracks'] == []

    def test_the_older_single_upload_still_works_and_counts_as_a_run(self, client, project):
        q = dict(folder=project.folder); assert client.post('/api/track', params=dict(q, filename='t.gpx'), content=self.gpx()).status_code == 200
        t = client.get('/api/tracks', params=q).json(); assert [(x['id'], x['kind']) for x in t['tracks']] == [('main', 'run')]


class TestGapSettings(TestGapClipsApi):
    def test_the_gap_page_settings_are_saved_and_checked(self, client, project):
        from strata360.edit import synthetic as SY
        self.with_gap(project); q = lambda **b: client.post('/api/gaps/settings', json=dict(folder=project.folder, gap='G01', **b))
        assert client.get('/api/gaps', params=dict(folder=project.folder)).json()['gaps'][0]['settings'] == dict(kind=None, mode=None, seconds=None, must=False)
        r = q(kind='flyover', mode='min', seconds=8, must=True); assert r.status_code == 200 and r.json() == dict(kind='flyover', mode='min', seconds=8.0, must=True)
        assert SY.gap_settings(project.folder, 'G01')['kind'] == 'flyover' and client.get('/api/gaps', params=dict(folder=project.folder)).json()['gaps'][0]['settings']['must'] is True
        assert q(seconds=1).status_code == 400 and q(mode='exactly').status_code == 400 and q(kind='3d').status_code == 400
        assert client.post('/api/gaps/settings', json=dict(folder=project.folder, gap='G99', must=True)).status_code == 404
        assert q(kind=None, mode=None, must=False).json() == dict(kind=None, mode=None, seconds=None, must=False) and SY.settings(project.folder) == {}


class TestPhotosApi(TestGapClipsApi):
    def jpeg(self, off, gps=None):
        import datetime as dt, io
        from PIL import Image
        t = dt.datetime.fromtimestamp(self.T0 + off, dt.timezone.utc); ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = t.strftime('%Y:%m:%d %H:%M:%S'); ex.get_ifd(0x8769)[0x9011] = '+00:00'
        if gps: g = ex.get_ifd(0x8825); g[1] = 'N'; g[2] = (int(gps[0]), 0.0, (gps[0] % 1) * 3600); g[3] = 'E'; g[4] = (int(gps[1]), 0.0, (gps[1] % 1) * 3600)
        b = io.BytesIO(); Image.new('RGB', (80, 60), (5, 90, 200)).save(b, 'JPEG', exif=ex); return b.getvalue() + b'\0' * 200

    def test_photos_are_uploaded_placed_in_the_clip_or_gap_and_served_as_jpeg(self, client, project):
        self.with_gap(project); q = dict(folder=project.folder)
        a = client.post('/api/photos', params=dict(q, filename='in_clip.jpg'), content=self.jpeg(60)).json()                            # inside the first clip (0 to 300 s)
        b = client.post('/api/photos', params=dict(q, filename='in_gap.jpg'), content=self.jpeg(2000)).json()                            # between the clips: the gap
        c = client.post('/api/photos', params=dict(q, filename='far.jpg'), content=self.jpeg(2000, gps=(50.5, 5.5))).json()               # its own position is nowhere near the run
        assert a['where'] == dict(kind='clip', id='CAM_20260222190000_0001_D') and a['loc']['source'] == 'run track' and a['flag'] is None and a['track']['elapsed_s'] == 60
        assert b['where'] == dict(kind='gap', id='G01') and c['loc']['source'] == 'photo gps' and 'km apart' in c['flag'] and c['apart_m'] > 20000
        rows = client.get('/api/photos', params=q).json(); assert [p['id'] for p in rows['photos']] == ['p1', 'p2', 'p3'] and rows['tz']
        t = client.get('/api/photos/thumb', params=dict(q, id='p1', w=40)); assert t.status_code == 200 and t.headers['content-type'] == 'image/jpeg' and t.content[:2] == b'\xff\xd8'
        assert client.get('/api/photos/file', params=dict(q, id='p1')).headers['content-type'] == 'image/jpeg' and client.get('/api/photos/file', params=dict(q, id='p1', original=1)).status_code == 200
        assert client.get('/api/photos/thumb', params=dict(q, id='p9')).status_code == 404
        r = client.delete('/api/photos', params=dict(q, id='p2')); assert [p['id'] for p in r.json()['photos']] == ['p1', 'p3'] and client.delete('/api/photos', params=dict(q, id='p2')).status_code == 404

    def test_a_file_that_is_not_a_usable_photo_is_refused_with_its_name(self, client, project):
        q = dict(folder=project.folder, filename='notes.txt'); assert client.post('/api/photos', params=q, content=b'x' * 300).status_code == 400
        r = client.post('/api/photos', params=dict(folder=project.folder, filename='bad.jpg'), content=b'x' * 300); assert r.status_code == 400 and r.json()['detail'].startswith('bad.jpg: ')
        assert client.get('/api/photos', params=dict(folder=project.folder)).json()['photos'] == []


class TestPhotoAnalysisApi(TestPhotosApi):
    def test_the_analysis_is_started_in_the_background_and_its_results_are_in_the_list(self, client, project, fake_popen):
        self.with_gap(project); q = dict(folder=project.folder); client.post('/api/photos', params=dict(q, filename='a.jpg'), content=self.jpeg(60))
        r = client.post('/api/photos/analyse', json=dict(folder=project.folder, stages=['scenes', 'exposure'], photo=['p1'], force=True)); assert r.json() == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'photos-analyse' in cmd and cmd[cmd.index('--stages') + 1] == 'scenes,exposure' and cmd[cmd.index('--photo') + 1] == 'p1' and '--force' in cmd
        assert client.post('/api/photos/analyse', json=dict(folder=project.folder, stages=['audio'])).status_code == 400
        j = client.get('/api/photos', params=q).json(); assert j['job']['running'] is True and j['photos'][0]['analysis']['stages'] == [] and client.post('/api/photos/analyse', json=dict(folder=project.folder)).json()['started'] is False

    def test_results_and_an_overlay_picture_are_served(self, client, project):
        from strata360.analysis import photo_analysis as PA
        self.with_gap(project); q = dict(folder=project.folder); client.post('/api/photos', params=dict(q, filename='a.jpg'), content=self.jpeg(60)); rd = project.race_dir
        assert client.get('/api/photos/thumb', params=dict(q, id='p1', overlay=1)).status_code == 404
        doc = PA.load_doc(rd, 'p1'); doc['scenes'] = dict(ok=True, setting='trail', description='x', tags=['a'], scenery=7.0, clarity=4.0); doc['stages']['scenes'] = dict(version=1, key='k'); PA.save_doc(rd, doc)
        os.makedirs(PA.adir(rd), exist_ok=True); open(os.path.join(PA.adir(rd), 'p1-overlay.jpg'), 'wb').write(b'\xff\xd8jpeg')
        a = client.get('/api/photos', params=q).json()['photos'][0]['analysis']; assert a['scenery'] == 7.0 and a['tags'] == ['a'] and a['stages'] == ['scenes']
        assert client.get('/api/photos/thumb', params=dict(q, id='p1', overlay=1)).content == b'\xff\xd8jpeg'


class TestPhotoMotionApi(TestPhotosApi):
    def test_the_move_is_planned_from_what_was_found_in_the_photo_and_the_choice_is_saved(self, client, project):
        from strata360.analysis import photo_analysis as PA
        self.with_gap(project); q = dict(folder=project.folder); client.post('/api/photos', params=dict(q, filename='a.jpg'), content=self.jpeg(60))
        doc = PA.load_doc(project.race_dir, 'p1'); doc['people'] = dict(w=80, h=60, people=[], faces=[dict(box=[10, 10, 24, 24], score=0.9, pose=[0, 0, 0], emb=0)]); doc['identity'] = dict(me=dict(face=0, sim=0.9, box=[10, 10, 24, 24]), n_people=1, others=0, threshold=0.45); PA.save_doc(project.race_dir, doc)
        pl = client.get('/api/photos/motion', params=dict(q, id='p1', style='push_in', seconds=5)).json()
        assert pl['style'] == 'push_in' and pl['duration_s'] == 5.0 and pl['subjects'][0]['label'] == 'you' and len(pl['windows']) == 2 and all(0 <= v <= 1 for w in pl['windows'] for v in w) and pl['settings'] == dict(style='auto', seconds=None, seed=0)
        saved = client.post('/api/photos/motion', json=dict(q, id='p1', style='reveal', seconds=8, seed=3)); assert saved.status_code == 200 and saved.json()['style'] == 'reveal' and saved.json()['settings'] == dict(style='reveal', seconds=8.0, seed=3)
        assert client.get('/api/photos/motion', params=dict(q, id='p1')).json()['duration_s'] == 8.0
        assert client.post('/api/photos/motion', json=dict(q, id='p1', style='spin')).status_code == 400 and client.post('/api/photos/motion', json=dict(q, id='p1', seconds=100)).status_code == 400 and client.post('/api/photos/motion', json=dict(q, id='p9')).status_code == 404
        assert client.post('/api/photos/motion', json=dict(q, id='p1', style='auto', seconds=None, seed=0)).json()['settings'] == dict(style='auto', seconds=None, seed=0) and client.get('/api/photos/motion', params=dict(q, id='p9')).status_code == 404


class TestPhotoMotionVideo(TestPhotosApi):
    def test_the_video_is_made_once_per_move_and_served(self, client, project, monkeypatch):
        from strata360.edit import photo_motion as PM
        self.with_gap(project); q = dict(folder=project.folder); client.post('/api/photos', params=dict(q, filename='a.jpg'), content=self.jpeg(60)); made = []
        def fake(path, img, pl, size, fps=25.0): made.append((size, pl['style'])); open(path, 'wb').write(b'mp4'); return 1
        monkeypatch.setattr(PM, 'write_video', fake)
        a = client.get('/api/photos/motion/video', params=dict(q, id='p1', style='pull_out', seconds=4, w=640)); assert a.status_code == 200 and a.headers['content-type'] == 'video/mp4' and a.content == b'mp4' and made == [((640, 360), 'pull_out')]
        client.get('/api/photos/motion/video', params=dict(q, id='p1', style='pull_out', seconds=4, w=640)); assert len(made) == 1                                           # kept
        client.get('/api/photos/motion/video', params=dict(q, id='p1', style='push_in', seconds=4, w=640)); assert len(made) == 2 and client.get('/api/photos/motion/video', params=dict(q, id='p9')).status_code == 404
        monkeypatch.setattr(PM, 'write_video', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('ffmpeg failed (1): x'))); r = client.get('/api/photos/motion/video', params=dict(q, id='p1', style='hold', seconds=3)); assert r.status_code == 500 and 'ffmpeg failed' in r.json()['detail']


class TestPhotoUse(TestPhotosApi):
    def test_a_photo_can_be_marked_for_the_film_and_its_clip_goes_when_it_is_removed(self, client, project):
        from strata360.edit import synthetic as SY
        self.with_gap(project); q = dict(folder=project.folder); client.post('/api/photos', params=dict(q, filename='a.jpg'), content=self.jpeg(60))
        assert client.post('/api/photos/settings', json=dict(q, id='p1', must=True)).json() == dict(id='p1', use=True, must=True) and client.get('/api/photos', params=q).json()['photos'][0]['must'] is True
        assert client.post('/api/photos/settings', json=dict(q, id='p9', must=True)).status_code == 404
        SY.upsert(project.folder, SY.make_photo(dict(id='p1', taken_utc=self.T0 + 60, file='x'), 5.0, dict(style='auto', seed=0))); assert [c['id'] for c in SY.load(project.folder)['clips']] == ['P1']
        client.delete('/api/photos', params=dict(q, id='p1')); assert SY.load(project.folder)['clips'] == []
        client.post('/api/photos', params=dict(q, filename='b.jpg'), content=self.jpeg(70)); assert client.post('/api/photos/settings', json=dict(q, id='p2', must=False)).json()['must'] is False


class TestStreetViewApi(TestGapClipsApi):
    def make_docs(self, project):
        from strata360 import streetview as SV
        rd = project.race_dir; roads = dict(schema=1, id='r1', stretches=[dict(id='R1', km0=1.0, km1=1.5, length_m=500, highways=['residential'], names=['Rue A'], line=[[50.0, 5.0], [50.001, 5.0]])], run=[[50.0, 5.0]], total_km=2)
        SV._save(rd, 'roads', roads)
        sec = dict(id='M1', provider='mapillary', stretch='R1', kind='2d', km0=1.0, km1=1.2, length_m=200, frames=2, spacing_m=100, years=[2024], camera=None, size=None, seq='s', angles={'forward': 2}, items=[dict(id='m1', km=1.0, lat=50.0, lon=5.0, a=0, b=0)])
        SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [sec], roads))

    def test_the_page_gets_stretches_sections_status_and_which_keys_are_set(self, client, project, monkeypatch):
        from strata360.edit import llm_remote as LR
        monkeypatch.setattr(LR, 'secret', lambda n: 'x' if n == 'MAPILLARY_TOKEN' else None)
        q = dict(folder=project.folder); j = client.get('/api/streetview', params=q).json()
        assert j['roads'] is None and j['status']['roads']['done'] is False and j['keys'] == dict(mapillary=True, google=False) and j['job'] == dict(running=False, log=[], error='')
        self.make_docs(project); j = client.get('/api/streetview', params=q).json()
        assert j['roads']['stretches'][0]['id'] == 'R1' and [x['id'] for x in j['sections']] == ['M1'] and j['providers'] == dict(mapillary=dict(frames=2, km=0.2), panoramax=None, google=None)
        assert j['status']['mapillary'] == dict(done=True, stale=False, sections=1, frames=2, km=0.2) and j['status']['roads'] == dict(done=True, stretches=1, km=0.5)

    def test_sections_come_with_whether_they_are_plausible_what_they_overlap_and_the_choice_made(self, client, project):
        from strata360 import streetview as SV
        self.make_docs(project); rd = project.race_dir; roads = SV.load(rd, 'roads'); base = SV.load(rd, 'mapillary')['sections'][0]
        good = dict(base, id='M2', seq='s2', km0=1.1, km1=1.3, length_m=200, frames=40, spacing_m=5.0); other = dict(base, id='P1', provider='panoramax', seq='c', km0=1.15, km1=1.25, length_m=100, frames=12, spacing_m=8.0)
        SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [base, good], roads)); SV._save(rd, 'panoramax', SV.provider_doc('panoramax', [other], roads)); q = dict(folder=project.folder)
        by = {x['id']: x for x in client.get('/api/streetview', params=q).json()['sections']}
        assert by['M1']['plausible'] is False and 'only 2 pictures' in by['M1']['why_not'] and by['M2']['plausible'] is True and by['M2']['play_s'] == 2.7 and by['M2']['speed_ms'] == 75.0 and (by['M2']['min_s'], by['M2']['max_s']) == (2.0, 10.0) and (by['M1']['min_s'], by['M1']['max_s']) == (2.0, 0.5)
        assert by['M2']['overlaps'] == ['M1', 'P1'] and by['P1']['overlaps'] == ['M1', 'M2'] and by['M1']['overlaps'] == ['M2', 'P1'] and by['M2']['choice'] is None and by['M2']['key'] == 'mapillary:s2:1.10'
        assert client.post('/api/streetview/choice', json=dict(folder=project.folder, key='mapillary:s2:1.10', choice='must')).json() == dict(key='mapillary:s2:1.10', choice='must')
        assert {x['id']: x['choice'] for x in client.get('/api/streetview', params=q).json()['sections']}['M2'] == 'must'
        assert client.post('/api/streetview/choice', json=dict(folder=project.folder, key='mapillary:s2:1.10', choice='none')).json()['choice'] is None and {x['id']: x['choice'] for x in client.get('/api/streetview', params=q).json()['sections']}['M2'] is None
        assert client.post('/api/streetview/choice', json=dict(folder=project.folder, key='nope', choice='must')).status_code == 404 and client.post('/api/streetview/choice', json=dict(folder=project.folder, key='mapillary:s2:1.10', choice='maybe')).status_code == 400

    def test_the_stages_are_started_in_the_background_one_job_at_a_time(self, client, project, fake_popen):
        r = client.post('/api/streetview/run', json=dict(folder=project.folder, stages=['roads', 'mapillary'], force=True)); assert r.json() == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'streetview' in cmd and cmd[cmd.index('--stages') + 1] == 'roads,mapillary' and '--force' in cmd
        assert client.post('/api/streetview/run', json=dict(folder=project.folder, stages=['bing'])).status_code == 400
        assert client.get('/api/streetview', params=dict(folder=project.folder)).json()['job']['running'] is True
        assert client.post('/api/streetview/run', json=dict(folder=project.folder)).json()['started'] is False

    def test_the_failure_of_a_stage_is_shown(self, client, project):
        from strata360 import streetview as SV
        os.makedirs(SV.adir(project.race_dir), exist_ok=True); open(os.path.join(SV.adir(project.race_dir), 'run.log'), 'w').write('roads: 3 stretches\nstreetview: mapillary: no MAPILLARY_TOKEN in secrets.env\n')
        assert 'no MAPILLARY_TOKEN' in client.get('/api/streetview', params=dict(folder=project.folder)).json()['job']['error']

    def test_pictures_only_for_frames_the_stage_found_and_google_ones_are_not_kept(self, client, project, monkeypatch):
        from strata360 import streetview as SV
        self.make_docs(project); q = dict(folder=project.folder, provider='mapillary', id='m1')
        monkeypatch.setattr(SV, 'image', lambda rd, provider, doc, item_id, w, **k: (_ for _ in ()).throw(KeyError(item_id)) if item_id != 'm1' else b'\xff\xd8jpg')
        r = client.get('/api/streetview/image', params=q); assert r.status_code == 200 and r.content == b'\xff\xd8jpg' and r.headers['content-type'] == 'image/jpeg'
        assert client.get('/api/streetview/image', params=dict(q, id='other')).status_code == 404 and client.get('/api/streetview/image', params=dict(q, provider='bing')).status_code == 400
        assert client.get('/api/streetview/image', params=dict(q, provider='google')).status_code == 200
        monkeypatch.setattr(SV, 'image', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('mapillary answered 500')))
        assert client.get('/api/streetview/image', params=q).status_code == 502


class TestOverlaysAreMadeAgain(TestTracksCollection):
    """Whatever the overlay shows changes (a cut-off, a track): the thumbnails with the overlay are forgotten and made again."""

    def with_overlay_files(self, project):
        p = os.path.join(project.race_dir, 'race.json'); cfg = json.load(open(p)); cfg['library'] = project.folder; json.dump(cfg, open(p, 'w'))               # (a project with a library of footage: the thumbnails are made by a worker)
        d = os.path.join(project.race_dir, 'clips', 'CAM_X'); os.makedirs(d, exist_ok=True); files = [os.path.join(d, 'thumb_overlay.jpg'), os.path.join(d, 'thumb_overlay.json')]
        for f in files: open(f, 'wb').write(b'x')
        return files

    def test_a_cutoff_forgets_the_overlay_thumbnails_and_starts_making_them_again(self, client, project, fake_popen):
        q = dict(folder=project.folder); up = lambda name, data, **kw: client.post('/api/tracks', params=dict(q, filename=name, **kw), content=data)
        up('a.gpx', self.gpx()); up('route.gpx', self.gpx(route=True), kind='route'); files = self.with_overlay_files(project); n = len(fake_popen.instances); files = self.with_overlay_files(project)      # (adding the tracks did it once already)
        r = client.post('/api/tracks/cutoff', json=dict(q, key='finish', text='1h')); assert r.status_code == 200
        assert not any(os.path.exists(f) for f in files)
        cmds = [i.cmd for i in fake_popen.instances[n:]]; assert any('run' in c and 'thumb_overlay' in c for c in cmds), cmds

    def test_adding_changing_and_removing_a_track_do_the_same(self, client, project, fake_popen):
        q = dict(folder=project.folder); up = lambda name, data, **kw: client.post('/api/tracks', params=dict(q, filename=name, **kw), content=data)
        files = self.with_overlay_files(project); a = up('a.gpx', self.gpx()).json(); assert not any(os.path.exists(f) for f in files)
        files = self.with_overlay_files(project); b = up('b.gpx', self.gpx(lat0=50.01, t0=1_770_001_000)).json(); assert not any(os.path.exists(f) for f in files)
        files = self.with_overlay_files(project); client.post('/api/tracks/kind', json=dict(q, id=b['id'], kind='run')); assert not any(os.path.exists(f) for f in files)
        files = self.with_overlay_files(project); client.delete('/api/tracks', params=dict(q, id=b['id'])); assert not any(os.path.exists(f) for f in files)
        assert any('thumb_overlay' in i.cmd for i in fake_popen.instances)

    def test_photo_overlays_are_forgotten_too_and_made_again(self, client, project, fake_popen):
        from strata360 import photos as PH
        from strata360.analysis import photo_analysis as PA
        import io
        from PIL import Image
        ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = '2026:02:22 10:01:30'; ex.get_ifd(0x8769)[0x9011] = '+00:00'; b = io.BytesIO(); Image.new('RGB', (80, 60), (5, 90, 200)).save(b, 'JPEG', exif=ex); PH.add(project.race_dir, 'a.jpg', b.getvalue() + b'\0' * 200, 'UTC')
        os.makedirs(PA.adir(project.race_dir), exist_ok=True); o = os.path.join(PA.adir(project.race_dir), 'p1-overlay.jpg'); open(o, 'wb').write(b'x'); q = dict(folder=project.folder)
        client.post('/api/tracks', params=dict(q, filename='a.gpx'), content=self.gpx()); assert not os.path.exists(o)
        assert any('photos-analyse' in i.cmd and 'thumb_overlay' in i.cmd for i in fake_popen.instances)


class TestStreetViewVideoApi(TestStreetViewApi):
    def key(self, project):
        self.make_docs(project); return 'mapillary:s:1.00'

    def test_the_state_of_a_sections_video_and_making_it_in_the_background(self, client, project, fake_popen):
        key = self.key(project); q = dict(folder=project.folder, key=key)
        s = client.get('/api/streetview/video', params=q).json(); assert s['exists'] is False and s['running'] is False and s['error'] == '' and s['seconds'] >= 2
        assert client.post('/api/streetview/video', json=dict(folder=project.folder, key=key)).json() == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'streetview-video' in cmd and cmd[-1] == key
        assert client.get('/api/streetview/video', params=q).json()['running'] is True
        assert client.post('/api/streetview/video', json=dict(folder=project.folder, key=key)).json()['started'] is False

    def test_a_finished_video_is_served_and_not_made_again_and_a_failure_is_shown(self, client, project, fake_popen):
        from strata360 import streetview as SV
        key = self.key(project); q = dict(folder=project.folder, key=key); rd = project.race_dir
        assert client.get('/api/streetview/video/file', params=q).status_code == 404
        s = next(x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['key'] == key); p = SV.video_path(rd, s); os.makedirs(os.path.dirname(p)); open(p, 'wb').write(b'MP4DATA')
        r = client.get('/api/streetview/video/file', params=q); assert r.status_code == 200 and r.content == b'MP4DATA' and r.headers['content-type'] == 'video/mp4'
        assert client.get('/api/streetview/video', params=q).json()['exists'] is True and client.post('/api/streetview/video', json=dict(folder=project.folder, key=key)).json() == dict(started=False, reason='the video is already made')
        os.remove(p); open(os.path.splitext(p)[0] + '.log', 'w').write('fetching\nstreetview-video: mapillary answered 500\n')
        assert 'answered 500' in client.get('/api/streetview/video', params=q).json()['error']

    def test_unknown_sections_are_refused(self, client, project):
        assert client.get('/api/streetview/video', params=dict(folder=project.folder, key='nope')).status_code == 404
        assert client.post('/api/streetview/video', json=dict(folder=project.folder, key='nope')).status_code == 404

    def test_the_command_makes_the_video_or_says_why_not(self, project, monkeypatch, capsys):
        import argparse
        from strata360 import cli, streetview as SV
        key = self.key(project); made = []; monkeypatch.setattr(SV, 'make_video', lambda rd, s, log=print, pano=False, hires=False: made.append((s['key'], pano)) or '/x.mp4')
        cli.cmd_streetview_video(argparse.Namespace(name=project.folder, key=key)); assert made == [(key, False)] and 'done: /x.mp4' in capsys.readouterr().out
        with pytest.raises(SystemExit, match='no section nope'): cli.cmd_streetview_video(argparse.Namespace(name=project.folder, key='nope'))
        monkeypatch.setattr(SV, 'make_video', lambda rd, s, log=print, pano=False, hires=False: (_ for _ in ()).throw(RuntimeError('boom')))
        with pytest.raises(SystemExit, match='streetview-video: boom'): cli.cmd_streetview_video(argparse.Namespace(name=project.folder, key=key))


class TestStreetViewNearClips(TestStreetViewApi):
    def test_each_section_says_how_far_the_nearest_clips_are_along_the_run(self, client, project):
        import datetime as dt
        from strata360 import streetview as SV
        self.make_docs(project); rd = project.race_dir
        sec = SV.load(rd, 'mapillary')['sections'][0]; sec['items'] = [dict(i, t=1_700_000_000) for i in sec['items']]; SV._save(rd, 'mapillary', SV.provider_doc('mapillary', [sec], SV.load(rd, 'roads')))
        j = client.get('/api/streetview', params=dict(folder=project.folder)).json()['sections'][0]
        assert 'near' in j and (j['near'] is None or set(j['near']) == {'before', 'after', 'overlaps', 'in_gap'})                                  # (None without a race track in this project)


class TestStreetViewNearApi(TestStreetViewApi):
    def test_a_click_is_only_looked_up_in_the_cache_until_a_search_is_asked_for_and_its_pictures_can_then_be_fetched(self, client, project, monkeypatch):
        import time
        from strata360 import streetview as SV
        self.make_docs(project); seen = {}
        def fake(rd, lat, lon, n, tr, clips, gaps, log=None, **kw): seen.update(lat=lat, lon=lon, n=n, kw=kw, clips=clips); log('asking mapillary…'); return dict(lat=lat, lon=lon, n=n, providers=dict(mapillary=dict(items=[dict(id='m1', url=None, compass=10)], radius_m=100.0), panoramax=dict(items=[dict(id='p1', url='https://x/p1.jpg', compass=None)], radius_m=100.0), google=dict(items=[], radius_m=110.0)))
        monkeypatch.setattr(SV, 'near_point', fake); q = dict(folder=project.folder)
        j = client.get('/api/streetview/near', params=dict(q, lat=50.1, lon=5.2)).json(); assert j['cached'] is False and j['result'] is None and seen == {}                       # nothing fetched by a click
        assert client.post('/api/streetview/near', json=dict(q, lat=50.1, lon=5.2, n=99)).json() == dict(started=True)
        for _ in range(100):
            j = client.get('/api/streetview/near', params=dict(q, lat=50.1, lon=5.2)).json()
            if j['cached']: break
            time.sleep(0.05)
        assert j['cached'] and j['result']['providers']['mapillary']['items'][0]['id'] == 'm1' and seen['n'] == 12 and seen['kw'].keys() >= {'token', 'gkey'} and j['job']['log'] == ['asking mapillary…']
        near = client.get('/api/streetview/near', params=dict(q, lat=50.1005, lon=5.2)).json(); assert near['cached'] and near['result']['lat'] == 50.1                    # 55 m away: the same search
        assert client.get('/api/streetview/near', params=dict(q, lat=50.103, lon=5.2)).json()['cached'] is False                                                          # 330 m away: not
        monkeypatch.setattr(SV, 'image_near', lambda rd, provider, item, w, **k: b'\xff\xd8' + provider.encode() + item['id'].encode())
        r = client.get('/api/streetview/near/image', params=dict(q, provider='panoramax', id='p1')); assert r.status_code == 200 and r.content == b'\xff\xd8panoramaxp1' and r.headers['content-type'] == 'image/jpeg'
        assert client.get('/api/streetview/near/image', params=dict(q, provider='mapillary', id='other')).status_code == 404 and client.get('/api/streetview/near/image', params=dict(q, provider='bing', id='m1')).status_code == 404
        monkeypatch.setattr(SV, 'image_near', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('mapillary answered 500'))); assert client.get('/api/streetview/near/image', params=dict(q, provider='mapillary', id='m1')).status_code == 502


class TestStreetViewPromote:
    def test_a_nearby_capture_is_made_a_section_or_refused_with_the_reason(self, client, project, monkeypatch):
        from strata360 import streetview as SV
        body = dict(folder=project.folder, provider='mapillary', id='m1', sequence='s1', lat=50.0, lon=5.0)
        assert client.post('/api/streetview/promote', json=dict(body, provider='bing')).status_code == 400
        assert client.post('/api/streetview/promote', json={k: v for k, v in body.items() if k != 'lat'}).status_code == 400
        monkeypatch.setattr(SV, 'promote', lambda *a, **k: (_ for _ in ()).throw(ValueError('none of its 3 pictures lies within 30 m of the run track')))
        r = client.post('/api/streetview/promote', json=body); assert r.status_code == 400 and 'within 30 m' in r.json()['detail']
        monkeypatch.setattr(SV, 'promote', lambda rd, prov, i, seq, lat, lon, tr, **k: dict(provider=prov, seq=seq, km0=1.0, id='M+1'))
        assert client.post('/api/streetview/promote', json=body).json() == dict(key='mapillary:s1:1.00', id='M+1')

    def test_a_promoted_section_can_be_taken_out(self, client, project, monkeypatch):
        from strata360 import streetview as SV
        monkeypatch.setattr(SV, 'unpromote', lambda rd, key: key == 'k')
        assert client.post('/api/streetview/unpromote', json=dict(folder=project.folder, key='k')).json() == dict(removed=True)
        assert client.post('/api/streetview/unpromote', json=dict(folder=project.folder, key='x')).status_code == 404


class TestStreetViewChosen:
    def test_the_chosen_sections_come_with_when_the_runner_passed_them(self, client, project):
        r = client.get('/api/streetview/chosen', params=dict(folder=project.folder)); assert r.status_code == 200 and isinstance(r.json()['sections'], list)


class TestStreetViewLength(TestStreetViewApi):
    def test_a_length_is_set_refused_outside_what_the_section_plays_and_cleared(self, client, project):
        from strata360 import streetview as SV
        self.make_docs(project); rd = project.race_dir; s = SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})[0]; key = s['key']; q = dict(folder=project.folder, key=key)
        assert client.post('/api/streetview/length', json=dict(q, seconds=9999)).status_code == 400 and client.post('/api/streetview/length', json=dict(folder=project.folder, key='nope', seconds=5)).status_code == 404
        assert client.post('/api/streetview/length', json=dict(q, seconds=None)).json() == dict(key=key, seconds=None)


class TestStreetViewPanoVideo(TestStreetViewVideoApi):
    def test_the_360_video_is_its_own_file_started_only_for_a_360_section(self, client, project, fake_popen):
        from strata360 import streetview as SV
        key = self.key(project); rd = project.race_dir; s = next(x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['key'] == key)
        assert SV.video_path(rd, s, True) != SV.video_path(rd, s) and SV.video_path(rd, s, True).endswith('-360.mp4')
        q = dict(folder=project.folder, key=key, pano='true'); assert client.get('/api/streetview/video', params=q).json()['exists'] is False and client.get('/api/streetview/video/file', params=q).status_code == 404
        r = client.post('/api/streetview/video', json=dict(folder=project.folder, key=key, pano=True))
        if s['kind'] == '360' and s['provider'] != 'google': assert r.json() == dict(started=True) and '--pano' in fake_popen.instances[-1].cmd
        else: assert r.status_code == 400


class TestStreetViewHires(TestStreetViewApi):
    def test_the_higher_resolution_is_a_setting_of_a_google_section_that_changes_its_videos(self, client, project, fake_popen):
        from strata360 import streetview as SV
        self.make_docs(project); rd = project.race_dir; g = dict(SV.load(rd, 'mapillary')['sections'][0], id='G1', provider='google', seq='g', kind='360'); SV._save(rd, 'google', SV.provider_doc('google', [g], SV.load(rd, 'roads'))); key = SV.section_key(g); q = dict(folder=project.folder)
        before = next(x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['key'] == key); assert before['hires'] is False
        assert client.post('/api/streetview/hires', json=dict(q, key=key, hires=True)).json() == dict(key=key, hires=True)
        after = next(x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['key'] == key); assert after['hires'] is True and len({SV.video_path(rd, before, True), SV.video_path(rd, after, True), SV.video_path(rd, after), SV.video_path(rd, before)}) == 4
        assert client.get('/api/streetview/video', params=dict(q, key=key, pano='true')).json()['hires'] is True
        assert client.post('/api/streetview/hires', json=dict(q, key=key, hires=False)).json() == dict(key=key, hires=False)
        m = next(x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['provider'] == 'mapillary'); assert client.post('/api/streetview/hires', json=dict(q, key=m['key'], hires=True)).status_code == 400 and client.post('/api/streetview/hires', json=dict(q, key='nope', hires=True)).status_code == 404

    def test_a_chosen_google_section_in_the_film_is_made_from_the_higher_resolution_pictures_when_ticked(self, project, monkeypatch):
        from strata360.edit import streetview_clip as SC, streetview_cam as CAM
        from strata360 import streetview as SV
        calls = []; monkeypatch.setattr(CAM, 'fetch_google_pano', lambda *a, **k: calls.append(('pano', k.get('grid')))); monkeypatch.setattr(CAM, 'fetch', lambda *a, **k: calls.append(('flat', None))); monkeypatch.setattr(CAM, 'render', lambda *a, **k: calls.append(('render', k.get('grid'))) or {})
        sec = dict(provider='google', id='G1', key='k', seq='g', km0=0.0, hires=True); SC.render(project.folder, sec, 8.0, project.race_dir + '/x/v.mp4', log=lambda m: None); assert calls == [('pano', 'hi'), ('render', 'hi')]
        calls.clear(); SC.render(project.folder, dict(sec, hires=False), 8.0, project.race_dir + '/x/v.mp4', log=lambda m: None); assert calls == [('flat', None), ('render', None)]
