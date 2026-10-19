"""edit/hyperlapse.py: speed ramps through quiet running, the IMU frame picker, and the planner's pass (synthetic plans and telemetry only)."""
import numpy as np
import pytest
from hypothesis import given, strategies as st

from strata360.edit import hyperlapse as HL


# ---------------------------------------------------------------------------------------------------------------- the ramp
def test_a_ramp_plays_its_moment_at_real_speed_then_races_and_lands_at_real_speed():
    rp = HL.profile(6.0, 50.0)
    assert rp['dur_s'] == 6.0 and rp['lead_s'] == pytest.approx(2.1) and rp['ramp_s'] == 0.6 and rp['tail_s'] == 0.3
    assert rp['src_dur_s'] == pytest.approx(50.0, abs=2e-3)                                         # lands on the clip second asked for
    assert HL.speed_at(rp, [0.0, 2.0, 6.0]) == pytest.approx([1.0, 1.0, 1.0]) and float(HL.speed_at(rp, 4.0)) == pytest.approx(rp['speed'])
    t = np.linspace(0, 6, 6001); o = HL.offsets(rp, t)
    assert o[0] == 0.0 and np.all(np.diff(o) > 0) and o[-1] == pytest.approx(rp['src_dur_s'])
    assert np.allclose(np.gradient(o, t), HL.speed_at(rp, t), atol=1e-3)                            # the offsets are the integral of the speed
    assert np.allclose(HL.offsets(rp, [-1.0, 0.5]), [-1.0, 0.5])                                    # real speed before it (a dissolve into it) and through the lead
    assert float(HL.offsets(rp, 7.0)) == pytest.approx(rp['src_dur_s'] + 1.0)                       # and after it


def test_the_speed_is_capped_and_a_window_too_short_or_a_stretch_too_small_gets_no_ramp():
    rp = HL.profile(6.0, 500.0); assert rp['speed'] == HL.MAX_SPEED and rp['src_dur_s'] < 500.0
    assert HL.profile(2.0, 60.0) is None                                                            # under MIN_WINDOW_S
    assert HL.profile(6.0, 8.0) is None                                                             # would need less than MIN_SPEED
    assert HL.profile(4.0, 40.0, HL.Settings(lead_min_s=4.0)) is None                                # no room left after the lead


@given(D=st.floats(3.0, 8.0), extra=st.floats(20.0, 400.0))
def test_offsets_are_increasing_and_land_where_the_profile_says(D, extra):
    rp = HL.profile(D, D + extra)
    assert rp is not None and HL.MIN_SPEED <= rp['speed'] <= HL.MAX_SPEED
    t = np.linspace(0, D, 400); o = HL.offsets(rp, t)
    assert np.all(np.diff(o) > 0) and o[-1] == pytest.approx(rp['src_dur_s'], abs=1e-4) and rp['src_dur_s'] <= D + extra + 1e-2


def test_src_time_and_span_of_plain_and_ramp_windows():
    plain = dict(clip_start_s=10.0, dur_s=4.0)
    assert HL.src_span(plain) == (10.0, 14.0) and float(HL.src_time(plain, 1.5)) == 11.5
    rp = HL.profile(4.0, 40.0); g = dict(clip_start_s=10.0, dur_s=4.0, ramp=rp, src_dur_s=rp['src_dur_s'])
    assert HL.src_span(g) == (10.0, 10.0 + rp['src_dur_s']) and float(HL.src_time(g, 4.0)) == pytest.approx(10.0 + rp['src_dur_s'])


# ---------------------------------------------------------------------------------------------------------------- choosing the frames
FPS = 50.0


def running(n, cadence=3.0, fps=FPS, seed=0):
    """Telemetry of a runner: |acc| bouncing at the cadence (peaks at foot strike), the gyro turning gently with a few jolts."""
    t = np.arange(n) / fps; rng = np.random.default_rng(seed)
    acc = np.stack([np.zeros(n), np.zeros(n), 9.8 + 6.0 * np.cos(2 * np.pi * cadence * t) + 0.3 * rng.standard_normal(n)], axis=1)
    ang = np.cumsum(np.full(n, 0.01) + 0.002 * rng.standard_normal(n)); quat = np.stack([np.cos(ang / 2), np.zeros(n), np.zeros(n), np.sin(ang / 2)], axis=1)
    return t, acc, quat


