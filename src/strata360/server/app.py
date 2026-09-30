"""strata360 web server: run it on the machine that holds the footage, open it from any browser.

    ./strata360 serve --root ~/footage --root /Volumes/Expansion [--host 127.0.0.1] [--port 8360] [--token SECRET]

Built on FastAPI (interactive API docs at /api/docs). Security model: the server can only see inside the whitelisted roots (`--root`, repeatable, or `~/.strata360/server.json` {"roots": [...]}); every path from the browser is resolved
(symlinks included) and refused if it leaves a root. It binds to 127.0.0.1 unless told otherwise; when bound to another address a token is required (sent as a cookie after
`?token=` on first visit, or as `Authorization: Bearer`). Nothing here deletes or modifies footage; the only writes are the project folders (`<footage>/strata360/`).

API (JSON):  GET /api/roots, /api/browse?path=, /api/progress?folder=, /api/log?folder=;  POST /api/open {folder, languages?, gps?}, /api/run {folder}, /api/stop {folder}."""
import argparse, glob, json, os, secrets, subprocess, sys, threading, time

from strata360.pipeline import config, clips as clipmod

STATIC = os.path.join(os.path.dirname(__file__), 'static')
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
JOBS = {}                     # folder -> [Popen] of workers started by this server (workers started elsewhere are found through the project's registry)
MAX_WORKERS = 3
SCRIPT_JOBS = {}              # folder -> Popen of a running `strata360 script`
LOCK = threading.Lock()


class Forbidden(Exception): pass


def load_roots(cli_roots):
    roots = list(cli_roots or [])
    p = os.path.expanduser('~/.strata360/server.json')
    if os.path.exists(p):
        try: roots += json.load(open(p)).get('roots', [])
        except ValueError: pass
    return [os.path.realpath(os.path.expanduser(r)) for r in roots if os.path.isdir(os.path.expanduser(r))]


def safe_path(roots, path):
    """Resolve `path` (symlinks too) and require it to be inside a whitelisted root; returns the real path."""
    if not path: raise Forbidden('no path')
    real = os.path.realpath(os.path.expanduser(path))
    for r in roots:
        if real == r or real.startswith(r + os.sep): return real
    raise Forbidden('outside the allowed folders')


def browse(roots, path):
    real = safe_path(roots, path); items = []; n_footage = 0
    try: names = sorted(os.listdir(real), key=str.lower)
    except OSError as e: raise Forbidden(str(e))
    is_proj = os.path.exists(os.path.join(real, config.PROJECT_SUBFOLDER, 'race.json'))
    for n in ([] if is_proj else names):                                                                  # a project folder is opened as a whole: its sub-folders are not offered
        if n.startswith('.') or n == config.PROJECT_SUBFOLDER: continue
        full = os.path.join(real, n)
        if os.path.isdir(full):
            try: real_child = safe_path(roots, full)
            except Forbidden: continue                                                                    # a symlink pointing out of the roots is not shown
            items.append(dict(name=n, path=real_child, kind='dir', is_project=os.path.exists(os.path.join(real_child, config.PROJECT_SUBFOLDER, 'race.json'))))
        elif os.path.splitext(n)[1].lower() in clipmod.SUPPORTED: n_footage += 1
    parent = os.path.dirname(real); parent = parent if any(parent == r or parent.startswith(r + os.sep) for r in roots) else None
    return dict(path=real, parent=parent, footage_here=n_footage, is_project=is_proj, can_create=(not is_proj and real not in roots and (n_footage > 0 or has_footage(real))), entries=items)


def has_footage(folder, depth=3):
    """True if a supported camera file exists in `folder` or up to `depth` levels below (stops at the first hit; never descends into our own results folder)."""
    base = folder.rstrip(os.sep).count(os.sep)
    seen = 0
    for root, dirs, files in os.walk(folder):
        seen += 1
        if seen > 300: return False                                                                       # a huge tree is not scanned for ever (an external drive can be slow)
        dirs[:] = [d for d in dirs if d != config.PROJECT_SUBFOLDER and not d.startswith('.')]
        if root.count(os.sep) - base >= depth: dirs[:] = []
        if any(os.path.splitext(n)[1].lower() in clipmod.SUPPORTED for n in files): return True
    return False


