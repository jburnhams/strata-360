"""A still of the final film (render/still.py: which frame, which piece, the picture file) and its server endpoints (start, state, file). The renderer is not run: the film's own tests cover it; here the worker is faked."""
import os

import cv2
import numpy as np
import pytest

from strata360.edit import project as PJ
from strata360.render import final as FN, still as ST
from strata360.render.film import pieces


def plan(durs=(2.0, 3.0, 1.0)):
    t = 0.0; segs = []
    for i, d in enumerate(durs): segs.append(dict(id=f'w{i}', clip='C', film_start_s=t, dur_s=d, clip_start_s=0.0)); t += d
    return dict(segments=segs)


class TestFrameFor:
    def test_time_times_rate_rounded(self): assert ST.frame_for(plan(), 1.5, 50.0) == 75

    def test_held_to_the_film(self):
        assert ST.frame_for(plan(), -3.0, 50.0) == 0 and ST.frame_for(plan(), 99.0, 50.0) == 6 * 50 - 1


class TestLocate:
    def segs(self, trans=None):
        s = plan(); 
        if trans: s['segments'][1]['transition'] = dict(type=trans, dur_s=0.5)
        return s['segments']

    def test_a_frame_in_a_plain_stretch_is_found_with_its_place_in_the_piece(self):
        ps = pieces(self.segs(), 10.0); piece, j = ST.locate(ps, 25)                     # 2 s = 20 frames, so frame 25 is 5 frames into the second window
        assert piece['kind'] == 'plain' and piece['k'] == 1 and j == 5

    def test_the_first_and_last_frames(self):
        ps = pieces(self.segs(), 10.0); assert ST.locate(ps, 0)[0]['k'] == 0 and ST.locate(ps, 59)[0]['k'] == 2 and ST.locate(ps, 59)[1] == 9

    def test_a_frame_past_the_end_is_the_last(self):
        ps = pieces(self.segs(), 10.0); assert ST.locate(ps, 10_000) == ST.locate(ps, 59)

    def test_a_frame_inside_a_transition_is_in_the_transition_piece(self):
        ps = pieces(self.segs('dissolve'), 10.0); piece, j = ST.locate(ps, 20)         # the cut is at frame 20: the dissolve covers 10 frames on each side
        assert piece['kind'] == 'dissolve' and 0 <= j < piece['frames']

    def test_every_frame_belongs_to_exactly_one_piece(self):
        ps = pieces(self.segs('dissolve'), 10.0); total = sum(p['frames'] for p in ps)
        seen = [ST.locate(ps, n) for n in range(total)]; assert len({(p['id'], j) for p, j in seen}) == total


class TestPicture:
    def test_sixteen_bit_values_become_eight_bit_in_bgr_order(self):
        rgb = np.zeros((2, 2, 3), np.uint16); rgb[0, 0] = (65535, 32768, 0)
        out = ST.to_png_array(rgb); assert out.dtype == np.uint8 and tuple(out[0, 0]) == (0, 128, 255)

    def test_eight_bit_input_is_only_reordered(self):
        rgb = np.zeros((1, 1, 3), np.uint8); rgb[0, 0] = (10, 20, 30); assert tuple(ST.to_png_array(rgb)[0, 0]) == (30, 20, 10)

    def test_names_carry_the_key_and_the_frame(self): assert ST.still_name('abcdef0123', 42) == 'abcdef0123_f000042.png'


class TestRenderStill:
    def test_an_existing_picture_for_the_same_frame_is_returned_without_rendering(self, project, monkeypatch):
        p = plan(); out = os.path.join(ST.still_dir(project.folder), ST.still_name(FN.final_key(p, [1920, 1080], 50.0, '100M', project.folder), 75)); os.makedirs(os.path.dirname(out)); open(out, 'wb').write(b'png')
        monkeypatch.setattr(FN, 'FinalSource', lambda *a, **k: pytest.fail('rendered again'))
        assert ST.render_still(project.folder, p, {}, 1.5, (1920, 1080), 50.0) == out

    def test_the_frame_asked_for_is_the_one_written(self, project, monkeypatch):
        import strata360.edit.pans as PN, strata360.overlay as OV
        from strata360.render import grade as GR
        monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1')                                                  # (the load guard must not decide a unit test)
        p = plan(); monkeypatch.setattr(PN, 'apply_pans', lambda segs, fr, scorer=None: (segs, None)); monkeypatch.setattr(PN, 'looker', lambda f: None); monkeypatch.setattr(OV, 'for_project', lambda f, size: None); monkeypatch.setattr(GR, 'gains_for', lambda *a: {})
        class Src:
            why = {}
            def __init__(self, *a, **k): pass
            def shot_factor(self, sg): return 1
            def frames(self, k, a0, a1, **kw):
                for i in range(a0, a1): yield np.full((6, 8, 3), (k * 40 + i) * 256, np.uint16)          # the picture tells which window and frame it is
        monkeypatch.setattr(FN, 'FinalSource', Src)
        out = ST.render_still(project.folder, p, {}, 2.6, (8, 6), 10.0)                                      # frame 26: window 1 (frames 20..49), 6 frames in
        got = cv2.imread(out); assert got.shape == (6, 8, 3) and int(got[0, 0, 0]) == 1 * 40 + 6


