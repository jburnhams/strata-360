"""The point camera endpoints: make one by clicking near a clip's path, change it, watch its preview video being made, take it away."""
import os

import numpy as np
import pytest

from strata360.edit import pointcam as PC, pointcam_clip as PCL

T0 = 1_771_700_000.0
M = 1 / 111_195.0


def put_track(project, n=300):
    """A run due north at 3 m/s for 50 minutes (one fix every 10 s), as the track cache the server reads."""
    t = T0 + 10.0 * np.arange(n); d = 3.0 * 10.0 * np.arange(n); nan = np.full(n, np.nan); p = os.path.join(project.race_dir, 'track.gpx'); os.makedirs(project.race_dir, exist_ok=True); open(p, 'w').write('<gpx/>')
    np.savez_compressed(p + '.npz', t=t, lat=50.0 + d * M, lon=np.full(n, 5.0), alt=100 + np.arange(n) * 0.2, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)


@pytest.fixture
def proj(project):
    put_track(project); project.add_clip('c1', start_utc='2026-02-22T00:00:00+00:00', source_frames=3000, fps=30.0)         # (start fixed below to the track)
    from strata360.edit import pointcam_clip as PCL
    import datetime as dt
    iso = dt.datetime.fromtimestamp(T0 + 600, dt.timezone.utc).isoformat(); project.add_clip('c1', start_utc=iso, source_frames=3000, fps=30.0); return project                 # 100 s of it from 10 minutes in


def click(along, east=30.0): return dict(lat=50.0 + along * M, lon=5.0 + east * M / np.cos(np.radians(50.0)))


