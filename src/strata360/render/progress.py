"""What a render is doing and how long each part takes, kept in a small JSON file the page reads while the render runs (render/final.py and render/still.py write it, the server hands it on, the page shows it).

  {state: running | done | error, started, updated, error?,
   stages:  [{name, state: running | done | error, started, seconds, detail}],       the steps in order (prepare, load model, render, audio, ...), `detail` is where the step has got to ("piece 3 of 40")
   timings: {bucket: {seconds, calls}},                                               time spent so far in each kind of work inside the render: decode, project, upscale, grade, overlay, encode
   log:     [[seconds since the start, text], ...]}                                   the last LOG_KEEP lines

Writes are atomic and at most every FLUSH_S seconds apart (a change of stage is written at once), so a page that polls never reads half a file and a fast loop does not spend its time writing."""
import contextlib, json, os, time

LOG_KEEP = 200
FLUSH_S = 0.5


class Progress:
    def __init__(self, path=None, clock=time.time):
        self.path, self.clock = path, clock; self.started = clock(); self.state = 'running'; self.error = None; self.stages = []; self.timings = {}; self.log = []; self._last = 0.0

    def _current(self): return self.stages[-1] if self.stages and self.stages[-1]['state'] == 'running' else None

    def note(self, text):
        """A line in the log, stamped with the seconds since the start."""
        self.log.append([round(self.clock() - self.started, 1), text]); del self.log[:-LOG_KEEP]; self.flush()

    @contextlib.contextmanager
    def stage(self, name, detail=''):
        """`with progress.stage('load model'):` times a step; an exception marks it (and the render) as failed and goes on up."""
        st = dict(name=name, state='running', started=self.clock(), seconds=0.0, detail=detail); self.stages.append(st); self.note(name + (f': {detail}' if detail else '')); self.flush(True)
        try: yield st
        except BaseException as e:
            st.update(state='error', seconds=self.clock() - st['started']); self.fail(f'{name}: {e}'); raise
        st.update(state='done', seconds=self.clock() - st['started']); self.flush(True)

    def detail(self, text):
        """Where the running step has got to."""
        st = self._current()
        if st is not None: st['detail'] = text; st['seconds'] = self.clock() - st['started']; self.flush()

    def add(self, bucket, seconds, calls=1):
        b = self.timings.setdefault(bucket, dict(seconds=0.0, calls=0)); b['seconds'] += seconds; b['calls'] += calls

    @contextlib.contextmanager
    def timed(self, bucket):
        t = self.clock()
        try: yield
        finally: self.add(bucket, self.clock() - t)

    def finish(self):
        self.state = 'done' if self.state == 'running' else self.state; self.flush(True)

    def fail(self, error):
        self.state = 'error'; self.error = str(error)[-300:]; self.note('failed: ' + self.error); self.flush(True)

    def doc(self):
        st = self._current()
        if st is not None: st['seconds'] = self.clock() - st['started']
        return dict(state=self.state, started=self.started, updated=self.clock(), error=self.error, stages=[dict(s, seconds=round(s['seconds'], 2)) for s in self.stages],
                    timings={k: dict(seconds=round(v['seconds'], 2), calls=v['calls']) for k, v in self.timings.items()}, log=self.log)

    def flush(self, force=False):
        if not self.path: return
        now = self.clock()
        if not force and now - self._last < FLUSH_S: return
        self._last = now; tmp = f'{self.path}.{os.getpid()}.tmp'
        try: os.makedirs(os.path.dirname(self.path), exist_ok=True); json.dump(self.doc(), open(tmp, 'w')); os.replace(tmp, self.path)
        except OSError: pass                                                           # a progress file that cannot be written must never stop a render


def load(path):
    """The progress document at `path`, or None (not started, or half-written by a crash)."""
    try: return json.load(open(path))
    except (OSError, ValueError): return None


class Null(Progress):
    """Records nothing on disk: for callers that do not want a file (and for tests)."""
    def __init__(self, clock=time.time): super().__init__(None, clock)
