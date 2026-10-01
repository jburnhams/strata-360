"""Platform-aware ffmpeg hardware options: decode acceleration and video encoders, chosen from the OS and from what this ffmpeg build offers.

macOS uses VideoToolbox, Windows uses NVENC when the build has it, and everything else (Linux, or anything missing) falls back to software
(libx264 / libx265), so the pipeline runs anywhere ffmpeg does. Overrides: STRATA_ENCODER=software forces software encoding,
STRATA_HWACCEL=none|<ffmpeg hwaccel name> sets the decode acceleration."""
import functools, os, subprocess, sys


@functools.lru_cache(maxsize=None)
def _ffmpeg_list(kind):
    try: return subprocess.run(['ffmpeg', '-hide_banner', '-v', 'quiet', f'-{kind}'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError): return ''


def has_encoder(name): return f' {name} ' in _ffmpeg_list('encoders')


def hwaccel_args():
    """Input option for decoding the lens streams: VideoToolbox on macOS, otherwise software decode (always works)."""
    want = os.environ.get('STRATA_HWACCEL')
    if want is None: want = 'videotoolbox' if sys.platform == 'darwin' else 'none'
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


def gpu_device():
    """torch device for optional GPU use (STRATA_GPU=1): Apple GPU, CUDA, else CPU."""
    if os.environ.get('STRATA_GPU') != '1': return 'cpu'
    import torch
    if torch.backends.mps.is_available(): return 'mps'
    return 'cuda' if torch.cuda.is_available() else 'cpu'