def test_stride_cost_is_lowest_at_the_top_of_the_stride_and_off_without_a_stride():
    t, acc, _ = running(1000); c = HL.stride_cost(acc, FPS); trough = np.cos(2 * np.pi * 3.0 * t) < -0.95
    assert c[trough].mean() < 0.1 and c[np.cos(2 * np.pi * 3.0 * t) > 0.95].mean() > 0.9
    still = np.tile([0.0, 0.0, 9.8], (1000, 1)) + 0.01 * np.random.default_rng(1).standard_normal((1000, 3))
    assert not HL.stride_cost(still, FPS).any()                                                     # noise only: no stride to keep in step
    assert not HL.stride_cost(acc[:20], FPS).any() and not HL.stride_cost(np.zeros(5), FPS).any()   # too short, wrong shape


def test_blur_cost_marks_the_frames_where_the_gyro_jolts():
    n = 200; ang = np.cumsum(np.full(n, 0.01)); ang[100:] += 0.5                                    # a jolt between frames 99 and 100
    q = np.stack([np.cos(ang / 2), np.zeros(n), np.zeros(n), np.sin(ang / 2)], axis=1); c = HL.blur_cost(q)
    assert c[99] == 1.0 and c[50] == pytest.approx(0.25) and len(c) == n
    assert not HL.blur_cost(np.tile([1.0, 0, 0, 0], (5, 1))).any() and not HL.blur_cost(np.zeros((1, 4))).any()


def test_at_real_speed_the_picker_takes_the_ideal_frames():
    f = np.arange(10, 60, dtype=float); assert list(HL.select_frames(f, np.random.default_rng(0).random(100))) == list(range(10, 60))
    assert HL.select_frames([], np.zeros(5)).size == 0


@pytest.mark.parametrize('speed,gain', [(20.0, 0.35), (12.0, 0.75)])
def test_at_speed_the_picker_keeps_the_stride_in_step_and_moves_forwards(speed, gain):
    n = 8000; _, acc, quat = running(n); stride = HL.stride_cost(acc, FPS); f = np.arange(0, 7000, speed)
    k = HL.select_frames(f, HL.blur_cost(quat) + stride); naive = np.round(f).astype(int)
    assert np.all(np.diff(k) >= 1) and np.abs(k - f).max() <= HL.MAX_RADIUS                         # always forwards, never far from the time asked for
    assert stride[k].mean() < gain * stride[naive].mean()                                            # in step with the stride (fully only above one stride a frame: 17 frames at 3 steps a second)
    steps = np.diff(k); assert abs(steps.mean() - speed) < 0.2 and steps.std() < speed / 3            # the speed stays about what was asked


def test_source_times_pick_frames_only_in_a_ramp_window():
    n = 4000; _, acc, quat = running(n); pts = 100.0 + np.arange(n) / FPS                          # (frame timestamps need not start at zero)
    plain = dict(clip_start_s=5.0, dur_s=4.0); t = np.arange(200) / FPS
    assert np.allclose(HL.source_times(plain, t, pts, quat, acc), 5.0 + t)
    rp = HL.profile(4.0, 50.0); g = dict(clip_start_s=5.0, dur_s=4.0, ramp=rp)
    s = HL.source_times(g, t, pts, quat, acc); ideal = HL.src_time(g, t)
    assert np.all(np.diff(s) > 0) and np.abs(s - ideal).max() <= HL.MAX_RADIUS / FPS + 1e-9
    assert np.allclose(s[:50], ideal[:50]) and np.allclose(np.round(s * FPS), s * FPS)              # the lead is untouched; every time is a real frame
    assert np.allclose(HL.source_times(g, t, pts), s, atol=HL.MAX_RADIUS / FPS) and np.allclose(HL.source_times(g, t, pts[:1]), ideal)     # no telemetry: still real frames; no timestamps: the ramp's times
    late = HL.source_times(g, np.array([100.0]), pts); assert late[0] == pytest.approx(float(HL.src_time(g, 100.0)))                       # past the clip: the renderer holds the end frame, as before


