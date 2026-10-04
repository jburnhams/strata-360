"""Project metadata backups: `<project>/backups/meta-<UTC time>.tar.gz`, at most one every 30 minutes, and only when something changed.

*What is saved* is everything in the project folder except what can be rebuilt or is bulky: the folder `backups/` itself, claim / worker / lock / temp / log files, media and image files (`SKIP_EXT`) and any
file over `MAX_FILE_MB` (but the current .gpx / .fit tracks and `music/track.*` are always saved). Uploaded photos, voice-over takes and the history of tracks and music are not backed up: they are never overwritten or deleted instead (unique names, replaced files get a time stamp, removal moves to a `removed/` folder). It is a rule of exclusion, not a list of names, so a new data file written by any new feature is included without anyone registering it.

*The flag* is a fingerprint of the saved files (path, size, modification time) kept in `backups/state.json`: no writer has to remember to mark anything. The project is "dirty" while the fingerprint differs from the
last backup's, and `maybe_backup` (cheap: one directory walk) does nothing until it is dirty and `INTERVAL_S` has passed since the last backup. Processes may race: the check is repeated under a file lock.

*Retention* thins old backups on an exponential scale (`TIERS`): all of the last 3 hours, then one per hour for a day, one per day for a week, one per week for 5 weeks, one per month for 13 months, then one per year;
the newest backup of each period is the one kept."""
import datetime as dt, hashlib, json, os, re, tarfile, threading, time
from strata360 import oslib
from strata360.pipeline import config

INTERVAL_S = 30 * 60
DIR = 'backups'
MAX_FILE_MB = 5
TRACK_RE = re.compile(r'\.(gpx|fit)$', re.I)                                                          # the current tracks: track.gpx, tracks/t2-run.gpx
SKIP_DIRS = {DIR, '.claims', '.workers', '__pycache__', 'removed'}
SKIP_SUFFIX = ('.replaced', '.removed', '.bad')                                                        # history kept on disk (replaced / removed / unreadable uploads), not part of the backup
SKIP_EXT = {'.lock', '.tmp', '.log', '.pyc', '.mp4', '.mov', '.mkv', '.m4v', '.avi', '.ts', '.m3u8', '.wav', '.flac', '.mp3', '.m4a', '.aac', '.ogg', '.jpg', '.jpeg', '.png', '.webp', '.osv', '.insv', '.npy'}
TIERS = [(3 * 3600, None), (86400, '%Y%m%d%H'), (7 * 86400, '%Y%m%d'), (35 * 86400, '%G-W%V'), (400 * 86400, '%Y%m'), (float('inf'), '%Y')]       # (age up to, calendar period of which one backup is kept; None keeps all)
_STAMP = '%Y%m%dT%H%M%SZ'


def backup_dir(folder): return os.path.join(config.race_dir(folder), DIR)


def collect(folder):
    """[(relative posix path, absolute path)] of the files that belong in a backup, sorted."""
    rd = config.race_dir(folder); out = []
    for root, dirs, files in os.walk(rd):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in files:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, rd).replace(os.sep, '/')
            if n.endswith(SKIP_SUFFIX) or '.tmp' in n: continue                              # `stages.json.123.tmp` style names are half-written files
            current = TRACK_RE.search(n) or rel.startswith('music/track.')                  # the current tracks and music are saved whatever their type and size (their history is kept as files, not backed up)
            if not current:
                if os.path.splitext(n)[1].lower() in SKIP_EXT: continue
                try:
                    if os.path.getsize(p) > MAX_FILE_MB * 1_000_000: continue
                except OSError: continue
            out.append((rel, p))
    return sorted(out)


def fingerprint(files):
    h = hashlib.sha1()
    for rel, p in files:
        try: s = os.stat(p)
        except OSError: continue
        h.update(f'{rel}\0{s.st_size}\0{s.st_mtime_ns}\n'.encode())
    return h.hexdigest()


def _state(folder):
    try: return json.load(open(os.path.join(backup_dir(folder), 'state.json')))
    except (OSError, ValueError): return {}


def is_dirty(folder):
    """True when the saved files differ from what the last backup recorded."""
    return fingerprint(collect(folder)) != _state(folder).get('fingerprint')


