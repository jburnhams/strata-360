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

    def test_clips_summarise_each_clip(self, client, make_project):
        p = make_project(config=True)
        p.add_clip(CLIP_ID, source_frames=300, fps=30.0, motion={'summary': {'steady': 0.8}}, candidates={'summary': {'n': 3}})
        open(os.path.join(p.clip_dir(), 'thumb.jpg'), 'wb').write(b'x')
        [c] = client.get('/api/clips', params={'folder': p.folder}).json()['clips']
        assert c == dict(id=CLIP_ID, start_utc='2026-02-21T12:00:07+00:00', duration_s=10.0, has_note=False, thumb='best', thumb_overlay=False, audio_original=False, audio_clean=False, steady=0.8, candidates=3)

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
        assert [x['id'] for x in g] == ['G01'] and 4000 < g[0]['duration_s'] < 4800 and g[0]['clips'] == [] and 6 <= g[0]['default_seconds'] <= 45

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

    def test_a_failed_run_shows_its_real_error_not_the_interpreters_warnings(self, client, project, fake_popen):
        self.plan(project); f = project.folder; client.post('/api/script2/mix', json=dict(folder=f)); fake_popen.instances[-1].returncode = 1
        open(os.path.join(project.race_dir, 'roughmix', 'mix.log'), 'w').write('ValueError: unsupported hash type blake2s\nTraceback (most recent call last):\n  File "x", line 1\nno voice is installed: run voice setup\n')
        s = client.get('/api/script2/mix', params=dict(folder=f)).json(); assert s['building'] is False and s['error'] == 'no voice is installed: run voice setup'
