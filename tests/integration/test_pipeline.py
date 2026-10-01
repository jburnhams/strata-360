"""The scripted pipeline (ingest, audio, exposure) end to end on synthetic OSVs built with ffmpeg (tests/utils/synthetic_osv.py). Needs ffmpeg and ffprobe, no footage, no models.
Transcription and alignment need models, so those are run by hand (README section 0)."""
import json, os, pathlib
import pytest
from conftest import STAGES

CLIP = 'CAM_20260221120007_0019_D'


def load(path): return json.load(open(path))


class TestInit:
    @pytest.fixture
    def race(self, library, cli):
        """An old-layout race `t` (results in $STRATA_RACES/t) over a 1-clip library with junk files."""
        out = cli('init', 't', '--library', library(1), '--languages', 'en,fr', '--clock-offset-hours', '0').stdout
        return pathlib.Path(os.environ['STRATA_RACES']) / 't', out

    def test_reports_the_clips_and_the_files_it_ignored(self, race):
        _, out = race
        assert '1 clips' in out and 'notes.txt' in out and '.hidden' not in out

    def test_writes_the_configuration(self, race):
        rd, _ = race; cfg = load(rd / 'race.json')
        assert cfg['languages'] == ['en', 'fr'] and cfg['camera_clock']['utc_offset_hours'] == 0.0

    def test_refuses_to_overwrite_an_existing_race_without_force(self, race, cli, library):
        r = cli('init', 't', '--library', library(1, name='other'), check=False)
        assert r.code != 0


class TestProcessedFacts:
    """What the model-free stages recorded for each of the two clips (the `processed` project is built once per session)."""

    def test_clip_facts_come_from_the_header_and_the_streams(self, processed):
        clip = load(f'{processed}/strata360/clips/{CLIP}/clip.json')
        assert clip['time']['start_utc'] == '2026-02-21T12:00:07Z' and clip['time']['utc_status'] == 'provisional', clip['time']
        assert clip['video']['streams'] == 2 and clip['video']['nominal_fps'] == 50.0
        assert clip['camera']['model'] == 'Osmo 360' and clip['colour_mode'] == 'normal' and clip['calibration_slots'] == 16
        assert clip['audio']['channels'] == 2 and abs(clip['duration_s'] - 1.2) < 0.05

    def test_dropped_frames_are_found_with_where_they_were_dropped(self, processed):
        v = load(f'{processed}/strata360/clips/{CLIP}/clip.json')['video']
        assert v['dropped_frames'] == 2 and v['gaps'][0]['after_frame'] == 29

    def test_the_second_clip_has_its_own_start_time(self, processed):
        clip = load(f'{processed}/strata360/clips/CAM_20260221120107_0020_D/clip.json')
        assert clip['time']['start_utc'] == '2026-02-21T12:01:07Z'

    def test_audio_and_exposure_are_tied_to_the_clip_by_its_time_hash(self, processed):
        d = f'{processed}/strata360/clips/{CLIP}'; clip = load(f'{d}/clip.json'); h = clip['time']['utc_hash']
        au, ex = load(f'{d}/audio.json'), load(f'{d}/exposure.json')
        assert au['summary']['integrated_lufs'] < 0 and au['utc_hash'] == h
        assert ex['clip_id'] == CLIP and ex['sampling']['n_samples'] > 0 and ex['utc_hash'] == h

    def test_a_header_out_of_step_with_the_clip_is_detected(self, processed):
        from strata360.pipeline.ingest import check_header
        d = f'{processed}/strata360/clips/{CLIP}'; clip, au = load(f'{d}/clip.json'), load(f'{d}/audio.json')
        check_header(clip, au)
        with pytest.raises(ValueError): check_header(clip, dict(au, utc_hash='000000000000'))


class TestRerunning:
    def test_unchanged_work_is_not_redone(self, processed, cli):
        assert 'nothing left to do' in cli('run', processed, '--stages', STAGES).stdout

    def test_a_changed_clock_redoes_ingest_and_everything_after_it(self, processed, cli):
        p = pathlib.Path(processed, 'strata360', 'race.json'); cfg = load(p); cfg['camera_clock'] = dict(utc_offset_hours=1.0, verified=True); json.dump(cfg, open(p, 'w'))
        out = cli('run', processed, '--stages', STAGES).stdout
        d = f'{processed}/strata360/clips/{CLIP}'; clip = load(f'{d}/clip.json')
        assert clip['time']['start_utc'] == '2026-02-21T11:00:07Z' and clip['time']['utc_status'] == 'definitive', clip['time']
        assert 'ingest: ok' in out and load(f'{d}/audio.json')['utc_hash'] == clip['time']['utc_hash']

    def test_force_redoes_every_stage_of_every_clip(self, processed, cli):
        assert "'ok': 6" in cli('run', processed, '--stages', STAGES, '--force').stdout

    def test_clear_forgets_a_stage_and_what_depends_on_it(self, processed, cli):
        out = cli('clear', processed, 'ingest', '--clip', CLIP).stdout
        assert 'cleared' in out and 'ingest' in out and 'nothing had a status' not in out
        assert 'ingest: ok' in cli('run', processed, '--stages', STAGES).stdout


class TestReports:
    def test_status_lists_each_clip_without_failures(self, processed, cli):
        st = cli('status', processed).stdout
        assert CLIP in st and 'FAIL' not in st and 'stale' not in st, st

    def test_report_summarises_the_race(self, processed, cli):
        rep = cli('report', processed).stdout
        assert '2 clips' in rep and 'colour modes' in rep, rep

    def test_show_prints_one_clip_and_its_stage_states(self, processed, cli):
        out = cli('show', processed, CLIP).stdout
        assert '"clip_id"' in out and 'stages:' in out and "'ingest': 'ok'" in out

    def test_show_of_an_unknown_clip_exits_with_a_message(self, processed, cli):
        r = cli('show', processed, 'CAM_nope', check=False)
        assert r.code != 0 and 'no such clip' in r.out


def test_the_entry_point_runs_as_a_module(cli_subprocess):
    assert 'usage: strata360' in cli_subprocess('--help').stdout
