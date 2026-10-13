"""A hardware encoder is used only when a test encode works, not merely when ffmpeg lists it."""
import subprocess
from strata360 import hw


def test_listed_but_unusable_nvenc_falls_back_to_software(monkeypatch):
    monkeypatch.delenv('STRATA_ENCODER', raising=False); monkeypatch.setattr(hw.sys, 'platform', 'win32')
    monkeypatch.setattr(hw, 'has_encoder', lambda n: True); hw._encoder_works.cache_clear()
    monkeypatch.setattr(hw.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, b'', b'no device'))
    assert hw.h264_args('8M')[1] == 'libx264'
    hw._encoder_works.cache_clear()
    monkeypatch.setattr(hw.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, b'', b''))
    assert hw.h264_args('8M')[1] == 'h264_nvenc'
    hw._encoder_works.cache_clear()