# ---------------------------------------------------------------------------------------------------------------- the planner's pass
def clip(cid='A', dur=600.0, speech=(), unusable=()):
    cands = [dict(id=f'{cid}#00', start_s=0.0, end_s=dur, kind='span')] + [dict(id=f'{cid}#s{i}', start_s=a, end_s=b, kind='speech') for i, (a, b) in enumerate(speech)]
    return dict(id=cid, start_utc='2026-02-19T17:00:00Z', duration_s=dur, candidates=cands, unusable=[dict(start_s=a, end_s=b) for a, b in unusable])


def seg(cs, dur=6.0, clip='A', tech='follow_runner', fs=0.0, **kw):
    return dict(id=f'{clip}@{cs:.2f}', clip=clip, clip_start_s=cs, dur_s=dur, film_start_s=fs, technique=tech, options=[dict(tech=tech, score=1.0)], utc_start='2026-02-19T17:00:00.000Z', **kw)


def test_a_window_before_quiet_running_ramps_and_lands_on_the_next_window():
    segs = [seg(10.0), seg(60.0, fs=6.0)]; rep = HL.apply(segs, [clip(dur=70.0)])
    g = segs[0]; assert g['ramp']['lands'] and g['src_dur_s'] == pytest.approx(50.0, abs=2e-3) and g['utc_end'] == '2026-02-19T17:00:50.000Z'
    assert rep == [dict(id='A@10.00', clip='A', film_start_s=0.0, dur_s=6.0, from_s=16.0, to_s=pytest.approx(60.0, abs=2e-3), speed=g['ramp']['speed'], lands=True, technique_was=None)]
    assert 'ramp' not in segs[1]                                                                     # the clip ends 4 s after the last window: nothing to race through


def test_the_last_window_of_a_clip_races_on_through_the_rest_of_it_without_a_landing():
    segs = [seg(10.0), seg(60.0, fs=6.0)]; c = clip(dur=100.0); HL.apply(segs, [c])
    assert segs[1]['ramp']['lands'] is False and segs[1]['src_dur_s'] == pytest.approx(40.0, abs=2e-3)      # 66 s .. 100 s: the end of the clip


def test_a_gap_too_long_for_the_top_speed_is_raced_partly_and_does_not_land():
    segs = [seg(10.0), seg(500.0, fs=6.0)]; HL.apply(segs, [clip()])
    assert segs[0]['ramp']['speed'] == HL.MAX_SPEED and not segs[0]['ramp']['lands'] and segs[0]['src_dur_s'] < 490.0


@pytest.mark.parametrize('kw,why', [
    (dict(speech=[(30.0, 40.0)]), 'someone talks 14 s in: too little quiet before it'),
    (dict(unusable=[(18.0, 25.0)]), 'a long unusable stretch'),
])
def test_talk_and_unusable_footage_end_the_quiet_stretch(kw, why):
    segs = [seg(10.0), seg(60.0, fs=6.0)]; HL.apply(segs, [clip(**kw)]); assert 'ramp' not in segs[0], why


def test_a_brief_unusable_moment_flashes_by_and_a_later_blocker_shortens_the_ramp():
    segs = [seg(10.0), seg(90.0, fs=6.0)]; HL.apply(segs, [clip(unusable=[(30.0, 31.0)], speech=[(70.0, 80.0)])])
    assert segs[0]['ramp']['lands'] is False and segs[0]['src_dur_s'] == pytest.approx(60.0, abs=2e-3)      # races 16 s .. 70 s, stops before the talk


