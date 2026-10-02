"""The HTTP API over a real processed project (2 synthetic clips through ingest, audio and exposure): what the web app reads, with real files instead of hand-written JSON."""
import json, os
import pytest

CLIP, CLIP2 = 'CAM_20260221120007_0019_D', 'CAM_20260221120107_0020_D'


def get(served, path, **params):
    client, folder = served
    return client.get(path, params=dict(folder=folder, **params))


class TestProgress:
    def test_a_project_with_work_left_is_processing(self, served):
        p = get(served, '/api/progress').json()
        assert p['state'] == 'processing' and p['clips'] == 2 and p['job_running'] is False and p['max_workers'] >= 1

    def test_each_stage_reports_how_many_clips_are_done(self, served):
        stages = {s['name']: (s['done'], s['total']) for s in get(served, '/api/progress').json()['stages']}
        assert stages['ingest'] == (2, 2) and stages['audio'] == (2, 2) and stages['exposure'] == (2, 2) and stages['transcribe'] == (0, 2)

    def test_it_says_what_is_waiting_for_the_user(self, served):
        assert {'race_track', 'wearer_profile', 'camera_clock'} <= set(get(served, '/api/progress').json()['needs'])

    def test_the_api_and_the_cli_agree(self, served, cli):
        api = get(served, '/api/progress').json(); cli_p = json.loads(cli('progress', served[1], '--json').stdout)
        assert api['stages'] == cli_p['stages'] and api['percent'] == cli_p['percent'] and api['needs'] == cli_p['needs']

    def test_a_folder_that_is_not_a_project_yet_is_new(self, make_client, tmp_path):
        os.makedirs(tmp_path / 'empty')
        p = make_client(roots=[tmp_path]).get('/api/progress', params={'folder': str(tmp_path / 'empty')}).json()
        assert p['state'] == 'new'

    def test_a_folder_outside_the_roots_is_forbidden(self, served): assert served[0].get('/api/progress', params={'folder': '/etc'}).status_code == 403


class TestClips:
    def test_lists_both_clips_with_their_real_length(self, served):
        clips = get(served, '/api/clips').json()['clips']
        assert [c['id'] for c in clips] == [CLIP, CLIP2] and [c['start_utc'] for c in clips] == ['2026-02-21T12:00:07Z', '2026-02-21T12:01:07Z']
        assert all(c['duration_s'] == pytest.approx(1.2, abs=0.05) and c['thumb'] is None and not c['has_note'] for c in clips)

    def test_the_clip_detail_carries_what_the_stages_found(self, served):
        c = get(served, '/api/clip', clip=CLIP).json()
        assert c['id'] == CLIP and c['time']['start_utc'] == '2026-02-21T12:00:07Z' and c['video']['dropped_frames'] == 2
        assert c['camera']['model'] == 'Osmo 360' and c['audio']['summary']['integrated_lufs'] < 0 and c['exposure'] and c['transcript'] == []

    def test_stages_that_have_not_run_are_absent(self, served):
        c = get(served, '/api/clip', clip=CLIP).json()
        assert c['motion'] is None and c['scenes'] is None and c['candidates'] is None and c['places'] is None and c['preview'] is False

    def test_an_unknown_clip_is_404(self, served): assert get(served, '/api/clip', clip='CAM_nope').status_code == 404

    def test_a_clip_id_cannot_climb_out_of_the_project(self, served): assert get(served, '/api/clip', clip='../../../etc').status_code == 404


class TestStateAndClear:
    def test_the_matrix_shows_which_clip_has_done_which_stage(self, served):
        m = get(served, '/api/state').json()
        assert m['clips'][CLIP]['ingest'] == 'ok' and m['clips'][CLIP2]['exposure'] == 'ok' and m['clips'][CLIP]['transcribe'] is None
        assert 'candidates' in m['dependents']['scenes']

    def test_clearing_a_stage_makes_it_pending_again(self, served):
        client, folder = served
        r = client.post('/api/clear', json=dict(folder=folder, items=[dict(clip=CLIP, stage='audio')]))
        assert r.status_code == 200 and r.json()['cleared'] >= 1
        assert get(served, '/api/state').json()['clips'][CLIP]['audio'] != 'ok'
        assert {s['name']: s['done'] for s in get(served, '/api/progress').json()['stages']}['audio'] == 1

    def test_clearing_nothing_clears_nothing(self, served):
        client, folder = served; assert client.post('/api/clear', json=dict(folder=folder, items=[])).json() == {'cleared': 0}


class TestLog:
    def test_the_log_shows_the_worker_run(self, served):
        lines = get(served, '/api/log').json()['lines']
        assert any('worker done' in l for l in lines) and any('ingest: ok' in l for l in lines)


class TestNotesOnARealProject:
    def test_a_note_on_a_clip_flags_it_in_the_clip_list(self, served):
        client, folder = served
        assert client.post('/api/notes', json=dict(folder=folder, clip=CLIP, text='the start')).status_code == 200
        assert {c['id']: c['has_note'] for c in get(served, '/api/clips').json()['clips']} == {CLIP: True, CLIP2: False}
        assert get(served, '/api/clip', clip=CLIP).json()['note'] == 'the start'
