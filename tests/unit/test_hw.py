"""Platform-aware ffmpeg options (strata360.hw): hardware where the OS and ffmpeg build offer it, software everywhere else."""
import pytest
from strata360 import hw

ALL = ' h264_videotoolbox  hevc_videotoolbox  h264_nvenc  hevc_nvenc  libx264  libx265 '


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    for k in ('STRATA_ENCODER', 'STRATA_HWACCEL'): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(hw, '_ffmpeg_list', lambda kind: ALL)


def codec(args): return args[args.index('-c:v') + 1]


@pytest.mark.parametrize('platform,h264,hevc', [('darwin', 'h264_videotoolbox', 'hevc_videotoolbox'), ('win32', 'h264_nvenc', 'hevc_nvenc'), ('linux', 'libx264', 'libx265')])
def test_encoder_follows_the_os(monkeypatch, platform, h264, hevc):
    monkeypatch.setattr(hw.sys, 'platform', platform)
    assert codec(hw.h264_args('5M')) == h264 and codec(hw.hevc_args('5M')) == hevc


def test_falls_back_to_software_when_the_build_lacks_the_hardware_encoder(monkeypatch):
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); monkeypatch.setattr(hw, '_ffmpeg_list', lambda kind: ' libx264  libx265 ')
    assert codec(hw.h264_args('5M')) == 'libx264' and codec(hw.hevc_args('5M')) == 'libx265'


def test_software_can_be_forced(monkeypatch):
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); monkeypatch.setenv('STRATA_ENCODER', 'software')
    assert codec(hw.hevc_args('5M')) == 'libx265' and codec(hw.live_h264_args()) == 'libx264'


def test_hevc_is_ten_bit_and_tagged_on_request(monkeypatch):
    for platform, pix in (('darwin', 'p010le'), ('linux', 'yuv420p10le')):
        monkeypatch.setattr(hw.sys, 'platform', platform); a = hw.hevc_args('5M', main10=True)
        assert a[a.index('-pix_fmt') + 1] == pix and a[a.index('-tag:v') + 1] == 'hvc1'
        assert '-tag:v' not in hw.hevc_args('5M', tag=False)


def test_decode_acceleration_only_on_macos_unless_overridden(monkeypatch):
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); assert hw.hwaccel_args() == ['-hwaccel', 'videotoolbox']
    monkeypatch.setattr(hw.sys, 'platform', 'linux'); assert hw.hwaccel_args() == []
    monkeypatch.setenv('STRATA_HWACCEL', 'cuda'); assert hw.hwaccel_args() == ['-hwaccel', 'cuda']
    monkeypatch.setattr(hw.sys, 'platform', 'darwin'); monkeypatch.setenv('STRATA_HWACCEL', 'none'); assert hw.hwaccel_args() == []


def test_gpu_is_opt_in(monkeypatch):
    assert hw.gpu_device() == 'cpu'
