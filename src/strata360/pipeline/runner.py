"""Run stages over a race's clips with caching, fail-soft error handling and **parallel workers**.

Work is a set of items (clip, stage). Any number of workers (processes started from the GUI, the command line, or both) can run at the same time: a worker repeatedly scans the items in
stage order, skips those that are done, blocked or claimed, *claims* one (an atomic file `.claims/<clip>__<stage>` holding its pid), runs it, releases it and scans again, until nothing
is left. The first worker therefore loops through everything; a worker started later simply picks up whatever is unfinished and unclaimed. A claim whose process has died is stale and is
taken over. The per-clip state file (`stages.json`) is updated under a file lock so workers finishing different stages of one clip never overwrite each other.

`clear` removes the recorded status of a stage (and, by default, of every stage that depends on it) so it will be processed again."""
import atexit, datetime as dt, fcntl, fnmatch, hashlib, json, os, time, traceback
from contextlib import contextmanager
from strata360.pipeline import config, clips as clipmod
from strata360.pipeline.stages import STAGES, ORDER, Ctx


def clip_dir(race, clip_id):
    return os.path.join(config.race_dir(race), 'clips', clip_id)


def _sha(obj): return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def stage_key(stage, clip, cfg, dep_keys, extra=None):
    """Changes when the code version, the clip content, the relevant config, or an upstream result changes."""
    return _sha([stage.name, stage.version, clip.fingerprint, {k: cfg.get(k) for k in stage.keys}, dep_keys] + ([extra] if extra is not None else []))      # `extra` only joins the key when a stage uses it, so existing keys stay valid


# ---- state (one json per clip, updated under a file lock) ------------------------------------------------------------------------------------------------------------
def load_state(race, clip_id):
    p = os.path.join(clip_dir(race, clip_id), 'stages.json')
    try: return json.load(open(p)) if os.path.exists(p) else {}
    except ValueError: return {}                                                                       # caught mid-write on a slow drive: treat as empty this time


def save_state(race, clip_id, state):
    d = clip_dir(race, clip_id); os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f'stages.json.{os.getpid()}.tmp'); json.dump(state, open(tmp, 'w'), indent=1); os.replace(tmp, os.path.join(d, 'stages.json'))


@contextmanager
def state_lock(race, clip_id):
    d = clip_dir(race, clip_id); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, '.state.lock'), 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)


def update_state(race, clip_id, name, entry):
    with state_lock(race, clip_id):
        st = load_state(race, clip_id)
        if entry is None: st.pop(name, None)
        else: st[name] = entry
        save_state(race, clip_id, st)


# ---- claims and workers ------------------------------------------------------------------------------------------------------------------------------------------------
def _alive(pid):
    try: os.kill(int(pid), 0); return True
    except (ProcessLookupError, ValueError): return False
    except PermissionError: return True


def _claims(race): return os.path.join(config.race_dir(race), '.claims')
def _workers(race): return os.path.join(config.race_dir(race), '.workers')


def claim(race, clip_id, stage):
    """Atomically claim (clip, stage) for this process. The claim file is written completely under a private name and then hard-linked into place (link fails if the name exists), so no
    other process can ever see it half-written; a claim left by a dead process is taken over."""
    os.makedirs(_claims(race), exist_ok=True); p = os.path.join(_claims(race), f'{clip_id}__{stage}'); tmp = f'{p}.{os.getpid()}.tmp'
    open(tmp, 'w').write(f'{os.getpid()} {time.time():.0f}')
    try:
        for _ in range(2):
            try: os.link(tmp, p); return True
            except FileExistsError:
                try: pid = open(p).read().split()[0]
                except (OSError, IndexError): return False                                             # unreadable for a moment: someone is claiming it right now
                if _alive(pid): return False
                try: os.remove(p)
                except OSError: pass
        return False
    finally:
        try: os.remove(tmp)
        except OSError: pass


def release(race, clip_id, stage):
    try: os.remove(os.path.join(_claims(race), f'{clip_id}__{stage}'))
    except OSError: pass


def workers(race):
    """Pids of live workers on this race (registered by `work`); stale registrations are removed."""
    out = []; d = _workers(race)
    if os.path.isdir(d):
        for n in os.listdir(d):
            if _alive(n): out.append(int(n))
            else:
                try: os.remove(os.path.join(d, n))
                except OSError: pass
    return sorted(out)


def active_items(race):
    """[(clip, stage, pid)] currently being processed."""
    out = []; d = _claims(race)
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith('.tmp'): continue
            try: pid = open(os.path.join(d, n)).read().split()[0]
            except (OSError, IndexError): continue
            if _alive(pid) and '__' in n: c, s = n.rsplit('__', 1); out.append((c, s, int(pid)))
    return out