def test_a_skipped_moment_is_never_raced_through():
    segs = [seg(10.0), seg(60.0, fs=6.0)]
    HL.apply(segs, [clip()], bans=['win:A@20@25']); assert 'ramp' not in segs[0]
    HL.apply(segs, [clip()], bans=['A#00']); assert 'ramp' not in segs[0]                            # (a banned stretch by its candidate id)
    HL.apply(segs, [clip()], bans=['win:B@20@25', 'win:bad']); assert 'ramp' in segs[0]              # another clip's, or a key that is not a window


@pytest.mark.parametrize('g', [
    seg(10.0, speech=True), seg(10.0, role='clip'), seg(10.0, locked=True), seg(10.0, dur=2.5), seg(10.0, synthetic='/x.mp4'), seg(10.0, tech='selfie_hold'),
])
def test_windows_that_cannot_ramp_are_left_alone(g):
    segs = [g, seg(60.0, fs=6.0)]; HL.apply(segs, [clip()]); assert 'ramp' not in segs[0]


def test_a_window_switches_to_following_the_heading_when_that_was_one_of_its_options_or_its_length_suits_it():
    class T: family, hero, dmin, dmax = 'follow', False, 3.0, 10.0
    g = seg(10.0, tech='hold_wide'); g['options'] = [dict(tech='hold_wide', score=1.0), dict(tech='follow_runner', score=0.5)]
    segs = [g, seg(60.0, fs=6.0)]; rep = HL.apply(segs, [clip()])
    assert g['technique'] == 'follow_runner' and g['ramp_from'] == 'hold_wide' and rep[0]['technique_was'] == 'hold_wide'
    g = seg(10.0, tech='look_around'); g['options'] = [dict(tech='look_around', score=1.0)]; segs = [g, seg(60.0, fs=6.0)]
    HL.apply(segs, [clip()], lib={'follow_runner': T}); assert g['technique'] == 'follow_runner' and g['family'] == 'follow' and g['hero'] is False
    g = seg(10.0, tech='look_around'); g['options'] = []; segs = [g, seg(60.0, fs=6.0)]; HL.apply(segs, [clip()]); assert 'ramp' not in g          # nothing says it would suit
    g = seg(10.0, tech='hold_wide'); g['options'] = [dict(tech='follow_runner', score=0.5)]; segs = [g, seg(60.0, fs=6.0)]
    HL.apply(segs, [clip()], protect=['A@10.00']); assert 'ramp' not in g and g['technique'] == 'hold_wide'                                    # you chose its technique


def test_footage_shown_elsewhere_in_the_film_is_not_raced_through_and_settings_turn_it_off():
    segs = [seg(10.0), seg(30.0, dur=4.0, tech='selfie_hold', fs=6.0), seg(60.0, fs=10.0)]; HL.apply(segs, [clip()])
    assert 'ramp' not in segs[0] and segs[1].get('ramp') is None and segs[2]['ramp']['lands'] is False          # 16 .. 30 s is too short; window 2 cannot ramp; window 3 runs on to the end
    segs = [seg(10.0), seg(60.0, fs=6.0)]; assert HL.apply(segs, [clip()], st=HL.Settings(enabled=False)) == [] and 'ramp' not in segs[0]
    segs = [seg(10.0, clip='Z'), seg(60.0, fs=6.0, clip='Z')]; assert HL.apply(segs, [clip()]) == []                # a clip the planner does not know


def test_a_ramp_window_is_not_ramped_twice_and_the_summary_reads_in_minutes():
    segs = [seg(10.0), seg(130.0, fs=6.0)]; rep = HL.apply(segs, [clip()]); first = dict(segs[0]['ramp'])
    assert HL.apply(segs[:1], [clip()]) == [] and segs[0]['ramp'] == first
    assert HL.summary([]) is None and HL.summary(rep).startswith('2 speed ramps race through')
    assert HL.summary(rep[:1]) == f"1 speed ramp race through {(rep[0]['to_s'] - rep[0]['from_s']) / 60:.1f} min of running that would have been cut (up to x{rep[0]['speed']:.0f})"


