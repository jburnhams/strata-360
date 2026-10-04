import os, tarfile, time
import pytest
from strata360.pipeline import backup as B, config

H = 3600


@pytest.fixture
def proj(tmp_path):
    f = str(tmp_path / 'footage'); rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'clips', 'c1'))
    open(os.path.join(rd, 'race.json'), 'w').write('{}'); open(os.path.join(rd, 'clips', 'c1', 'clip.json'), 'w').write('{"a": 1}')
    return f


def names(f, p): return sorted(m.name for m in tarfile.open(p).getmembers())


def test_collect_takes_new_data_files_and_skips_bulk_and_scratch(proj):
    rd = config.race_dir(proj)
    for rel, n in [('clips/c1/new_feature.json', 10), ('notes.txt', 5), ('clips/c1/thumb.jpg', 5), ('clips/c1/a.wav', 5), ('run.log', 5), ('.claims/x', 5), ('clips/c1/stages.json.1.tmp', 5), ('big.json', 6_000_000)]:
        p = os.path.join(rd, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'wb').write(b'x' * n)
    assert [r for r, _ in B.collect(proj)] == ['clips/c1/clip.json', 'clips/c1/new_feature.json', 'notes.txt', 'race.json']


def test_backup_only_when_changed_and_not_more_often_than_the_interval(proj):
    t = 1_800_000_000
    p = B.backup(proj, now=t); assert p and p.endswith('.tar.gz') and names(proj, p) == ['clips/c1/clip.json', 'race.json'] and not B.is_dirty(proj)
    assert B.backup(proj, now=t + 4 * H) is None                                                   # nothing changed
    f = os.path.join(config.race_dir(proj), 'clips', 'c1', 'clip.json'); open(f, 'w').write('{"a": 22}'); assert B.is_dirty(proj)
    assert B.backup(proj, now=t + 600) is None and B.is_dirty(proj)                              # changed, but only 10 min since the last
    assert B.backup(proj, now=t + 1801) and not B.is_dirty(proj)
    assert len(B.list_backups(proj)) == 2


def test_backups_folder_is_not_part_of_the_backup(proj):
    B.backup(proj, now=1_800_000_000, force=True); assert not any(r.startswith('backups') for r, _ in B.collect(proj))


def test_retention_thins_on_an_exponential_scale():
    now = 1_800_000_000.0; times = [now - i * 1800 for i in range(0, 2 * 24 * 2 * 40)]             # 40 days of half-hourly backups
    k = sorted(B.keep_set(times, now))
    assert all(t in k for t in times if now - t < 3 * H)                                              # the last 3 h in full
    assert 20 <= len([t for t in k if 3 * H <= now - t < 86400]) <= 22                                # then hourly
    assert len(k) < 60 and k[-1] == now


def test_prune_removes_the_unwanted_files(proj):
    d = B.backup_dir(proj); os.makedirs(d); now = 1_800_000_000
    for i in range(6): open(os.path.join(d, 'meta-' + time.strftime(B._STAMP, time.gmtime(now - 10 * 86400 - i * 600)) + '.tar.gz'), 'w').write('x')
    assert len(B.prune(proj, now)) == 5 and len(B.list_backups(proj)) == 1


def test_restore_unpacks_beside_not_over_the_project(proj, tmp_path):
    p = B.backup(proj, now=1_800_000_000); n = B.restore(proj, os.path.basename(p), str(tmp_path / 'out'))
    assert n == 2 and open(tmp_path / 'out' / 'clips' / 'c1' / 'clip.json').read() == '{"a": 1}'


def test_ticker_backs_up_and_survives_errors(proj, monkeypatch):
    t = B.Ticker(lambda: [proj, '/no/such/place'], every=999); t.tick(); assert len(B.list_backups(proj)) == 1
    monkeypatch.setattr(B, 'backup', lambda f: 1 / 0); t.tick()


def test_gpx_tracks_are_always_metadata_whatever_their_size(proj):
    rd = config.race_dir(proj); os.makedirs(os.path.join(rd, 'tracks'))
    for rel in ('track.gpx', 'tracks/t2-run.gpx', 'track.gpx.20260101.replaced'): open(os.path.join(rd, rel), 'wb').write(b'x' * 6_000_000)
    assert {'track.gpx', 'tracks/t2-run.gpx', 'track.gpx.20260101.replaced'} <= {r for r, _ in B.collect(proj)}
