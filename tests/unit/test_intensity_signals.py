"""edit/intensity_signals.py: the footage signals in film time from a plan, motion, sound events and a track, with fakes; and the footage preset of the studio."""
import json, os
import numpy as np
import pytest
from strata360.edit import intensity as I, intensity_signals as IS, music_studio as MS


def seg(i, clip='A', dur=20.0, start=0.0, **kw): return dict(dict(film_start_s=i * dur, dur_s=dur, clip=clip, clip_start_s=start, utc_start='2026-02-21T12:00:00.000Z', energy=0.5), **kw)


def motion(level): return {'series': {'t': [0, 100], 'acc_energy': [level, level]}}
def events(cat, level): return {'windows': [dict(t0=0, t1=100, cats={cat: level})]}


class Track:
    def at(self, t):
        t = np.asarray(t, float); n = np.full(len(t), np.nan)
        return dict(pace_s_km=np.full(len(t), 300.0), slope_pct=np.linspace(-10, 10, len(t)), hr=np.linspace(120, 170, len(t)) if len(t) > 1 else n)


def test_every_source_becomes_a_signal_in_film_time():
    segs = [seg(0, energy=0.2), seg(1, energy=0.9), seg(2, energy=0.4)]
    mot = lambda c: motion({'A': 0.5}[c]); ev = lambda c: events('cheering', 0.8)
    r = IS.signals_from(segs, mot, ev, Track(), step_s=2.0)
    assert r['length_s'] == 60.0 and 'technique' in r['used'] and 'climb' in r['used'] and 'heart' in r['used'] and r['marks'] == [(0.0, 1.0, 0.0), (60.0, 1.0, 0.0)]
    tech = next(s for s in r['signals'] if s['name'] == 'technique'); assert min(tech['t']) < 2 and max(tech['t']) > 58 and tech['weight'] == 1.0


def test_a_flat_signal_is_left_out_and_missing_sources_are_skipped():
    r = IS.signals_from([seg(0), seg(1)], lambda c: motion(0.3), None, None, step_s=2.0); assert r['used'] == []                  # constant energy and constant motion say nothing
    r = IS.signals_from([seg(0, energy=0.1), seg(1, energy=0.9)], None, None, None, step_s=2.0); assert r['used'] == ['technique']


def test_crowd_sound_is_the_loudest_of_its_categories_and_weighs_double():
    r = IS.signals_from([seg(0), seg(1, start=50.0)], None, lambda c: {'windows': [dict(t0=0, t1=30, cats={'cheering': 0.9, 'crowd': 0.2}), dict(t0=30, t1=100, cats={'crowd': 0.1})]}, None, step_s=5.0)
    c = next(s for s in r['signals'] if s['name'] == 'crowd'); assert c['weight'] == 2.0 and max(c['v']) == pytest.approx(0.9) and min(c['v']) == pytest.approx(0.1)


def test_speech_and_voice_over_segments_are_marked_for_ducking():
    r = IS.signals_from([seg(0), seg(1, speech=True), seg(2, role='vo'), seg(3)], None, None, None); assert r['speech'] == [(20.0, 40.0), (40.0, 60.0)]


def test_synthetic_clips_have_no_motion_or_sound_and_a_missing_plan_gives_nothing(tmp_path):
    called = []; IS.signals_from([seg(0, synthetic='map')], lambda c: called.append(c), lambda c: called.append(c), None); assert called == []
    assert IS.signals_from([], None, None, None)['length_s'] == 0.0 and IS.gather(str(tmp_path)) is None


def test_the_curve_follows_a_busy_stretch_of_footage():
    segs = [seg(i, energy=0.2 if i < 3 else 0.9 if i < 5 else 0.2) for i in range(8)]; r = IS.signals_from(segs, None, None, None, step_s=2.0)
    lv = I.curve(80, 2.0, r['signals'], r['marks'], r['speech'])['levels']; assert lv[0] == I.LEVELS[-1] and lv[-1] == I.LEVELS[-1] and lv[40] > lv[20]


def test_gather_reads_a_project(project):
    from strata360.edit import project as PJ
    ed = PJ.load(project.folder); ed['plan'] = dict(segments=[seg(0, clip='C1', energy=0.2), seg(1, clip='C1', energy=0.9)]); PJ.save(project.folder, ed)
    project.add_clip('C1', motion={'series': {'t': [0, 100], 'acc_energy': [0.1, 0.9]}}, audio_events=events('cheering', 0.7)); IS._CACHE.clear()
    r = IS.gather(project.folder); assert r['length_s'] == 40.0 and {'technique', 'motion'} <= set(r['used'])
    assert IS.cached(project.folder) is IS.cached(project.folder)


class TestFootagePreset:
    def grid(self, tmp_path):
        from test_music_studio import write_grid
        write_grid(str(tmp_path)); return str(tmp_path)

    def footage(self):
        segs = [seg(i, energy=0.1 if i < 3 else 0.9) for i in range(6)]; return IS.signals_from(segs, None, None, None, step_s=2.0)

    def test_the_preview_is_driven_by_the_footage_and_says_why(self, tmp_path):
        rd = self.grid(tmp_path); p = MS.preview(rd, 'music/track.mp3', 40.0, 'footage', footage=self.footage())
        assert p['bars'] == 20 and p['levels'][0] == I.LEVELS[-1] and p['why']['signals'][0]['name'] == 'technique' and len(p['why']['signals'][0]['values']) == 20 and len(p['why']['speech']) == 20

    def test_without_footage_it_is_refused(self, tmp_path):
        rd = self.grid(tmp_path)
        with pytest.raises(RuntimeError, match='no film plan'): MS.preview(rd, 'music/track.mp3', 40.0, 'footage')

    def test_the_summary_lists_the_signals_or_nothing(self):
        assert MS.footage_summary(self.footage()) == dict(length_s=120.0, used=['technique']) and MS.footage_summary(None) is None and MS.footage_summary(dict(signals=[])) is None