@pytest.fixture
def with_plan(project):
    PJ.save(project.folder, dict(plan=plan())); return project


def pick(project, name): return os.path.join(ST.still_dir(project.folder), name)


class TestEndpoints:
    def test_starts_one_still_worker_with_the_time_and_size(self, client, with_plan, fake_popen):
        r = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=2.5, size='1920x1080')).json()
        cmd = fake_popen.instances[0].cmd
        assert r['state'] == 'rendering' and r['name'].endswith('_f000125.png') and 'still' in cmd and cmd[cmd.index('--t') + 1] == '2.5' and cmd[cmd.index('--size') + 1] == '1920x1080'

    def test_the_same_still_is_not_started_twice(self, client, with_plan, fake_popen):
        body = dict(folder=with_plan.folder, t=1.0, size='2560x1440'); a = client.post('/api/film/still', json=body).json(); b = client.post('/api/film/still', json=body).json()
        assert a['name'] == b['name'] and len(fake_popen.instances) == 1

    def test_a_different_size_is_a_different_picture(self, client, with_plan, fake_popen):
        a = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, size='1920x1080')).json()['name']; b = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, size='3840x2160')).json()['name']
        assert a != b and len(fake_popen.instances) == 2

    def test_a_finished_picture_is_reported_done_and_served(self, client, with_plan, fake_popen):
        name = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0)).json()['name']
        os.makedirs(ST.still_dir(with_plan.folder), exist_ok=True); cv2.imwrite(pick(with_plan, name), np.zeros((4, 4, 3), np.uint8))
        r = client.get('/api/film/still', params=dict(folder=with_plan.folder, name=name)).json(); assert r['name'] == name and r['state'] == 'done' and r['progress'] is None
        f = client.get('/api/film/still/file', params=dict(folder=with_plan.folder, name=name)); assert f.status_code == 200 and f.headers['content-type'] == 'image/png'

    def test_a_worker_that_ends_without_a_picture_is_an_error(self, client, with_plan, fake_popen):
        name = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0)).json()['name']; fake_popen.instances[0].returncode = 1
        r = client.get('/api/film/still', params=dict(folder=with_plan.folder, name=name)).json(); assert r['state'] == 'error'

    def test_nothing_is_started_without_a_plan(self, client, project, fake_popen):
        r = client.post('/api/film/still', json=dict(folder=project.folder, t=1.0)); assert r.status_code == 400 and not fake_popen.instances

    @pytest.mark.parametrize('body', [dict(t=1.0, size='100x100'), dict(t='soon'), dict(t=-1.0), dict()])
    def test_bad_requests_are_refused(self, client, with_plan, fake_popen, body):
        assert client.post('/api/film/still', json=dict(folder=with_plan.folder, **body)).status_code == 400 and not fake_popen.instances

    def test_a_name_that_is_not_a_still_is_refused(self, client, with_plan):
        for bad in ('../../race.json', 'x.png', 'a1b2c3d4e5_f1.png'):
            assert client.get('/api/film/still', params=dict(folder=with_plan.folder, name=bad)).status_code == 400
            assert client.get('/api/film/still/file', params=dict(folder=with_plan.folder, name=bad)).status_code == 400

    def test_a_picture_that_is_not_there_is_404(self, client, with_plan):
        assert client.get('/api/film/still/file', params=dict(folder=with_plan.folder, name='a1b2c3d4e5_f000001.png')).status_code == 404

    def test_each_enlarge_mode_is_a_different_picture_and_is_passed_to_the_worker(self, client, with_plan, fake_popen):
        names = [client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, size='3840x2160', upscale=m)).json()['name'] for m in ('off', '1080p', '1440p', 'full')]
        cmds = [w.cmd for w in fake_popen.instances]
        assert len(set(names)) == 4 and '--upscale' not in cmds[0] and [c[c.index('--upscale') + 1] for c in cmds[1:]] == ['1080p', '1440p', 'full']

    def test_true_still_means_the_full_size_mode(self, client, with_plan, fake_popen):
        a = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, upscale=True)).json()['name']; b = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, upscale='full')).json()['name']
        assert a == b and len(fake_popen.instances) == 1

    def test_a_mode_that_does_not_exist_is_refused(self, client, with_plan, fake_popen):
        r = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, upscale='8k')); assert r.status_code == 400 and not fake_popen.instances

    def test_the_final_film_setting_is_the_default_for_stills(self, client, with_plan, fake_popen):
        client.post('/api/final/start', json=dict(folder=with_plan.folder, upscale='1440p')); fake_popen.instances.clear()
        client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0)); cmd = fake_popen.instances[0].cmd; assert cmd[cmd.index('--upscale') + 1] == '1440p'

    def test_what_the_render_reports_is_passed_on_and_its_error_shown(self, client, with_plan, fake_popen):
        from strata360.render import progress as PG
        name = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0)).json()['name']
        pg = PG.Progress(ST.progress_path(pick(with_plan, name)))
        with pg.stage('prepare'): pass
        pg.fail('the model weights are missing'); fake_popen.instances[0].returncode = 1
        r = client.get('/api/film/still', params=dict(folder=with_plan.folder, name=name)).json()
        assert r['state'] == 'error' and r['error'] == 'the model weights are missing' and [x['name'] for x in r['progress']['stages']] == ['prepare']