def test_quiet_run_and_blockers():
    assert HL.quiet_run(10.0, 50.0, [(5.0, 8.0), (20.0, 30.0)]) == 20.0 and HL.quiet_run(25.0, 50.0, [(20.0, 30.0)]) == 25.0 and HL.quiet_run(10.0, 50.0, []) == 50.0
    c = clip(speech=[(30.0, 40.0), (38.0, 45.0)], unusable=[(1.0, 2.0), (50.0, 60.0)])
    assert HL.blockers(c, bans=['win:A@70@75']) == [(30.0, 45.0), (50.0, 60.0), (70.0, 75.0)]


# ---------------------------------------------------------------------------------------------------------------- where the ramp is used
def ramp_seg(cs=10.0, dur=4.0, src=40.0, fs=0.0, **kw):
    rp = HL.profile(dur, src); return dict(id=f'A@{cs:.2f}', clip='A', clip_start_s=cs, dur_s=dur, film_start_s=fs, ramp=rp, src_dur_s=rp['src_dur_s'], utc_start='2026-02-19T17:00:10.000Z',
                                         utc_end=HL._iso('2026-02-19T17:00:10.000Z', rp['src_dur_s']), transition=dict(type='cut', dur_s=0.0), **kw)


def test_the_final_source_plays_the_ramp_and_picks_frames_once_for_the_whole_window():
    from strata360.render import final as FN, progress as PG
    n = 4000; _, acc, quat = running(n); ci = dict(pts=np.arange(n) / FPS, T=dict(quat=quat, acc=acc)); g = ramp_seg()
    s = FN.FinalSource('/f', [g], {}, 640, 360, FPS, progress=PG.Null())
    whole = s.source_times(g, 0, 200, ci); parts = np.concatenate([s.source_times(g, 0, 120, ci), s.source_times(g, 120, 200, ci)])
    assert np.array_equal(whole, parts) and whole[-1] == pytest.approx(10.0 + g['src_dur_s'], abs=HL.MAX_RADIUS / FPS)        # the pieces of one window agree, and it lands
    assert np.allclose(s.source_times(g, -10, 0, ci), 10.0 + np.arange(-10, 0) / FPS)                                        # a transition before it: real speed
    assert np.allclose(s.source_times(g, 0, 200), HL.src_time(g, np.arange(200) / FPS))                                      # the preview: the ramp's own times
    plain = dict(g, ramp=None); assert np.allclose(s.source_times(plain, 5, 10), 10.0 + np.arange(5, 10) / FPS)
    far = s.source_times(g, 600, 602, ci); assert np.allclose(far, HL.src_time(g, np.arange(600, 602) / FPS))                # outside what was picked: the ramp's times


def test_the_time_map_follows_the_ramp():
    from strata360.render import timemap as TM
    g = ramp_seg(); h = dict(id='A@50.00', clip='A', clip_start_s=10.0 + g['src_dur_s'], dur_s=4.0, film_start_s=4.0, utc_start=g['utc_end'], transition=dict(type='dissolve', dur_s=1.0))
    tm = TM.build(dict(segments=[g, h]), 50.0); w = tm['windows'][0]
    assert w['source_out_s'] == pytest.approx(10.0 + g['src_dur_s'], abs=1e-3) and w['utc_out'] == g['utc_end'] and w['ramp'] == g['ramp']
    assert TM.utc_at(tm, 25) == '2026-02-19T17:00:10.500Z'                                                                    # the lead: real time
    assert TM.utc_at(tm, 150) == HL._iso(g['utc_start'], float(HL.offsets(g['ramp'], 3.0)))                                   # in the ramp: the race clock races
    t = tm['transitions'][0]; assert t['outgoing']['source_out_s'] == pytest.approx(float(HL.src_time(g, 4.5)), abs=1e-3) and t['incoming']['source_in_s'] == pytest.approx(h['clip_start_s'] - 0.5, abs=1e-3)


