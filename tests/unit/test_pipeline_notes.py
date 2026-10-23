import json
import os
import pytest
from strata360.pipeline import notes, config

def test_path(tmp_path):
    assert notes._path(tmp_path) == os.path.join(config.race_dir(tmp_path), 'notes.json')

def test_load_empty_or_invalid(tmp_path):
    # Empty
    res = notes.load(tmp_path)
    assert res['folder'] == ''
    assert res['clips'] == {}
    assert res['updated'] == {}
    assert res['vo_must'] == {'folder': '', 'folder_ordered': True, 'clips': {}}

    # Invalid JSON
    os.makedirs(config.race_dir(tmp_path))
    with open(notes._path(tmp_path), 'w') as f:
        f.write("not json")
    res2 = notes.load(tmp_path)
    assert res2 == res

    # Partial JSON gets defaults filled
    with open(notes._path(tmp_path), 'w') as f:
        json.dump({'clips': {'CAM_A': 'nice'}}, f)
    res3 = notes.load(tmp_path)
    assert res3['clips'] == {'CAM_A': 'nice'}
    assert res3['folder'] == ''
    assert res3['vo_must'] == {'folder': '', 'folder_ordered': True, 'clips': {}}

def test_save(tmp_path):
    # Save folder note
    res = notes.save(tmp_path, 'What a race!')
    assert res['folder'] == 'What a race!'
    assert 'folder' in res['updated']

    # Save clip note
    res2 = notes.save(tmp_path, 'Cool scenery here', clip='CAM_A')
    assert res2['clips']['CAM_A'] == 'Cool scenery here'
    assert 'CAM_A' in res2['updated']

    # Remove clip note (empty text)
    res3 = notes.save(tmp_path, '   ', clip='CAM_A')
    assert 'CAM_A' not in res3['clips']
    assert 'CAM_A' not in res3['updated']

    # Very long text gets truncated
    long_text = "A" * 30000
    res4 = notes.save(tmp_path, long_text)
    assert len(res4['folder']) == 20000

def test_save_vo(tmp_path):
    # Save folder VO
    res = notes.save_vo(tmp_path, 'Must say this.')
    assert res['vo_must']['folder'] == 'Must say this.'
    assert res['vo_must']['folder_ordered'] is True

    # Save folder VO with ordered flag
    res2 = notes.save_vo(tmp_path, 'Must say this 2.', ordered=False)
    assert res2['vo_must']['folder'] == 'Must say this 2.'
    assert res2['vo_must']['folder_ordered'] is False

    # Save clip VO
    res3 = notes.save_vo(tmp_path, 'Watch this part!', clip='CAM_B')
    assert res3['vo_must']['clips']['CAM_B'] == 'Watch this part!'

    # Remove clip VO
    res4 = notes.save_vo(tmp_path, '', clip='CAM_B')
    assert 'CAM_B' not in res4['vo_must']['clips']
