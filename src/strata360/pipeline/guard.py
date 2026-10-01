"""Safeguards for heavy work, so a job can never take over the machine (a leaked pile of ffmpeg processes and a runaway load once froze it):

  check(label, gb)     at the start of any heavy job: fails FAST with a message that says what is wrong and what is using the machine (the top processes, any ffmpeg already running), so the caller can wait
                       or clear it up. Not a wait (the pipeline runner waits itself, resources.wait_for_headroom); this is the guard for everything else: the CLI renders, scripts, a stage run by hand.
  popen(cmd, ...)      subprocess.Popen for ffmpeg and friends: refuses to start another ffmpeg when `STRATA_MAX_FFMPEG` (6) are already running anywhere, and remembers the child so it is
                       killed when the job ends, fails or is interrupted (a render that crashed used to leave its decoders and encoder running for hours).
  heavy(label, gb)     the context manager that does both and then WATCHES the job: every few seconds it compares the machine's load and free memory (and this job's own memory) with the limits and, when
                       they are passed, kills the job's processes and stops it with an explanation: `STRATA_KILL_LOAD` (load per CPU, default 1.5), `STRATA_KILL_FREE_GB` (0.8), `max_gb` (the job's cap).
STRATA_NO_RESOURCE_LIMITS=1 turns all of it off (tests, CI). Limits can be set per call."""
import atexit, contextlib, os, signal, subprocess, sys, threading, time
from strata360.pipeline import resources as RS

MAX_FFMPEG = 6; KILL_LOAD = 1.5; KILL_FREE_GB = 0.8; POLL_S = 5.0
_CHILDREN = []; _LOCK = threading.Lock()


class ResourceBusy(RuntimeError):
    """The machine has no room for this job right now. Retryable: wait (or clear up what the message names) and try again."""
    retryable = True


def _off(): return bool(os.environ.get('STRATA_NO_RESOURCE_LIMITS'))


def _env_f(name, default):
    try: return float(os.environ.get(name, default))
    except ValueError: return float(default)


def processes():
    """[(pid, ppid, cpu %, rss MB, elapsed, command)] of every process (`ps`); [] if ps is unavailable."""
    try: out = subprocess.run(['ps', '-Ao', 'pid=,ppid=,pcpu=,rss=,etime=,command='], capture_output=True, text=True, timeout=10).stdout
    except Exception: return []
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


def load_per_cpu():
    try: return os.getloadavg()[0] / (os.cpu_count() or 4)
    except OSError: return 0.0


def check(label, gb=1.0, cfg=None, max_ffmpeg=None):
    """Raise ResourceBusy (with what to do about it) unless the machine has room for a job needing about `gb` GB: free memory above that plus the reserve, load below the busy limit, fewer than
    max_ffmpeg ffmpeg processes running."""
    if _off(): return
    v = RS.cfg_values(cfg); need = float(gb) + float(v['reserve_gb']); free = RS.mem_available_gb(); problems = []; rows = None
    if free < need: rows = processes(); problems.append(f'only {free:.1f} GB of memory is free, {label} needs about {need:.1f} GB (including a {float(v["reserve_gb"]):.0f} GB reserve); biggest: {top(rows)}')
    lim = float(v['busy_load_fraction'])
    if load_per_cpu() > lim:
        rows = rows or processes(); problems.append(f'the machine is busy (load {os.getloadavg()[0]:.0f} on {os.cpu_count()} CPUs, limit {lim * (os.cpu_count() or 4):.0f}); busiest: {top(rows, by="cpu")}')
    cap = int(max_ffmpeg if max_ffmpeg is not None else _env_f('STRATA_MAX_FFMPEG', MAX_FFMPEG)); rows = rows or processes(); ff = ffmpeg_processes(rows)
    if len(ff) >= cap: problems.append(f"{len(ff)} ffmpeg/ffprobe processes are already running (limit {cap}), oldest pids {[r[0] for r in sorted(ff, key=lambda r: -len(r[4]))[:5]]}: finished or crashed jobs may have left them (pkill ffmpeg clears them)")
    if problems: raise ResourceBusy(f'not starting {label}: ' + ' | '.join(problems) + '. Wait for it to clear, or free those up, then run it again.')


def popen(cmd, *a, **k):
    """subprocess.Popen that refuses a new ffmpeg/ffprobe over the limit and remembers the child so `kill_children` (at exit, on failure, on interruption) can stop it."""
    if not _off() and os.path.basename(str(cmd[0])) in ('ffmpeg', 'ffprobe'):
        cap = int(_env_f('STRATA_MAX_FFMPEG', MAX_FFMPEG)); ff = ffmpeg_processes()
        if len(ff) >= cap: raise ResourceBusy(f'not starting {os.path.basename(str(cmd[0]))}: {len(ff)} ffmpeg/ffprobe processes are already running (limit {cap}), pids {[r[0] for r in ff[:6]]}: pkill ffmpeg clears leftovers')
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
    if load_per_cpu() > kl: return f'the machine is overloaded (load {os.getloadavg()[0]:.0f} on {os.cpu_count()} CPUs, limit {kl * (os.cpu_count() or 4):.0f})'
    free = RS.mem_available_gb()
    if free < kf: return f'the machine is out of memory ({free:.1f} GB free, limit {kf:.1f} GB)'
    if max_gb:
        rows = rows if rows is not None else processes(); used = _own_tree_mb(rows) / 1024.0
        if used > max_gb: return f'this job uses {used:.1f} GB, over its cap of {max_gb:.1f} GB'
    return None


@contextlib.contextmanager
def heavy(label, gb=1.0, max_gb=None, cfg=None, on_abort=None):
    """Around a heavy job: `check` first (ResourceBusy if there is no room), then a watchdog thread that stops the job (kills its processes, then `on_abort(reason)`, default: print the reason and exit 75)
    when `verdict` says the machine is overloaded or short of memory or the job is over `max_gb` (default: three times `gb`). Its ffmpeg children are killed when the block ends, however it ends."""
    if _off(): yield; return
    check(label, gb, cfg); stop = threading.Event(); cap = max_gb if max_gb is not None else 3.0 * float(gb)
    def abort(reason):
        kill_children()
        if on_abort: on_abort(reason); return
        print(f'\n{label} stopped: {reason}. Its processes were killed so the machine stays usable; run it again when that clears.', file=sys.stderr, flush=True); os._exit(75)
    def watch():
        while not stop.wait(POLL_S):
            why = verdict(cap)
            if why: abort(why); return
    t = threading.Thread(target=watch, daemon=True); t.start()
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try: old[sig] = signal.signal(sig, lambda s, f, sig=sig: (kill_children(), (old.get(sig) or signal.SIG_DFL) if False else None, sys.exit(128 + s)))
            except (ValueError, OSError): pass
    try: yield
    finally:
        stop.set(); kill_children()
        for sig, h in old.items():
            try: signal.signal(sig, h)
            except (ValueError, OSError): pass
