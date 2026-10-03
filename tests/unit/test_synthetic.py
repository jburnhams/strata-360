import pytest
from strata360.edit import synthetic as SY




def test_the_planner_draws_a_big_climb_as_a_flyover_a_short_hop_or_clip_as_a_map_and_alternates_in_between():
    from strata360.edit import synthetic as SY
    big = dict(ascent_m=800, descent_m=300, distance_km=40); mid = dict(ascent_m=300, descent_m=250, distance_km=30); flat = dict(ascent_m=100, descent_m=80, distance_km=30); hop = dict(ascent_m=900, descent_m=900, distance_km=6)
    assert SY.choose_kind(big, 8) == 'flyover' and SY.choose_kind(big, 8, last='flyover') == 'flyover'          # the land is the story: always
    assert SY.choose_kind(big, 4) == 'map' and SY.choose_kind(flat, 10) == 'map' and SY.choose_kind(hop, 10) == 'map'      # too short, too flat, or a short hop
    assert SY.choose_kind(mid, 8) == 'flyover' and SY.choose_kind(mid, 8, last='flyover') == 'map' and SY.choose_kind(mid, 8, last='map') == 'flyover'      # in between: variety
    assert SY.make(dict(id='G01', t0=0.0, t1=3600.0), seconds=8)['by'] == 'planner' and SY.make(dict(id='G01', t0=0.0, t1=3600.0), seconds=8, by='user')['by'] == 'user'


class TestGapSettings:
    def test_settings_are_saved_changed_and_cleared(self, tmp_path, monkeypatch):
        from strata360.pipeline import config
        monkeypatch.setattr(config, 'race_dir', lambda f: str(tmp_path))
        assert SY.gap_settings('f', 'G01') == dict(kind=None, mode=None, seconds=None, must=False)
        assert SY.set_settings('f', 'G01', kind='flyover', mode='min', seconds=8) == dict(kind='flyover', mode='min', seconds=8.0, must=False)
        assert SY.set_settings('f', 'G01', must=True)['mode'] == 'min' and SY.settings('f')['G01']['must'] is True                  # only the fields sent change
        assert SY.set_settings('f', 'G01', mode=None)['seconds'] is None                                                              # no mode, no length
        assert SY.set_settings('f', 'G01', kind=None, must=False) == dict(kind=None, mode=None, seconds=None, must=False) and SY.settings('f') == {}
        doc = SY.load('f'); assert 'settings' not in doc

    def test_what_is_not_allowed_is_refused(self, tmp_path, monkeypatch):
        from strata360.pipeline import config
        monkeypatch.setattr(config, 'race_dir', lambda f: str(tmp_path))
        for bad in (dict(kind='3d'), dict(mode='exactly', seconds=5), dict(mode='set'), dict(mode='set', seconds=1), dict(mode='min', seconds=60), dict(colour='red')):
            with pytest.raises(ValueError): SY.set_settings('f', 'G01', **bad)
        assert SY.settings('f') == {}

    def test_a_clip_saved_later_keeps_the_settings(self, tmp_path, monkeypatch):
        from strata360.pipeline import config
        monkeypatch.setattr(config, 'race_dir', lambda f: str(tmp_path)); SY.set_settings('f', 'G01', must=True)
        gap = dict(id='G01', t0=0.0, t1=7200.0); SY.upsert('f', SY.make(gap, seconds=10)); assert SY.settings('f')['G01']['must'] is True and [c['id'] for c in SY.load('f')['clips']] == ['G01']