class TestFinalSettings:
    def test_enlarging_is_off_until_asked_for(self, client, with_plan, fake_popen):
        assert client.get('/api/final', params=dict(folder=with_plan.folder)).json()['settings']['upscale'] == 'off'

    def test_the_mode_is_saved_and_sent_to_the_worker(self, client, with_plan, fake_popen):
        client.post('/api/final/start', json=dict(folder=with_plan.folder, upscale='1080p')); cmd = fake_popen.instances[0].cmd
        assert cmd[cmd.index('--upscale') + 1] == '1080p' and client.get('/api/final', params=dict(folder=with_plan.folder)).json()['settings']['upscale'] == '1080p'

    def test_a_bad_mode_is_a_bad_request_but_a_bad_saved_one_is_just_off(self, client, with_plan, fake_popen):
        assert client.post('/api/final/start', json=dict(folder=with_plan.folder, upscale='8k')).status_code == 400
        with_plan.write_json('final/settings.json', dict(upscale='8k')); assert client.get('/api/final', params=dict(folder=with_plan.folder)).json()['settings']['upscale'] == 'off'

    def test_an_old_saved_true_is_the_full_size_mode(self, client, with_plan):
        with_plan.write_json('final/settings.json', dict(upscale=True)); assert client.get('/api/final', params=dict(folder=with_plan.folder)).json()['settings']['upscale'] == 'full'

    def test_each_mode_has_its_own_film_folder(self, with_plan):
        p = PJ.load(with_plan.folder)['plan']; k = lambda m: FN.final_key(p, [3840, 2160], 50.0, '100M', with_plan.folder, m)
        assert len({k('off'), k('1080p'), k('1440p'), k('full')}) == 4 and k('off') == k(False) == FN.final_key(p, [3840, 2160], 50.0, '100M', with_plan.folder)

    def test_a_mode_that_reaches_the_output_size_is_the_same_film_as_full(self, with_plan):
        p = PJ.load(with_plan.folder)['plan']; k = lambda m: FN.final_key(p, [1920, 1080], 50.0, '100M', with_plan.folder, m)
        assert k('1080p') == k('full') and k('1440p') == k('full')               # at 1080p output the model never works wider than the output


def film(durs, clips=None, fovs=None, synthetic=()):
    """A plan and its camera paths: shots of the given lengths, each with its clip and narrowest field of view."""
    t = 0.0; segs = []; framing = {}
    for i, d in enumerate(durs):
        segs.append(dict(id=f'w{i}', clip=(clips or ['C'] * len(durs))[i], film_start_s=t, dur_s=d, clip_start_s=0.0, **(dict(synthetic='x.mp4') if i in synthetic else {})))
        framing[f'w{i}'] = dict(ref='world', keyframes=[dict(t=0.0, yaw=0.0, fov=float((fovs or [90] * len(durs))[i]))]); t += d
    return dict(segments=segs), framing


