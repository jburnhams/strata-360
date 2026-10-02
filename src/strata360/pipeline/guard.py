"""Safeguards for heavy work, so a job can never take over the machine (a leaked pile of ffmpeg processes and a runaway load once froze it):

  check(label, gb)     at the start of any heavy job: fails FAST with a message that says what is wrong and what is using the machine (the top processes, any ffmpeg already running), so the caller can wait
                       or clear it up. Not a wait (the pipeline runner waits itself, resources.wait_for_headroom); this is the guard for everything else: the CLI renders, scripts, a stage run by hand.
  popen(cmd, ...)      subprocess.Popen for ffmpeg and friends: refuses to start another ffmpeg when `STRATA_MAX_FFMPEG` (6) are already running anywhere, and remembers the child so it is
                       killed when the job ends, fails or is interrupted (a render that crashed used to leave its decoders and encoder running for hours).
  heavy(label, gb)     the context manager that does both and then WATCHES the job: every few seconds it compares the machine's load and free memory (and this job's own memory) with the limits and, when
                       they are passed, kills the job's whole process tree and stops it with an explanation: `STRATA_KILL_LOAD` (load per CPU, default 1.5), `STRATA_KILL_FREE_GB` (1.5), `STRATA_KILL_SWAP_PCT`
                       (20 percent of memory; and `STRATA_START_SWAP_PCT`, 15, for starting), the system's memory-pressure level (macOS: warning or critical), `max_gb` (the job's cap). It polls every 2 s: memory runs out in seconds, not minutes.
  watch(label)         the same watchdog without the start check, for things that are not one job (the test run).
  panic()              kill every ffmpeg/ffprobe/pytest/strata360 process of this user except the server and this one (`./strata360 stop-all`).
STRATA_NO_RESOURCE_LIMITS=1 turns all of it off (tests, CI). Limits can be set per call."""
import atexit, contextlib, os, signal, subprocess, sys, threading, time
from strata360.pipeline import resources as RS

MAX_FFMPEG = 8; KILL_LOAD = 1.5; KILL_FREE_GB = 1.5; KILL_SWAP_PCT = 20.0; POLL_S = 2.0; START_SWAP_PCT = 15.0
_CHILDREN = []; _LOCK = threading.Lock()


class ResourceBusy(RuntimeError):
    """The machine has no room for this job right now. Retryable: wait (or clear up what the message names) and try again."""
    retryable = True


def _off(): return bool(os.environ.get('STRATA_NO_RESOURCE_LIMITS'))


def _env_f(name, default):
    try: return float(os.environ.get(name, default))
    except ValueError: return float(default)


def _load1():
    try: return os.getloadavg()[0]
    except (OSError, AttributeError): return 0.0                                                    # Windows has no load average


def processes():
    """[(pid, ppid, cpu %, rss MB, elapsed, command)] of every process (`ps`); [] where ps is unavailable (Windows)."""
    if sys.platform == 'win32': return []
    out = RS.run_text(['ps', '-Ao', 'pid=,ppid=,pcpu=,rss=,etime=,command='])
    rows = []
    for ln in out.splitlines():
        p = ln.split(None, 5)
        if len(p) == 6:
            try: rows.append((int(p[0]), int(p[1]), float(p[2]), int(p[3]) / 1024.0, p[4], p[5]))
            except ValueError: pass
    return rows


def ffmpeg_processes(rows=None):
    """The ffmpeg and ffprobe processes running now (anyone's)."""
    return [r for r in (rows if rows is not None else processes()) if os.path.basename(r[5].split()[0]) in ('ffmpeg', 'ffprobe')]


def top(rows=None, n=4, by='rss'):
    """The `n` biggest processes by memory (`rss`) or CPU, as short text."""
    rows = rows if rows is not None else processes(); key = (lambda r: -r[3]) if by == 'rss' else (lambda r: -r[2])
    return '; '.join(f"{os.path.basename(r[5].split()[0])[:24]} pid {r[0]} {r[3]:.0f} MB {r[2]:.0f}% CPU up {r[4]}" for r in sorted(rows, key=key)[:n])


def pressure_level():
    """The system's memory-pressure level: 1 normal, 2 warning, 4 critical (macOS `kern.memorystatus_vm_pressure_level`); 1 where it cannot be read."""
    if sys.platform != 'darwin': return 1
    try:
        import ctypes, ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library('c')); v = ctypes.c_int(0); n = ctypes.c_size_t(4)
        return int(v.value) if libc.sysctlbyname(b'kern.memorystatus_vm_pressure_level', ctypes.byref(v), ctypes.byref(n), None, 0) == 0 else 1
    except Exception: return 1


