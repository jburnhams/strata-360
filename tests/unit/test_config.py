"""pipeline/config.py: where the wearer's face and voice profiles live (the project folder, with the older repository-level folder still found)."""
import os


def test_the_wearer_profile_is_saved_in_the_project_and_an_older_one_in_the_working_folder_is_still_found(tmp_path, monkeypatch):
    from strata360.pipeline import config as C
    rd = str(tmp_path / 'proj'); monkeypatch.chdir(tmp_path); monkeypatch.setattr(C, 'LEGACY_PROFILE_DIRS', ['profiles'])
    assert C.profile_path(rd, {}) == os.path.join(rd, 'profiles', 'me.npz') and C.profile_path(rd, dict(profile='ann'), voice=True) == os.path.join(rd, 'profiles', 'ann_voice.npz')      # none anywhere: where it would be saved
    os.makedirs('profiles'); open('profiles/me.npz', 'w').write('old'); assert C.profile_path(rd, {}) == os.path.abspath('profiles/me.npz')
    os.makedirs(os.path.join(rd, 'profiles')); open(os.path.join(rd, 'profiles', 'me.npz'), 'w').write('new'); assert C.profile_path(rd, {}) == os.path.join(rd, 'profiles', 'me.npz')   # the project's own wins
