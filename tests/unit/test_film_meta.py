"""Film details in project.json: the official race distance feeds the script writer's facts."""
import pytest
from strata360.pipeline import meta as M


def test_the_race_distance_is_saved_validated_and_described(project):
    f = project.folder; assert M.load(f)['distance_km'] is None and 'distance' not in M.describe(f)
    assert M.save(f, dict(distance_km=350))['distance_km'] == 350.0 and 'Official race distance: 350 km' in M.describe(f)
    assert M.save(f, dict(distance_km=''))['distance_km'] is None
    for bad in (0, -5, 10000):
        with pytest.raises(ValueError): M.save(f, dict(distance_km=bad))
