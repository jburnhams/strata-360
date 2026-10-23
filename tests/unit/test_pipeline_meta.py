import datetime as dt
import json
import os
import pytest
from strata360.pipeline import meta, config

def test_path(tmp_path):
    assert meta._path(tmp_path) == os.path.join(config.race_dir(tmp_path), 'project.json')

def test_default_title():
    assert meta.default_title('/tmp/2023-10-27-My Race') == 'My Race'
    assert meta.default_title('/tmp/2023-10-27 - My Race') == 'My Race'
    assert meta.default_title('/tmp/My Race') == 'My Race'
    assert meta.default_title('/tmp/') == 'tmp'
    assert meta.default_title('/tmp/2023-10-27 ') is None

def test_earliest_capture(tmp_path):
    assert meta.earliest_capture(tmp_path) == (None, None)

    # Missing clip folder
    (tmp_path / 'strata360').mkdir()

    # Write a clip with a start time
    clip_dir = tmp_path / 'strata360' / 'clips' / 'CAM_A'
    clip_dir.mkdir(parents=True)
    with open(clip_dir / 'clip.json', 'w') as f:
        json.dump({'time': {'start_utc': '2023-10-27T10:00:00Z'}}, f)

    date, iso = meta.earliest_capture(tmp_path)
    assert date == '2023-10-27'
    assert iso == '2023-10-27T10:00:00Z'

    # Write an older clip
    clip_dir2 = tmp_path / 'strata360' / 'clips' / 'CAM_B'
    clip_dir2.mkdir(parents=True)
    with open(clip_dir2 / 'clip.json', 'w') as f:
        json.dump({'time': {'start_utc': '2023-10-27T09:00:00Z'}}, f)

    date, iso = meta.earliest_capture(tmp_path)
    assert iso == '2023-10-27T09:00:00Z'

    # Write a bad clip
    clip_dir3 = tmp_path / 'strata360' / 'clips' / 'CAM_C'
    clip_dir3.mkdir(parents=True)
    with open(clip_dir3 / 'clip.json', 'w') as f:
        f.write("not json")

    date, iso = meta.earliest_capture(tmp_path)
    assert iso == '2023-10-27T09:00:00Z'

def test_load_empty(tmp_path):
    res = meta.load(tmp_path)
    assert res['title'] is None
    assert res['date'] is None
    assert res['distance_km'] is None
    assert res['results'] == {'starters': None, 'finishers': None, 'finished': None, 'position': None}
    assert res['effective']['title'] == tmp_path.name
    assert res['effective']['date'] is None

def test_load_and_save(tmp_path):
    res = meta.save(tmp_path, {'title': 'The Great Race', 'date': '2023-10-27', 'distance_km': 10.5, 'results': {'starters': 100, 'finishers': 90, 'finished': True, 'position': 10}})
    assert res['title'] == 'The Great Race'
    assert res['date'] == '2023-10-27'
    assert res['distance_km'] == 10.5
    assert res['results']['starters'] == 100
    assert res['results']['finishers'] == 90
    assert res['results']['finished'] is True
    assert res['results']['position'] == 10

    # Load reads it back
    res2 = meta.load(tmp_path)
    assert res == res2

def test_save_constraints(tmp_path):
    with pytest.raises(ValueError, match="distance_km must be between 0 and 5000"):
        meta.save(tmp_path, {'distance_km': 6000})
    with pytest.raises(ValueError, match="distance_km must be between 0 and 5000"):
        meta.save(tmp_path, {'distance_km': -1})
    with pytest.raises(ValueError, match="date must be YYYY-MM-DD"):
        meta.save(tmp_path, {'date': '2023/10/27'})
    with pytest.raises(ValueError, match="starters must be 1 or more"):
        meta.save(tmp_path, {'results': {'starters': 0}})
    with pytest.raises(ValueError, match="finishers cannot exceed starters"):
        meta.save(tmp_path, {'results': {'starters': 10, 'finishers': 20}})
    with pytest.raises(ValueError, match="finishing position cannot be worse than the number of finishers"):
        meta.save(tmp_path, {'results': {'starters': 20, 'finishers': 10, 'position': 15}})

    # Removing optional fields
    meta.save(tmp_path, {'distance_km': 10, 'date': '2023-10-27'})
    res = meta.save(tmp_path, {'distance_km': '', 'date': ''})
    assert res['distance_km'] is None
    assert res['date'] is None

def test_save_dnf_position(tmp_path):
    res = meta.save(tmp_path, {'results': {'finished': False, 'position': 1}})
    assert res['results']['position'] is None

def test_describe(tmp_path):
    assert f"Title: {tmp_path.name}." in meta.describe(tmp_path)
    meta.save(tmp_path, {'title': 'The Great Race', 'date': '2023-10-27', 'distance_km': 10.5, 'results': {'starters': 100, 'finishers': 90, 'finished': True, 'position': 10}})
    desc = meta.describe(tmp_path)
    assert "Title: The Great Race." in desc
    assert "Date: 2023-10-27." in desc
    assert "Official race distance: 10.5 km" in desc
    assert "100 runners started and 90 finished." in desc
    assert "The runner finished, in position 10." in desc

def test_describe_dnf(tmp_path):
    meta.save(tmp_path, {'title': 'The Great Race', 'results': {'starters': 100, 'finished': False}})
    desc = meta.describe(tmp_path)
    assert "100 runners started." in desc
    assert "The runner did not finish (DNF)." in desc