def kill_tree(pid, sig=15):
    """Signal a worker and every process it started (a stage may have launched ffmpeg or a model process); errors are ignored."""
    import subprocess
    try: kids = subprocess.run(['pgrep', '-P', str(pid)], stdout=subprocess.PIPE, text=True).stdout.split()
    except OSError: kids = []
    for k in kids: kill_tree(int(k), sig)
    try: os.kill(int(pid), sig)
    except OSError: pass


def runnable_count(race):
    """How many items could be started right now: unfinished, dependencies done, not claimed. (What an additional worker could pick up.)"""
    cfg = config.load(race); cl, _ = discover(race, cfg); names = [s for s in ORDER if s in cfg['stages']]; taken = {(c, s) for c, s, _ in active_items(race)}; n = 0
    for name in names:
        st = STAGES[name]
        for c in cl:
            if (c.id, name) in taken: continue
            done, _, blocked = _cached(race, st, c, cfg, load_state(race, c.id), clip_dir(race, c.id))
            if not done and not blocked: n += 1
    return n


def dependents(stage):
    """`stage` plus every stage that depends on it, directly or not (the stages that must be redone after it changes)."""
    out = {stage}; grew = True
    while grew:
        grew = False
        for n, st in STAGES.items():
            if n not in out and any(d in out for d in st.deps): out.add(n); grew = True
    return [n for n in ORDER if n in out]


def clear(race, stage, clips=None, cascade=True):
    """Forget the recorded status of `stage` (and its dependents) for the given clip ids (default all) so it is processed again. Returns [(clip, stage)] cleared. Outputs stay on disk until replaced."""
    if stage not in STAGES: raise ValueError(f'unknown stage {stage!r}; available: {ORDER}')
    names = dependents(stage) if cascade else [stage]; cfg = config.load(race); cl, _ = clipmod.discover(cfg['library']); ids = [c.id for c in cl if clips is None or c.id in clips]; done = []
    for cid in ids:
        for n in names:
            if load_state(race, cid).get(n) is not None: update_state(race, cid, n, None); done.append((cid, n))
    return done


def clear_items(race, items):
    """Forget the status of exactly these (clip_id, stage) items. Returns how many had a status."""
    n = 0
    for cid, name in items:
        if name in STAGES and load_state(race, cid).get(name) is not None: update_state(race, cid, name, None); n += 1
    return n


def item_states(race):
    """The whole state matrix for the GUI: {clip_id: {stage: 'ok'|'failed'|'active'|'stale'|None}} for the configured stages (active = being processed right now)."""
    cfg = config.load(race); cl, _ = discover(race, cfg); names = [s for s in ORDER if s in cfg['stages']]; act = {(c, s) for c, s, _ in active_items(race)}; out = {}
    for c in cl:
        state = load_state(race, c.id); row = {}
        for n in names:
            e = state.get(n); done, _, blocked = _cached(race, STAGES[n], c, cfg, state, clip_dir(race, c.id))
            row[n] = 'active' if (c.id, n) in act else None if e is None else 'failed' if e.get('status') == 'failed' else 'ok' if done else 'stale'
        out[c.id] = row
    return dict(stages=names, clips=out, dependents={n: dependents(n) for n in names})


def discover(race, cfg):
    return clipmod.discover(cfg['library'])


def track_signature(race, cfg):
    """Identity of everything the clip-to-track match depends on: the track file's content and the camera clock (offset, drift): None when there is no track. A change of either makes every
    stage that uses the track out of date, so it is redone."""
    p = config.track_path(race, cfg)
    if not p: return None
    h = hashlib.sha1(); size = os.path.getsize(p); h.update(str(size).encode())
    with open(p, 'rb') as f:
        h.update(f.read(1 << 20)); f.seek(max(size - (1 << 20), 0)); h.update(f.read(1 << 20))
    return _sha([h.hexdigest(), cfg.get('camera_clock', {}).get('utc_offset_hours'), cfg.get('camera_clock', {}).get('offset_seconds'), cfg.get('camera_clock', {}).get('drift_s_per_day'), cfg.get('camera_clock', {}).get('drift_ref_camera_time')])


def _cached(race, st, c, cfg, state, ctx_dir):
    """(is_done, key, blocked_by) for one item given the clip's state."""
    deps = {d: state.get(d, {}) for d in st.deps}; bad = [d for d, v in deps.items() if v.get('status') != 'ok']
    extra = None
    if st.needs_track:
        extra = track_signature(race, cfg)
        if extra is None: bad = bad + ['race_track']                                               # paused until a track is set
    if bad: return False, None, bad
    key = stage_key(st, c, cfg, {d: v.get('key') for d, v in deps.items()}, extra); cur = state.get(st.name, {}); clock_sig = _sha(cfg.get('camera_clock'))
    if st.name == 'ingest' and cur.get('key') and cur.get('version') == st.version and cur.get('fp', c.fingerprint) == c.fingerprint: key = cur['key']    # frozen identity: a clock change re-times, it does not invalidate clip-relative stages
    done = cur.get('status') == 'ok' and cur.get('key') == key and all(os.path.exists(os.path.join(ctx_dir, o)) for o in st.outputs) and (st.name != 'ingest' or cur.get('clock') == clock_sig)
    return done, key, []