def stamp_of(name):
    """UTC time of a backup file name (`meta-20261004T153000Z.tar.gz`), or None."""
    try: return dt.datetime.strptime(name[len('meta-'):-len('.tar.gz')], _STAMP).replace(tzinfo=dt.timezone.utc).timestamp() if name.startswith('meta-') and name.endswith('.tar.gz') else None
    except ValueError: return None


def list_backups(folder):
    """[(name, time, size)] oldest first."""
    d = backup_dir(folder); out = []
    for n in os.listdir(d) if os.path.isdir(d) else []:
        t = stamp_of(n)
        if t is not None: out.append((n, t, os.path.getsize(os.path.join(d, n))))
    return sorted(out, key=lambda x: x[1])


def _write(folder, now, files):
    d = backup_dir(folder); os.makedirs(d, exist_ok=True)
    name = 'meta-' + dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(_STAMP) + '.tar.gz'; final = os.path.join(d, name); tmp = final + f'.{os.getpid()}.tmp'
    with tarfile.open(tmp, 'w:gz') as tf:
        for rel, p in files:
            try: tf.add(p, arcname=rel, recursive=False)
            except OSError: pass                                                           # vanished or locked while we copied: the next backup has it
    os.replace(tmp, final); return final


def backup(folder, now=None, force=False, interval=INTERVAL_S):
    """Make a backup when the project is dirty and the last one is `interval` seconds old (`force`: whenever there is anything to save). Returns the archive path or None."""
    now = time.time() if now is None else now; rd = config.race_dir(folder)
    if not os.path.isdir(rd): return None
    os.makedirs(backup_dir(folder), exist_ok=True)
    with open(os.path.join(backup_dir(folder), '.lock'), 'a+') as lf, oslib.file_lock(lf):
        st = _state(folder); files = collect(folder); fp = fingerprint(files)          # the fingerprint is taken BEFORE copying: a change during the copy leaves the project dirty
        if not files or fp == st.get('fingerprint'): return None
        if not force and now - st.get('time', 0) < interval: return None
        path = _write(folder, now, files)
        tmp = os.path.join(backup_dir(folder), f'state.json.{os.getpid()}.tmp'); json.dump(dict(fingerprint=fp, time=now, last=os.path.basename(path)), open(tmp, 'w')); os.replace(tmp, os.path.join(backup_dir(folder), 'state.json'))
        prune(folder, now); return path


def keep_set(times, now):
    """Which of the backup times to keep under TIERS."""
    keep = {}
    for t in sorted(times):
        age = now - t
        for limit, fmt in TIERS:
            if age < limit:
                key = (limit, dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(fmt) if fmt else t); keep[key] = t; break      # later ones in the same period replace earlier ones
    return set(keep.values())


def prune(folder, now=None):
    """Delete the backups the retention scale no longer wants; returns their names."""
    now = time.time() if now is None else now; bk = list_backups(folder); keep = keep_set([t for _, t, _ in bk], now); gone = []
    for n, t, _ in bk:
        if t not in keep:
            try: os.remove(os.path.join(backup_dir(folder), n)); gone.append(n)
            except OSError: pass
    return gone


def restore(folder, name, dest):
    """Unpack one backup into `dest` (a new or empty folder); nothing in the project is touched. Returns the number of files."""
    src = os.path.join(backup_dir(folder), os.path.basename(name)); os.makedirs(dest, exist_ok=True); n = 0
    with tarfile.open(src, 'r:gz') as tf:
        for m in tf.getmembers():
            target = os.path.abspath(os.path.join(dest, m.name))
            if not m.isfile() or not target.startswith(os.path.abspath(dest) + os.sep): continue          # only plain files, never outside dest
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tf.extractfile(m) as r, open(target, 'wb') as w: w.write(r.read())
            os.utime(target, (m.mtime, m.mtime)); n += 1
    return n


class Ticker:
    """A background thread that calls `backup` for every project in `folders()` once a minute (a long-running server or worker); failures never reach the caller."""
    def __init__(self, folders, every=60.0):
        self.folders, self.every, self._stop = folders, every, threading.Event(); self.thread = threading.Thread(target=self._run, daemon=True, name='strata360-backup')

    def start(self): self.thread.start(); return self

    def stop(self): self._stop.set()

    def tick(self):
        for f in list(self.folders()):
            try: backup(f)
            except Exception: pass

    def _run(self):
        while not self._stop.wait(self.every): self.tick()