def swap_limit_gb(kind):
    """The swap limit in GB: a share of the machine's physical memory (so a 16 GB and a 64 GB machine are judged alike). `kind` is 'start' (no new heavy job above it, 15 percent: 2.4 GB on 16 GB) or 'kill' (a running job
    is stopped above it, 20 percent: 3.2 GB on 16 GB). `STRATA_START_SWAP_PCT` / `STRATA_KILL_SWAP_PCT` change the share; `STRATA_KILL_SWAP_GB` still sets the kill limit in GB."""
    if kind == 'kill' and os.environ.get('STRATA_KILL_SWAP_GB'): return _env_f('STRATA_KILL_SWAP_GB', 0.0)
    pct = _env_f('STRATA_START_SWAP_PCT', START_SWAP_PCT) if kind == 'start' else _env_f('STRATA_KILL_SWAP_PCT', KILL_SWAP_PCT); return pct / 100.0 * RS.mem_total_gb()


def swap_used_gb():
    """Swap in use, GB (macOS `vm.swapusage`); 0 where it cannot be read."""
    if sys.platform != 'darwin': return 0.0
    try:
        import ctypes, ctypes.util                                                                     # struct xsw_usage { u64 total, avail, used; u32 pagesize; bool encrypted }
        libc = ctypes.CDLL(ctypes.util.find_library('c')); buf = ctypes.create_string_buffer(32); n = ctypes.c_size_t(32)
        if libc.sysctlbyname(b'vm.swapusage', buf, ctypes.byref(n), None, 0) != 0: return 0.0
        return int.from_bytes(buf.raw[16:24], 'little') / 1e9
    except Exception: return 0.0


def load_per_cpu():
    return _load1() / (os.cpu_count() or 4)


def check(label, gb=1.0, cfg=None, max_ffmpeg=None):
    """Raise ResourceBusy (with what to do about it) unless the machine has room for a job needing about `gb` GB: free memory above that plus the reserve, load below the busy limit, fewer than
    max_ffmpeg ffmpeg processes running."""
    if _off(): return
    v = RS.cfg_values(cfg); need = float(gb) + float(v['reserve_gb']); free = RS.mem_available_gb(); problems = []; rows = None
    if free < need: rows = processes(); problems.append(f'only {free:.1f} GB of memory is free, {label} needs about {need:.1f} GB (including a {float(v["reserve_gb"]):.0f} GB reserve); biggest: {top(rows)}')
    lvl = pressure_level(); sw = swap_used_gb()
    if lvl >= 2: rows = rows or processes(); problems.append(f'the system reports memory pressure (level {lvl}); biggest: {top(rows)}')
    elif sw > swap_limit_gb('start'): rows = rows or processes(); problems.append(f"{sw:.1f} GB of swap is in use already (limit {swap_limit_gb('start'):.1f} GB, {_env_f('STRATA_START_SWAP_PCT', START_SWAP_PCT):.0f}% of memory); biggest: {top(rows)}")
    lim = float(v['busy_load_fraction'])
    if load_per_cpu() > lim:
        rows = rows or processes(); problems.append(f'the machine is busy (load {_load1():.0f} on {os.cpu_count()} CPUs, limit {lim * (os.cpu_count() or 4):.0f}); busiest: {top(rows, by="cpu")}')
    cap = int(max_ffmpeg if max_ffmpeg is not None else _env_f('STRATA_MAX_FFMPEG', MAX_FFMPEG)); rows = rows or processes(); ff = ffmpeg_processes(rows)
    if len(ff) >= cap: problems.append(f"{len(ff)} ffmpeg/ffprobe processes are already running (limit {cap}), oldest pids {[r[0] for r in sorted(ff, key=lambda r: -len(r[4]))[:5]]}: finished or crashed jobs may have left them (pkill ffmpeg clears them)")
    if problems: raise ResourceBusy(f'not starting {label}: ' + ' | '.join(problems) + '. Wait for it to clear, or free those up, then run it again.')


def popen(cmd, *a, **k):
    """subprocess.Popen that refuses a new ffmpeg/ffprobe over the limit and remembers the child so `kill_children` (at exit, on failure, on interruption) can stop it."""
    if not _off() and os.path.basename(str(cmd[0])) in ('ffmpeg', 'ffprobe'):
        cap = int(_env_f('STRATA_MAX_FFMPEG', MAX_FFMPEG)); ff = ffmpeg_processes()
        if len(ff) >= cap: raise ResourceBusy(f'not starting {os.path.basename(str(cmd[0]))}: {len(ff)} ffmpeg/ffprobe processes are already running (limit {cap}), pids {[r[0] for r in ff[:6]]}: pkill ffmpeg clears leftovers')
    if os.path.basename(str(cmd[0])) == 'ffmpeg' and '-threads' not in cmd: cmd = [cmd[0], '-threads', str(int(RS.cfg_values(None)['threads']))] + list(cmd[1:])          # a decoder or encoder must not take every core
    p = subprocess.Popen(cmd, *a, **k)
    with _LOCK: _CHILDREN[:] = [c for c in _CHILDREN if c.poll() is None] + [p]
    return p


def kill_children():
    """Stop every process started with `popen` that is still running."""
    with _LOCK: kids = list(_CHILDREN); _CHILDREN.clear()
    for p in kids:
        try:
            if p.poll() is None: p.terminate()
        except Exception: pass
    for p in kids:
        try: p.wait(timeout=3)
        except Exception:
            try: p.kill()
            except Exception: pass


