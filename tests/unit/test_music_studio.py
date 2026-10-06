"""edit/music_studio.py and the Music studio endpoints: the preview of a build with no audio, the presets, the state, and the background build command."""
import json, os
import numpy as np
import pytest
from strata360.edit import music as MU, music_studio as MS, project as PJ

N = 8


def write_grid(rd, rel='music/track.mp3', n=N):
    os.makedirs(os.path.join(rd, 'music'), exist_ok=True); p = os.path.join(rd, rel); open(p, 'wb').write(b'abc'); chords = [0, 0, 1, 1, 0, 0, 2, 2][:n]
    sim = [[1.0 if chords[i] == chords[j] else 0.4 for j in range(n)] for i in range(n)]; db = [2.0 * i for i in range(n + 1)]
    g = dict(version=2, file=rel, sig=MU._sig(p), bpm=120.0, bar_beats=4, beats=[], downbeats=db, key=dict(tonic=9, mode='minor', name='A minor', confidence=0.8), duration_s=2.0 * n, energy=[0.2, 0.2, 0.5, 0.5, 0.8, 0.8, 0.3, 0.3][:n], sim=sim)
    json.dump(g, open(os.path.join(rd, 'music', 'grid.json'), 'w')); return rel


@pytest.fixture
def rd(tmp_path): return str(tmp_path)


@pytest.mark.parametrize('preset', ['flat', 'arc', 'build', 'quiet'])
def test_a_preset_gives_a_level_for_every_bar_in_phrases(preset):
    lv = MS.levels_for(preset, 30); assert len(lv) == 30 and all(0 <= v <= 1 for v in lv) and all(len(set(lv[i:i + 4])) == 1 for i in range(0, 28, 4))


def test_the_arc_is_full_at_both_ends_and_a_build_rises():
    a = MS.levels_for('arc', 40); b = MS.levels_for('build', 40); assert a[0] == a[-1] == max(a) and b[-1] > b[0] and MS.levels_for('quiet', 8).tolist() == [0.15] * 8


def test_manual_levels_are_resampled_to_the_bars():
    assert MS.levels_for('manual', 4, [0.0, 1.0]).tolist() == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0]) and MS.levels_for('manual', 2, [0.3, 0.9]).tolist() == [0.3, 0.9]


def test_the_state_without_a_grid_or_a_build_is_empty(rd):
    p = os.path.join(rd, 'music'); os.makedirs(p); open(os.path.join(p, 'track.mp3'), 'wb').write(b'x'); assert MS.state(rd, 'music/track.mp3') == dict(grid=None, built=None, stems=False)


def test_the_state_reports_the_grid_and_the_built_score(rd):
    rel = write_grid(rd); json.dump(dict(source='built', length_s=40.0), open(os.path.join(rd, 'music', 'built.json'), 'w')); s = MS.state(rd, rel)
    assert s['grid']['bars'] == 8 and s['grid']['bar_s'] == 2.0 and s['grid']['key']['name'] == 'A minor' and s['built']['length_s'] == 40.0


def test_a_replaced_track_has_no_grid(rd):
    rel = write_grid(rd); open(os.path.join(rd, rel), 'wb').write(b'a longer file'); assert MS.state(rd, rel)['grid'] is None


def test_the_preview_has_the_length_a_plan_and_gains_for_every_bar(rd):
    rel = write_grid(rd); p = MS.preview(rd, rel, 40.0, 'arc', windows=[(4, 6)])
    assert p['bars'] == 20 and p['length_s'] == 40.0 and len(p['levels']) == 20 and len(p['plan']['bars']) == 20 and p['plan']['bars'][0] == 0 and p['plan']['bars'][-2:] == [6, 7]
    assert all(len(v) == 20 for v in p['gains'].values()) and p['gains']['vocals'] == [0, 0, 0, 0, 1, 1] + [0] * 14 and np.array(p['sim']).shape == (8, 8)


def test_a_quiet_preview_prefers_quiet_bars(rd):
    rel = write_grid(rd); q = MS.preview(rd, rel, 40.0, 'quiet'); l = MS.preview(rd, rel, 40.0, 'build')
    assert np.mean([q['energy'][b] for b in q['plan']['bars'][1:-2]]) < np.mean([l['energy'][b] for b in l['plan']['bars'][-10:-2]])


def test_a_preview_needs_the_grid(rd):
    os.makedirs(os.path.join(rd, 'music')); open(os.path.join(rd, 'music', 'track.mp3'), 'wb').write(b'x')
    with pytest.raises(RuntimeError, match='analyse'): MS.preview(rd, 'music/track.mp3', 40.0)


