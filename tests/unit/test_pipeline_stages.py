import json
import os
import pytest
from strata360.pipeline import stages

def test_stage_decorator():
    # Verify the decorator registers into STAGES and ORDER

    # Store old state
    old_stages = dict(stages.STAGES)
    old_order = list(stages.ORDER)

    try:
        @stages.stage('test_dummy', 1, keys=('k1',), deps=('d1',), outputs=('out.json',), note='dummy', needs_track=True)
        def my_dummy_stage(ctx):
            pass

        assert 'test_dummy' in stages.STAGES
        assert 'test_dummy' in stages.ORDER

        stg = stages.STAGES['test_dummy']
        assert stg.name == 'test_dummy'
        assert stg.version == 1
        assert stg.fn is my_dummy_stage
        assert stg.keys == ('k1',)
        assert stg.deps == ('d1',)
        assert stg.outputs == ('out.json',)
        assert stg.default is True
        assert stg.note == 'dummy'
        assert stg.needs_track is True

    finally:
        # Restore state
        stages.STAGES.clear()
        stages.STAGES.update(old_stages)
        stages.ORDER.clear()
        stages.ORDER.extend(old_order)

def test_ctx_methods(tmp_path, monkeypatch):
    # Set up fake context
    clip_dir = tmp_path / 'myclip'
    clip_dir.mkdir()

    class DummyClip:
        pass

    cfg = {'some_key': 'val'}
    log = []

    ctx = stages.Ctx(clip=DummyClip(), cfg=cfg, clip_dir=str(clip_dir), log=log)

    # Test path()
    assert ctx.path('test.json') == os.path.join(str(clip_dir), 'test.json')

    # Test write() and read()
    clip_data = {'clip_id': 'c1', 'video': {'source_frames': 100}, 'time': {'start_utc': '2023-10-27T10:00:00Z', 'utc_hash': 'h1'}}
    ctx.write('clip.json', clip_data)
    assert ctx.read('clip.json') == clip_data

    # Test clip_json property
    assert ctx.clip_json == clip_data

    # Test stamped()
    stamped_obj = ctx.stamped({'my_data': 123})
    assert stamped_obj['my_data'] == 123
    assert stamped_obj['clip_id'] == 'c1'
    assert stamped_obj['start_utc'] == '2023-10-27T10:00:00Z'
    assert stamped_obj['utc_hash'] == 'h1'
