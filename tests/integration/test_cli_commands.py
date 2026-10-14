"""The command line over real project files: the commands that need no model (catalog, progress, coverage, backup, credits, open, plan-blocks, gaps, doctor) run in-process on the synthetic clips."""
import csv, json, os
import pytest


class TestCatalog:
    def test_lists_the_clips_and_writes_a_csv_of_them(self, processed, cli):
        r = cli('catalog', processed); rd = os.path.join(processed, 'strata360')
        assert '2 clips; 1 unsupported files' in r.stdout                                        # (the library has a notes.txt the program ignores)
        rows = list(csv.DictReader(open(os.path.join(rd, 'catalog.csv'), newline='')))
        assert len(rows) == 2 and all(row['id'] for row in rows) and len({row['id'] for row in rows}) == 2
        for row in rows: assert row['id'] in r.stdout

    def test_init_refuses_a_library_that_does_not_exist(self, cli, tmp_path):
        r = cli('init', 'nolib', '--library', str(tmp_path / 'missing'), check=False)
        assert r.code != 0 and 'library folder not found' in r.out


class TestProgress:
    def test_json_gives_the_state_each_stage_and_what_it_waits_for(self, processed, cli):
        p = json.loads(cli('progress', processed, '--json').stdout)
        assert p['clips'] == 2 and p['state'] in ('processing', 'needs_input') and p['running'] is False and p['has_gps'] is False
        done = {s['name']: (s['done'], s['total']) for s in p['stages']}
        assert done['ingest'] == (2, 2) and done['audio'] == (2, 2) and done['exposure'] == (2, 2)
        assert 'race_track' in p['needs'] and 'camera_clock' in p['needs'] and 0 < p['percent'] < 100

    def test_text_shows_a_bar_for_each_stage(self, processed, cli):
        out = cli('progress', processed).stdout
        assert 'of stage work done' in out and 'ingest' in out and '  2/2' in out and 'waiting for you:' in out and 'race_track' in out

    def test_a_folder_without_a_project_is_new(self, library, cli):
        folder = library(1)
        assert json.loads(cli('progress', folder, '--json').stdout)['state'] == 'new'
        assert 'no project in' in cli('progress', folder).stdout


class TestOpen:
    def test_a_new_folder_becomes_a_project_without_running(self, library, cli):
        folder = library(2); r = cli('open', folder, '--no-run')
        assert 'new project' in r.stdout and '2 clips' in r.stdout and 'state: processing, 0.0% done' in r.stdout
        assert os.path.exists(os.path.join(folder, 'strata360', 'race.json'))
        again = cli('open', folder, '--no-run').stdout; assert 'new project' not in again and 'state: processing' in again

    def test_languages_are_saved_in_the_new_project(self, library, cli):
        folder = library(1); cli('open', folder, '--no-run', '--languages', 'en,nl')
        assert json.load(open(os.path.join(folder, 'strata360', 'race.json')))['languages'] == ['en', 'nl']

    def test_a_finished_project_says_what_it_waits_for(self, processed, cli):
        out = cli('open', processed, '--no-run').stdout
        assert 'waiting for you:' in out and 'camera_clock' in out

    def test_something_that_is_not_a_folder_is_refused(self, cli, tmp_path):
        r = cli('open', str(tmp_path / 'nothing'), check=False); assert r.code != 0 and 'not a folder' in r.out


class TestCoverage:
    def test_json_counts_the_artefacts_per_stage_and_what_is_missing(self, processed, cli):
        r = json.loads(cli('coverage', processed, '--json').stdout)
        assert r['clips'] == 2 and r['complete'] is False and r['missing'] and set(r['totals']) == set(r['stages'])
        assert all({'clip', 'stage', 'state'} <= set(m) for m in r['missing'])

    def test_text_lists_the_missing_artefacts_and_the_decisions_they_block(self, processed, cli):
        out = cli('coverage', processed).stdout
        assert '2 clips; default-stage artefacts present:' in out and 'missing:' in out and 'decisions blocked:' in out


class TestBackup:
    def test_makes_lists_and_restores_a_backup(self, processed, cli, tmp_path):
        made = cli('backup', processed).stdout; assert made.startswith('saved ') and made.strip().endswith('.tar.gz')
        path = made.split('saved ', 1)[1].strip(); assert os.path.exists(path)
        listing = cli('backup', processed, '--list').stdout; name = os.path.basename(path)
        assert name in listing and 'kB' in listing and 'no changes since the last backup' in listing
        assert 'nothing changed since the last backup' in cli('backup', processed).stdout
        dest = str(tmp_path / 'restored'); out = cli('backup', processed, '--restore', name, '--to', dest).stdout
        n = int(out.split(' files restored')[0]); assert n > 0 and f'restored to {dest}' in out
        assert sum(len(fs) for _, _, fs in os.walk(dest)) == n and any(f == 'race.json' for _, _, fs in os.walk(dest) for f in fs)

    def test_a_change_makes_the_next_listing_say_so(self, processed, cli):
        cli('backup', processed); assert cli('backup', processed, '--list').stdout.endswith('no changes since the last backup\n')
        open(os.path.join(processed, 'strata360', 'notes.json'), 'w').write('{"a": 1}')
        assert cli('backup', processed, '--list').stdout.endswith('\nchanges since the last backup\n')


class TestCredits:
    def test_a_project_without_maps_needs_none_and_write_saves_the_text(self, processed, cli):
        assert cli('credits', processed).stdout.startswith('No credits are needed')
        r = cli('credits', processed, '--write'); p = os.path.join(processed, 'strata360', 'credits.txt')
        assert 'written to' in r.stdout and open(p).read().startswith('No credits are needed')


class TestPlanning:
    def test_the_rough_plan_without_candidates_says_so(self, processed, cli):
        r = cli('plan-blocks', processed, '--target-s', '60')
        assert 'film length guide: the target you gave (60.0 s)' in r.stdout and '0 blocks' in r.stdout and '2 clip(s) have no candidates yet' in r.stdout
        doc = json.load(open(os.path.join(processed, 'strata360', 'blocks.json'))); assert doc['target_source'] == 'target' and len(doc['clips_without_candidates']) == 2

    def test_json_gives_the_plan_and_automatic_needs_no_target(self, processed, cli):
        r = json.loads(cli('plan-blocks', processed, '--json').stdout); assert r['target_source'] == 'automatic' and r['plan']['blocks'] == []
        assert 'automatic (from the usable footage)' in cli('plan-blocks', processed, '--auto').stdout

    def test_gaps_need_a_race_track(self, processed, cli):
        r = cli('gaps', processed, check=False); assert r.code != 0 and 'no race track' in r.out


class TestDoctor:
    def test_reports_the_tools_and_the_encoder_the_tests_rely_on(self, cli):
        r = cli('doctor', check=False)
        assert r.code in (0, 1) and 'tools:' in r.stdout and 'races folder:' in r.stdout and 'map overlay:' in r.stdout
        assert 'ok   ffmpeg:' in r.stdout and 'ok   libx265 encoder' in r.stdout
        assert ('all required checks passed' in r.stdout) == (r.code == 0) and ('some required checks FAILED' in r.stdout) == (r.code == 1)
