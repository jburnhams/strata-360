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


def test_cuda_decode_is_used_only_when_the_test_decode_says_nothing(monkeypatch):
    """ffmpeg falls back to software and exits 0 when the GPU cannot decode, so any message on stderr (or a missing hwaccel) means no."""
    import subprocess
    from strata360 import hw
    runs = []

    def fake(cmd, **kw):
        runs.append(cmd)
        if '-hwaccel' in cmd: return subprocess.CompletedProcess(cmd, 0, b'', fake.err)
        return subprocess.CompletedProcess(cmd, 0, b'hevc-bytes', b'')
    fake.err = b''
    monkeypatch.setattr(hw.subprocess, 'run', fake); monkeypatch.setattr(hw, '_ffmpeg_list', lambda kind: 'Hardware acceleration methods:\ncuda\nvaapi\n')
    hw._cuda_decode_works.cache_clear(); assert hw._cuda_decode_works() is True
    fake.err = b'cuvidCreateDecoder failed -> CUDA_ERROR_OUT_OF_MEMORY'; hw._cuda_decode_works.cache_clear(); assert hw._cuda_decode_works() is False
    monkeypatch.setattr(hw, '_ffmpeg_list', lambda kind: 'Hardware acceleration methods:\nvaapi\n'); hw._cuda_decode_works.cache_clear(); assert hw._cuda_decode_works() is False
    hw._cuda_decode_works.cache_clear()
