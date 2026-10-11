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


def _windows_memory():
    import ctypes

    class MemStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                    ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong), ('total_virt', ctypes.c_ulonglong), ('avail_virt', ctypes.c_ulonglong), ('avail_ext', ctypes.c_ulonglong)]
    s = MemStatus(); s.length = ctypes.sizeof(s); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)); return s


def windows_available_gb(): return _windows_memory().avail_phys / 1e9


def windows_total_gb(): return _windows_memory().total_phys / 1e9


def big_pipe(parent_reads, size=8 << 20):
    """(parent_file, child_fd) for streaming raw video frames to or from a child process on Windows.

    An anonymous pipe (subprocess.PIPE) has a 4 KB buffer there, which moves a 3840x3840 rgb48 frame at about 80 MB/s (1.2 s a frame, measured); a named pipe with a few MB of buffer (more gains nothing, and a dozen 256 MB ones exhausted the pool) does
    the same frame in 0.03 s. `parent_reads` True: the child writes to the pipe (give `child_fd` as its stdout, read `parent_file`); False: the parent writes (child's stdin).
    The caller closes `child_fd` (os.close) once the child has started."""
    import ctypes, io, msvcrt, uuid
    from ctypes import wintypes as wt
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateNamedPipeW.restype = wt.HANDLE; k.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    k.CreateFileW.restype = wt.HANDLE; k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]

    class SecAttr(ctypes.Structure): _fields_ = [('n', wt.DWORD), ('desc', ctypes.c_void_p), ('inherit', wt.BOOL)]
    bad = ctypes.c_void_p(-1).value; bs = chr(92); name = bs * 2 + '.' + bs + 'pipe' + bs + f'strata360-{os.getpid()}-{uuid.uuid4().hex}'
    server = k.CreateNamedPipeW(name, 1 if parent_reads else 2, 0, 1, 0 if parent_reads else size, size if parent_reads else 0, 0, None)       # PIPE_ACCESS_INBOUND / OUTBOUND, byte mode, one instance
    if server in (None, bad): raise ctypes.WinError(ctypes.get_last_error())
    sa = SecAttr(ctypes.sizeof(SecAttr), None, True)
    client = k.CreateFileW(name, 0x40000000 if parent_reads else 0x80000000, 0, ctypes.byref(sa), 3, 0, None)                              # GENERIC_WRITE / GENERIC_READ, OPEN_EXISTING, inheritable
    if client in (None, bad): err = ctypes.get_last_error(); k.CloseHandle(server); raise ctypes.WinError(err)
    sfd = msvcrt.open_osfhandle(server, os.O_RDONLY if parent_reads else os.O_WRONLY); cfd = msvcrt.open_osfhandle(client, os.O_WRONLY if parent_reads else os.O_RDONLY)
    raw = io.FileIO(sfd, 'rb' if parent_reads else 'wb', closefd=True)
    return (io.BufferedReader(raw, 1 << 20) if parent_reads else io.BufferedWriter(raw, 1 << 20)), cfd


def venv_python(venv):
    """The interpreter of a virtual environment: bin/python on POSIX, Scripts\\python.exe on Windows."""
    return os.path.join(venv, 'Scripts', 'python.exe') if WIN else os.path.join(venv, 'bin', 'python')


def cli_command():
    """Command prefix that starts the strata360 CLI with the interpreter running this process (what the bash launcher does, minus bash, so it also works
    on Windows and without a .venv). Sets PYTHONPATH and PYTHONWARNINGS for the child like the launcher does."""
    os.environ['PYTHONPATH'] = os.path.join(ROOT_DIR, 'src') + os.pathsep + os.environ.get('PYTHONPATH', ''); os.environ.setdefault('PYTHONWARNINGS', 'ignore')
    return [sys.executable, '-m', 'strata360']


def replace_file(src, dst, tries=40, wait=0.05):
    """os.replace that waits a moment when Windows refuses because another process has the destination open (the server reads the status files while a render rewrites them)."""
    import time
    for i in range(tries):
        try: os.replace(src, dst); return
        except PermissionError:
            if i == tries - 1: raise
            time.sleep(wait)
