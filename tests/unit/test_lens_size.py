"""The lens picture size comes from the video itself (osv/source.py), so every stage works at the camera's native size."""
import json, subprocess
from strata360.osv import source


def test_lens_size_is_the_width_of_the_lens_video(monkeypatch):
    seen = []
    monkeypatch.setattr(source.subprocess if hasattr(source, 'subprocess') else subprocess, 'check_output', lambda cmd, **k: seen.append(cmd) or json.dumps(dict(streams=[dict(width=2880)])).encode())
    source.lens_size.cache_clear(); assert source.lens_size('clip_a.osv') == 2880 and source.lens_size('clip_a.osv') == 2880     # asked once, then remembered
    assert len(seen) == 1 and seen[0][-1].endswith('clip_a.osv')
    source.lens_size.cache_clear()
