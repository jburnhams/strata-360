"""Test doubles for the outside world: HTTP (urllib), subprocesses, the clock. Use through the fixtures in tests/conftest.py (`fake_urlopen`, `fake_popen`, `fake_run`)."""
import io, json, urllib.error


class FakeResponse:
    """What `urllib.request.urlopen` returns: `.read()` and use as a context manager. `body` is bytes, str or anything JSON-serialisable."""
    def __init__(self, body=b'', status=200, headers=None):
        self.body = body if isinstance(body, bytes) else body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.status, self.headers = status, headers or {}
    def read(self, n=-1): return self.body if n < 0 else self.body[:n]
    def getcode(self): return self.status
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeUrlopen:
    """A scripted `urlopen`: queue replies, then inspect `.calls`. A reply is a body (see FakeResponse), a FakeResponse, an `Exception` (raised), or `http_error(code, body)`.
        fake_urlopen.reply({'ok': 1}).reply(http_error(429, {'error': 'slow down'}))
    Running out of replies fails the test rather than reaching the network."""
    def __init__(self): self.replies, self.calls = [], []
    def reply(self, *items):
        self.replies.extend(items); return self
    def __call__(self, req, data=None, timeout=None, **kw):
        body = getattr(req, 'data', None) if not isinstance(req, str) else data
        self.calls.append(dict(url=req if isinstance(req, str) else req.full_url, method=None if isinstance(req, str) else req.get_method(), timeout=timeout,
                               headers={} if isinstance(req, str) else {k.lower(): v for k, v in req.header_items()}, body=_maybe_json(body)))
        if not self.replies: raise AssertionError(f'unexpected HTTP request to {self.calls[-1]["url"]} (no reply queued)')
        r = self.replies.pop(0)
        if isinstance(r, BaseException): raise r
        return r if isinstance(r, FakeResponse) else FakeResponse(r)


def http_error(code, body=None, url='http://fake'):
    return urllib.error.HTTPError(url, code, 'error', {}, io.BytesIO(body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()))


def _maybe_json(b):
    if b is None: return None
    try: return json.loads(b)
    except (ValueError, TypeError): return b


class FakePopen:
    """Stands in for `subprocess.Popen`: records the command line and kwargs, never starts anything. `.instances` lists every one made.
    File objects passed as stdin/stdout/stderr are recorded by name, not kept: holding them open would stop a test deleting the project folder on Windows."""
    instances = []
    def __init__(self, cmd, **kw):
        self.cmd, self.kw, self.pid, self.returncode = list(cmd), {k: getattr(v, 'name', v) if hasattr(v, 'fileno') else v for k, v in kw.items()}, 4242 + len(FakePopen.instances), None
        FakePopen.instances.append(self)
    def poll(self): return self.returncode
    def wait(self, timeout=None): return self.returncode if self.returncode is not None else 0
    def terminate(self): self.returncode = -15
    def kill(self): self.returncode = -9


class FakeRun:
    """Stands in for `subprocess.run` / `check_output`: `.calls` holds the commands; `.returns` maps a substring of the command line to stdout (default b'')."""
    def __init__(self): self.calls, self.returns, self.code = [], {}, 0
    def _out(self, cmd):
        line = ' '.join(map(str, cmd))
        return next((v for k, v in self.returns.items() if k in line), b'')
    def __call__(self, cmd, *a, **kw):
        import subprocess
        self.calls.append(list(cmd)); out = self._out(cmd)
        if self.code and kw.get('check'): raise subprocess.CalledProcessError(self.code, cmd, out)
        return subprocess.CompletedProcess(cmd, self.code, out, b'')
    def check_output(self, cmd, *a, **kw):
        self.calls.append(list(cmd)); return self._out(cmd)

class FakeTorchNoGrad:
    def __enter__(self): pass
    def __exit__(self, *args): pass

class FakeTorchTensor:
    def __init__(self, x): self.x = x
    @property
    def logits(self): return self
    def numpy(self):
        import numpy as np
        return np.zeros((10, 4)) if self.x is None else self.x
    def astype(self, t): return self.x

def mock_torch(monkeypatch):
    import sys, types
    fake_torch = types.ModuleType('torch')
    fake_torch.no_grad = FakeTorchNoGrad
    fake_torch.from_numpy = lambda x: x
    def fake_log_softmax(logits, dim): return [FakeTorchTensor(None)]
    fake_torch.log_softmax = fake_log_softmax
    monkeypatch.setitem(sys.modules, 'torch', fake_torch)

class FakeHuggingFaceModel:
    def __init__(self): pass
    def generate(self, input_ids, **kw):
        return [input_ids[0] + '_TRANSLATED']
    @classmethod
    def from_pretrained(cls, name):
        class M:
            def eval(self):
                class Ev:
                    def __call__(self, x):
                        return FakeTorchTensor(x)
                    def generate(self, input_ids, **kw):
                        return [input_ids[0] + '_TRANSLATED']
                return Ev()
        return M()

class FakeHuggingFaceTokenizer:
    def __init__(self): pass
    def __call__(self, text, **kw):
        return {'input_ids': text}
    def decode(self, out, **kw):
        return out.upper()
    @classmethod
    def from_pretrained(cls, name):
        return cls()

def mock_transformers(monkeypatch):
    import sys, types
    fake_transformers = types.ModuleType('transformers')
    fake_transformers.MarianMTModel = FakeHuggingFaceModel
    fake_transformers.MarianTokenizer = FakeHuggingFaceTokenizer
    fake_transformers.Wav2Vec2ForCTC = FakeHuggingFaceModel
    fake_transformers.Wav2Vec2Processor = FakeHuggingFaceTokenizer
    monkeypatch.setitem(sys.modules, 'transformers', fake_transformers)
