"""Support for rendering on Windows with several processes: seam solver speed-up, piece claims, worker count, source path lookup, Whisper device, big pipes."""
import os, subprocess, sys
import numpy as np
import pytest
from strata360 import hw, oslib
from strata360.pipeline import config
from strata360.render import final as FN, seam as SM


def test_compiled_seam_solver_gives_the_same_path_as_the_numpy_one():
    pytest.importorskip('numba')
    rng = np.random.default_rng(3)
    for _ in range(3):
        cost = rng.random((97, 256)).astype(np.float32) * 3; cost[rng.random(cost.shape) < 0.03] = SM.FORBIDDEN
        assert (SM.solve_dp(cost) == SM.solve_dp_numpy(cost)).all()


def test_a_claimed_piece_is_left_alone_until_its_process_is_gone(tmp_path, monkeypatch):
    f = str(tmp_path / 'p0.mov.claim')
    assert FN._claim(f) and open(f).read() == str(os.getpid())
    assert not FN._claim(f)                                                       # held by a live process (this one)
    monkeypatch.setattr(oslib, 'pid_alive', lambda pid: False)
    assert FN._claim(f)                                                           # its owner died: taken over


def test_worker_count_follows_the_environment_then_the_machine(monkeypatch):
    monkeypatch.setattr(FN, 'vram_workers', lambda w, h: None)
    monkeypatch.setenv('STRATA_RENDER_WORKERS', '3'); assert FN.render_workers() == 3
    monkeypatch.setenv('STRATA_RENDER_WORKERS', '0'); assert FN.render_workers() == 1
    monkeypatch.delenv('STRATA_RENDER_WORKERS'); monkeypatch.setattr(sys, 'platform', 'darwin'); assert FN.render_workers() == 1
    monkeypatch.setattr(sys, 'platform', 'win32'); monkeypatch.setattr(os, 'cpu_count', lambda: 32)
    from strata360.pipeline import resources as RS
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 64.0); assert FN.render_workers() == 6
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 12.0); assert FN.render_workers() == 2
    monkeypatch.setattr(os, 'cpu_count', lambda: 4); assert FN.render_workers() == 1


def test_a_source_recorded_on_another_machine_is_found_beside_the_project(tmp_path):
    proj = tmp_path / 'Legends'; clip = proj / 'strata360' / 'clips' / 'c1'; clip.mkdir(parents=True); (proj / 'CAM_1.OSV').write_bytes(b'x')
    assert config.source('/Volumes/Expansion/Legends/CAM_1.OSV', clip) == str(proj / 'CAM_1.OSV')
    here = tmp_path / 'there.osv'; here.write_bytes(b'x'); assert config.source(str(here), clip) == str(here)               # a path that exists is kept
    assert config.source('/Volumes/x/CAM_2.OSV', clip) == '/Volumes/x/CAM_2.OSV' and config.source(None, clip) is None        # not found: unchanged


def test_a_library_recorded_on_another_machine_is_the_folder_the_project_sits_in(tmp_path):
    proj = tmp_path / 'Legends'; config.save(str(proj), dict(name='x', library='/Volumes/Expansion/Legends', stages=['ingest']))
    assert config.load(str(proj))['library'] == str(proj)
    config.save(str(proj), dict(name='x', library=str(tmp_path), stages=['ingest'])); assert config.load(str(proj))['library'] == str(tmp_path)          # one that exists is kept


def test_whisper_uses_the_gpu_when_ctranslate2_sees_one(monkeypatch):
    import types
    fake = types.SimpleNamespace(get_cuda_device_count=lambda: 1); monkeypatch.setitem(sys.modules, 'ctranslate2', fake)
    monkeypatch.delenv('STRATA_GPU', raising=False); monkeypatch.setattr(hw, '_cuda_dll_dirs', lambda: None)
    assert hw.whisper_args() == ('cuda', 'float16')
    monkeypatch.setenv('STRATA_GPU', '0'); assert hw.whisper_args() == ('cpu', 'int8')
    monkeypatch.delenv('STRATA_GPU'); fake.get_cuda_device_count = lambda: 0; assert hw.whisper_args() == ('cpu', 'int8')


def test_windows_decodes_with_d3d11va_unless_told_otherwise(monkeypatch):
    monkeypatch.delenv('STRATA_HWACCEL', raising=False); monkeypatch.setattr(sys, 'platform', 'win32')
    assert hw.hwaccel_args() == ['-hwaccel', 'd3d11va']
    monkeypatch.setenv('STRATA_HWACCEL', 'none'); assert hw.hwaccel_args() == []


@pytest.mark.skipif(sys.platform != 'win32', reason='named pipes are the Windows way round the 4 KB anonymous pipe')
def test_big_pipe_carries_a_large_frame_both_ways():
    data = os.urandom(20 << 20)
    code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"                      # echoes stdin to stdout
    rf, cfd_out = oslib.big_pipe(True); wf, cfd_in = oslib.big_pipe(False)
    p = subprocess.Popen([sys.executable, '-c', code], stdout=cfd_out, stdin=cfd_in); os.close(cfd_out); os.close(cfd_in)
    import threading
    t = threading.Thread(target=lambda: (wf.write(data), wf.close())); t.start()
    got = rf.read(len(data)); t.join(); p.wait(); rf.close()
    assert got == data


def test_worker_count_is_capped_by_the_free_gpu_memory(monkeypatch):
    import types
    from strata360.render import gpu
    monkeypatch.delenv('STRATA_RENDER_WORKERS', raising=False); monkeypatch.setattr(sys, 'platform', 'win32'); monkeypatch.setattr(os, 'cpu_count', lambda: 32); monkeypatch.setattr(gpu, 'available', lambda: True)
    from strata360.pipeline import resources as RS
    monkeypatch.setattr(RS, 'mem_total_gb', lambda: 64.0); torch = pytest.importorskip('torch')
    monkeypatch.setattr(torch.cuda, 'mem_get_info', lambda: (15.7e9, 16e9))
    assert FN.render_workers((3840, 2160)) == 2 and FN.render_workers((1920, 1080)) == 6
    monkeypatch.setattr(gpu, 'available', lambda: False); assert FN.vram_workers(3840, 2160) is None and FN.render_workers((3840, 2160)) == 6
