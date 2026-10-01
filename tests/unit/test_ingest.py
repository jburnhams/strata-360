import pytest
import numpy as np
from strata360.pipeline.ingest import utc_hash, check_header, stamp, ingest_clip

class MockClip:
    def __init__(self, clip_id, osv, lrf, size, filename_time=None, fingerprint='fp1'):
        self.id = clip_id
        self.osv = osv
        self.lrf = lrf
        self.size = size
        self.filename_time = filename_time
        self.fingerprint = fingerprint

class TestIngestClip:
    @pytest.fixture
    def mock_dependencies(self, monkeypatch):
        # Mock _probe
        def mock_probe(path):
            return {
                'format': {
                    'tags': {'creation_time': '2023-01-01T12:00:00.000000Z'}
                },
                'streams': [
                    {'codec_type': 'video', 'codec_name': 'hevc', 'width': 1920, 'height': 1080, 'pix_fmt': 'yuvj420p'},
                    {'codec_type': 'video', 'codec_name': 'hevc', 'width': 1920, 'height': 1080, 'pix_fmt': 'yuvj420p'},
                    {'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2, 'sample_rate': 48000}
                ]
            }
        monkeypatch.setattr('strata360.pipeline.ingest._probe', mock_probe)

        # Mock video_sample_times
        monkeypatch.setattr('strata360.pipeline.ingest.video_sample_times', lambda p: np.array([0.0, 0.033, 0.066]))

        # Mock frame_gaps
        # returns gaps (empty here), nominal frame duration
        monkeypatch.setattr('strata360.pipeline.ingest.frame_gaps', lambda pts: ([], 0.03333333))

        # Mock header
        def mock_header(path):
            return {
                'device': 'Camera X',
                'serial': '12345',
                'firmware': '1.0.0',
                'proto': 'v1',
                'colour_mode': 'normal',
                'colour_mode_raw': 0,
                'calibration_slots': 1
            }
        monkeypatch.setattr('strata360.pipeline.ingest.header', mock_header)

    def test_ingest_clip_happy_path(self, mock_dependencies):
        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000, filename_time='2023-01-01T12:00:01')
        cfg = {'camera_clock': {'verified': True, 'utc_offset_hours': 1.0}}

        res = ingest_clip(clip, cfg)

        assert res['schema_version'] == 1
        assert res['clip_id'] == 'clip1'
        assert res['fingerprint'] == 'fp1'
        assert res['camera']['model'] == 'Camera X'
        assert res['video']['streams'] == 2
        assert res['audio']['present'] is True

        # '2023-01-01T12:00:00Z' minus 1 hour offset => '2023-01-01T11:00:00Z'
        assert res['time']['start_utc'] == '2023-01-01T11:00:00Z'
        assert res['time']['utc_status'] == 'definitive'
        assert res['time']['utc_source'] == 'container_creation_time'
        assert 'expected two HEVC lens streams' not in str(res['notes'])

    def test_ingest_clip_drift(self, mock_dependencies):
        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000)
        cfg = {
            'camera_clock': {
                'verified': True,
                'drift_s_per_day': 86400, # 1 day drift per day (extreme to test easily)
                'drift_ref_camera_time': '2022-12-31T12:00:00Z' # 1 day before creation
            }
        }
        # Creation time is '2023-01-01T12:00:00.000000Z'
        # difference from ref is 1 day. drift is 86400s -> offset becomes 1 day.
        # start = creation - offset -> '2022-12-31T12:00:00Z'
        res = ingest_clip(clip, cfg)
        assert res['time']['start_utc'] == '2022-12-31T12:00:00Z'

    def test_ingest_clip_filename_fallback(self, mock_dependencies, monkeypatch):
        # Override probe to remove creation_time
        def mock_probe(path):
            return {
                'format': {'tags': {}},
                'streams': [
                    {'codec_type': 'video', 'codec_name': 'hevc', 'width': 1920, 'height': 1080},
                    {'codec_type': 'video', 'codec_name': 'hevc', 'width': 1920, 'height': 1080}
                ]
            }
        monkeypatch.setattr('strata360.pipeline.ingest._probe', mock_probe)

        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000, filename_time='2023-01-01T15:00:00')
        cfg = {'camera_clock': {'verified': True}}

        res = ingest_clip(clip, cfg)

        assert res['time']['start_utc'] == '2023-01-01T15:00:00Z'
        assert res['time']['utc_source'] == 'filename'
        assert any('container has no creation_time' in note for note in res['notes'])
        assert res['time']['utc_status'] == 'definitive'

    def test_ingest_clip_no_time_source(self, mock_dependencies, monkeypatch):
        def mock_probe(path):
            return {'format': {'tags': {}}, 'streams': []}
        monkeypatch.setattr('strata360.pipeline.ingest._probe', mock_probe)

        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000, filename_time=None)
        cfg = {'camera_clock': {}}

        res = ingest_clip(clip, cfg)

        assert res['time']['start_utc'] is None
        assert res['time']['utc_source'] == 'none'
        assert any('no time source found' in note for note in res['notes'])

    def test_ingest_clip_disagreement(self, mock_dependencies):
        # creation time is 12:00:00
        # filename time is 12:00:05 (5 seconds diff) -> disagreement > 3.0s
        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000, filename_time='2023-01-01T12:00:05')
        cfg = {'camera_clock': {'verified': True}}

        res = ingest_clip(clip, cfg)

        assert res['time']['utc_status'] == 'provisional'
        assert any('container time and file name disagree by 5 s' in note for note in res['notes'])

    def test_ingest_clip_not_verified(self, mock_dependencies):
        clip = MockClip('clip1', 'test.mp4', 'test.lrf', 1000, filename_time='2023-01-01T12:00:00')
        cfg = {'camera_clock': {'verified': False}}

        res = ingest_clip(clip, cfg)

        assert res['time']['utc_status'] == 'provisional'
        assert any('camera clock not verified' in note for note in res['notes'])


