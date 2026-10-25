import pytest
from strata360 import cli

@pytest.fixture
def parser():
    return cli.create_parser()

def test_init_command(parser):
    args = parser.parse_args(['init', 'my-race', '--library', '/tmp/lib', '--languages', 'en,fr', '--clock-offset-hours', '2.5'])
    assert args.cmd == 'init'
    assert args.name == 'my-race'
    assert args.library == '/tmp/lib'
    assert args.languages == 'en,fr'
    assert args.clock_offset_hours == 2.5
    assert args.fn == cli.cmd_init

def test_run_command(parser):
    args = parser.parse_args(['run', 'my-race', '--clips', 'C0001', '--clips', 'C0002'])
    assert args.cmd == 'run'
    assert args.name == 'my-race'
    assert args.clips == 'C0002'
    assert args.fn == cli.cmd_run

def test_serve_command(parser):
    args = parser.parse_args(['serve', '--root', '/a', '--root', '/b', '--port', '8080'])
    assert args.cmd == 'serve'
    assert args.root == ['/a', '/b']
    assert args.port == 8080
    assert args.fn == cli.cmd_serve

def test_voiceover_command(parser):
    args = parser.parse_args(['voiceover', 'my-race', '--engine', 'coqui', '--fetch'])
    assert args.cmd == 'voiceover'
    assert args.name == 'my-race'
    assert args.engine == 'coqui'
    assert args.fetch is True
    assert args.fn == cli.cmd_voiceover

def test_script_command(parser):
    args = parser.parse_args(['script', 'my-race', '--length', '120.5', '--provider', 'anthropic'])
    assert args.cmd == 'script'
    assert args.name == 'my-race'
    assert args.length == 120.5
    assert args.provider == 'anthropic'
    assert args.fn == cli.cmd_script

def test_final_command(parser):
    args = parser.parse_args(['final', 'my-race', '--size', '3840x2160', '--vr', '--fps', '60.0'])
    assert args.cmd == 'final'
    assert args.name == 'my-race'
    assert args.size == '3840x2160'
    assert args.vr is True
    assert args.fps == 60.0
    assert args.fn == cli.cmd_final

def test_chapters_command(parser):
    args = parser.parse_args(['chapters', 'my-race', '--min-s', '15.0'])
    assert args.cmd == 'chapters'
    assert args.name == 'my-race'
    assert args.min_s == 15.0
    assert args.fn == cli.cmd_chapters

def test_music_build_command(parser):
    args = parser.parse_args(['music-build', 'my-race', '--fidelity', '0.5', '--take', 'A=1', '--take', 'B=2'])
    assert args.cmd == 'music-build'
    assert args.name == 'my-race'
    assert args.fidelity == 0.5
    assert args.take == ['A=1', 'B=2']
    assert args.fn == cli.cmd_music_build


def test_migrate_projects_copies_each_strata360_folder_to_the_projects_folder_and_leaves_the_footage_alone(tmp_path, monkeypatch, capsys):
    import argparse
    from strata360 import cli
    footage = tmp_path / 'footage'; projects = tmp_path / 'projects'; projects.mkdir()
    (footage / 'a' / 'strata360' / 'clips').mkdir(parents=True); (footage / 'a' / 'strata360' / 'race.json').write_text('{}'); (footage / 'a' / 'VID.osv').write_text('v')
    (footage / 'b').mkdir()
    monkeypatch.setenv('STRATA_FOOTAGE', str(footage)); monkeypatch.setenv('STRATA_PROJECTS', str(projects))
    cli.cmd_migrate_projects(argparse.Namespace(dry_run=True, force=False)); assert not (projects / 'a').exists()
    cli.cmd_migrate_projects(argparse.Namespace(dry_run=False, force=False))
    assert (projects / 'a' / 'race.json').exists() and (projects / 'a' / 'clips').is_dir() and not (projects / 'b').exists()
    assert (footage / 'a' / 'strata360' / 'race.json').exists()                          # copied, not moved
    (projects / 'a' / 'race.json').write_text('{"edited": 1}')
    cli.cmd_migrate_projects(argparse.Namespace(dry_run=False, force=False))             # a second run does not overwrite work done since
    assert (projects / 'a' / 'race.json').read_text() == '{"edited": 1}' and 'skip' in capsys.readouterr().out