class TestPointCamApi:
    def make(self, client, project, **kw):
        return client.post('/api/pointcams', json=dict(folder=project.folder, source=dict(kind='clip', clip='c1'), **(click(1900.0) | kw)))

    def test_a_click_near_the_path_makes_a_camera_with_its_shot_and_facts(self, client, proj):
        r = self.make(client, proj); assert r.status_code == 200, r.text; c = r.json()
        assert c['id'] == 'C1' and c['use'] == '' and c['source'] == dict(kind='clip', clip='c1') and c['t_pass'] == pytest.approx(T0 + 633.0, abs=1.0) and c['ok'] and c['seconds'] == pytest.approx(26.7, abs=1.0) and c['range'] == [2.0, c['source_seconds']]
        assert c['facts']['min_dist_m'] == pytest.approx(30.0, abs=2.0) and c['geometry']['sights'] and c['window'][0] < c['t_pass'] < c['window'][1]
        listing = client.get('/api/pointcams', params=dict(folder=proj.folder)).json(); assert [x['id'] for x in listing['cams']] == ['C1'] and listing['limits']['fov_near'] == [30.0, 130.0] and listing['defaults']['before_m'] == 40.0
        assert client.get('/api/pointcams', params=dict(folder=proj.folder, clip='c2')).json()['cams'] == [] and len(client.get('/api/pointcams', params=dict(folder=proj.folder, clip='c1')).json()['cams']) == 1

    def test_a_click_far_from_the_path_or_a_bad_request_is_refused(self, client, proj):
        r = self.make(client, proj, lon=5.01); assert r.status_code == 400 and 'from the path' in r.json()['detail']
        assert client.post('/api/pointcams', json=dict(folder=proj.folder, source=dict(kind='map'), **click(1900.0))).status_code == 400
        assert client.post('/api/pointcams', json=dict(folder=proj.folder, source=dict(kind='clip', clip='nope'), **click(1900.0))).status_code == 400
        assert client.post('/api/pointcams', json=dict(folder=proj.folder, source=dict(kind='clip', clip='c1'))).status_code == 400 and client.get('/api/pointcams', params=dict(folder=proj.folder)).json()['cams'] == []

    def test_the_settings_change_the_shot(self, client, proj):
        self.make(client, proj); u = lambda **kw: client.post('/api/pointcams/update', json=dict(folder=proj.folder, id='C1', **kw))
        a = u(before_m=20, after_m=20, fov_far=40, use='must', name='the mill').json(); assert a['use'] == 'must' and a['name'] == 'the mill' and a['seconds'] == pytest.approx(13.3, abs=1.0) and a['facts']['fov_min'] > 80.0                                   # (the point is never twice as far as at the closest in a window of 20 m each side: the zoom barely moves)
        assert u(before_m=100, after_m=100).json()['facts']['fov_min'] == pytest.approx(40.0, abs=1.0)
        assert u(use='maybe').status_code == 400 and u(colour='red').status_code == 400 and client.post('/api/pointcams/update', json=dict(folder=proj.folder, id='C9', use='')).status_code == 404
        assert u(before_m=9999).json()['before_m'] == PC.LIMITS['before_m'][1]                                                  # held to its limit

    def test_a_camera_whose_clip_is_gone_says_why_instead_of_failing(self, client, proj):
        self.make(client, proj); os.remove(proj.path('clips', 'c1', 'clip.json')); c = client.get('/api/pointcams', params=dict(folder=proj.folder)).json()['cams'][0]
        assert c['ok'] is False and 'no clip c1' in c['error'] and c['id'] == 'C1'

    def test_the_preview_video_is_made_in_the_background_once(self, client, proj, fake_popen):
        self.make(client, proj); q = dict(folder=proj.folder, id='C1'); s = client.get('/api/pointcams/video', params=q).json(); assert s['exists'] is False and s['running'] is False and s['progress'] is None
        assert client.post('/api/pointcams/video', json=q).json() == dict(started=True); cmd = fake_popen.instances[-1].cmd; assert 'pointcam-video' in cmd and cmd[-1] == 'C1' and cmd[-2] == proj.folder
        assert client.get('/api/pointcams/video', params=q).json()['running'] is True and client.post('/api/pointcams/video', json=q).json()['started'] is False
        cam = PC.get(proj.race_dir, 'C1'); out = PCL.preview_path(proj.folder, cam); open(os.path.splitext(out)[0] + '.log', 'w').write('rendering 30 of 60 frames\n')
        assert client.get('/api/pointcams/video', params=q).json()['progress']['pct'] == pytest.approx(50.0, abs=1.0)
        open(out, 'wb').write(b'\x00\x00\x00\x18ftypmp42'); fake_popen.instances[-1].returncode = 0; s = client.get('/api/pointcams/video', params=q).json(); assert s['exists'] and not s['running']
        assert client.post('/api/pointcams/video', json=q).json() == dict(started=False, reason='the video is already made')
        r = client.get('/api/pointcams/video/file', params=q); assert r.status_code == 200 and r.headers['content-type'] == 'video/mp4' and client.get('/api/pointcams/video/file', params=dict(q, id='C7')).status_code == 404

    def test_a_failed_preview_says_why(self, client, proj, fake_popen):
        self.make(client, proj); q = dict(folder=proj.folder, id='C1'); out = PCL.preview_path(proj.folder, PC.get(proj.race_dir, 'C1')); os.makedirs(os.path.dirname(out), exist_ok=True)
        open(os.path.splitext(out)[0] + '.log', 'w').write('pointcam-video: clip c1 has no proxy yet\n'); s = client.get('/api/pointcams/video', params=q).json(); assert s['running'] is False and 'no proxy' in s['error']
        assert client.get('/api/pointcams/video/file', params=q).status_code == 404 and client.get('/api/pointcams/thumb', params=q).status_code == 404

    def test_the_thumbnail_is_a_frame_of_the_video(self, client, proj, monkeypatch, tmp_path):
        self.make(client, proj); out = PCL.preview_path(proj.folder, PC.get(proj.race_dir, 'C1')); os.makedirs(os.path.dirname(out), exist_ok=True); open(out, 'wb').write(b'v'); jpg = tmp_path / 'f.jpg'; jpg.write_bytes(b'\xff\xd8jpg')
        import strata360.server.app as A
        monkeypatch.setattr(A.subprocess, 'run', lambda cmd, **kw: (open(cmd[-1], 'wb').write(b'\xff\xd8jpg'), type('R', (), dict(returncode=0))())[1])
        r = client.get('/api/pointcams/thumb', params=dict(folder=proj.folder, id='C1', w=120)); assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg' and r.content == b'\xff\xd8jpg'

    def test_a_camera_can_be_taken_away(self, client, proj):
        self.make(client, proj); assert client.post('/api/pointcams/delete', json=dict(folder=proj.folder, id='C1')).json() == dict(removed=True) and client.post('/api/pointcams/delete', json=dict(folder=proj.folder, id='C1')).json() == dict(removed=False)
        assert client.get('/api/pointcams', params=dict(folder=proj.folder)).json()['cams'] == []
