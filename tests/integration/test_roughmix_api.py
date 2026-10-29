"""Test the rough mix HTTP endpoints in server/app.py."""
import json
import os
from strata360.edit import project as PJ
from strata360.edit import roughmix as RM

def test_rough_mix_endpoints_happy_path(served, fake_popen):
    client, folder = served
    # Setup: a plan so we can mix. RM.status requires segments to have length > 0
    edit = PJ.load(folder)
    edit['plan'] = dict(source='script', film=dict(length_s=8.0, music=None), segments=[dict(clip='X', clip_start_s=0.0, dur_s=4.0, role='vo', speech=False)])
    PJ.save(folder, edit)

    # 1. GET status initially
    r = client.get('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    st = r.json()
    assert not st['exists']
    assert not st['building']

    # 2. POST to start
    r = client.post('/api/script2/mix', json=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['started'] is True

    # 3. Job is running in fake_popen
    assert len(fake_popen.instances) == 1
    assert 'rough-mix' in fake_popen.instances[-1].cmd

    # GET status while running
    r = client.get('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['building'] is True

    # POST again while running returns started=False
    r = client.post('/api/script2/mix', json=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['started'] is False
    assert 'already being made' in r.json()['reason']

    # DELETE while running returns 409
    assert client.delete('/api/script2/mix', params=dict(folder=folder)).status_code == 409

    # 4. Job finishes
    fake_popen.instances[-1].returncode = 0

    # Simulate job finishing by creating the output file
    os.makedirs(RM.dir_of(folder), exist_ok=True)
    with open(RM.path_of(folder), 'wb') as f:
        f.write(b'x')
    with open(os.path.join(RM.dir_of(folder), 'mix.json'), 'w') as f:
        json.dump(dict(length_s=8.0, source='script', parts=RM.parts_of(folder, edit['plan'])), f)

    # GET status when done
    r = client.get('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['exists'] is True
    assert r.json()['building'] is False

    # 5. GET audio
    r = client.get('/api/script2/mix/audio', params=dict(folder=folder))
    assert r.status_code == 200
    assert r.content == b'x'

    # 6. DELETE resets
    r = client.delete('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['reset'] is True

    r = client.get('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    assert not r.json()['exists']

def test_rough_mix_endpoints_no_plan(served):
    client, folder = served

    # POST returns started=False when no plan (no segments)
    edit = PJ.load(folder)
    edit['plan'] = dict(source='script', film=dict(length_s=8.0, music=None), segments=[])
    PJ.save(folder, edit)

    r = client.post('/api/script2/mix', json=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['started'] is False
    assert 'no film plan yet' in r.json()['reason']

    # GET audio returns 404 when not made
    assert client.get('/api/script2/mix/audio', params=dict(folder=folder)).status_code == 404

def test_rough_mix_endpoints_job_fails(served, fake_popen):
    client, folder = served
    edit = PJ.load(folder)
    edit['plan'] = dict(source='script', film=dict(length_s=8.0, music=None), segments=[dict(clip='X', clip_start_s=0.0, dur_s=4.0, role='vo', speech=False)])
    PJ.save(folder, edit)

    client.post('/api/script2/mix', json=dict(folder=folder))

    # Simulate job failing and logging
    os.makedirs(RM.dir_of(folder), exist_ok=True)
    with open(os.path.join(RM.dir_of(folder), 'mix.log'), 'w') as f:
        f.write('error something broke')
    fake_popen.instances[-1].returncode = 1

    r = client.get('/api/script2/mix', params=dict(folder=folder))
    assert r.status_code == 200
    assert r.json()['building'] is False
    assert r.json()['error'] == 'error something broke'