def work(race, stages=None, clip_glob=None, log=print, fail_fast=False, max_items=None):
    """One worker: process unfinished, unclaimed items until none is left. Safe to run several at once. Returns {(clip, stage): 'ok'|'failed'} for what this worker did."""
    cfg = config.load(race); rd = config.race_dir(race); names = [s for s in ORDER if s in (stages or cfg['stages'])]
    unknown = set(stages or []) - set(STAGES)
    if unknown: raise SystemExit(f'unknown stage(s): {sorted(unknown)}; available: {ORDER}')
    cl, other = discover(race, cfg)
    if clip_glob: cl = [c for c in cl if fnmatch.fnmatch(c.id, clip_glob) or clip_glob in c.id]
    os.makedirs(_workers(race), exist_ok=True); reg = os.path.join(_workers(race), str(os.getpid())); open(reg, 'w').write(dt.datetime.now().isoformat(timespec='seconds'))
    atexit.register(lambda: os.path.exists(reg) and os.remove(reg))
    logf = open(os.path.join(rd, 'run.log'), 'a')

    def L(msg):
        line = f"{dt.datetime.now().strftime('%H:%M:%S')} [{os.getpid()}] {msg}"; log(line); logf.write(line + '\n'); logf.flush()

    result = {}; tried = set(); L(f'worker started: {len(cl)} clips, stages {names}')
    while max_items is None or len(result) < max_items:
        picked = None
        for name in names:
            st = STAGES[name]
            for n, c in enumerate(cl, 1):
                if (c.id, name) in tried: continue
                state = load_state(race, c.id); done, key, blocked = _cached(race, st, c, cfg, state, clip_dir(race, c.id))
                if done or blocked: continue
                if not claim(race, c.id, name): continue
                state = load_state(race, c.id); done, key, blocked = _cached(race, st, c, cfg, state, clip_dir(race, c.id))      # someone may have finished it between the look and the claim
                if done or blocked: release(race, c.id, name); continue
                picked = (n, c, st, key); break
            if picked: break
        if not picked: break
        n, c, st, key = picked; name = st.name; tried.add((c.id, name)); ctx = Ctx(c, cfg, clip_dir(race, c.id), L); os.makedirs(ctx.dir, exist_ok=True); clock_sig = _sha(cfg.get('camera_clock')); t0 = time.time()
        try:
            st.fn(ctx)
            if name == 'ingest':
                from strata360.pipeline.ingest import restamp; n_re = restamp(ctx.dir)
                if n_re: L(f'    re-stamped {n_re} artefacts with the new time')
            update_state(race, c.id, name, dict(status='ok', key=key, version=st.version, clock=clock_sig, fp=c.fingerprint, seconds=round(time.time() - t0, 1), at=dt.datetime.now().isoformat(timespec='seconds')))
            result[(c.id, name)] = 'ok'; L(f'[{n}/{len(cl)}] {c.id} {name}: ok ({time.time() - t0:.1f} s)')
        except Exception as e:
            update_state(race, c.id, name, dict(status='failed', key=key, version=st.version, seconds=round(time.time() - t0, 1), error=''.join(traceback.format_exception_only(type(e), e)).strip(), trace=traceback.format_exc()[-1500:]))
            result[(c.id, name)] = 'failed'; L(f'[{n}/{len(cl)}] {c.id} {name}: FAILED {e!r}')
            if fail_fast: release(race, c.id, name); raise
        finally:
            release(race, c.id, name)
    if not workers(race) or workers(race) == [os.getpid()]:
        json.dump(dict(race=race, generated=dt.datetime.now().isoformat(timespec='seconds'), clips=[c.to_dict() for c in cl], unsupported=[dict(path=p, reason=r) for p, r in other]), open(os.path.join(rd, 'catalog.json'), 'w'), indent=1)
    counts = {}
    for v in result.values(): counts[v] = counts.get(v, 0) + 1
    L(f'worker done: {counts or "nothing left to do"}'); logf.close()
    try: os.remove(reg)
    except OSError: pass
    return result


def run(race, stages=None, clip_glob=None, force=False, log=print, fail_fast=False):
    """Compatibility wrapper: `force` clears the selected stages (and dependents) for the selected clips first, then works like any worker."""
    if force:
        cfg = config.load(race); sel = [s for s in ORDER if s in (stages or cfg['stages'])]
        cl, _ = discover(race, cfg); ids = [c.id for c in cl if not clip_glob or fnmatch.fnmatch(c.id, clip_glob) or clip_glob in c.id]
        for s in sel: clear(race, s, ids, cascade=False)
    return work(race, stages, clip_glob, log, fail_fast)
