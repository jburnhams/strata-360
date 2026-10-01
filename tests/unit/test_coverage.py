import json

import pytest

from strata360.pipeline import coverage as C
from strata360.pipeline.stages import STAGES


@pytest.fixture
def cov_project(make_project):
    p = make_project('trip', config=True)
    p.write_json('race.json', {'library': p.folder, 'stages': ['ingest', 'motion', 'places', 'candidates']})
    return p


def add(p, clip, *files):
    d = p.add_clip(clip)
    for f in files: open(f'{d}/{f}', 'w').write('{}')


def test_every_output_present_is_ok(cov_project):
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json', 'places.json', 'candidates.json')
    r = C.coverage(cov_project.folder)
    assert r['complete'] and r['missing'] == [] and r['blocked'] == {}
    assert r['totals'] == {'ingest': 1, 'motion': 1, 'places': 1, 'candidates': 1}


def test_missing_artefacts_block_decisions(cov_project):
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json')
    r = C.coverage(cov_project.folder)
    row = r['rows'][0]['stages']
    assert row['motion'] == 'ok' and row['candidates'] == 'missing'
    assert row['places'] == 'waiting' if STAGES['places'].needs_track else row['places'] == 'missing'
    assert 'planning the film from the clip' in r['blocked']
    assert {'clip': 'CAM_20260221120007_0019_D', 'stage': 'candidates', 'state': 'missing'} in r['missing']
    assert not r['complete']


def test_track_unblocks_waiting(cov_project):
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json')
    open(cov_project.path('track.gpx'), 'w').write('<gpx/>')
    assert C.coverage(cov_project.folder)['rows'][0]['stages']['places'] == 'missing'


def test_partial_when_only_some_outputs(cov_project, monkeypatch):
    monkeypatch.setitem(STAGES, 'motion', STAGES['motion'].__class__(**{**STAGES['motion'].__dict__, 'outputs': ('motion.json', 'extra.json')}))
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json')
    assert C.coverage(cov_project.folder)['rows'][0]['stages']['motion'] == 'partial'


def test_cli_json_and_text(cov_project, capsys):
    from strata360 import cli
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json')
    cli.cmd_coverage(type('A', (), dict(name=cov_project.folder, json=True)))
    assert json.loads(capsys.readouterr().out)['clips'] == 1
    cli.cmd_coverage(type('A', (), dict(name=cov_project.folder, json=False)))
    out = capsys.readouterr().out
    assert 'missing:' in out and 'candidates (missing)' in out and 'decisions blocked:' in out


def test_api(make_client, cov_project, client):
    add(cov_project, 'CAM_20260221120007_0019_D', 'motion.json')
    c = make_client(roots=[cov_project.folder.rsplit('/', 1)[0]])
    r = c.get('/api/coverage', params={'folder': cov_project.folder})
    assert r.status_code == 200 and r.json()['clips'] == 1
