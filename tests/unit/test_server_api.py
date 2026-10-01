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
