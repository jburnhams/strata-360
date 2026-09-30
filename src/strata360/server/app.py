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
JOBS = {}                     # folder -> Popen of a running `strata360 open`
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
    for n in names:
        if n.startswith('.') : continue
        full = os.path.join(real, n)
        if os.path.isdir(full):
            try: real_child = safe_path(roots, full)
            except Forbidden: continue                                                                    # a symlink pointing out of the roots is not shown
            items.append(dict(name=n, path=real_child, kind='dir', is_project=os.path.exists(os.path.join(real_child, config.PROJECT_SUBFOLDER, 'race.json'))))
        elif os.path.splitext(n)[1].lower() in clipmod.SUPPORTED: n_footage += 1
    parent = os.path.dirname(real); parent = parent if any(parent == r or parent.startswith(r + os.sep) for r in roots) else None
    return dict(path=real, parent=parent, footage_here=n_footage, is_project=os.path.exists(os.path.join(real, config.PROJECT_SUBFOLDER, 'race.json')), entries=items)


def start_job(folder, args=('open',)):
    with LOCK:
        j = JOBS.get(folder)
        if j and j.poll() is None: return False
        rd = config.race_dir(folder); os.makedirs(rd, exist_ok=True)
        log = open(os.path.join(rd, 'server_job.log'), 'ab')
        JOBS[folder] = subprocess.Popen([os.path.join(ROOT_DIR, 'strata360'), args[0], folder, *args[1:]], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR)
        return True


def progress(folder):
    from strata360.cli import project_progress
    p = project_progress(folder); j = JOBS.get(folder); p['job_running'] = bool(j and j.poll() is None); return p


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

    @api.get('/api/clips', dependencies=[Depends(auth)])
    def get_clips(folder: str):                                                          # the clips of a project with the facts the notes panel shows next to each
        from strata360.pipeline import notes as N
        f = folder_of(folder); rd = config.race_dir(f); out = []; nt = N.load(f)
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            try: c = json.load(open(d + 'clip.json'))
            except OSError: continue
            out.append(dict(id=c['clip_id'], start_utc=c['time']['start_utc'], duration_s=round(c['video']['source_frames'] / c['video']['nominal_fps'], 1), has_note=bool(nt['clips'].get(c['clip_id']))))
        return dict(clips=out)

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

    @api.post('/api/open', dependencies=[Depends(auth)])
    def post_open(body: dict):                                                             # create the project if new, then continue whatever is unfinished
        f = folder_of(body.get('folder')); args = ['open']
        if body.get('languages'): args += ['--languages', str(body['languages'])]
        if body.get('gps'): args += ['--gps', folder_of(body['gps'])]
        return dict(started=start_job(f, tuple(args)))

    @api.post('/api/run', dependencies=[Depends(auth)])
    def post_run(body: dict): return dict(started=start_job(folder_of(body.get('folder'))))

    @api.post('/api/stop', dependencies=[Depends(auth)])
    def post_stop(body: dict):
        j = JOBS.get(folder_of(body.get('folder')))
        if j and j.poll() is None: j.terminate()
        return dict(stopped=bool(j))

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
