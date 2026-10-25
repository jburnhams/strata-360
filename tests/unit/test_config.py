"""pipeline/config.py: where the wearer's face and voice profiles live (the project folder, with the older repository-level folder still found)."""
import os


def test_the_wearer_profile_is_saved_in_the_project_and_an_older_one_in_the_working_folder_is_still_found(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    rd = str(tmp_path / 'proj'); monkeypatch.chdir(tmp_path); monkeypatch.setattr(C, 'LEGACY_PROFILE_DIRS', ['profiles'])
    assert C.profile_path(rd, {}) == os.path.join(rd, 'profiles', 'me.npz') and C.profile_path(rd, dict(profile='ann'), voice=True) == os.path.join(rd, 'profiles', 'ann_voice.npz')      # none anywhere: where it would be saved
    os.makedirs('profiles'); open('profiles/me.npz', 'w').write('old'); assert C.profile_path(rd, {}) == os.path.abspath('profiles/me.npz')
    os.makedirs(os.path.join(rd, 'profiles')); open(os.path.join(rd, 'profiles', 'me.npz'), 'w').write('new'); assert C.profile_path(rd, {}) == os.path.join(rd, 'profiles', 'me.npz')   # the project's own wins


def _roots(tmp_path, monkeypatch):
    footage = tmp_path / 'footage'; projects = tmp_path / 'projects'; footage.mkdir(); projects.mkdir()
    monkeypatch.setenv('STRATA_FOOTAGE', str(footage)); monkeypatch.setenv('STRATA_PROJECTS', str(projects))
    return footage.resolve(), projects.resolve()


def test_without_a_projects_folder_results_stay_in_the_footage_folder(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    monkeypatch.delenv('STRATA_PROJECTS', raising=False); monkeypatch.delenv('STRATA_FOOTAGE', raising=False)
    assert C.race_dir(str(tmp_path / 'f')) == str(tmp_path / 'f' / 'strata360')


def test_with_a_projects_folder_a_project_is_named_after_its_footage_folder_with_no_strata360_folder(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    footage, projects = _roots(tmp_path, monkeypatch)
    f = footage / '2026 - Race'; f.mkdir()
    assert C.race_dir(str(f)) == str(projects / '2026 - Race')
    assert C.footage_of(C.race_dir(str(f))) == str(f)                                    # and back again
    sub = footage / 'year' / 'race'; sub.mkdir(parents=True)
    assert C.race_dir(str(sub)) == str(projects / 'year' / 'race') and C.footage_of(C.race_dir(str(sub))) == str(sub)


def test_a_folder_outside_the_footage_folder_or_the_footage_folder_itself_is_refused(tmp_path, monkeypatch):
    import pytest
    from strata360.pipeline import config as C
    footage, _ = _roots(tmp_path, monkeypatch)
    with pytest.raises(ValueError): C.race_dir(str(tmp_path / 'elsewhere'))
    with pytest.raises(ValueError): C.race_dir(str(footage))


def test_a_projects_folder_without_a_footage_folder_is_refused(tmp_path, monkeypatch):
    import pytest
    from strata360.pipeline import config as C
    monkeypatch.setenv('STRATA_PROJECTS', str(tmp_path)); monkeypatch.delenv('STRATA_FOOTAGE', raising=False)
    with pytest.raises(ValueError, match='footage'): C.race_dir(str(tmp_path / 'x'))


def test_race_names_go_in_the_projects_folder_too_so_nothing_is_written_in_the_code_folder(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    _, projects = _roots(tmp_path, monkeypatch); monkeypatch.delenv('STRATA_RACES', raising=False)
    assert C.race_dir('belgium') == str(projects / 'belgium')


def test_the_folders_are_read_from_server_json_when_the_environment_has_none(tmp_path, monkeypatch):
    import json
    from strata360.pipeline import config as C
    for v in ('STRATA_FOOTAGE', 'STRATA_PROJECTS'): monkeypatch.delenv(v, raising=False)
    (tmp_path / 'f').mkdir(); (tmp_path / 'p').mkdir(); monkeypatch.setenv('HOME', str(tmp_path / 'home')); os.makedirs(tmp_path / 'home' / '.strata360')
    json.dump(dict(footage=str(tmp_path / 'f'), projects=str(tmp_path / 'p')), open(tmp_path / 'home' / '.strata360' / 'server.json', 'w'))
    assert C.footage_root() == str((tmp_path / 'f').resolve()) and C.projects_root() == str((tmp_path / 'p').resolve())


def test_a_source_file_recorded_elsewhere_is_found_in_the_footage_folder_by_name_even_from_a_windows_path(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    footage, _ = _roots(tmp_path, monkeypatch); C._FOOTAGE_INDEX.clear()
    f = footage / 'race'; (f / 'day1').mkdir(parents=True); (f / 'day1' / 'VID_1.insv').write_text('x')
    rd = C.race_dir(str(f)); os.makedirs(os.path.join(rd, 'clips', 'c')); open(os.path.join(rd, 'race.json'), 'w').write('{}')
    assert C.source('D:\\Insta360\\race\\VID_1.insv', os.path.join(rd, 'clips', 'c')) == str(f / 'day1' / 'VID_1.insv')
    assert C.source('D:\\gone\\nothing.insv', os.path.join(rd, 'clips', 'c')) == 'D:\\gone\\nothing.insv'
