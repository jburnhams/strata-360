"""server/app.py: the folders the browser may look in, and where a service gets its token."""
import json, os


def test_the_footage_folder_is_always_an_allowed_root_once_and_a_missing_one_is_dropped(tmp_path, monkeypatch):
    from strata360.server import app
    footage = tmp_path / 'footage'; footage.mkdir()
    monkeypatch.setenv('STRATA_FOOTAGE', str(footage)); monkeypatch.delenv('STRATA_PROJECTS', raising=False)
    assert app.load_roots(None) == [str(footage.resolve())]
    assert app.load_roots([str(footage), str(tmp_path / 'gone')]) == [str(footage.resolve())]          # not listed twice; a folder that is not there (a share not mounted) is left out


def test_the_server_reads_its_token_from_the_environment_so_a_service_keeps_it_off_the_command_line(tmp_path, monkeypatch):
    from strata360.server import app
    (tmp_path / 'f').mkdir(); seen = {}
    monkeypatch.setenv('STRATA360_SERVER_TOKEN', 'sekrit'); monkeypatch.setattr(app, 'create_app', lambda roots, token: seen.update(token=token) or 'app')
    import sys, types
    monkeypatch.setitem(sys.modules, 'uvicorn', types.SimpleNamespace(run=lambda *a, **k: None))
    app.main(['--root', str(tmp_path / 'f')])
    assert seen['token'] == 'sekrit'