STATE = os.path.expanduser('~/.strata360/state.json')


def remember(folder):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    try: d = json.load(open(STATE))
    except (OSError, ValueError): d = {}
    d['last_project'] = folder; json.dump(d, open(STATE, 'w'))


def last_project(roots):
    try: f = json.load(open(STATE)).get('last_project')
    except (OSError, ValueError): return None
    try: f = safe_path(roots, f)
    except Forbidden: return None
    return f if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None


def start_job(folder, args=('open',)):
    """Start one more worker on the project (returns False when the maximum are already running). Each worker loops until nothing is left; extra workers pick up unfinished, unclaimed items."""
    from strata360.pipeline import runner
    with LOCK:
        live = [p for p in JOBS.get(folder, []) if p.poll() is None]; JOBS[folder] = live
        from strata360.pipeline import resources
        cfg = config.load(folder) if os.path.exists(os.path.join(config.race_dir(folder), 'race.json')) else {}
        ok, why = resources.may_start_extra_worker(len(runner.workers(folder)), cfg)
        if not ok: return False
        rd = config.race_dir(folder); os.makedirs(rd, exist_ok=True); log = open(os.path.join(rd, 'server_job.log'), 'ab')
        live.append(subprocess.Popen([os.path.join(ROOT_DIR, 'strata360'), args[0], folder, *args[1:]], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True)); return True


def progress(folder):
    from strata360.cli import project_progress
    p = project_progress(folder); from strata360.pipeline import resources; p['job_running'] = bool(p.get('workers')); p['max_workers'] = resources.DEFAULTS['max_workers']; return p


