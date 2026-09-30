"""Run stages over a race's clips with caching, fail-soft error handling, an atomic state file per clip and a run lock."""
import datetime as dt, fnmatch, hashlib, json, os, sys, time, traceback
from strata360.pipeline import config, clips as clipmod
from strata360.pipeline.stages import STAGES, ORDER, Ctx


def clip_dir(race, clip_id):
    return os.path.join(config.race_dir(race), 'clips', clip_id)


def _sha(obj): return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def stage_key(stage, clip, cfg, dep_keys):
    """Changes when the code version, the clip content, the relevant config, or an upstream result changes."""
    return _sha([stage.name, stage.version, clip.fingerprint, {k: cfg.get(k) for k in stage.keys}, dep_keys])


def load_state(race, clip_id):
    p = os.path.join(clip_dir(race, clip_id), 'stages.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def save_state(race, clip_id, state):
    d = clip_dir(race, clip_id); os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, 'stages.json.tmp'); json.dump(state, open(tmp, 'w'), indent=1); os.replace(tmp, os.path.join(d, 'stages.json'))


class Lock:
    def __init__(self, race): self.p = os.path.join(config.race_dir(race), '.lock')
    def __enter__(self):
        if os.path.exists(self.p):
            pid = int(open(self.p).read().strip() or 0)
            try: os.kill(pid, 0); raise RuntimeError(f'another run is active on this race (pid {pid}); remove {self.p} if that is stale')
            except ProcessLookupError: pass
        open(self.p, 'w').write(str(os.getpid())); return self
    def __exit__(self, *a):
        try: os.remove(self.p)
        except OSError: pass


def discover(race, cfg):
    cl, other = clipmod.discover(cfg['library'])
    return cl, other


def run(race, stages=None, clip_glob=None, force=False, log=print, fail_fast=False):
    """Run `stages` (default: the race's configured set) over the selected clips. Returns {(clip, stage): status}."""
    cfg = config.load(race); rd = config.race_dir(race)
    names = [s for s in ORDER if s in (stages or cfg['stages'])]
    unknown = set(stages or []) - set(STAGES)
    if unknown: raise SystemExit(f'unknown stage(s): {sorted(unknown)}; available: {ORDER}')
    cl, other = discover(race, cfg)
    if clip_glob: cl = [c for c in cl if fnmatch.fnmatch(c.id, clip_glob) or clip_glob in c.id]
    logf = open(os.path.join(rd, 'run.log'), 'a')
    def L(msg):
        line = f"{dt.datetime.now().strftime('%H:%M:%S')} {msg}"; log(line); logf.write(line + '\n'); logf.flush()
    result = {}
    with Lock(race):
        L(f'race {race}: {len(cl)} clips, stages {names}' + (' (force)' if force else ''))
        for name in names:
            st = STAGES[name]
            for n, c in enumerate(cl, 1):
                state = load_state(race, c.id); ctx = Ctx(c, cfg, clip_dir(race, c.id), L); os.makedirs(ctx.dir, exist_ok=True)
                deps = {d: state.get(d, {}) for d in st.deps}
                if any(v.get('status') != 'ok' for v in deps.values()):
                    result[(c.id, name)] = 'blocked'; L(f'[{n}/{len(cl)}] {c.id} {name}: blocked (needs {[d for d, v in deps.items() if v.get("status") != "ok"]})'); continue
                key = stage_key(st, c, cfg, {d: v.get('key') for d, v in deps.items()})
                cur = state.get(name, {}); clock_sig = _sha(cfg.get('camera_clock'))
                if name == 'ingest' and cur.get('key') and cur.get('version') == st.version and cur.get('fp', c.fingerprint) == c.fingerprint: key = cur['key']     # frozen identity: a camera-clock change re-times (below) but does not invalidate stages whose data is clip-relative
                if not force and cur.get('status') == 'ok' and cur.get('key') == key and all(os.path.exists(ctx.path(o)) for o in st.outputs) and (name != 'ingest' or cur.get('clock') == clock_sig):
                    result[(c.id, name)] = 'cached'; L(f'[{n}/{len(cl)}] {c.id} {name}: cached'); continue
                t0 = time.time()
                try:
                    st.fn(ctx)
                    if name == 'ingest':
                        from strata360.pipeline.ingest import restamp; n_re = restamp(ctx.dir)
                        if n_re: L(f'    re-stamped {n_re} artefacts with the new time')
                    state[name] = dict(status='ok', key=key, version=st.version, clock=clock_sig, fp=c.fingerprint, seconds=round(time.time() - t0, 1), at=dt.datetime.now().isoformat(timespec='seconds')); result[(c.id, name)] = 'ok'
                    L(f'[{n}/{len(cl)}] {c.id} {name}: ok ({time.time() - t0:.1f} s)')
                except Exception as e:
                    state[name] = dict(status='failed', key=key, version=st.version, seconds=round(time.time() - t0, 1), error=''.join(traceback.format_exception_only(type(e), e)).strip(),
                                       trace=traceback.format_exc()[-1500:]); result[(c.id, name)] = 'failed'
                    L(f'[{n}/{len(cl)}] {c.id} {name}: FAILED {e!r}')
                    if fail_fast: save_state(race, c.id, state); raise
                save_state(race, c.id, state)
        json.dump(dict(race=race, generated=dt.datetime.now().isoformat(timespec='seconds'), clips=[c.to_dict() for c in cl], unsupported=[dict(path=p, reason=r) for p, r in other]),
                  open(os.path.join(rd, 'catalog.json'), 'w'), indent=1)
    counts = {}
    for v in result.values(): counts[v] = counts.get(v, 0) + 1
    L(f'done: {counts}')
    logf.close()
    return result
