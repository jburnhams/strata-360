"""OS differences in one place: file locks, process liveness and termination, priority, free memory and how to start the CLI.

POSIX (macOS, Linux) uses fcntl, os.kill and os.nice; Windows uses msvcrt, the Win32 API through ctypes and taskkill. Other modules should call these
instead of importing fcntl or calling os.kill(pid, 0) (on Windows that would terminate the process)."""
import contextlib, os, subprocess, sys, time

WIN = sys.platform == 'win32'
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


@contextlib.contextmanager
def file_lock(f):
    """Exclusive lock on an open file, held for the duration of the block (other processes block until it is released)."""
    if WIN:
        import msvcrt
        f.seek(0)
        while True:
            try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1); break
            except OSError: time.sleep(0.02)
        try: yield
        finally:
            f.seek(0)
            with contextlib.suppress(OSError): msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def pid_alive(pid):
    """Is that process still running?"""
    try: pid = int(pid)
    except (TypeError, ValueError): return False
    if pid <= 0: return False
    if WIN:
        import ctypes
        k = ctypes.windll.kernel32; h = k.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
        if not h: return False
        try:
            code = ctypes.c_ulong(); ok = k.GetExitCodeProcess(h, ctypes.byref(code)); return bool(ok) and code.value == 259     # STILL_ACTIVE
        finally: k.CloseHandle(h)
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True
    except OSError: return False


def kill_tree(pid, sig=15):
    """Terminate a worker and every process it started (a stage may have launched ffmpeg or a model process); errors are ignored."""
    if WIN:
        with contextlib.suppress(OSError): subprocess.run(['taskkill', '/T', '/F', '/PID', str(int(pid))], capture_output=True)
        return
    try: kids = subprocess.run(['pgrep', '-P', str(pid)], stdout=subprocess.PIPE, text=True).stdout.split()
    except OSError: kids = []
    for k in kids: kill_tree(int(k), sig)
    with contextlib.suppress(OSError): os.kill(int(pid), sig)


def lower_priority(nice=19):
    """Run this process at lower CPU priority (nice value on POSIX, below-normal/idle class on Windows). Children inherit it."""
    if WIN:
        import ctypes
        with contextlib.suppress(Exception): ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40 if nice >= 15 else 0x4000)    # IDLE / BELOW_NORMAL
        return
    with contextlib.suppress(OSError, AttributeError): os.nice(nice)


def load_average():
    """1-minute load average, or None where the OS has no such thing (Windows)."""
    try: return os.getloadavg()[0]
    except (OSError, AttributeError): return None


def windows_available_gb():
    import ctypes

    class MemStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                    ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong), ('total_virt', ctypes.c_ulonglong), ('avail_virt', ctypes.c_ulonglong), ('avail_ext', ctypes.c_ulonglong)]
    s = MemStatus(); s.length = ctypes.sizeof(s); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)); return s.avail_phys / 1e9


def cli_command():
    """Command prefix that starts the strata360 CLI with the interpreter running this process (what the bash launcher does, minus bash, so it also works
    on Windows and without a .venv). Sets PYTHONPATH and PYTHONWARNINGS for the child like the launcher does."""
    os.environ['PYTHONPATH'] = os.path.join(ROOT_DIR, 'src') + os.pathsep + os.environ.get('PYTHONPATH', ''); os.environ.setdefault('PYTHONWARNINGS', 'ignore')
    return [sys.executable, '-m', 'strata360']
