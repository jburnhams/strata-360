"""Server path safety and project-folder convention."""
import os, json
import pytest
from strata360.server import app
from strata360.pipeline import config


@pytest.fixture
def layout(tmp_path):
    root = str(tmp_path / 'home'); out = str(tmp_path / 'outside')
    os.makedirs(os.path.join(root, 'race1')); os.makedirs(out); open(os.path.join(out, 'secret.txt'), 'w').write('x')
    open(os.path.join(root, 'race1', 'CAM_20260101000000_0001_D.OSV'), 'wb').write(b'x')
    try: os.symlink(out, os.path.join(root, 'escape'))
    except OSError: pass
    return root, out


def test_paths_outside_roots_are_refused(layout):
    root, out = layout; roots = [root]
    assert app.safe_path(roots, root) == root and app.safe_path(roots, os.path.join(root, 'race1'))

    if os.path.exists(os.path.join(root, 'escape')):
        bad_paths = (out, '/etc', os.path.join(root, '..', 'outside'), os.path.join(root, 'escape'), os.path.join(root, 'escape', 'secret.txt'), '', root + '-evil')
    else:
        bad_paths = (out, '/etc', os.path.join(root, '..', 'outside'), '', root + '-evil')

    for bad in bad_paths:
        with pytest.raises(app.Forbidden):
            app.safe_path(roots, bad)


def test_browse_lists_only_safe_entries_and_counts_footage(layout):
    root, _ = layout; b = app.browse([root], root)
    names = [e['name'] for e in b['entries']]; assert 'race1' in names and 'escape' not in names and b['parent'] is None
    assert app.browse([root], os.path.join(root, 'race1'))['footage_here'] == 1


def test_project_folder_convention(layout):
    root, _ = layout; f = os.path.join(root, 'race1')
    assert config.race_dir(f) == os.path.join(f, 'strata360') and config.race_dir('legends-2026').endswith(os.path.join('races', 'legends-2026'))
    from strata360.pipeline import clips
    os.makedirs(os.path.join(f, 'strata360')); open(os.path.join(f, 'strata360', 'x.OSV'), 'wb').write(b'x')
    cl, _ = clips.discover(f); assert len(cl) == 1                                            # our own results folder is not footage


def test_has_footage_and_roots_are_not_projects(layout):
    root, out = layout; assert app.has_footage(os.path.join(root, 'race1')) and app.has_footage(root) and not app.has_footage(out)
    os.makedirs(os.path.join(out, 'a', 'b', 'c', 'd')); open(os.path.join(out, 'a', 'b', 'c', 'd', 'X.OSV'), 'wb').write(b'x'); assert not app.has_footage(out, depth=3)


def test_project_folders_are_opened_whole(layout):
    root, _ = layout; f = os.path.join(root, 'race1'); os.makedirs(os.path.join(f, 'sub')); os.makedirs(os.path.join(f, 'strata360')); open(os.path.join(f, 'strata360', 'race.json'), 'w').write('{}')
    b = app.browse([root], f); assert b['is_project'] and b['entries'] == [] and not b['can_create']              # no sub-folder choice inside a project
    r = app.browse([root], root); assert [e['name'] for e in r['entries']] == ['race1'] and r['entries'][0]['is_project'] and not r['can_create']   # a root is never a project to create
    os.makedirs(os.path.join(root, 'new')); open(os.path.join(root, 'new', 'CAM_20260101000000_0002_D.OSV'), 'wb').write(b'x')
    n = app.browse([root], os.path.join(root, 'new')); assert n['can_create'] and not n['is_project']


def test_endpoints_that_show_a_clip_and_the_transcript_work_with_words_and_corrections(layout, make_client):
    from strata360.analysis import transcript_edits as TE
    root, _ = layout; f = os.path.join(root, 'race1'); rd = config.race_dir(f); cd = os.path.join(rd, 'clips', 'CAM_20260101000000_0001_D'); os.makedirs(cd)
    json.dump(dict(clip_id='CAM_20260101000000_0001_D', time=dict(start_utc='2026-01-01T00:00:00Z'), video=dict(source_frames=500, nominal_fps=50.0), source_files=dict(osv='x.OSV')), open(os.path.join(cd, 'clip.json'), 'w'))
    ws = [dict(w='a', t0=0.0, t1=0.4, p=0.9), dict(w='wave', t0=0.4, t1=0.8, p=0.3)]
    json.dump(dict(segments=[dict(t0=0.0, t1=1.0, lang='en', text='a wave', text_en='a wave', words=ws)]), open(os.path.join(cd, 'transcript.json'), 'w')); json.dump(dict(library=f), open(os.path.join(rd, 'race.json'), 'w'))
    TE.set_user(cd, 0, 1, 'wade'); c = make_client(roots=[root]); q = dict(folder=f, clip='CAM_20260101000000_0001_D')
    r = c.get('/api/clip', params=q); assert r.status_code == 200, r.text[-300:]
    tr = r.json()['transcript'][0]; assert tr['si'] == 0 and tr['text'] == 'a wade' and tr['words'][1]['e']['orig'] == 'wave' and tr['words'][1]['e']['src'] == 'user'
    r = c.get('/api/transcript', params=dict(folder=f)); assert r.status_code == 200 and r.json()['segments'][0]['words'][1]['w'] == 'wade'
    assert c.post('/api/transcript/edit', json=dict(folder=f, clip='CAM_20260101000000_0001_D', seg=0, word=1, action='clear')).status_code == 200 and c.get('/api/clip', params=q).json()['transcript'][0]['text'] == 'a wave'
