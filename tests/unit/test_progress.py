"""The render progress recorder (render/progress.py): steps with their times, time spent by kind of work, a short log, and a file the page can read at any moment."""
import json

import pytest

from strata360.render import progress as PG


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def tick(self, s): self.t += s


@pytest.fixture
def clock(): return Clock()


class TestStages:
    def test_a_step_is_timed_and_marked_done(self, clock):
        pg = PG.Progress(clock=clock)
        with pg.stage('prepare', 'glides'): clock.tick(3.5)
        s = pg.stages[0]; assert (s['name'], s['state'], s['seconds'], s['detail']) == ('prepare', 'done', 3.5, 'glides')

    def test_steps_keep_their_order(self, clock):
        pg = PG.Progress(clock=clock)
        for n in ('a', 'b', 'c'):
            with pg.stage(n): clock.tick(1)
        assert [s['name'] for s in pg.stages] == ['a', 'b', 'c']

    def test_a_running_step_shows_its_time_so_far_in_the_document(self, clock):
        pg = PG.Progress(clock=clock)
        with pg.stage('render'):
            clock.tick(7); assert pg.doc()['stages'][0]['seconds'] == 7 and pg.doc()['stages'][0]['state'] == 'running'

    def test_detail_changes_the_running_step(self, clock):
        pg = PG.Progress(clock=clock)
        with pg.stage('render'): pg.detail('piece 3 of 9'); assert pg.stages[0]['detail'] == 'piece 3 of 9'

    def test_detail_with_no_step_running_is_ignored(self, clock):
        PG.Progress(clock=clock).detail('nothing')

    def test_a_failing_step_marks_itself_and_the_render_and_raises_on(self, clock):
        pg = PG.Progress(clock=clock)
        with pytest.raises(ValueError):
            with pg.stage('load model'): raise ValueError('weights missing')
        assert pg.stages[0]['state'] == 'error' and pg.state == 'error' and 'weights missing' in pg.error

    def test_finish_marks_a_running_render_done_but_keeps_an_error(self, clock):
        a = PG.Progress(clock=clock); a.finish(); b = PG.Progress(clock=clock); b.fail('x'); b.finish()
        assert (a.state, b.state) == ('done', 'error')


class TestTimings:
    def test_time_is_added_up_by_kind_of_work(self, clock):
        pg = PG.Progress(clock=clock)
        for s in (1.0, 2.5):
            with pg.timed('upscale'): clock.tick(s)
        with pg.timed('decode'): clock.tick(0.25)
        d = pg.doc()['timings']; assert d['upscale'] == dict(seconds=3.5, calls=2) and d['decode'] == dict(seconds=0.25, calls=1)

    def test_time_is_counted_even_when_the_work_fails(self, clock):
        pg = PG.Progress(clock=clock)
        with pytest.raises(RuntimeError):
            with pg.timed('encode'): clock.tick(2); raise RuntimeError
        assert pg.timings['encode']['seconds'] == 2


class TestLog:
    def test_lines_carry_the_seconds_since_the_start(self, clock):
        pg = PG.Progress(clock=clock); clock.tick(4.26); pg.note('hello'); assert pg.log[-1] == [4.3, 'hello']

    def test_only_the_last_lines_are_kept(self, clock):
        pg = PG.Progress(clock=clock)
        for i in range(PG.LOG_KEEP + 50): pg.note(str(i))
        assert len(pg.log) == PG.LOG_KEEP and pg.log[-1][1] == str(PG.LOG_KEEP + 49)

    def test_a_step_writes_its_name_to_the_log(self, clock):
        pg = PG.Progress(clock=clock)
        with pg.stage('audio', 'loudness'): pass
        assert pg.log[0][1] == 'audio: loudness'


class TestFile:
    def test_the_document_is_written_and_read_back(self, tmp_path, clock):
        path = str(tmp_path / 'sub' / 'progress.json'); pg = PG.Progress(path, clock=clock)
        with pg.stage('prepare'): clock.tick(1)
        pg.finish(); d = PG.load(path); assert d['state'] == 'done' and d['stages'][0]['name'] == 'prepare' and d['started'] == 1000.0

    def test_writes_are_throttled_but_stage_changes_are_not(self, tmp_path, clock):
        path = str(tmp_path / 'p.json'); pg = PG.Progress(path, clock=clock)
        with pg.stage('render'):
            pg.detail('one'); clock.tick(PG.FLUSH_S + 0.1); pg.detail('two'); pg.detail('three')           # 'three' comes straight after 'two': not written yet
            assert PG.load(path)['stages'][0]['detail'] == 'two'
        assert PG.load(path)['stages'][0]['state'] == 'done'

    def test_nothing_is_left_half_written(self, tmp_path, clock):
        pg = PG.Progress(str(tmp_path / 'p.json'), clock=clock); pg.note('x'); pg.flush(True)
        assert [f.name for f in tmp_path.iterdir()] == ['p.json']

    def test_a_missing_or_broken_file_reads_as_none(self, tmp_path):
        assert PG.load(str(tmp_path / 'none.json')) is None
        (tmp_path / 'bad.json').write_text('{"state": '); assert PG.load(str(tmp_path / 'bad.json')) is None

    def test_a_file_that_cannot_be_written_never_stops_the_render(self, tmp_path, clock):
        blocker = tmp_path / 'file'; blocker.write_text('x'); pg = PG.Progress(str(blocker / 'p.json'), clock=clock)           # the folder is a file
        with pg.stage('render'): pg.note('still going')
        assert pg.stages[0]['state'] == 'done'

    def test_the_null_recorder_keeps_the_numbers_and_writes_nothing(self, tmp_path, clock):
        pg = PG.Null(clock); pg.add('decode', 1.0); pg.flush(True); assert pg.timings['decode']['seconds'] == 1.0 and list(tmp_path.iterdir()) == []

    def test_the_document_is_plain_json(self, clock):
        pg = PG.Progress(clock=clock)
        with pg.stage('x'): pg.add('decode', 0.5)
        json.dumps(pg.doc())
