"""The shared test doubles in tests/utils and tests/conftest.py behave as their docs say (a wrong double would mislead every test built on it)."""
import os, subprocess, time, urllib.request
import pytest
from fakes import FakeResponse, http_error


def test_fake_urlopen_records_requests_and_replays_replies(fake_urlopen):
    fake_urlopen.reply({'a': 1}, b'raw', http_error(429, {'error': 'slow'}), OSError('down'))
    req = urllib.request.Request('http://x/y', data=b'{"q": 2}', headers={'X-Key': 'k'}, method='POST')
    assert urllib.request.urlopen(req, timeout=5).read() == b'{"a": 1}' and urllib.request.urlopen('http://x/z').read() == b'raw'
    assert fake_urlopen.calls[0] == dict(url='http://x/y', method='POST', timeout=5, headers={'x-key': 'k'}, body={'q': 2})
    with pytest.raises(urllib.error.HTTPError) as e: urllib.request.urlopen('http://x/')
    assert e.value.code == 429 and b'slow' in e.value.read()
    with pytest.raises(OSError): urllib.request.urlopen('http://x/')


def test_fake_urlopen_fails_loudly_when_nothing_is_queued(fake_urlopen):
    with pytest.raises(AssertionError, match='unexpected HTTP request'): urllib.request.urlopen('http://x/')


def test_fake_response_is_a_context_manager():
    with FakeResponse({'ok': True}, status=201) as r: assert r.read() == b'{"ok": true}' and r.getcode() == 201


def test_fake_popen_starts_nothing(fake_popen):
    p = subprocess.Popen(['ffmpeg', '-i', 'x'], cwd='/tmp')
    assert fake_popen.instances == [p] and p.cmd == ['ffmpeg', '-i', 'x'] and p.kw == {'cwd': '/tmp'} and p.poll() is None
    p.terminate(); assert p.poll() == -15


def test_fake_run_returns_scripted_output_and_can_fail(fake_run):
    fake_run.returns['ffprobe'] = b'{"streams": []}'
    assert subprocess.check_output(['ffprobe', '-v', 'quiet']) == b'{"streams": []}' and subprocess.run(['ffmpeg', '-y']).returncode == 0
    fake_run.code = 1
    with pytest.raises(subprocess.CalledProcessError): subprocess.run(['ffmpeg'], check=True)
    assert [c[0] for c in fake_run.calls] == ['ffprobe', 'ffmpeg', 'ffmpeg']


def test_no_sleep_records_instead_of_waiting(no_sleep):
    t = time.time(); time.sleep(30); time.sleep(2)
    assert no_sleep.delays == [30, 2] and time.time() - t < 5


def test_make_project_lays_out_the_folder_convention(make_project):
    p = make_project('trip', config={'languages': ['fr']}, clips=['C1'])
    assert p.read_json('race.json') == {'languages': ['fr']} and p.read_json('clips/C1/clip.json')['clip_id'] == 'C1' and p.race_dir.endswith(os.path.join('trip', 'strata360'))


def test_the_network_is_blocked_in_unit_tests():
    import socket
    with pytest.raises(AssertionError, match='must not use the network'): socket.create_connection(('example.com', 80), timeout=1)


def test_home_is_isolated(isolated_home, tmp_path):
    assert os.path.expanduser('~') == str(isolated_home) and not str(isolated_home).startswith(str(tmp_path))