def create_app(roots, token=None):
    """The FastAPI application. `roots` are the only folders it may look inside; `token` (optional) is required on every request (cookie, `?token=` on first visit, or Bearer)."""
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse, Response

    api = FastAPI(title='strata360', docs_url='/api/docs', openapi_url='/api/openapi.json')

    def auth(request: Request):
        if not token: return
        if request.query_params.get('token') == token or request.headers.get('authorization') == f'Bearer {token}' or request.cookies.get('strata360_token') == token: return
        raise HTTPException(401, 'token required')

    def folder_of(path):
        try: return safe_path(roots, path)
        except Forbidden as e: raise HTTPException(403, str(e))

    @api.middleware('http')
    async def cookie(request: Request, call_next):                                        # a valid ?token= on the first visit becomes a cookie
        resp = await call_next(request)
        if token and request.query_params.get('token') == token: resp.set_cookie('strata360_token', token, httponly=True, samesite='strict')
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    @api.get('/', dependencies=[Depends(auth)])
    def index():
        f = os.path.join(STATIC, 'index.html')
        if not os.path.exists(f): return Response('The web app is not built yet: cd web && npm install && npm run build', status_code=503)
        return FileResponse(f)

    if os.path.isdir(os.path.join(STATIC, 'assets')):                                    # the built React app (web/): hashed JS/CSS
        from fastapi.staticfiles import StaticFiles
        api.mount('/assets', StaticFiles(directory=os.path.join(STATIC, 'assets')), name='assets')

    @api.get('/api/last', dependencies=[Depends(auth)])
    def get_last(): return dict(folder=last_project(roots))                                 # the project opened last time, if it still exists inside an allowed root

    @api.get('/api/roots', dependencies=[Depends(auth)])
    def get_roots(): return dict(roots=roots)

    @api.get('/api/browse', dependencies=[Depends(auth)])
    def get_browse(path: str = None):
        try: return browse(roots, path or roots[0])
        except Forbidden as e: raise HTTPException(403, str(e))

    @api.get('/api/progress', dependencies=[Depends(auth)])
    def get_progress(folder: str): return progress(folder_of(folder))

    @api.get('/api/log', dependencies=[Depends(auth)])
    def get_log(folder: str):
        p = os.path.join(config.race_dir(folder_of(folder)), 'run.log')
        return dict(lines=open(p).read().splitlines()[-40:] if os.path.exists(p) else [])

    def _cd(f, clip):
        d = os.path.join(config.race_dir(f), 'clips', os.path.basename(clip))                         # basename: a clip id can never climb out of the project
        if not os.path.isdir(d): raise HTTPException(404, 'no such clip')
        return d

    def _j(d, name):
        p = os.path.join(d, name)
        try: return json.load(open(p)) if os.path.exists(p) else None
        except ValueError: return None

    @api.get('/api/clips', dependencies=[Depends(auth)])
    def get_clips(folder: str):                                                          # the clip list: id, time, length, a note flag, whether a thumbnail exists and a few facts
        from strata360.pipeline import notes as N
        f = folder_of(folder); rd = config.race_dir(f); out = []; nt = N.load(f)
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json')
            if not c: continue
            mo = _j(d, 'motion.json'); cd = _j(d, 'candidates.json'); thumb = 'best' if os.path.exists(d + 'thumb.jpg') else 'quick' if os.path.exists(d + 'thumb_quick.jpg') else None
            out.append(dict(id=c['clip_id'], start_utc=c['time']['start_utc'], duration_s=round(c['video']['source_frames'] / c['video']['nominal_fps'], 1), has_note=bool(nt['clips'].get(c['clip_id'])),
                            thumb=thumb, steady=None if not mo else mo['summary']['steady'], candidates=None if not cd else cd['summary']['n']))
        return dict(clips=out)

    @api.get('/api/transcript', dependencies=[Depends(auth)])
    def get_transcript(folder: str):                                                     # every recognised phrase of every clip, in clip order: the overview's running transcript
        f = folder_of(folder); rd = config.race_dir(f); out = []
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json'); tr = _j(d, 'transcript.json')
            if not c or not tr: continue
            sp = _j(d, 'speakers.json'); lab = {(round(s['t0'], 2), round(s['t1'], 2)): s.get('label') for s in (sp or {}).get('segments', [])}
            for s in tr['segments']:
                if not s.get('text', '').strip(): continue
                out.append(dict(clip=c['clip_id'], t0=round(s['t0'], 2), t1=round(s['t1'], 2), lang=s['lang'], text=s['text'].strip(), text_en=s.get('text_en'), flagged=bool(s.get('flags') or s.get('suspect')), who=lab.get((round(s['t0'], 2), round(s['t1'], 2)))))
        return dict(segments=out)

    @api.get('/api/meta', dependencies=[Depends(auth)])
    def get_meta_tz(folder: str):
        from strata360.pipeline import meta as M
        f = folder_of(folder); m = M.load(f); m['timezone'] = (config.load(f).get('timezone') if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None) or 'Europe/Brussels'; return m

    @api.get('/api/thumb')
    def get_thumb(request: Request, folder: str, clip: str):                              # the image itself: an <img> tag cannot send headers, so the cookie/query token is what authenticates it
        auth(request); f = folder_of(folder); d = _cd(f, clip)
        for n in ('thumb.jpg', 'thumb_quick.jpg'):
            if os.path.exists(os.path.join(d, n)): return FileResponse(os.path.join(d, n), media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
        raise HTTPException(404, 'no thumbnail yet')

    @api.get('/api/preview')
    def get_preview(request: Request, folder: str, clip: str):                           # the preview video (Range requests are handled, so seeking works); <video> cannot send headers, so the cookie/query token authenticates
        auth(request); f = folder_of(folder); p = os.path.join(_cd(f, clip), 'preview.mp4')
        if not os.path.exists(p): raise HTTPException(404, 'the preview has not been made yet')
        return FileResponse(p, media_type='video/mp4', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/clip', dependencies=[Depends(auth)])
    def get_clip(folder: str, clip: str):                                                # everything known about one clip, for its detail view
        from strata360.pipeline import notes as N
        f = folder_of(folder); d = _cd(f, clip); c = _j(d, 'clip.json'); out = dict(id=c['clip_id'], time=c['time'], video=c['video'], camera=c.get('camera'), audio_info=c.get('audio'), note=N.load(f)['clips'].get(c['clip_id'], ''))
        mo = _j(d, 'motion.json'); out['motion'] = None if not mo else mo['summary']
        au = _j(d, 'audio.json'); out['audio'] = None if not au else dict(summary=au.get('summary'), segments=au.get('segments', [])[:40])
        tr = _j(d, 'transcript.json'); sp = _j(d, 'speakers.json'); lab = {(round(s['t0'], 2), round(s['t1'], 2)): s.get('label') for s in (sp or {}).get('segments', [])}
        out['transcript'] = [dict(t0=s['t0'], t1=s['t1'], lang=s['lang'], text=s['text'], text_en=s.get('text_en'), flagged=bool(s.get('flags')), who=lab.get((round(s['t0'], 2), round(s['t1'], 2)))) for s in (tr or {}).get('segments', [])]
        sc = _j(d, 'scenes.json'); out['scenes'] = None if not sc else dict(summary=sc['summary'], items=[i for i in sc['items'] if i['ok'] and i['view'] == 'front'][:60])
        idn = _j(d, 'identity.json'); out['identity'] = None if not idn else idn['summary']
        cd = _j(d, 'candidates.json'); out['candidates'] = None if not cd else [{k: v for k, v in x.items() if k not in ('transcript', 'cuts')} for x in cd['candidates']]
        mo_ = _j(d, 'motion.json'); out['heading'] = None if not mo_ else dict(t=mo_['series']['t'], deg=mo_['series']['heading_deg']); pv = os.path.join(d, 'preview.mp4'); out['preview'] = os.path.exists(pv) and os.path.getsize(pv) > 0
        try:
            from strata360.analysis.views import focus_samples
            out['focus'] = focus_samples(d, c['source_files']['osv'])
        except Exception: out['focus'] = []
        out['unusable'] = None if not cd else cd.get('unusable', []); out['thresholds'] = None if not cd else cd.get('thresholds')
        ex = _j(d, 'exposure.json'); out['exposure'] = None if not ex else ex['summary']
        th = _j(d, 'thumb.json') or _j(d, 'thumb_quick.json'); out['thumb'] = th; out['places'] = _j(d, 'places.json')
        p = config.track_path(f, config.load(f))
        if p:
            import datetime as dt
            from strata360.gps import track, context as X
            t0 = dt.datetime.fromisoformat(c['time']['start_utc'].replace('Z', '+00:00')).timestamp(); t1 = dt.datetime.fromisoformat(c['time']['end_utc'].replace('Z', '+00:00')).timestamp()
            ctx = X.context_at(track.load(p), t0, t1); out['track'] = ctx; out['track_text'] = X.describe(ctx)
        return out

    @api.post('/api/meta', dependencies=[Depends(auth)])
    def post_meta(body: dict):                                                           # {folder, title?, date?, results?: {starters, finishers, finished, position}}
        from strata360.pipeline import meta as M
        try: return M.save(folder_of(body.get('folder')), {k: v for k, v in body.items() if k != 'folder'})
        except (ValueError, TypeError) as e: raise HTTPException(400, str(e))

    @api.get('/api/notes', dependencies=[Depends(auth)])
    def get_notes(folder: str):
        from strata360.pipeline import notes as N
        return N.load(folder_of(folder))

    @api.post('/api/notes', dependencies=[Depends(auth)])
    def post_notes(body: dict):                                                          # {folder, text, clip?}: the folder note, or one clip's note
        from strata360.pipeline import notes as N
        return N.save(folder_of(body.get('folder')), body.get('text', ''), body.get('clip'))

    @api.get('/api/track', dependencies=[Depends(auth)])
    def get_track(folder: str):                                                          # overview map + main stats of the race track, or {present: false}
        f = folder_of(folder); p = config.track_path(f, config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None)
        if not p: return dict(present=False)
        from strata360.gps.overview import overview
        try: return overview(p)
        except Exception as e: return dict(present=True, error=f'{type(e).__name__}: {e}')

    @api.post('/api/track', dependencies=[Depends(auth)])
    async def post_track(request: Request, folder: str, filename: str = 'track.fit'):    # the file is the raw request body; saved under the known name track.fit / track.gpx
        f = folder_of(folder); ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.fit', '.gpx'): raise HTTPException(400, 'a .fit or .gpx file, please')
        data = await request.body()
        if len(data) < 200 or len(data) > 200 * 1024 * 1024: raise HTTPException(400, 'the file is empty or too large')
        rd = config.race_dir(f); os.makedirs(rd, exist_ok=True)
        for n in config.TRACK_NAMES:
            for suffix in ('', '.npz'):
                q = os.path.join(rd, n + suffix)
                if os.path.exists(q): os.replace(q, q + '.replaced')                       # keep the previous file next to it, never silently lose it
        dest = os.path.join(rd, 'track' + ext); open(dest, 'wb').write(data)
        from strata360.gps.overview import overview
        try: return overview(dest)
        except Exception as e:
            os.replace(dest, dest + '.bad'); raise HTTPException(400, f'could not read that file: {type(e).__name__}: {e}')

    @api.get('/api/script', dependencies=[Depends(auth)])
    def get_script(folder: str):                                                         # key status (never the key), the model list, whether a run is going, and the newest script
        from strata360.edit import llm_remote as LR
        f = folder_of(folder); rd = config.race_dir(f); j = SCRIPT_JOBS.get(f); running = bool(j and j.poll() is None)
        files = sorted(glob.glob(os.path.join(rd, 'scripts', 'script-*.json'))); latest = None
        if files:
            try: latest = json.load(open(files[-1])); latest.pop('facts', None); latest['file'] = os.path.basename(files[-1])
            except ValueError: latest = None
        log = ''
        try: log = open(os.path.join(rd, 'script_job.log')).read()[-600:]
        except OSError: pass
        cfg = config.load(f).get('llm', {}) if os.path.exists(os.path.join(rd, 'race.json')) else {}
        prov = cfg.get('provider', 'gemini'); providers = {k: dict(models=v['models'], default=v['default'], configured=LR.key_configured(k)) for k, v in LR.PROVIDERS.items()}
        return dict(key_configured=providers.get(prov, {}).get('configured', False), providers=providers, models=LR.PROVIDERS.get(prov, LR.PROVIDERS['gemini'])['models'], llm=dict(provider=prov, model=cfg.get('model') or LR.PROVIDERS[prov]['default']), running=running,
                    last_exit=None if (j is None or running) else j.returncode, log=log, latest=latest, scripts=len(files))

    @api.post('/api/llm/key', dependencies=[Depends(auth)])
    def post_key(body: dict):                                                            # write-only: the key is stored server-side (mode 600) and never returned
        from strata360.edit import llm_remote as LR
        prov = body.get('provider') if body.get('provider') in LR.PROVIDERS else 'gemini'
        try: return dict(configured=LR.set_key(str(body.get('key') or ''), prov))
        except LR.LLMError as e: raise HTTPException(400, str(e))

    @api.post('/api/script/generate', dependencies=[Depends(auth)])
    def post_generate(body: dict):                                                       # {folder, length, wpm?, style?, model?}: runs `strata360 script` in the background
        f = folder_of(body.get('folder')); j = SCRIPT_JOBS.get(f)
        if j and j.poll() is None: return dict(started=False)
        args = [os.path.join(ROOT_DIR, 'strata360'), 'script', f, '--length', str(float(body.get('length') or 90))]
        if body.get('wpm'): args += ['--wpm', str(float(body['wpm']))]
        if body.get('style'): args += ['--style', str(body['style'])[:400]]
        from strata360.edit import llm_remote as LR
        prov = body.get('provider') if body.get('provider') in LR.PROVIDERS else None
        if prov: args += ['--provider', prov]
        if body.get('model') in [m for v in LR.PROVIDERS.values() for m in v['models']]: args += ['--model', body['model']]
        rd = config.race_dir(f); os.makedirs(rd, exist_ok=True); log = open(os.path.join(rd, 'script_job.log'), 'wb')
        SCRIPT_JOBS[f] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/open', dependencies=[Depends(auth)])
    def post_open(body: dict):                                                             # create the project if new, then continue whatever is unfinished
        f = folder_of(body.get('folder')); args = ['open']
        if f in roots: raise HTTPException(400, 'that is an allowed root, not a footage folder: choose the folder that holds the camera files')
        if not os.path.exists(os.path.join(config.race_dir(f), 'race.json')) and not has_footage(f): raise HTTPException(400, 'no camera files (.OSV) found in that folder or its sub-folders (down to 3 levels)')
        if body.get('languages'): args += ['--languages', str(body['languages'])]
        if body.get('gps'): args += ['--gps', folder_of(body['gps'])]
        remember(f); return dict(started=start_job(f, tuple(args)))

    @api.post('/api/run', dependencies=[Depends(auth)])
    def post_run(body: dict): return dict(started=start_job(folder_of(body.get('folder'))))

    @api.post('/api/stop', dependencies=[Depends(auth)])
    def post_stop(body: dict):                                                           # stop every worker on the project (their claimed items are released and picked up again later)
        import signal
        from strata360.pipeline import runner
        f = folder_of(body.get('folder')); pids = runner.workers(f)
        if body.get('pid') is not None: pids = [p for p in pids if p == int(body['pid'])]                  # one worker (only a registered worker of this project can be signalled)
        for pid in pids: runner.kill_tree(pid, signal.SIGTERM)
        return dict(stopped=len(pids))

    @api.get('/api/state', dependencies=[Depends(auth)])
    def get_state(folder: str):                                                          # the (clip x stage) status matrix, for the redo dialog and the clip stage badges
        from strata360.pipeline import runner
        return runner.item_states(folder_of(folder))

    @api.post('/api/clear', dependencies=[Depends(auth)])
    def post_clear(body: dict):                                                          # {folder, items: [{clip, stage}]}: forget those statuses so they are processed again
        from strata360.pipeline import runner
        f = folder_of(body.get('folder')); items = [(str(i['clip']), str(i['stage'])) for i in body.get('items', [])]
        return dict(cleared=runner.clear_items(f, items))

    return api


def main(argv=None):
    ap = argparse.ArgumentParser(prog='strata360 serve'); ap.add_argument('--root', action='append', help='folder the browser may look inside (repeatable)'); ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8360); ap.add_argument('--token', help='shared secret (required when --host is not 127.0.0.1; generated if omitted)'); a = ap.parse_args(argv)
    roots = load_roots(a.root)
    if not roots: sys.exit('no allowed folders: give --root PATH (repeatable) or list them in ~/.strata360/server.json {"roots": [...]}')
    token = a.token if a.token else (secrets.token_urlsafe(16) if a.host not in ('127.0.0.1', 'localhost') else None)
    print(f'strata360 server on http://{a.host}:{a.port}/' + (f'?token={token}' if token else '')); print('allowed folders:', ', '.join(roots))
    import uvicorn; uvicorn.run(create_app(roots, token), host=a.host, port=a.port, log_level='warning')


if __name__ == '__main__':
    main()