def test_the_window_sound_fades_as_the_picture_speeds_up(project, fake_run):
    from strata360.audio import mix
    g = ramp_seg(); h = dict(g, id='B', clip='B', clip_start_s=0.0, film_start_s=4.0, ramp=None, src_dur_s=None)
    mix.build_audio(project.folder, dict(segments=[g, h]), str(project.path('mix.wav')), 8.0)
    chain = next(c for c in fake_run.calls if '-filter_complex' in c); chain = chain[chain.index('-filter_complex') + 1]
    fade = f"afade=t=out:st={g['ramp']['lead_s']:.4f}:d={g['ramp']['ramp_s']:.4f}"
    assert fade in chain[chain.index('[s0]'):].split('[w0]')[0] and chain.count(fade) == 1                                  # the ramp window's own sound only; the next window is untouched


def test_the_planner_ramps_long_quiet_clips_and_the_setting_turns_it_off(tmp_path, monkeypatch):
    import json, os
    from strata360.edit import project as P
    import test_project_edit as TPE
    monkeypatch.setattr(TPE.tempfile, 'mkdtemp', lambda: str(tmp_path))
    f = TPE.make_project((30, 400, 25)); plan = P.propose(f, dict(length_s=60, seed=1))['plan']
    ramps = [g for g in plan['segments'] if g.get('ramp')]
    assert plan['hyperlapse'] and [r['id'] for r in plan['hyperlapse']] == [g['id'] for g in ramps] and all(g['technique'] == 'follow_runner' for g in ramps)
    assert all(g['clip'].endswith('C01') for g in ramps)                                                                    # only the 400 s clip has a long quiet stretch
    assert sum(g['beats'] for g in plan['segments']) == plan['film']['beats']                                                # the film's length and cuts are unchanged
    off = P.propose(f, dict(hyperlapse=False))['plan']; assert off['hyperlapse'] == [] and not any(g.get('ramp') for g in off['segments'])
    assert json.load(open(os.path.join(f, 'strata360', 'project.json')))['edit']['settings']['hyperlapse'] is False


def test_the_preview_from_the_proxy_skips_the_frames_a_ramp_races_past(tmp_path, monkeypatch):
    import io, json
    from strata360.render import final as FN, progress as PG
    n, w, h = 120, 16, 8; frames = b''.join(bytes([k]) * (w * h * 3) for k in range(n))                       # decoded proxy frame k is all value k
    class Dec:
        def __init__(self, cmd, **kw): self.cmd, self.stdout = cmd, io.BytesIO(frames)
        def terminate(self): pass
        def wait(self): pass
    made = []; monkeypatch.setattr(FN.guard, 'popen', lambda cmd, **kw: made.append(Dec(cmd)) or made[-1])
    p = tmp_path / 'proxy.mp4'; p.write_bytes(b''); json.dump(dict(size=[w, h], frames=[dict(source_frame=k) for k in range(n)]), open(tmp_path / 'proxy.json', 'w'))
    monkeypatch.setattr(FN, 'proxy_of', lambda folder, clip: str(p))
    rp = dict(dur_s=0.5, lead_s=0.1, ramp_s=0.1, tail_s=0.05, speed=4.0); rp['src_dur_s'] = round(float(HL.offsets(rp, 0.5)), 4)
    g = dict(id='A@0.00', clip='A', clip_start_s=0.0, dur_s=0.5, ramp=rp, utc_start='2026-02-19T17:00:00Z')
    s = FN.FinalSource(str(tmp_path), [g], {'A@0.00': dict(ref='world', keyframes=[dict(t=0.0, yaw=0.0, pitch=0.0, fov=90.0)])}, 32, 18, 50.0, progress=PG.Null(), source='proxy')
    shown = [int(img[9, 16, 0]) // 257 for img in s.frames(0, 0, 25)]
    assert shown == [int(k) for k in np.round(HL.src_time(g, np.arange(25) / 50.0) * 50)] and shown[-1] > 40                # each film frame shows the proxy frame the ramp asks for
    assert float(made[0].cmd[made[0].cmd.index('-t') + 1]) == pytest.approx(float(HL.src_time(g, 24 / 50.0)) + 1 / 50.0 + 0.2, abs=2e-3)      # it decodes the whole stretch the ramp covers
