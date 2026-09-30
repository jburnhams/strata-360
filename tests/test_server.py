"""Server path safety and project-folder convention. Run: .venv/bin/python tests/test_server.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.server import app
from strata360.pipeline import config


def make():
    base = os.path.realpath(tempfile.mkdtemp()); root = os.path.join(base, 'home'); out = os.path.join(base, 'outside')
    os.makedirs(os.path.join(root, 'race1')); os.makedirs(out); open(os.path.join(out, 'secret.txt'), 'w').write('x')
    open(os.path.join(root, 'race1', 'CAM_20260101000000_0001_D.OSV'), 'wb').write(b'x'); os.symlink(out, os.path.join(root, 'escape'))
    return root, out


def test_paths_outside_roots_are_refused():
    root, out = make(); roots = [root]
    assert app.safe_path(roots, root) == root and app.safe_path(roots, os.path.join(root, 'race1'))
    for bad in (out, '/etc', os.path.join(root, '..', 'outside'), os.path.join(root, 'escape'), os.path.join(root, 'escape', 'secret.txt'), '', root + '-evil'):
        try: app.safe_path(roots, bad); raise AssertionError(f'{bad!r} should be refused')
        except app.Forbidden: pass


def test_browse_lists_only_safe_entries_and_counts_footage():
    root, out = make(); b = app.browse([root], root)
    names = [e['name'] for e in b['entries']]; assert 'race1' in names and 'escape' not in names and b['parent'] is None
    assert app.browse([root], os.path.join(root, 'race1'))['footage_here'] == 1


def test_project_folder_convention():
    root, _ = make(); f = os.path.join(root, 'race1')
    assert config.race_dir(f) == os.path.join(f, 'strata360') and config.race_dir('legends-2026').endswith(os.path.join('races', 'legends-2026'))
    from strata360.pipeline import clips
    os.makedirs(os.path.join(f, 'strata360')); open(os.path.join(f, 'strata360', 'x.OSV'), 'wb').write(b'x')
    cl, _ = clips.discover(f); assert len(cl) == 1                                            # our own results folder is not footage


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