class TestUtcHash:
    def test_utc_hash_deterministic(self):
        hash1 = utc_hash('clip1', '2023-01-01T12:00:00Z', '2023-01-01T12:01:00Z')
        hash2 = utc_hash('clip1', '2023-01-01T12:00:00Z', '2023-01-01T12:01:00Z')
        assert hash1 == hash2
        assert len(hash1) == 12

    def test_utc_hash_changes_with_inputs(self):
        hash_base = utc_hash('clip1', '2023-01-01T12:00:00Z', '2023-01-01T12:01:00Z')
        assert hash_base != utc_hash('clip2', '2023-01-01T12:00:00Z', '2023-01-01T12:01:00Z')
        assert hash_base != utc_hash('clip1', '2023-01-01T12:00:01Z', '2023-01-01T12:01:00Z')
        assert hash_base != utc_hash('clip1', '2023-01-01T12:00:00Z', '2023-01-01T12:01:01Z')

class TestCheckHeader:
    def test_check_header_valid(self):
        clip_json = {'clip_id': 'clip1', 'time': {'utc_hash': 'abcdef123456'}}
        artefact = {'clip_id': 'clip1', 'utc_hash': 'abcdef123456', 'data': 123}
        # Should not raise an exception
        check_header(clip_json, artefact)

    def test_check_header_mismatch_clip_id(self):
        clip_json = {'clip_id': 'clip1', 'time': {'utc_hash': 'abcdef123456'}}
        artefact = {'clip_id': 'clip2', 'utc_hash': 'abcdef123456', 'data': 123}
        with pytest.raises(ValueError, match="stale artefact for clip1: header clip2/abcdef123456 != clip.json abcdef123456"):
            check_header(clip_json, artefact)

    def test_check_header_mismatch_hash(self):
        clip_json = {'clip_id': 'clip1', 'time': {'utc_hash': 'abcdef123456'}}
        artefact = {'clip_id': 'clip1', 'utc_hash': '000000000000', 'data': 123}
        with pytest.raises(ValueError, match="stale artefact for clip1: header clip1/000000000000 != clip.json abcdef123456"):
            check_header(clip_json, artefact)

    def test_check_header_missing_keys(self):
        clip_json = {'clip_id': 'clip1', 'time': {'utc_hash': 'abcdef123456'}}
        artefact = {'data': 123}
        with pytest.raises(ValueError, match="stale artefact for clip1: header None/None != clip.json abcdef123456"):
            check_header(clip_json, artefact)

class TestStamp:
    def test_stamp_adds_fields(self):
        clip_json = {
            'clip_id': 'clip1',
            'time': {'start_utc': '2023-01-01T12:00:00Z', 'utc_hash': 'abcdef123456'}
        }
        artefact = {'data': 123}
        stamped = stamp(clip_json, artefact)

        # artefact should not be modified in place (stamp creates a copy)
        assert 'clip_id' not in artefact

        assert stamped['clip_id'] == 'clip1'
        assert stamped['start_utc'] == '2023-01-01T12:00:00Z'
        assert stamped['utc_hash'] == 'abcdef123456'
        assert stamped['data'] == 123

class TestRestamp:
    def test_restamp_updates_valid_artefacts(self, tmp_path):
        import json
        from strata360.pipeline.ingest import restamp

        # Setup fake clip dir
        clip_dir = tmp_path / 'clip1'
        clip_dir.mkdir()

        # Write clip.json with new times
        clip_json_path = clip_dir / 'clip.json'
        new_time = {'time': {'start_utc': '2023-02-02T12:00:00Z', 'utc_hash': 'newhash123'}}
        with open(clip_json_path, 'w') as f:
            json.dump(new_time, f)

        # Write an artefact that should be updated
        artefact_path = clip_dir / 'some_data.json'
        with open(artefact_path, 'w') as f:
            json.dump({'utc_hash': 'oldhash123', 'start_utc': 'oldtime', 'other': 'data'}, f)

        # Write an artefact that should NOT be updated (missing utc_hash)
        skip_path = clip_dir / 'skip_me.json'
        with open(skip_path, 'w') as f:
            json.dump({'other': 'data'}, f)

        # Write an artefact that is invalid json
        invalid_path = clip_dir / 'invalid.json'
        with open(invalid_path, 'w') as f:
            f.write('not json')

        # Write stages.json which should be ignored
        stages_path = clip_dir / 'stages.json'
        with open(stages_path, 'w') as f:
            json.dump({'utc_hash': 'oldhash123'}, f)

        # Call restamp
        count = restamp(str(clip_dir))

        assert count == 1

        # Verify the artefact was updated
        with open(artefact_path, 'r') as f:
            updated = json.load(f)
        assert updated['utc_hash'] == 'newhash123'
        assert updated['start_utc'] == '2023-02-02T12:00:00Z'
        assert updated['other'] == 'data'

        # Verify others were ignored
        with open(skip_path, 'r') as f:
            skipped = json.load(f)
        assert 'utc_hash' not in skipped

        with open(stages_path, 'r') as f:
            stages = json.load(f)
        assert stages['utc_hash'] == 'oldhash123'