class TestMomentCount:
    @pytest.mark.parametrize('minutes, n', [(0.5, 4), (2, 4), (3, 4), (10, 6), (16, 7), (30, 10), (90, 10)])
    def test_four_at_two_minutes_rising_to_ten_at_thirty(self, minutes, n): assert ST.moment_count(minutes * 60) == n

    def test_it_never_falls_as_the_film_gets_longer(self):
        counts = [ST.moment_count(m * 30) for m in range(1, 120)]; assert counts == sorted(counts) and counts[0] == 4 and counts[-1] == 10


class TestPickMoments:
    def test_the_count_follows_the_length_and_the_moments_are_in_order_inside_the_film(self):
        p, fr = film([10.0] * 36)                                                  # 6 minutes
        m = ST.pick_moments(p, fr); assert len(m) == ST.moment_count(360) == 5 and [x['t'] for x in m] == sorted(x['t'] for x in m) and 0 <= m[0]['t'] and m[-1]['t'] < 360

    def test_each_stretch_of_the_film_gets_one_moment(self):
        p, fr = film([10.0] * 36); m = ST.pick_moments(p, fr, 6); assert [int(x['t'] // 60) for x in m] == [0, 1, 2, 3, 4, 5]

    def test_a_given_count_is_used(self):
        p, fr = film([10.0] * 36); assert len(ST.pick_moments(p, fr, 9)) == 9

    def test_it_prefers_shots_that_differ_in_clip_and_tightness(self):
        p, fr = film([10.0] * 8, clips=['A', 'A', 'A', 'A', 'B', 'B', 'B', 'B'], fovs=[90, 90, 50, 90, 90, 90, 90, 70]); m = ST.pick_moments(p, fr, 4)
        assert {x['clip'] for x in m} == {'A', 'B'} and any('tight' in x['label'] for x in m) and len({x['label'] for x in m}) >= 3

    def test_a_generated_clip_is_among_them(self):
        p, fr = film([10.0] * 4, synthetic=(2,)); assert any(x['label'].startswith('generated') for x in ST.pick_moments(p, fr, 4))

    def test_the_moment_is_in_its_shot_and_away_from_its_ends(self):
        p, fr = film([12.0] * 6)
        for x in ST.pick_moments(p, fr, 6):
            g = next(g for g in p['segments'] if g['id'] == x['id']); assert g['film_start_s'] + 1 < x['t'] < g['film_start_s'] + g['dur_s'] - 1

    def test_one_long_shot_still_gives_the_whole_series_inside_it(self):
        p, fr = film([100.0]); m = ST.pick_moments(p, fr, 4); assert len(m) == 4 and len({x['t'] for x in m}) == 4

    def test_a_missing_camera_path_does_not_stop_it(self):
        p, _ = film([10.0] * 4); assert len(ST.pick_moments(p, {}, 4)) == 4

    def test_no_shots_no_moments(self): assert ST.pick_moments(dict(segments=[]), {}) == []


class TestMetadata:
    def test_what_a_still_was_made_from_is_kept_beside_it(self, project, monkeypatch):
        import strata360.edit.pans as PN, strata360.overlay as OV
        from strata360.render import grade as GR
        monkeypatch.setenv('STRATA_NO_RESOURCE_LIMITS', '1'); p, fr = film([4.0, 4.0], fovs=[50, 90])
        monkeypatch.setattr(PN, 'apply_pans', lambda segs, f, scorer=None: (segs, None)); monkeypatch.setattr(PN, 'looker', lambda f: None); monkeypatch.setattr(OV, 'for_project', lambda f, size: None); monkeypatch.setattr(GR, 'gains_for', lambda *a: {})
        import strata360.edit.upscale as UP; monkeypatch.setattr(UP, 'load', lambda *a: None)
        class Src:
            why = {'w0': ''}
            def __init__(self, *a, **k): pass
            def shot_factor(self, sg): return 2
            def frames(self, k, a0, a1, **kw):
                for i in range(a0, a1): yield np.zeros((6, 8, 3), np.uint16)
        monkeypatch.setattr(FN, 'FinalSource', Src); out = ST.render_still(project.folder, p, fr, 1.0, (8, 6), 10.0, upscale='1080p')
        m = ST.read_meta(out); assert (m['name'], m['t'], m['frame'], m['size'], m['upscale'], m['model'], m['piece']) == (os.path.basename(out), 1.0, 10, [8, 6], '1080p', UP.MODEL, 'plain')
        assert m['shots'] == [dict(id='w0', clip='C', fov=50.0, factor=2, note='')] and m['rendered'].endswith('Z') and m['seconds'] >= 0 and 'render' in m['stages'] and m['key'] in out

    def test_a_still_without_metadata_reads_as_none(self, tmp_path): assert ST.read_meta(str(tmp_path / 'x.png')) is None


class TestBatch:
    def test_auto_picks_the_moments_and_starts_one_worker_for_all_of_them(self, client, with_plan, fake_popen, monkeypatch):
        import strata360.edit.framing as FR; monkeypatch.setattr(FR, 'resolve', lambda f, plan, head=True: {})
        r = client.post('/api/film/still', json=dict(folder=with_plan.folder, auto=True, size='1920x1080')).json(); ms = r['moments']; cmd = fake_popen.instances[0].cmd
        assert len(ms) == 4 and len(fake_popen.instances) == 1 and cmd.count('--t') == 4 and [m['state'] for m in ms] == ['rendering', 'queued', 'queued', 'queued'] and all(m['label'] and m['why'] for m in ms)

    def test_several_given_times_are_one_worker(self, client, with_plan, fake_popen):
        r = client.post('/api/film/still', json=dict(folder=with_plan.folder, times=[0.5, 2.5, 4.0], size='1920x1080')).json(); assert len(r['moments']) == 3 and fake_popen.instances[0].cmd.count('--t') == 3

    def test_a_still_that_already_exists_is_not_asked_for_again(self, client, with_plan, fake_popen):
        a = client.post('/api/film/still', json=dict(folder=with_plan.folder, times=[1.0], size='1920x1080')).json()['moments'][0]['name']
        os.makedirs(ST.still_dir(with_plan.folder), exist_ok=True); cv2.imwrite(pick(with_plan, a), np.zeros((4, 4, 3), np.uint8)); fake_popen.instances.clear()
        r = client.post('/api/film/still', json=dict(folder=with_plan.folder, times=[1.0, 3.0], size='1920x1080')).json()['moments']
        assert [m['state'] for m in r] == ['done', 'rendering'] and fake_popen.instances[0].cmd.count('--t') == 1

    @pytest.mark.parametrize('body', [dict(times=[]), dict(times=['a']), dict(times=list(range(25))), dict(times=[-1.0])])
    def test_bad_lists_are_refused(self, client, with_plan, fake_popen, body):
        assert client.post('/api/film/still', json=dict(folder=with_plan.folder, **body)).status_code == 400 and not fake_popen.instances

    def test_auto_needs_a_plan(self, client, project, fake_popen):
        assert client.post('/api/film/still', json=dict(folder=project.folder, auto=True)).status_code == 400

    def test_the_command_line_takes_several_times(self, monkeypatch, tmp_path):
        calls = []; monkeypatch.setattr(ST, 'render_still', lambda folder, plan, fr, t, size, fps, out, upscale='off': calls.append((t, out)) or f'p{t}.png')
        import strata360.edit.framing as FR; monkeypatch.setattr(FR, 'resolve', lambda *a, **k: {}); monkeypatch.setattr(PJ, 'load', lambda f: dict(plan=plan())); monkeypatch.setattr(FN, 'resolve_fps', lambda *a: 50.0)
        import sys; monkeypatch.setattr(sys, 'argv', ['still', str(tmp_path), '--t', '1', '--t', '2.5', '--size', '1920x1080', '--out', 'ignored.png']); ST.main()
        assert calls == [(1.0, None), (2.5, None)]                       # (one --out cannot hold several pictures)

    def test_a_failure_does_not_stop_the_next_one_but_ends_with_an_error(self, monkeypatch, tmp_path):
        done = []
        def fake(folder, plan, fr, t, size, fps, out, upscale='off'):
            if t == 1.0: raise RuntimeError('boom')
            done.append(t); return 'ok.png'
        monkeypatch.setattr(ST, 'render_still', fake); import strata360.edit.framing as FR; monkeypatch.setattr(FR, 'resolve', lambda *a, **k: {}); monkeypatch.setattr(PJ, 'load', lambda f: dict(plan=plan())); monkeypatch.setattr(FN, 'resolve_fps', lambda *a: 50.0)
        import sys; monkeypatch.setattr(sys, 'argv', ['still', str(tmp_path), '--t', '1', '--t', '2', '--size', '1920x1080'])
        with pytest.raises(SystemExit) as e: ST.main()
        assert done == [2.0] and e.value.code == 1


class TestGalleryEndpoints:
    def make(self, project, name, **meta):
        d = ST.still_dir(project.folder); os.makedirs(d, exist_ok=True); path = os.path.join(d, name); cv2.imwrite(path, np.full((90, 160, 3), 128, np.uint8))
        if meta: ST.write_meta(path, dict(name=name, **meta))
        return path

    def test_it_lists_every_still_with_its_metadata_and_whether_it_is_of_the_current_plan(self, client, with_plan):
        p = PJ.load(with_plan.folder)['plan']; key = FN.final_key(p, [1920, 1080], 50.0, '100M', with_plan.folder)
        self.make(with_plan, f'{key}_f000100.png', key=key, t=2.0, frame=100, size=[1920, 1080], upscale='off'); self.make(with_plan, 'aaaaaaaaaa_f000007.png', key='aaaaaaaaaa', t=0.1, frame=7, size=[1920, 1080], upscale='off')
        r = client.get('/api/film/stills', params=dict(folder=with_plan.folder)).json(); by = {s['name']: s for s in r['stills']}
        assert len(by) == 2 and by[f'{key}_f000100.png']['current'] is True and by['aaaaaaaaaa_f000007.png']['current'] is False and by[f'{key}_f000100.png']['t'] == 2.0 and r['auto_count'] == 4

    def test_a_still_from_before_the_metadata_was_kept_is_still_listed(self, client, with_plan):
        self.make(with_plan, 'bbbbbbbbbb_f000250.png'); s = client.get('/api/film/stills', params=dict(folder=with_plan.folder)).json()['stills'][0]
        assert s['legacy'] is True and s['frame'] == 250 and s['bytes'] > 0 and s['t'] is None

    def test_other_files_in_the_folder_are_not_stills(self, client, with_plan):
        self.make(with_plan, 'cccccccccc_f000001.png'); open(os.path.join(ST.still_dir(with_plan.folder), 'notes.txt'), 'w').write('x')
        assert len(client.get('/api/film/stills', params=dict(folder=with_plan.folder)).json()['stills']) == 1

    def test_renders_in_progress_are_listed_with_what_was_asked_for(self, client, with_plan, fake_popen):
        client.post('/api/film/still', json=dict(folder=with_plan.folder, times=[1.0, 2.0], size='1920x1080', upscale='1440p'))
        a = client.get('/api/film/stills', params=dict(folder=with_plan.folder)).json()['active']
        assert [x['state'] for x in a] == ['queued', 'queued'] and a[0]['t'] == 1.0 and a[0]['size'] == '1920x1080' and a[0]['upscale'] == '1440p'

    def test_a_finished_still_leaves_the_active_list(self, client, with_plan, fake_popen):
        name = client.post('/api/film/still', json=dict(folder=with_plan.folder, t=1.0, size='1920x1080')).json()['name']; self.make(with_plan, name)
        r = client.get('/api/film/stills', params=dict(folder=with_plan.folder)).json(); assert r['active'] == [] and len(r['stills']) == 1

    def test_the_thumbnail_is_a_small_jpeg_made_once(self, client, with_plan):
        self.make(with_plan, 'dddddddddd_f000002.png'); a = client.get('/api/film/still/thumb', params=dict(folder=with_plan.folder, name='dddddddddd_f000002.png', w=80))
        im = cv2.imdecode(np.frombuffer(a.content, np.uint8), 1); assert a.status_code == 200 and a.headers['content-type'] == 'image/jpeg' and im.shape[:2] == (45, 80)
        assert os.path.exists(os.path.join(ST.still_dir(with_plan.folder), '.thumbs', 'dddddddddd_f000002.png.80.jpg'))

    def test_a_thumbnail_is_never_larger_than_the_picture(self, client, with_plan):
        self.make(with_plan, 'eeeeeeeeee_f000002.png'); a = client.get('/api/film/still/thumb', params=dict(folder=with_plan.folder, name='eeeeeeeeee_f000002.png', w=100000))
        assert cv2.imdecode(np.frombuffer(a.content, np.uint8), 1).shape[1] == 160                  # never more than 1280 (here: the picture is only 160 wide, so it is enlarged to 1280? no: capped)

    def test_a_missing_or_bad_thumbnail_request(self, client, with_plan):
        assert client.get('/api/film/still/thumb', params=dict(folder=with_plan.folder, name='ffffffffff_f000003.png')).status_code == 404
        assert client.get('/api/film/still/thumb', params=dict(folder=with_plan.folder, name='../x.png')).status_code == 400
