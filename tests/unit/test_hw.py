"""Platform-aware ffmpeg options (strata360.hw): hardware where the OS and ffmpeg build offer it, software everywhere else."""
import pytest
from strata360 import hw

ALL = ' h264_videotoolbox  hevc_videotoolbox  h264_nvenc  hevc_nvenc  libx264  libx265 '


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    for k in ('STRATA_ENCODER', 'STRATA_HWACCEL'): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(hw, '_ffmpeg_list', lambda kind: ALL)
    monkeypatch.setattr(hw, '_encoder_works', lambda name: True)                      # the test encode is covered in test_hw_probe


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


def test_gpu_is_on_by_default_and_the_duty_cycle_leaves_gaps(monkeypatch):
    monkeypatch.setenv('STRATA_GPU', '0'); assert hw.gpu_device() == 'cpu'                                   # the opt-out
    monkeypatch.delenv('STRATA_GPU', raising=False); monkeypatch.setenv('STRATA_GPU_DUTY', '0.5'); slept = []
    assert hw.gpu_pause(1.0, sleep=slept.append) == 1.0 and slept == [1.0]                                    # busy half the time: a gap as long as the work
    assert hw.gpu_pause(10.0, sleep=slept.append) == 2.0                                                      # but never more than 2 s
    monkeypatch.setenv('STRATA_GPU_DUTY', '1'); assert hw.gpu_pause(5.0, sleep=slept.append) == 0.0           # flat out when asked
    calls = []; monkeypatch.setenv('STRATA_GPU_DUTY', '0.5'); monkeypatch.setattr(hw.time, 'sleep', calls.append)
    f = hw.gpu_throttled(lambda x: x + 1, device='mps'); assert f(1) == 2 and len(calls) == 1                # a throttled call returns its result and pauses once


def test_a_radeon_780m_gets_the_gfx1100_override_unless_the_user_set_one(tmp_path, monkeypatch):
    import strata360
    node = tmp_path / '1'; node.mkdir(); (node / 'properties').write_text('vendor_id 4098\ngfx_target_version 110003\n')
    monkeypatch.delenv('HSA_OVERRIDE_GFX_VERSION', raising=False)
    assert strata360.amd_env(str(tmp_path)) == {'HSA_OVERRIDE_GFX_VERSION': '11.0.0'} and strata360.amd_env(str(tmp_path / 'none')) == {}
    (node / 'properties').write_text('vendor_id 4098\ngfx_target_version 110000\n'); assert strata360.amd_env(str(tmp_path)) == {}              # gfx1100 has kernels of its own
    (node / 'properties').write_text('vendor_id 4098\ngfx_target_version 110003\n'); monkeypatch.setenv('HSA_OVERRIDE_GFX_VERSION', '10.3.0'); assert strata360.amd_env(str(tmp_path)) == {}


def test_an_amd_gpu_is_throttled_like_a_shared_screen_gpu_not_run_flat_out(monkeypatch):
    monkeypatch.delenv('STRATA_GPU_DUTY', raising=False); monkeypatch.setattr(hw, 'gpu_device', lambda: 'cuda')
    monkeypatch.setattr(hw, 'gpu_is_amd', lambda: False); assert hw.gpu_duty() == 1.0
    monkeypatch.setattr(hw, 'gpu_is_amd', lambda: True); assert hw.gpu_duty() == hw.GPU_DUTY
