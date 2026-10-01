"""Keep the machine usable while the pipeline works.

Rules (all applied by every worker, whoever started it):
  * a worker runs at the lowest CPU priority (nice 19) and, on macOS, in the *background* task class (throttled CPU, disk and network), and with few threads; its child processes
    (ffmpeg, model processes) inherit that;
  * only ONE worker runs unless there is plenty of free memory (default: at least 12 GB available for each extra worker) and the machine is not busy;
  * before starting an item a worker checks the memory that stage needs and waits while there is not enough, or while the machine is busy;
  * the heavy stages (the vision model, detectors, proxy rendering, speech recognition) never run twice at the same time: parallelism is only across different stages;
  * models use the GPU where it pays (STRATA_GPU=0 forces the CPU), in short slices with gaps (hw.gpu_throttled, duty STRATA_GPU_DUTY) so the screen stays responsive: macOS has no per-process GPU priority.
The numbers can be changed in race.json under `resources`; STRATA_NO_RESOURCE_LIMITS=1 turns the waiting off (the integration tests set it: a CI runner with little free memory would otherwise wait for ever)."""
import ctypes, ctypes.util, os, re, subprocess, sys, time
from strata360 import oslib

DEFAULTS = dict(max_workers=2, extra_worker_free_gb=12.0, reserve_gb=2.0, busy_load_fraction=0.6, threads=2)

# Approximate peak memory of each stage (GB) and how many may run at once (heavy stages: one).
STAGE_MEM_GB = dict(proxy=2.5, people=4.0, scenes=6.0, speakers=3.0, transcribe=4.0, align=2.0, exposure=2.0, audio=1.5, preview=1.0, thumb=1.5, thumb_best=1.5, motion=0.5, ingest=0.5,
                    places=0.3, identity=0.5, candidates=0.5, audio_extract=0.5, audio_clean=2.0, audio_events=2.0, audio_background=1.2, transcript_check=0.5)
STAGE_MAX_CONCURRENT = dict(transcript_check=1, audio_clean=1, audio_events=1, audio_background=1, proxy=1, people=1, scenes=1, speakers=1, transcribe=1, align=1, exposure=1, preview=1)


def cfg_values(cfg):
    d = dict(DEFAULTS); d.update((cfg or {}).get('resources') or {}); return d


def mem_available_gb():
    """Memory that can be used without swapping, in GB: free + inactive + speculative + purgeable pages (macOS `vm_stat`); falls back to /proc/meminfo, else a large number."""
    if oslib.WIN:
        try: return oslib.windows_available_gb()
        except Exception: return 1e3
    try:
        out = subprocess.run(['vm_stat'], stdout=subprocess.PIPE, text=True, timeout=5).stdout
        page = int(re.search(r'page size of (\d+) bytes', out).group(1)); n = lambda k: int(re.search(rf'{k}:\s+(\d+)', out).group(1))
        return (n('Pages free') + n('Pages inactive') + n('Pages speculative') + n('Pages purgeable')) * page / 1e9
    except Exception:
        try: return int(re.search(r'MemAvailable:\s+(\d+) kB', open('/proc/meminfo').read()).group(1)) / 1e6
        except Exception: return 1e3


def busy(cfg=None):
    """True when the 1-minute load average is above the allowed share of the CPUs."""
    load = oslib.load_average()
    return load is not None and load > (os.cpu_count() or 4) * cfg_values(cfg)['busy_load_fraction']


def may_start_extra_worker(n_running, cfg=None):
    """(ok, reason) for starting another worker when `n_running` are already going. The first worker is always allowed (it is low priority and waits for memory itself)."""
    v = cfg_values(cfg)
    if n_running <= 0: return True, ''
    if n_running >= int(v['max_workers']): return False, f"at the limit of {int(v['max_workers'])} workers"
    free = mem_available_gb()
    if free < float(v['extra_worker_free_gb']): return False, f"only {free:.0f} GB of memory is free; another worker needs at least {float(v['extra_worker_free_gb']):.0f} GB free"
    if busy(cfg): return False, 'the machine is busy'
    return True, ''


def low_priority(cfg=None):
    """Lowest priority for this process and everything it starts. Call once at the start of a worker."""
    v = cfg_values(cfg); n = str(int(v['threads']))
    oslib.lower_priority(19)
    if sys.platform == 'darwin':
        try:                                                                                          # macOS: the background task class (PRIO_DARWIN_PROCESS = 4, PRIO_DARWIN_BG = 0x1000)
            libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True); libc.setpriority(4, 0, 0x1000)
        except Exception: pass
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'): os.environ.setdefault(k, n)
    try:
        import cv2; cv2.setNumThreads(int(n))
    except Exception: pass


def wait_for_headroom(stage, cfg=None, active=None, log=print, poll=20, max_wait=None):
    """Block until the machine has room for one item of `stage`: enough available memory, not busy, and (for a heavy stage) no other worker running it. `active` is a callable returning the
    stages currently being processed by all workers. Returns True when it may go ahead, False if `max_wait` seconds passed."""
    if os.environ.get('STRATA_NO_RESOURCE_LIMITS'): return True                                    # tests and CI runners: nobody is waiting for the machine to be free
    v = cfg_values(cfg); need = STAGE_MEM_GB.get(stage, 1.0) + float(v['reserve_gb']); cap = STAGE_MAX_CONCURRENT.get(stage); t0 = time.time(); said = None
    while True:
        why = None; avail = mem_available_gb()
        if avail < need: why = f'waiting for memory ({stage} needs about {need:.0f} GB, {avail:.0f} GB available)'
        elif busy(cfg): why = 'waiting: the machine is busy'
        elif cap and active is not None and sum(1 for s in active() if s == stage) >= cap: why = f'waiting: another worker is already running {stage}'
        if why is None: return True
        if why != said: log(f'    {why}'); said = why
        if max_wait is not None and time.time() - t0 > max_wait: return False
        time.sleep(poll)
