

def test_recordings_are_new_takes_never_overwritten(tmp_path, monkeypatch):
    import os
    from strata360.edit import voiceover as V
    monkeypatch.setattr(V, '_run', lambda cmd: open(cmd[-1], 'wb').write(b'wav'))
    f = str(tmp_path); assert not os.path.exists(V.recorded_path(f, 3))
    a = V.save_recording(f, 3, 'in'); b = V.save_recording(f, 3, 'in'); c = V.save_recording(f, 30, 'in')
    assert a != b and os.path.exists(a) and V.recorded_path(f, 3) == b and V.recorded_path(f, 30) == c
    V.delete_recording(f, 3); assert not os.path.exists(V.recorded_path(f, 3)) and os.path.exists(os.path.join(os.path.dirname(a), 'removed', os.path.basename(a)))