atexit.register(kill_children)


def descendants(rows=None, root=None):
    """pids of every process below `root` (default this process)."""
    rows = rows if rows is not None else processes(); kids = {root or os.getpid()}; out = []; grew = True
    while grew:
        grew = False
        for r in rows:
            if r[1] in kids and r[0] not in kids: kids.add(r[0]); out.append(r[0]); grew = True
    return out


def kill_tree():
    """Kill everything this process started, however deep (ffmpeg children, helper processes), then the registered children."""
    for pid in descendants():
        try: os.kill(pid, signal.SIGKILL)
        except OSError: pass
    kill_children()


def panic(keep=()):
    """Kill every ffmpeg/ffprobe/pytest/strata360 process of this user except the web server, this process and `keep`. Returns the pids killed."""
    me = {os.getpid(), os.getppid(), *keep}; killed = []
    for r in processes():
        name = os.path.basename(r[5].split()[0]); cmd = r[5]
        mine = name in ('ffmpeg', 'ffprobe') or 'pytest' in cmd or ('strata360' in cmd and ' serve' not in cmd and 'stop-all' not in cmd)
        if mine and r[0] not in me:
            try: os.kill(r[0], signal.SIGKILL); killed.append(r[0])
            except OSError: pass
    return killed


def _own_tree_mb(rows):
    """Memory (MB) of this process and everything below it."""
    me = os.getpid(); kids = {me}; grew = True
    while grew:
        grew = False
        for r in rows:
            if r[1] in kids and r[0] not in kids: kids.add(r[0]); grew = True
    return sum(r[3] for r in rows if r[0] in kids)


def verdict(max_gb=None, kill_load=None, kill_free_gb=None, rows=None):
    """None while the machine is fine, else why the job must stop (what the watchdog checks)."""
    kl = _env_f('STRATA_KILL_LOAD', KILL_LOAD) if kill_load is None else kill_load; kf = _env_f('STRATA_KILL_FREE_GB', KILL_FREE_GB) if kill_free_gb is None else kill_free_gb
    lvl = pressure_level()
    if lvl >= 2: return f'the system reports memory pressure (level {lvl})'
    sw = swap_used_gb(); ks = swap_limit_gb('kill')
    if sw > ks: return f'swap is filling up ({sw:.1f} GB used, limit {ks:.1f} GB)'
    if load_per_cpu() > kl: return f'the machine is overloaded (load {_load1():.0f} on {os.cpu_count()} CPUs, limit {kl * (os.cpu_count() or 4):.0f})'
    free = RS.mem_available_gb()
    if free < kf: return f'the machine is out of memory ({free:.1f} GB free, limit {kf:.1f} GB)'
    if max_gb:
        rows = rows if rows is not None else processes(); used = _own_tree_mb(rows) / 1024.0
        if used > max_gb: return f'this job uses {used:.1f} GB, over its cap of {max_gb:.1f} GB'
    return None


def watch(label, max_gb=None, on_abort=None):
    """Start the watchdog thread (see the module doc); returns the function that stops it. On a bad `verdict` it kills this process's whole tree and calls `on_abort(reason)` (default: say why on stderr and exit 75)."""
    if _off(): return lambda: None                                                                 # the one switch (STRATA_NO_RESOURCE_LIMITS) turns every guard and watchdog off
    stop = threading.Event()
    def abort(reason):
        kill_tree()
        if on_abort: on_abort(reason); return
        msg = f'{label} stopped: {reason}. Its processes were killed so the machine stays usable; run it again when that clears.'
        try:                                                                                        # a log that survives output capture (pytest) and a dead terminal
            d = os.path.join(os.path.expanduser('~'), '.cache', 'strata360'); os.makedirs(d, exist_ok=True); open(os.path.join(d, 'abort.log'), 'a').write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
        except OSError: pass
        print('\n' + msg, file=sys.__stderr__, flush=True); os._exit(75)
    def run():
        bad = 0
        while not stop.wait(POLL_S):
            why = verdict(max_gb); bad = bad + 1 if why else 0
            if why and (bad >= 2 or 'critical' in why or 'level 4' in why): abort(why); return                  # two readings in a row (a momentary spike does not stop a job); a critical pressure level does at once
    threading.Thread(target=run, daemon=True).start(); return stop.set


@contextlib.contextmanager
def heavy(label, gb=1.0, max_gb=None, cfg=None, on_abort=None):
    """Around a heavy job: `check` first (ResourceBusy if there is no room), then the watchdog (`watch`; the job's cap defaults to three times `gb`). Its ffmpeg children are killed when the block ends, however it ends."""
    if _off(): yield; return
    check(label, gb, cfg); stop = watch(label, max_gb if max_gb is not None else 3.0 * float(gb), on_abort); old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try: old[sig] = signal.signal(sig, lambda s_, f, sig=sig: (kill_tree(), sys.exit(128 + s_)))
            except (ValueError, OSError): pass
    try: yield
    finally:
        stop(); kill_children()
        for sig, h in old.items():
            try: signal.signal(sig, h)
            except (ValueError, OSError): pass
