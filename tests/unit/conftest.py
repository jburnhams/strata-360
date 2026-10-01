"""Fixtures for the unit suite only: it must be hermetic (no network, no real home folder, no waiting)."""
import socket
import pytest
from hypothesis import HealthCheck, settings

settings.register_profile('unit', deadline=None, max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile('unit')


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """~ points into the test's tmp dir, so nothing reads or writes the developer's real ~/.strata360 (server state, secrets, keys)."""
    base = tmp_path_factory.mktemp('env'); home = base / 'home'; home.mkdir()      # outside the test's own tmp_path: tests browse that as a root
    monkeypatch.setenv('HOME', str(home)); monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('STRATA_RACES', str(base / 'races'))
    for k in ('ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'): monkeypatch.delenv(k, raising=False)
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A unit test that tries to open an outbound connection fails at once (loopback and unix sockets are fine). Use `fake_urlopen` to script HTTP."""
    real = socket.socket.connect
    def guarded(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in ('127.0.0.1', '::1', 'localhost'): raise AssertionError(f'unit tests must not use the network (tried {address!r})')
        return real(self, address, *a, **kw)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
