"""Platform-aware ffmpeg hardware options: decode acceleration and video encoders, chosen from the OS and from what this ffmpeg build offers.

macOS uses VideoToolbox, Windows uses NVENC when the build has it, and everything else (Linux, or anything missing) falls back to software
(libx264 / libx265), so the pipeline runs anywhere ffmpeg does. Overrides: STRATA_ENCODER=software forces software encoding,
STRATA_HWACCEL=none|<ffmpeg hwaccel name> sets the decode acceleration."""
import functools, os, subprocess, sys, time


@functools.lru_cache(maxsize=None)
def _ffmpeg_list(kind):
    try: return subprocess.run(['ffmpeg', '-hide_banner', '-v', 'quiet', f'-{kind}'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError): return ''


def has_encoder(name): return f' {name} ' in _ffmpeg_list('encoders')


def hwaccel_args():
    """Input option for decoding the lens streams: VideoToolbox on macOS, D3D11VA on Windows, otherwise software decode (always works)."""
    want = os.environ.get('STRATA_HWACCEL')
    if want is None: want = {'darwin': 'videotoolbox', 'win32': 'd3d11va'}.get(sys.platform, 'none')       # d3d11va is NVDEC on NVIDIA, and measured 3x faster than software on the 3840x3840 10-bit HEVC lenses
    return [] if want in ('', 'none') else ['-hwaccel', want]


def _hardware(codec):
    """Name of the platform's hardware encoder for 'h264' or 'hevc', or None."""
    if os.environ.get('STRATA_ENCODER') == 'software': return None
    name = {'darwin': f'{codec}_videotoolbox', 'win32': f'{codec}_nvenc'}.get(sys.platform)
    return name if name and has_encoder(name) else None


def h264_args(bitrate):
    """High-profile 8-bit H.264 at about `bitrate` (plays in every browser)."""
    hw = _hardware('h264')
    if hw: return ['-c:v', hw, '-b:v', bitrate, '-profile:v', 'high']
    return ['-c:v', 'libx264', '-preset', 'medium', '-b:v', bitrate, '-profile:v', 'high', '-pix_fmt', 'yuv420p']


def hevc_args(bitrate, main10=False, tag=True):
    """HEVC, 10-bit when `main10`; tagged hvc1 (QuickTime/Safari compatible) unless the caller adds its own tag."""
    t = ['-tag:v', 'hvc1'] if tag else []
    hw = _hardware('hevc')
    if hw: return ['-c:v', hw, '-profile:v', 'main10' if main10 else 'main', '-b:v', bitrate] + t + (['-pix_fmt', 'p010le'] if main10 else [])
    return ['-c:v', 'libx265', '-preset', 'medium', '-b:v', bitrate] + t + ['-pix_fmt', 'yuv420p10le' if main10 else 'yuv420p']


def live_h264_args():
    """Low-latency H.264 for the live preview stream (cheap on the CPU, which the rest of the processing needs)."""
    hw = _hardware('h264')
    if hw and hw.endswith('videotoolbox'): return ['-c:v', hw, '-b:v', '5M', '-realtime', '1']
    if hw: return ['-c:v', hw, '-preset', 'p1', '-b:v', '5M']
    return ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-crf', '26', '-threads', '2']


@functools.lru_cache(maxsize=None)
def _cuda_dll_dirs():
    """Windows: ctranslate2 loads cuBLAS and cuDNN by name; the pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 keep their DLLs under site-packages/nvidia/*/bin, which is on no search path, so add them."""
    if sys.platform != 'win32': return
    import glob, site
    for base in site.getsitepackages():
        for d in glob.glob(os.path.join(base, 'nvidia', '*', 'bin')):
            os.add_dll_directory(d); os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')


def whisper_args():
    """(device, compute_type) for faster-whisper: CUDA with float16 when ctranslate2 sees a GPU (STRATA_GPU=0 forces the CPU), else int8 on the CPU."""
    if os.environ.get('STRATA_GPU') != '0':
        _cuda_dll_dirs()
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0: return 'cuda', 'float16'
        except Exception: pass
    return 'cpu', 'int8'


def default_whisper_model():
    """The Whisper model a NEW project starts with: the full large-v3 where there is a CUDA GPU (on the RTX 5070 Ti it took 17 percent longer than large-v3-turbo on the Legends speech, 63 s against 54 s for 571 s, and reproduced 7 of the 25 Gemini word corrections against 5), else large-v3-turbo (on a CPU
    large-v3 is several times slower). A project keeps what its race.json says; `init --whisper-model` sets it."""
    return 'large-v3' if whisper_args()[0] == 'cuda' else 'large-v3-turbo'


GPU_DUTY = 0.6          # the share of the time a GPU job may keep the GPU busy; the rest is left for the screen (STRATA_GPU_DUTY, 0.1 to 1)


def gpu_device():
    """torch device for the models: the Apple GPU (or CUDA) when there is one, else the CPU. On by default (STRATA_GPU=0 forces the CPU). macOS has no per-process GPU priority, so a GPU job stays polite by
    working in short slices with gaps (`gpu_pause` / `gpu_throttled`, duty STRATA_GPU_DUTY) so the window server always gets its turn; its CPU side runs at the lowest priority as for every worker."""
    if os.environ.get('STRATA_GPU') == '0': return 'cpu'
    try:
        import torch
        if torch.backends.mps.is_available(): return 'mps'
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    except Exception: return 'cpu'


def gpu_duty():
    """The share of the time a GPU job may keep the GPU busy. 0.6 on a Mac, where the same GPU draws the screen and has no priorities; flat out (1.0) on CUDA, where Windows shares the card between processes (the 5070 Ti ran six renders and the desktop at once)."""
    default = 1.0 if gpu_device() == 'cuda' else GPU_DUTY
    try: return min(max(float(os.environ.get('STRATA_GPU_DUTY', default)), 0.1), 1.0)
    except ValueError: return default


def gpu_pause(worked_s, sleep=None):
    """After a slice of GPU work that took `worked_s` seconds, leave the GPU alone for the rest of the duty cycle (worked * (1 - duty) / duty), at most 2 s. Returns the seconds slept."""
    duty = gpu_duty(); gap = 0.0 if duty >= 1.0 else min(max(worked_s, 0.0) * (1.0 - duty) / duty, 2.0)
    if gap > 0: (sleep or time.sleep)(gap)
    return gap


def gpu_throttled(fn, device=None):
    """`fn` (a model's forward or predict) that waits for its GPU work to finish and then pauses for the duty cycle: the GPU is used in slices, never flat out."""
    def run(*a, **k):
        t0 = time.time(); out = fn(*a, **k); dev = device or gpu_device()
        try:
            import torch
            if dev == 'mps': torch.mps.synchronize()
            elif dev == 'cuda': torch.cuda.synchronize()
        except Exception: pass
        if dev != 'cpu': gpu_pause(time.time() - t0)
        return out
    return run


def mbgl_backend():
    """Graphics backend for `mbgl-render` (the 3D flyover): Metal on macOS, OpenGL elsewhere (run on Linux with Mesa under xvfb-run; Windows untried); STRATA_MBGL_BACKEND=metal|opengl|vulkan overrides."""
    return os.environ.get('STRATA_MBGL_BACKEND') or ('metal' if sys.platform == 'darwin' else 'opengl')