def test_film_seconds_become_whole_bars():
    assert MS.windows_to_bars([(3.0, 7.5), (0, 0), (100, 120)], 2.0, 20) == [(1, 4)]


class TestStudioApi:
    @pytest.fixture
    def track(self, project, monkeypatch):
        rel = write_grid(project.race_dir); monkeypatch.setattr(PJ, 'music_record', lambda f, s: dict(file=rel, name='t.mp3')); return rel

    def test_there_is_no_studio_without_a_track(self, client, project):
        assert client.get('/api/music/studio', params=dict(folder=project.folder)).status_code == 404

    def test_the_studio_state_shows_the_grid_and_no_build(self, client, project, track):
        s = client.get('/api/music/studio', params=dict(folder=project.folder)).json(); assert s['grid']['bars'] == 8 and s['built'] is None and s['building'] is False and s['error'] == ''

    def test_the_preview_comes_back_and_bad_input_is_refused(self, client, project, track):
        f = project.folder; r = client.post('/api/music/studio/preview', json=dict(folder=f, length_s=40, preset='arc', windows=[[8, 12]])).json()
        assert r['bars'] == 20 and r['gains']['vocals'][4:6] == [1, 1] and r['windows'] == [[4, 6]]
        assert client.post('/api/music/studio/preview', json=dict(folder=f, length_s=1)).status_code == 400 and client.post('/api/music/studio/preview', json=dict(folder=f, length_s='x')).status_code == 400
        assert client.post('/api/music/studio/preview', json=dict(folder=f, length_s=40, preset='loud')).status_code == 400

    def test_a_preview_before_the_grid_is_a_conflict(self, client, project, monkeypatch):
        os.makedirs(os.path.join(project.race_dir, 'music'), exist_ok=True); monkeypatch.setattr(PJ, 'music_record', lambda f, s: dict(file='music/track.mp3', name='t'))
        r = client.post('/api/music/studio/preview', json=dict(folder=project.folder, length_s=40)); assert r.status_code == 409 and 'analyse' in r.json()['detail']

    def test_analysing_the_track_makes_the_grid(self, client, project, track, monkeypatch):
        from strata360.edit import music_build as MB
        monkeypatch.setattr(MB, 'grid', lambda rd, rel: seen.append(rel) or {}); seen = []
        assert client.post('/api/music/studio/analyse', json=dict(folder=project.folder)).status_code == 200 and seen == [track]
        def bad(rd, rel): raise RuntimeError('could not read the audio')
        monkeypatch.setattr(MB, 'grid', bad); r = client.post('/api/music/studio/analyse', json=dict(folder=project.folder)); assert r.status_code == 400 and 'could not read' in r.json()['detail']

    def test_a_build_runs_the_command_once_with_its_settings_and_a_failure_shows_its_error(self, client, project, track, fake_popen):
        f = project.folder; r = client.post('/api/music/studio/build', json=dict(folder=f, length_s=60, preset='manual', levels=[0.15, 0.9], windows=[[10, 20]])).json(); assert r == dict(started=True)
        cmd = fake_popen.instances[-1].cmd; assert 'music-build' in cmd and cmd[cmd.index('--length-s') + 1] == '60.0' and cmd[cmd.index('--levels') + 1] == '0.15,0.9' and cmd[cmd.index('--vocals') + 1] == '10.0-20.0'
        assert client.post('/api/music/studio/build', json=dict(folder=f, length_s=60)).json()['started'] is False and client.get('/api/music/studio', params=dict(folder=f)).json()['building'] is True
        fake_popen.instances[-1].returncode = 1; open(os.path.join(project.race_dir, 'music', 'build.log'), 'w').write('Traceback (most recent call last):\n  File "x", line 1\nModuleNotFoundError: No module named demucs\n')
        s = client.get('/api/music/studio', params=dict(folder=f)).json(); assert s['building'] is False and s['error'] == 'ModuleNotFoundError: No module named demucs'
        assert client.post('/api/music/studio/build', json=dict(folder=f, length_s='x')).status_code == 400

    def test_the_built_track_is_served_when_there_is_one(self, client, project, track):
        f = project.folder; assert client.get('/api/music/built/audio', params=dict(folder=f)).status_code == 404
        open(os.path.join(project.race_dir, 'music', 'built.flac'), 'wb').write(b'fLaC'); r = client.get('/api/music/built/audio', params=dict(folder=f)); assert r.status_code == 200 and r.content == b'fLaC'
