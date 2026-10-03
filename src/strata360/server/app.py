"""strata360 web server: run it on the machine that holds the footage, open it from any browser.

    ./strata360 serve --root ~/footage --root /Volumes/Expansion [--host 127.0.0.1] [--port 8360] [--token SECRET]

Built on FastAPI (interactive API docs at /api/docs). Security model: the server can only see inside the whitelisted roots (`--root`, repeatable, or `~/.strata360/server.json` {"roots": [...]}); every path from the browser is resolved
(symlinks included) and refused if it leaves a root. It binds to 127.0.0.1 unless told otherwise; when bound to another address a token is required (sent as a cookie after
`?token=` on first visit, or as `Authorization: Bearer`). Nothing here deletes or modifies footage; the only writes are the project folders (`<footage>/strata360/`).

API (JSON):  GET /api/roots, /api/browse?path=, /api/progress?folder=, /api/log?folder=;  POST /api/open {folder, languages?, gps?}, /api/run {folder}, /api/stop {folder}."""
import argparse, glob, io, json, os, re, secrets, subprocess, sys, threading, time
from strata360.edit.script_pack import norm_label

from strata360 import oslib
from strata360.pipeline import config, clips as clipmod
from strata360.analysis import thumbs as TH, transcript_edits as TE, transcript_fix as TF, transcript_marks as TM

STATIC = os.path.join(os.path.dirname(__file__), 'static')
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
JOBS = {}                     # folder -> [Popen] of workers started by this server (workers started elsewhere are found through the project's registry)
MAX_WORKERS = 3
FINAL_JOBS = {}; FILM_JOBS = {}
TILES = {}                    # map style -> overlay.tiles.Tiles (one per style, shared by every request)
TILE_FETCH = None             # tests replace this: fetch(url) -> bytes
_NOISE = ('unsupported hash type', 'code for hash', 'hashlib.py', 'globals()[__func_name]', '__get_builtin_constructor', '__get_openssl_constructor')


def clean_log(lines):
    """Log lines without the interpreter's start-up noise (a pyenv Python 3.13 without blake2 prints a hashlib traceback into every job's log): the web panels show the last line, which must be the job's own."""
    lines = list(lines); out = []
    for i, l in enumerate(lines):
        if any(n in l for n in _NOISE) or set(l.strip()) <= set('^~') and l.strip(): continue
        if l.startswith('Traceback') and i + 1 < len(lines) and 'hashlib.py' in lines[i + 1]: continue
        out.append(l)
    return out


def scenic_samples(d, osv):
    """The Scenic aim's samples for a clip ([{t, yaw, pitch}], edit/scenery.py `samples`), cached in `scenic_view.json` and made again when the quality grid is newer; [] without a grid."""
    from strata360.analysis import quality_grid as QG
    cache, grid_file = os.path.join(d, 'scenic_view.json'), os.path.join(d, QG.FILE)
    if not os.path.exists(grid_file): return []
    try:
        if os.path.getmtime(cache) >= os.path.getmtime(grid_file): return json.load(open(cache))
    except (OSError, ValueError): pass
    try:
        from strata360.edit import clip_views as CV, scenery as SC
        v = CV.load(d, osv); out = SC.samples(v['grid'], v['heading'], v['prior'], v['boxes'])
        with open(cache + '.tmp', 'w') as f: json.dump(out, f)
        os.replace(cache + '.tmp', cache); return out
    except Exception: return []


LYRICS_JOBS = {}              # folder -> Popen of a running `strata360 lyrics`
STREETVIEW_NEAR = {}          # (folder, provider, picture id) -> what the near-point search found (so the thumbnails can be fetched, and nothing else)
STREETVIEW_VIDEO_JOBS = {}    # (folder, section key) -> Popen of a running `strata360 streetview-video`
STREETVIEW_JOBS = {}          # folder -> Popen of a running `strata360 streetview`
PHOTO_JOBS = {}               # folder -> Popen of a running `strata360 photos-analyse`
MIX_JOBS = {}                 # folder -> Popen of a running `strata360 rough-mix`
GAP_JOBS = {}                 # folder -> (clip id, Popen) of a running `strata360 gap-clip`
PLAN_JOBS = {}                # folder -> Popen of a running `strata360 script-plan`
SCRIPT2_JOBS = {}             # folder -> Popen of a running `strata360 script-draft`
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


def alive(pid):
    """Is that process still running (jobs outlive a restart of the server, so their own pid is recorded in their status)."""
    return oslib.pid_alive(pid)


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
        live.append(subprocess.Popen([*oslib.cli_command(), args[0], folder, *args[1:]], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True)); return True


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

    @api.get('/api/coverage', dependencies=[Depends(auth)])
    def get_coverage(folder: str):
        from strata360.pipeline.coverage import coverage
        f = folder_of(folder)
        if not os.path.exists(os.path.join(config.race_dir(f), 'race.json')): raise HTTPException(404, 'no project in this folder yet')
        return coverage(f)

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

    def in_film(f):
        """The ids of the clips and gaps the film's plan plays now (empty when there is no plan)."""
        from strata360.edit import project as PJ
        try: return {g['clip'] for g in (PJ.load(f).get('plan') or {}).get('segments') or []}
        except (OSError, ValueError, KeyError): return set()

    @api.get('/api/clips', dependencies=[Depends(auth)])
    def get_clips(folder: str):                                                          # the clip list: id, time, length, a note flag, whether a thumbnail exists and a few facts
        from strata360.pipeline import notes as N
        f = folder_of(folder); rd = config.race_dir(f); out = []; nt = N.load(f); used = in_film(f)
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json')
            if not c: continue
            mo = _j(d, 'motion.json'); cd = _j(d, 'candidates.json'); thumb = 'best' if os.path.exists(d + 'thumb.jpg') else 'quick' if os.path.exists(d + 'thumb_quick.jpg') else None
            if thumb and TH.overlay_fresh(d): thumb += '+overlay'                                                     # the version also busts the browser cache when the overlay one appears
            out.append(dict(id=c['clip_id'], start_utc=c['time']['start_utc'], duration_s=round(c['video']['source_frames'] / c['video']['nominal_fps'], 1), has_note=bool(nt['clips'].get(c['clip_id'])),
                            thumb=thumb and thumb.split('+')[0], thumb_overlay=bool(thumb and thumb.endswith('+overlay')), audio_original=os.path.exists(d + 'audio_original.flac'), audio_clean=os.path.exists(d + 'audio_clean.flac'), steady=None if not mo else mo['summary']['steady'], in_film=c['clip_id'] in used, candidates=None if not cd else cd['summary']['n']))
        return dict(clips=out)

    def effective(d):                                                                    # the transcript with the user's corrections and marks applied (None when there is none)
        tr = TE.load_effective(d); return TM.annotate(tr, d) if tr else tr

    def word_view(s):                                                                    # the words of a phrase for the editable view: shown text, timing, and the correction (if any)
        return [dict(i=i, w=w['w'], t0=w['t0'], t1=w['t1'], p=w.get('p'), **({'e': w['edit']} if w.get('edit') else {}), **({'m': w['mark']} if w.get('mark') else {})) for i, w in enumerate(s.get('words') or [])]

    def phrase_parts(s, si, who, **extra):                                               # the displayed phrases of one segment: a long phrase comes in parts (only at sentence ends, every part over 5 s)
        res = []; ps = TE.parts(s); whole = len(ps) == 1
        for p in ps:
            ws = [dict(i=w['i'], w=w['w'], t0=w['t0'], t1=w['t1'], p=w.get('p'), **({'e': w['edit']} if w.get('edit') else {}), **({'m': w['mark']} if w.get('mark') else {})) for w in p['words']]
            text = s['text'].strip() if (whole and not s.get('edited')) else ' '.join(w['w'].strip() for w in p['words'] if w['w'].strip())
            en = s.get('text_en') if (whole or s.get('lang') != 'en') else text
            if whole and s.get('lang') == 'en' and s.get('edited'): en = text
            res.append(dict(si=si, part=len(res), words=ws, t0=p['t0'], t1=p['t1'], play0=p['play0'], play1=p['play1'], lang=s['lang'], text=text, text_en=en, who=who, **extra))
        return res

    @api.post('/api/transcript/edit', dependencies=[Depends(auth)])
    def post_transcript_edit(body: dict):                                            # {folder, clip, seg, word, text}: your correction of one word; {action: 'clear'} drops it (the model's shows again)
        f = folder_of(body.get('folder')); d = _cd(f, body.get('clip'))
        try: si, wi = int(body['seg']), int(body['word'])
        except (KeyError, TypeError, ValueError): raise HTTPException(400, 'seg and word: numbers')
        try:
            if body.get('action') == 'clear': TE.clear_user(d, si, wi)
            elif isinstance(body.get('text'), str): TE.set_user(d, si, wi, body['text'])
            else: raise HTTPException(400, 'text: a string')
        except (IndexError, KeyError, OSError): raise HTTPException(404, 'no such word')
        return dict(ok=True)

    @api.post('/api/transcript/mark', dependencies=[Depends(auth)])
    def post_transcript_mark(body: dict):                                            # {folder, clip, spans: [{seg, from, to}], state: 'must' | 'never' | 'none'}: mark words green (must use) or red (never use); 'none' clears them
        f = folder_of(body.get('folder')); d = _cd(f, body.get('clip')); state = body.get('state'); state = None if state in ('none', 'white', None) else state
        try: spans = [(int(x['seg']), int(x['from']), int(x['to'])) for x in body.get('spans') or []]
        except (KeyError, TypeError, ValueError): raise HTTPException(400, 'spans: [{seg, from, to}] of numbers')
        if not spans: raise HTTPException(400, 'spans: at least one')
        try: TM.set_spans(d, spans, state)
        except ValueError as e: raise HTTPException(400, str(e))
        except (IndexError, OSError): raise HTTPException(404, 'no such word')
        return dict(ok=True, marked=len(TM.states(d)))

    @api.post('/api/transcript/suggest', dependencies=[Depends(auth)])
    def post_transcript_suggest(body: dict):                                         # {folder}: run the audio check of the transcript (stage `transcript_check`: paid Gemini calls, every reply cached, clips already done are skipped)
        f = folder_of(body.get('folder')); return dict(started=start_job(f, ('run', '--stages', 'transcript_check')))

    @api.get('/api/transcript/suggest', dependencies=[Depends(auth)])
    def get_transcript_suggest(folder: str):                                         # progress of the audio check: clips done of those with speech, corrections stored, and what the API calls used
        from strata360.pipeline import runner
        f = folder_of(folder); rd = config.race_dir(f); total = done = fixes = made = reused = tin = tout = 0; err = None
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            tr = _j(d, 'transcript.json')
            if not tr or not any(s.get('words') and s.get('text', '').strip() for s in tr['segments']): continue
            total += 1; cid = os.path.basename(d.rstrip('/\\')); st = runner.load_state(f, cid).get('transcript_check', {})
            if st.get('status') == 'ok':
                done += 1; r = _j(d, 'transcript_check.json') or {}; fixes += r.get('stored', 0); made += (r.get('calls') or {}).get('made', 0); reused += (r.get('calls') or {}).get('reused', 0)
                tin += (r.get('tokens') or {}).get('input', 0); tout += (r.get('tokens') or {}).get('output', 0)
            elif st.get('status') == 'failed': err = st.get('error') or 'failed'
        running = any(s_ == 'transcript_check' for _, s_, _ in runner.active_items(f))
        health = runner.stage_health(f).get('transcript_check')
        return dict(state='running' if running else ('done' if total and done == total else ('error' if err else 'none')), health=health, done=done, total=total, fixes=fixes, calls_made=made, calls_reused=reused, tokens=dict(input=tin, output=tout), usage=TF.usage_summary(f), error=err)

    @api.get('/api/transcript', dependencies=[Depends(auth)])
    def get_transcript(folder: str):                                                     # every recognised phrase of every clip, in clip order: the overview's running transcript
        f = folder_of(folder); rd = config.race_dir(f); out = []
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json'); tr = effective(d)
            if not c or not tr: continue
            sp = _j(d, 'speakers.json'); lab = {(round(s['t0'], 2), round(s['t1'], 2)): s.get('label') for s in (sp or {}).get('segments', [])}
            for si, s in enumerate(tr['segments']):
                if not s.get('text', '').strip(): continue
                out.extend(phrase_parts(s, si, lab.get((round(s['t0'], 2), round(s['t1'], 2))), clip=c['clip_id'], flagged=bool(s.get('flags') or s.get('suspect'))))
        return dict(segments=out)

    @api.get('/api/meta', dependencies=[Depends(auth)])
    def get_meta_tz(folder: str):
        from strata360.pipeline import meta as M
        f = folder_of(folder); m = M.load(f); m['timezone'] = (config.load(f).get('timezone') if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None) or 'Europe/Brussels'; return m

    @api.get('/api/thumb')
    def get_thumb(request: Request, folder: str, clip: str, overlay: bool = False):       # the image itself: an <img> tag cannot send headers, so the cookie/query token is what authenticates it
        auth(request); f = folder_of(folder); d = _cd(f, clip)                             # overlay=1: the version with the race overlay when it is up to date, else the plain one
        if overlay and TH.overlay_fresh(d): return FileResponse(os.path.join(d, 'thumb_overlay.jpg'), media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
        for n in ('thumb.jpg', 'thumb_quick.jpg'):
            if os.path.exists(os.path.join(d, n)): return FileResponse(os.path.join(d, n), media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
        raise HTTPException(404, 'no thumbnail yet')

    @api.get('/api/preview')
    def get_preview(request: Request, folder: str, clip: str):                           # the preview video (Range requests are handled, so seeking works); <video> cannot send headers, so the cookie/query token authenticates
        auth(request); f = folder_of(folder); p = os.path.join(_cd(f, clip), 'proxy.mp4')
        if not os.path.exists(p): raise HTTPException(404, 'the proxy video has not been made yet')
        return FileResponse(p, media_type='video/mp4', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/clip/audio')
    def get_clip_audio(request: Request, folder: str, clip: str, kind: str = 'original'):  # the clip's stored sound: original (lossless), cleaned, or the background without speech (Range requests work); <audio> cannot send headers, so the cookie/query token authenticates
        auth(request); f = folder_of(folder); name = {'clean': 'audio_clean.flac', 'background': 'audio_background.flac'}.get(kind, 'audio_original.flac'); p = os.path.join(_cd(f, clip), name)
        if not os.path.exists(p): raise HTTPException(404, 'not made yet')
        return FileResponse(p, media_type='audio/flac', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/clip', dependencies=[Depends(auth)])
    def get_clip(folder: str, clip: str):                                                # everything known about one clip, for its detail view
        from strata360.pipeline import notes as N
        f = folder_of(folder); d = _cd(f, clip); c = _j(d, 'clip.json'); out = dict(id=c['clip_id'], time=c['time'], video=c['video'], camera=c.get('camera'), audio_info=c.get('audio'), note=N.load(f)['clips'].get(c['clip_id'], ''))
        mo = _j(d, 'motion.json'); out['motion'] = None if not mo else mo['summary']
        au = _j(d, 'audio.json'); out['audio'] = None if not au else dict(summary=au.get('summary'), segments=au.get('segments', [])[:40])
        tr = effective(d); sp = _j(d, 'speakers.json'); lab = {(round(s['t0'], 2), round(s['t1'], 2)): s.get('label') for s in (sp or {}).get('segments', [])}
        out['transcript'] = [x for si, s in enumerate((tr or {}).get('segments', [])) for x in phrase_parts(s, si, lab.get((round(s['t0'], 2), round(s['t1'], 2))), flagged=bool(s.get('flags')))]
        sc = _j(d, 'scenes.json'); out['scenes'] = None if not sc else dict(summary=sc['summary'], items=[i for i in sc['items'] if i['ok'] and i['view'] == 'front'][:60])
        idn = _j(d, 'identity.json'); out['identity'] = None if not idn else idn['summary']
        cd = _j(d, 'candidates.json'); out['candidates'] = None if not cd else [{k: v for k, v in x.items() if k not in ('transcript', 'cuts')} for x in cd['candidates']]
        ev = _j(d, 'audio_events.json')
        if ev:
            from strata360.analysis import sound_events as SE
            out['sounds'] = dict(seconds=SE.category_seconds(ev), windows=[dict(t0=w['t0'], t1=w['t1'], cats={k: v for k, v in w['cats'].items() if v >= 0.2}, top=w['top'][:3]) for w in ev['windows']], hints={c: list(h) for c, h in SE.HINTS.items()})
        out['audio_files'] = dict(original=os.path.exists(os.path.join(d, 'audio_original.flac')), clean=os.path.exists(os.path.join(d, 'audio_clean.flac')), background=os.path.exists(os.path.join(d, 'audio_background.flac')))
        mo_ = _j(d, 'motion.json'); out['heading'] = None if not mo_ else dict(t=mo_['series']['t'], deg=mo_['series']['heading_deg']); pv = os.path.join(d, 'proxy.mp4'); out['preview'] = os.path.exists(pv) and os.path.getsize(pv) > 0
        try:
            from strata360.analysis.views import focus_samples, person_samples
            out['focus'] = focus_samples(d, c['source_files']['osv']); out['person'] = person_samples(d, c['source_files']['osv'])
        except Exception: out['focus'] = []; out['person'] = []
        try:                                                                              # the clearest view over time (the "Clarity" aim): from the view-quality maps of the exposure stage
            from strata360.analysis.exposure import load_quality
            from strata360.edit import attention as AT
            vq = load_quality(d); out['clarity'] = AT.clarity_samples(vq) if vq is not None and len(vq['t']) else []
        except Exception: out['clarity'] = []
        out['scenic'] = scenic_samples(d, (c.get('source_files') or {}).get('osv'))                      # the best people-free direction over time (the "Scenic" aim), kept beside the quality grid it comes from
        out['unusable'] = None if not cd else cd.get('unusable', []); out['thresholds'] = None if not cd else cd.get('thresholds')
        ex = _j(d, 'exposure.json'); out['exposure'] = None if not ex else ex['summary']
        th = _j(d, 'thumb.json') or _j(d, 'thumb_quick.json'); out['thumb'] = th and {**th, 'overlay': TH.overlay_fresh(d)}; out['places'] = _j(d, 'places.json')
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
    def post_notes(body: dict):                                                          # {folder, text, clip?}: the folder note, or one clip's note; with kind 'vo' the voice-over MUST INCLUDE text (and `ordered` for the folder's: keep the order written)
        from strata360.pipeline import notes as N
        if body.get('kind') == 'vo': return N.save_vo(folder_of(body.get('folder')), body.get('text', ''), body.get('clip'), body.get('ordered'))
        return N.save(folder_of(body.get('folder')), body.get('text', ''), body.get('clip'))

    @api.get('/api/track', dependencies=[Depends(auth)])
    def get_track(folder: str):                                                          # overview map + main stats of the race track, or {present: false}
        f = folder_of(folder); p = config.track_path(f, config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None)
        if not p: return dict(present=False)
        from strata360.gps.overview import overview
        try: return overview(p)
        except Exception as e: return dict(present=True, error=f'{type(e).__name__}: {e}')

    def start_voiceover(f):
        """Speak the newest script in a separate low-priority process (its progress is in voiceover/status.json); false when one is already working (it speaks a script saved meanwhile after it finishes)."""
        from strata360.edit import voiceover as VO
        if VO.running(f): return False
        rd = config.race_dir(f); os.makedirs(os.path.join(rd, 'voiceover'), exist_ok=True); log = open(os.path.join(rd, 'voiceover', 'job.log'), 'ab')
        subprocess.Popen([*oslib.cli_command(), 'voiceover', f], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return True

    @api.post('/api/script/edit', dependencies=[Depends(auth)])
    def post_script_edit(body: dict):                                                    # {folder, texts: {seg: new text}}: saved as a new script version, then spoken at once
        from strata360.edit import voiceover as VO
        f = folder_of(body.get('folder')); texts = body.get('texts')
        if not isinstance(texts, dict) or not texts: raise HTTPException(400, 'texts: {segment: text}')
        try: name = VO.save_edit(f, {str(k): str(v) for k, v in texts.items()})
        except RuntimeError as e: raise HTTPException(400, str(e))
        return dict(saved=name, speaking=bool(name) and start_voiceover(f))

    @api.get('/api/voiceover', dependencies=[Depends(auth)])
    def get_voiceover(folder: str):                                                      # engines and voices on this machine, the saved choice, and the timings of the last build
        from strata360.edit import voiceover as VO
        f = folder_of(folder); st = VO.load_state(folder_of(folder)); av = VO.available_engines(); script, lines = VO.script_lines(f)
        try: eng, voice = VO.pick(st)
        except RuntimeError: eng = voice = None
        return dict(engines=av, state=dict(engine=eng, voice=voice, rate=st['rate'], use=st['use']), timings=VO.load_timings(f), cached=VO.cached_tracks(f), script=script, lines=len(lines), building=VO.running(f), progress=(VO.load_status(f) or {}), error=((VO.load_status(f) or {}).get('error') if (VO.load_status(f) or {}).get('state') == 'error' else None))

    @api.post('/api/voiceover/build', dependencies=[Depends(auth)])
    def post_voiceover(body: dict):                                                      # {folder, engine?, voice?, rate?}: speak the script and mix the track (in the background; unchanged lines are reused)
        from strata360.edit import voiceover as VO
        f = folder_of(body.get('folder')); st = VO.load_state(f)
        for k in ('engine', 'voice'):
            if body.get(k): st[k] = body[k]
        if body.get('rate'): st['rate'] = int(body['rate'])
        VO.save_state(f, st); return dict(started=start_voiceover(f))

    @api.post('/api/voiceover/use', dependencies=[Depends(auth)])
    def post_voiceover_use(body: dict):                                                  # {folder, seg, use: 'synth'|'recorded'}
        from strata360.edit import voiceover as VO
        f = folder_of(body.get('folder')); st = VO.load_state(f)
        if body.get('use') not in ('synth', 'recorded'): raise HTTPException(400, 'use: synth or recorded')
        st['use'][str(int(body['seg']))] = body['use']; VO.save_state(f, st); return dict(ok=True)

    @api.post('/api/voiceover/record', dependencies=[Depends(auth)])
    async def post_voiceover_record(request: Request, folder: str, seg: int):            # your recording of one line: the raw audio file as the request body (any format ffmpeg reads)
        import tempfile
        from strata360.edit import voiceover as VO
        f = folder_of(folder); data = await request.body()
        if len(data) < 500 or len(data) > 100 * 1024 * 1024: raise HTTPException(400, 'the recording is empty or too large')
        with tempfile.NamedTemporaryFile(suffix='.audio', delete=False) as tf: tf.write(data)
        try: VO.save_recording(f, seg, tf.name)
        except RuntimeError as e: raise HTTPException(400, 'could not read that audio: ' + str(e)[-200:])
        finally: os.remove(tf.name)
        return dict(ok=True)

    @api.delete('/api/voiceover/record', dependencies=[Depends(auth)])
    def delete_voiceover_record(folder: str, seg: int):
        from strata360.edit import voiceover as VO
        VO.delete_recording(folder_of(folder), seg); return dict(ok=True)

    @api.get('/api/voiceover/audio')
    def get_voiceover_audio(request: Request, folder: str, seg: int | None = None, source: str = 'track', track: str = ''):   # one line (source synth|recorded) or the whole mixed track; <audio> cannot send headers, so the cookie/query token authenticates
        auth(request); from strata360.edit import voiceover as VO
        f = folder_of(folder); b = VO.base(f)
        if seg is None and track and '/' not in track and '..' not in track: p = os.path.join(b, 'tracks', track, 'voiceover.wav')       # one voice's whole track, to compare without switching
        elif seg is None: p = os.path.join(b, 'voiceover.wav')
        elif source == 'recorded': p = VO.recorded_path(f, seg)
        else:
            tm = VO.load_timings(f) or {}; o = next((o for o in tm.get('lines', []) if o['seg'] == seg), None); p = os.path.join(b, o['path']) if o and o['source'] == 'synth' else ''
            if not p or not os.path.exists(p):
                import glob as g; c = sorted(g.glob(os.path.join(b, 'synth', f'{seg:03d}-*.wav')), key=os.path.getmtime); p = c[-1] if c else ''
        if not p or not os.path.exists(p): raise HTTPException(404, 'not made yet')
        return FileResponse(p, media_type='audio/wav', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/film', dependencies=[Depends(auth)])
    def get_film(folder: str):                                                           # state of the preview of the CURRENT plan: none | rendering | done | error, with progress
        from strata360.edit import project as PJ
        from strata360.render import preview as PV
        f = folder_of(folder); plan = PJ.load(f).get('plan'); j = FILM_JOBS.get(f); running = bool(j and j.poll() is None)
        if not plan: return dict(state='noplan', running=False)
        key = PV.plan_key(f, plan); st = None
        try: st = json.load(open(os.path.join(PV.film_dir(f, key), 'status.json')))
        except (OSError, ValueError): pass
        running = running or bool(st and st['state'] in ('rendering', 'audio') and alive(st.get('pid')))
        state = st['state'] if st else ('starting' if running else 'none')
        if st and st['state'] in ('rendering', 'audio') and not running: state = 'error'; st['error'] = 'the preview was stopped'
        return dict(state=state, running=running, key=key, frames_done=(st or {}).get('frames_done', 0), frames_total=(st or {}).get('frames_total', 0), placeholders=(st or {}).get('placeholders', []), error=(st or {}).get('error'), length_s=plan['film']['length_s'])

    def job_pid(f, jobs, status_path_fn):
        """pid of the running job for folder f: our own child, or (after a restart of the server) the pid its status file names."""
        j = jobs.get(f)
        if j and j.poll() is None: return j.pid
        try:
            st = json.load(open(status_path_fn(f)))
            if st.get('state') in ('rendering', 'audio', 'assembling') and alive(st.get('pid')): return int(st['pid'])
        except (OSError, ValueError, KeyError, TypeError): pass
        return None

    def film_status_path(f):
        from strata360.edit import project as PJ
        from strata360.render import preview as PV
        plan = PJ.load(f).get('plan'); return os.path.join(PV.film_dir(f, PV.plan_key(f, plan)), 'status.json') if plan else ''

    def final_status_path(f):
        from strata360.edit import project as PJ
        from strata360.render import final as FN
        plan = PJ.load(f).get('plan'); s = final_settings(f)
        if not plan: return ''
        w, h = map(int, s['size'].split('x')); return os.path.join(FN.final_dir(f, FN.final_key(plan, [w, h], s['fps'], s['bitrate'], f)), 'status.json')

    @api.post('/api/film/start', dependencies=[Depends(auth)])
    def post_film_start(body: dict):                                                     # {folder}: render the preview of the saved plan (lowest priority, one at a time)
        f = folder_of(body.get('folder'))
        if job_pid(f, FILM_JOBS, film_status_path): return dict(started=False)
        rd = config.race_dir(f); os.makedirs(rd, exist_ok=True); log = open(os.path.join(rd, 'film_job.log'), 'wb')
        FILM_JOBS[f] = subprocess.Popen([*oslib.cli_command(), 'film', f] + (['--force'] if body.get('force') else []), stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/film/stop', dependencies=[Depends(auth)])
    def post_film_stop(body: dict):
        import signal
        from strata360.pipeline import runner
        pid = job_pid(folder_of(body.get('folder')), FILM_JOBS, film_status_path)
        if pid: runner.kill_tree(pid, signal.SIGTERM)
        return dict(ok=True)

    @api.get('/api/film/index.m3u8')
    def get_film_playlist(request: Request, folder: str):                                # the playlist with segment names made absolute (the query token / cookie authenticates the player's requests)
        auth(request); from urllib.parse import quote
        from strata360.edit import project as PJ
        from strata360.render import preview as PV
        f = folder_of(folder); plan = PJ.load(f).get('plan')
        if not plan: raise HTTPException(404, 'no plan')
        p = os.path.join(PV.film_dir(f, PV.plan_key(f, plan)), 'index.m3u8')
        if not os.path.exists(p): raise HTTPException(404, 'not started yet')
        txt = ''.join((f'/api/film/seg?folder={quote(folder)}&name={ln.strip()}\n' if ln.strip().endswith('.ts') else ln) for ln in open(p).readlines())
        return Response(txt, media_type='application/vnd.apple.mpegurl', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/film/seg')
    def get_film_seg(request: Request, folder: str, name: str):
        auth(request)
        from strata360.edit import project as PJ
        from strata360.render import preview as PV
        f = folder_of(folder); plan = PJ.load(f).get('plan')
        if not plan or not name.startswith('seg') or not name.endswith('.ts') or '/' in name: raise HTTPException(404)
        p = os.path.join(PV.film_dir(f, PV.plan_key(f, plan)), name)
        if not os.path.exists(p): raise HTTPException(404)
        return FileResponse(p, media_type='video/mp2t', headers={'Cache-Control': 'max-age=3600'})

    def final_settings(f):
        p = os.path.join(config.race_dir(f), 'final', 'settings.json')
        try: s = json.load(open(p))
        except (OSError, ValueError): s = {}
        return dict(size=s.get('size', '3840x2160'), fps=float(s.get('fps', 50.0)), bitrate=s.get('bitrate', '100M'))

    @api.get('/api/final', dependencies=[Depends(auth)])
    def get_final(folder: str):                                                          # state of the final render of the CURRENT plan with the saved settings
        from strata360.edit import project as PJ
        from strata360.render import final as FN
        f = folder_of(folder); plan = PJ.load(f).get('plan'); s = final_settings(f); j = FINAL_JOBS.get(f); running = bool(j and j.poll() is None)
        if not plan: return dict(state='noplan', running=False, settings=s)
        w, h = map(int, s['size'].split('x')); key = FN.final_key(plan, [w, h], s['fps'], s['bitrate'], f); st = None
        try: st = json.load(open(os.path.join(FN.final_dir(f, key), 'status.json')))
        except (OSError, ValueError): pass
        running = running or bool(st and st['state'] in ('rendering', 'assembling') and alive(st.get('pid')))
        state = st['state'] if st else ('starting' if running else 'none')
        if st and st['state'] in ('rendering', 'assembling') and not running: state = 'stopped'
        return dict(state=state, running=running, settings=s, frames_done=(st or {}).get('frames_done', 0), frames_total=(st or {}).get('frames_total', 0), pieces_done=(st or {}).get('pieces_done', 0), pieces_total=(st or {}).get('pieces_total', 0),
                    started=(st or {}).get('started'), error=(st or {}).get('error'), has_file=bool(st and st['state'] == 'done' and os.path.exists(st.get('film', ''))))

    @api.post('/api/final/start', dependencies=[Depends(auth)])
    def post_final_start(body: dict):                                                    # {folder, size?, fps?, bitrate?}: start or continue the final render (lowest priority; finished pieces are kept)
        f = folder_of(body.get('folder'))
        if job_pid(f, FINAL_JOBS, final_status_path): return dict(started=False)
        s = final_settings(f)
        if body.get('size') in ('1920x1080', '2560x1440', '3840x2160'): s['size'] = body['size']
        if body.get('fps') in (25, 25.0, 30, 30.0, 50, 50.0): s['fps'] = float(body['fps'])
        d = os.path.join(config.race_dir(f), 'final'); os.makedirs(d, exist_ok=True); json.dump(s, open(os.path.join(d, 'settings.json'), 'w'))
        log = open(os.path.join(d, 'final_job.log'), 'wb')
        FINAL_JOBS[f] = subprocess.Popen([*oslib.cli_command(), 'final', f, '--size', s['size'], '--fps', str(s['fps']), '--bitrate', s['bitrate']], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/final/stop', dependencies=[Depends(auth)])
    def post_final_stop(body: dict):
        import signal
        from strata360.pipeline import runner
        pid = job_pid(folder_of(body.get('folder')), FINAL_JOBS, final_status_path)
        if pid: runner.kill_tree(pid, signal.SIGTERM)
        return dict(ok=True)

    @api.get('/api/final/file')
    def get_final_file(request: Request, folder: str):                                   # the finished film (Range requests work, so it can be played or downloaded)
        auth(request)
        from strata360.edit import project as PJ
        from strata360.render import final as FN
        f = folder_of(folder); plan = PJ.load(f).get('plan'); s = final_settings(f)
        if not plan: raise HTTPException(404)
        w, h = map(int, s['size'].split('x')); d = FN.final_dir(f, FN.final_key(plan, [w, h], s['fps'], s['bitrate'], f))
        try: film = json.load(open(os.path.join(d, 'status.json'))).get('film')
        except (OSError, ValueError): film = None
        if not film or not os.path.exists(film): raise HTTPException(404, 'not rendered yet')
        return FileResponse(film, media_type='video/mp4', filename='film.mp4')

    @api.get('/api/who', dependencies=[Depends(auth)])
    def get_who(folder: str, refresh: bool = False):                                     # the face clusters found in the footage, the suggested one for the wearer, and whether a profile is saved
        from strata360.analysis import identity
        f = folder_of(folder); rd = config.race_dir(f); cfg = config.load(f); cj = os.path.join(rd, 'people', 'clusters.json'); prof = os.path.join(ROOT_DIR, 'profiles', cfg.get('profile', 'me') + '.npz')
        if refresh or not os.path.exists(cj):
            try: identity.run(rd, profiles_dir=os.path.join(ROOT_DIR, 'profiles'))
            except SystemExit as e: return dict(ready=False, reason=str(e), profile=os.path.exists(prof))
        d = json.load(open(cj)); return dict(ready=True, clusters=d['clusters'][:30], suggested=d['suggested_wearer'], profile=os.path.exists(prof), sheet=os.path.exists(os.path.join(rd, 'people', 'clusters.png')))

    @api.get('/api/who/sheet')
    def get_who_sheet(request: Request, folder: str):
        auth(request); p = os.path.join(config.race_dir(folder_of(folder)), 'people', 'clusters.png')
        if not os.path.exists(p): raise HTTPException(404)
        return FileResponse(p, media_type='image/png', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/who/me')
    def get_who_me(request: Request, folder: str, n: int = 4):                           # a strip of the chosen face (the saved profile's thumbnails)
        auth(request)
        import cv2, numpy as np
        f = folder_of(folder); p = os.path.join(ROOT_DIR, 'profiles', config.load(f).get('profile', 'me') + '.npz')
        if not os.path.exists(p): raise HTTPException(404, 'no face chosen yet')
        t = np.load(p)['thumbs']; k = max(1, min(int(n), len(t))); idx = np.argsort(-(t.max(3) > 12).mean((1, 2)), kind='stable')[:k]           # the crops with the least black border (faces near the frame edge are cut off)
        ok, buf = cv2.imencode('.jpg', np.concatenate([t[i] for i in idx], 1)[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])           # thumbnails are RGB
        return Response(buf.tobytes(), media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})

    @api.post('/api/who', dependencies=[Depends(auth)])
    def post_who(body: dict):                                                            # {folder, me: [cluster numbers]}: save them as the wearer's face profile and let the waiting stages continue
        from strata360.analysis import identity
        f = folder_of(body.get('folder')); rd = config.race_dir(f); cfg = config.load(f)
        try: ids = [int(x) for x in body.get('me', [])]
        except (TypeError, ValueError): raise HTTPException(400, 'me: a list of cluster numbers')
        if not ids: raise HTTPException(400, 'choose at least one cluster')
        try: identity.run(rd, me=','.join(map(str, ids)), profiles_dir=os.path.join(ROOT_DIR, 'profiles'), label=cfg.get('profile', 'me'))
        except SystemExit as e: raise HTTPException(400, str(e))
        start_job(f, ('run',)); return dict(ok=True)

    def clock_state(f):
        cfg = config.load(f); ck = cfg.get('camera_clock', {}); cur = float(ck.get('offset_seconds', 0.0)) + 3600 * float(ck.get('utc_offset_hours', 0.0))
        return dict(offset_s=cur, verified=bool(ck.get('verified')), note=ck.get('note'), drift_s_per_day=ck.get('drift_s_per_day'), anchors=ck.get('anchors', []), has_track=config.track_path(f, cfg) is not None)

    @api.get('/api/clock', dependencies=[Depends(auth)])
    def get_clock(folder: str):                                                          # the camera clock correction: seconds the camera is ahead of UTC (370 = the camera shows 6 min 10 s too late)
        return clock_state(folder_of(folder))

    @api.get('/api/clock/suggest', dependencies=[Depends(auth)])
    def get_clock_suggest(folder: str):                                                  # votes from running starts/stops seen by both the camera and the GPS (analysis/../gps/anchors.py)
        from strata360.gps import anchors as A, track
        f = folder_of(folder); cfg = config.load(f); tp = config.track_path(f, cfg)
        if not tp: raise HTTPException(400, 'add the race track first')
        cur = clock_state(f)['offset_s']; return dict(current=cur, suggestions=A.suggest(config.race_dir(f), track.load(tp), prior_s=cur))

    @api.post('/api/clock', dependencies=[Depends(auth)])
    def post_clock(body: dict):                                                          # {folder, offset_seconds}: set the offset; every clip is re-timed and the stages that use the track are redone
        from strata360.pipeline import runner
        f = folder_of(body.get('folder'))
        try: off = float(body['offset_seconds'])
        except (KeyError, TypeError, ValueError): raise HTTPException(400, 'offset_seconds: a number')
        if abs(off) > 86400: raise HTTPException(400, 'the offset is larger than a day')
        cfg = config.load(f); ck = cfg.setdefault('camera_clock', {}); ck['utc_offset_hours'] = 0.0; ck['offset_seconds'] = off; ck['verified'] = True; ck['note'] = 'set in the app'; config.save(f, cfg)
        res = runner.run(f, ['ingest'], None, False); return dict(clock=clock_state(f), retimed=len(res))

    def music_state(f, warning=None):                                                   # what the app shows about the track: music.json's record without the file names of its parts
        from strata360.edit import project as PJ
        r = PJ.music_record(f, PJ.load(f)['settings'])
        out = dict(file=r['file'] if r else None, name=r['name'] if r else None, analysis=r['analysis'] if r else None, waveform=r['waveform'] if r else None, spectrogram=bool(r))
        if warning: out['warning'] = warning
        return out

    @api.get('/api/music', dependencies=[Depends(auth)])
    def get_music(folder: str):                                                          # the music track of the project and what was found in it (music.json)
        return music_state(folder_of(folder))

    def music_file(f, name=None):
        from strata360.edit import project as PJ
        r = PJ.music_record(f, PJ.load(f)['settings'])
        if not r: raise HTTPException(404, 'no music track')
        return os.path.join(config.race_dir(f), name or r['file'])

    @api.get('/api/music/audio')
    def get_music_audio(request: Request, folder: str):                                  # the track itself, to play in the page (Range requests work); <audio> cannot send headers, so the cookie/query token authenticates
        import mimetypes
        auth(request); p = music_file(folder_of(folder)); return FileResponse(p, media_type=mimetypes.guess_type(p)[0] or 'audio/mpeg', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/music/spectrogram')
    def get_music_spectrogram(request: Request, folder: str, v: str = ''):               # the spectrogram picture (PNG) made with the analysis
        auth(request); f = folder_of(folder); from strata360.edit import project as PJ
        r = PJ.music_record(f, PJ.load(f)['settings'])
        if not r: raise HTTPException(404, 'no music track')
        return FileResponse(os.path.join(config.race_dir(f), r['spectrogram']), media_type='image/png', headers={'Cache-Control': 'max-age=3600'})

    @api.post('/api/music', dependencies=[Depends(auth)])
    async def post_music(request: Request, folder: str, filename: str = 'track.mp3'):    # the audio file is the raw request body; saved as music/track.<ext>, analysed into music.json and used for tempo, bars, energy and the film's sound
        from strata360.edit import project as PJ, optimise as O, music as MU
        f = folder_of(folder); ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'): raise HTTPException(400, 'an audio file: mp3, wav, m4a, aac, flac or ogg')
        data = await request.body()
        if len(data) < 5000 or len(data) > 300 * 1024 * 1024: raise HTTPException(400, 'the file is empty or too large')
        try: rec = MU.store(config.race_dir(f), data, ext, os.path.basename(filename))
        except RuntimeError as e: raise HTTPException(400, str(e))
        try: PJ.set_music(f, rec['file'])
        except O.Infeasible as e: return music_state(f, str(e))
        return music_state(f)

    @api.delete('/api/music', dependencies=[Depends(auth)])
    def delete_music(folder: str):
        from strata360.edit import project as PJ, optimise as O, music as MU
        f = folder_of(folder)
        try: PJ.set_music(f, None)
        except O.Infeasible: pass
        MU.remove(config.race_dir(f)); return dict(file=None, name=None, analysis=None, waveform=None, spectrogram=False)

    TRACKS = {}

    def loaded_track(f):                                                                 # the race track, loaded once per file version (a race is hundreds of thousands of samples)
        from strata360.gps import track, series as GS
        p = config.track_path(f, config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else None)
        if not p: raise HTTPException(404, 'no race track')
        key = (p, os.path.getmtime(p))
        if key not in TRACKS:
            TRACKS.clear()
            try: TRACKS[key] = GS.prepare(track.load(p))
            except Exception as e: raise HTTPException(400, f'could not read the track: {type(e).__name__}: {e}')
        return TRACKS[key]

    def tile_source(style):
        """The Tiles of a map style. The key stays on the server (secrets.env); the browser only ever sees /api/tiles URLs. A missing key is an error (503) with the message to fix it, never an empty map."""
        from strata360.overlay import tiles as TL
        if style not in TL.STYLES: raise HTTPException(404, f'unknown map style {style}: one of {", ".join(sorted(TL.STYLES))}')
        if style not in TILES:
            try: TILES[style] = TL.Tiles(style, fetch=TILE_FETCH)
            except TL.MissingKey as e: raise HTTPException(503, str(e))
        return TILES[style]

    @api.get('/api/tiles/status', dependencies=[Depends(auth)])
    def get_tiles_status(style: str = 'tf-landscape'):                                  # whether the map background can be drawn (and the credit it must carry), for the overview map
        from strata360.overlay import tiles as TL
        try: t = tile_source(style)
        except HTTPException as e: return dict(ok=False, style=style, error=str(e.detail))
        return dict(ok=True, style=style, error='', credit=TL.STYLES[style]['credit'], tile_px=t.px)

    @api.get('/api/tiles/{style}/{z}/{x}/{y}')
    def get_tile(request: Request, style: str, z: int, x: int, y: int):                 # one map tile as a PNG, from the disk cache shared by every race (fetched once from the tile service, key kept here)
        from strata360.overlay import tiles as TL
        auth(request)
        if not 0 <= z <= TL.MAX_ZOOM: raise HTTPException(404, 'zoom out of range')
        t = tile_source(style)
        try: im = t.tile(z, x, y)
        except TL.TileError as e: raise HTTPException(502, str(e))
        buf = io.BytesIO(); im.save(buf, 'PNG'); return Response(buf.getvalue(), media_type='image/png', headers={'Cache-Control': 'max-age=86400'})

    @api.get('/api/track/series', dependencies=[Depends(auth)])
    def get_track_series(folder: str, points: int = 2000):                               # the track decimated for the charts: elapsed time, km, altitude (with each bin's lowest and highest), pace of the moving part, share moving, heart rate
        from strata360.gps import series as GS
        return GS.series(loaded_track(folder_of(folder)), max(100, min(points, 6000)))

    @api.get('/api/track/line', dependencies=[Depends(auth)])
    def get_track_line(folder: str, bbox: str = '', limit: int = 3000):                  # the line of the track inside bbox=lat0,lon0,lat1,lon1 (or all of it), at most `limit` points: the map asks for more detail as it zooms in
        from strata360.gps import series as GS
        box = None
        if bbox:
            try: box = tuple(float(x) for x in bbox.split(','))
            except ValueError: raise HTTPException(400, 'bbox: lat0,lon0,lat1,lon1')
            if len(box) != 4: raise HTTPException(400, 'bbox: lat0,lon0,lat1,lon1')
        return GS.line(loaded_track(folder_of(folder)), box, max(200, min(limit, 20000)))

    @api.get('/api/track/clips', dependencies=[Depends(auth)])
    def get_track_clips(folder: str):                                                    # every clip placed on the track (middle, the stretch it covers, facts for the hover card), with whether the newest script draft plays it
        from strata360.gps import series as GS
        from strata360.edit import script_draft as SD, script_pack as SP
        f = folder_of(folder); rd = config.race_dir(f); cfg = config.load(f) if os.path.exists(os.path.join(rd, 'race.json')) else {}; items = GS.clips(loaded_track(f), GS.load_spans(f), cfg.get('timezone', 'Europe/Brussels'))
        draft = SD.load_draft(f); used = {}
        for it in (draft or {}).get('items') or []: used[norm_label(it.get('clip', ''))] = used.get(norm_label(it.get('clip', '')), 0.0) + float(it.get('seconds') or 0)
        for c in items:
            d = os.path.join(rd, 'clips', c['id']); sc = (_j(d, 'scenes.json') or {}).get('summary') or {}; cd = (_j(d, 'candidates.json') or {}).get('summary') or {}
            c['label'] = SP.label_of(c['id']); c['scene'] = dict(settings=list((sc.get('settings') or {}))[:2], weather=list((sc.get('weather') or {}))[:2] if isinstance(sc.get('weather'), dict) else []); c['moments'] = cd.get('n'); c['usable_s'] = cd.get('usable_s')
            c['used'] = c['label'] in used; c['used_s'] = round(used.get(c['label'], 0.0), 1)
        return dict(clips=items, has_draft=bool(draft))

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
        from strata360.gps import tracks as TKS
        try: o = overview(dest)
        except Exception as e:
            os.replace(dest, dest + '.bad'); raise HTTPException(400, f'could not read that file: {type(e).__name__}: {e}')
        TKS.update_merged(rd); return o

    def tz_of(f):                                                                        # the race's time zone (for cut-offs given as a time of day)
        rd = config.race_dir(f); return (config.load(f) if os.path.exists(os.path.join(rd, 'race.json')) else {}).get('timezone') or 'Europe/Brussels'

    # The project's tracks: any number of FIT / GPX files, each a run (merged into the one race track) or a route (shown on the overview map for planning only)
    @api.get('/api/tracks', dependencies=[Depends(auth)])
    def get_tracks(folder: str):                                                         # every track with kind and summary, the merged run track, and the points of interest
        from strata360.gps import tracks as TKS
        f = folder_of(folder); return TKS.listing(config.race_dir(f), tz_of(f))

    @api.post('/api/tracks', dependencies=[Depends(auth)])
    async def post_tracks(request: Request, folder: str, filename: str, kind: str = ''):  # one more track (raw request body); the first run defaults to run, later ones to route
        from strata360.gps import tracks as TKS
        f = folder_of(folder); data = await request.body(); rd = config.race_dir(f)
        try: out = TKS.add(rd, filename, data, kind or None)
        except ValueError as e: raise HTTPException(400, str(e))
        overlays_changed(f); return out                                                  # (the maps on the overlay show the tracks)

    @api.post('/api/tracks/kind', dependencies=[Depends(auth)])
    def post_tracks_kind(body: dict):                                        # mark a track run or route (the merged race track follows)
        from strata360.gps import tracks as TKS
        rd = config.race_dir(folder_of(body.get('folder')))
        try: TKS.set_kind(rd, str(body.get('id')), str(body.get('kind')))
        except KeyError: raise HTTPException(404, 'no such track')
        except ValueError as e: raise HTTPException(400, str(e))
        overlays_changed(folder_of(body.get('folder')))
        return TKS.listing(rd, tz_of(folder_of(body.get('folder'))))

    @api.post('/api/tracks/cutoff', dependencies=[Depends(auth)])
    def post_tracks_cutoff(body: dict):                                                  # {folder, key: 'cp:N' | 'finish', text}: the cut-off typed for a checkpoint or the finish (empty clears); read in any common form (gps/cutoffs.py)
        from strata360.gps import tracks as TKS
        f = folder_of(body.get('folder')); rd = config.race_dir(f)
        try: TKS.set_cutoff(rd, str(body.get('key')), str(body.get('text') or ''), tz_of(f))
        except KeyError: raise HTTPException(404, 'no such checkpoint')
        except ValueError as e: raise HTTPException(400, str(e))
        overlays_changed(f)                                                              # the overlay shows cut-offs: the thumbnails are made again
        return TKS.listing(rd, tz_of(f))

    @api.delete('/api/tracks', dependencies=[Depends(auth)])
    def delete_tracks(folder: str, id: str):                                             # take a track out (its file is kept under tracks/removed)
        from strata360.gps import tracks as TKS
        rd = config.race_dir(folder_of(folder))
        try: TKS.remove(rd, id)
        except KeyError: raise HTTPException(404, 'no such track')
        overlays_changed(folder_of(folder))
        return TKS.listing(rd, tz_of(folder_of(folder)))

    @api.get('/api/tracks/line', dependencies=[Depends(auth)])
    def get_tracks_line(folder: str, id: str, limit: int = 3000):                        # the line of one track (id, or `merged`) for the overview map: lat, lon (no times needed)
        from strata360.gps import tracks as TKS
        import numpy as np
        rd = config.race_dir(folder_of(folder))
        if id == 'merged': p = os.path.join(rd, TKS.MERGED); p = p if os.path.exists(p) else None
        else: p = next((e['file'] for e in TKS.entries(rd) if e['id'] == id), None)
        if not p: raise HTTPException(404, 'no such track')
        tr = TKS.read(p); ok = np.isfinite(tr['lat']) & np.isfinite(tr['lon']); lat, lon = tr['lat'][ok], tr['lon'][ok]
        idx = np.unique(np.linspace(0, len(lat) - 1, max(2, min(limit, len(lat)))).astype(int))
        return dict(id=id, lat=[round(float(lat[i]), 6) for i in idx], lon=[round(float(lon[i]), 6) for i in idx])

    @api.get('/api/edit', dependencies=[Depends(auth)])
    def get_edit(folder: str):                                                           # settings, overrides, the saved plan, the technique list and the newest script's lines by segment id
        from strata360.edit import project as PJ, techniques as TQ
        f = folder_of(folder); e = PJ.load(f); lib = TQ.load(); rd = config.race_dir(f)
        files = sorted(glob.glob(os.path.join(rd, 'scripts', 'script-*.json'))); lines = {}
        if files:
            try:
                for l in json.load(open(files[-1])).get('lines', []):
                    if l.get('id'): lines[l['id']] = dict(text=l.get('text', ''), says=l.get('says') or [], words=l.get('words'), budget=l.get('budget_words'))
            except ValueError: pass
        from strata360.analysis import sound_events as SE
        for g in (e.get('plan') or {}).get('segments', []):
            try: doc = json.load(open(os.path.join(rd, 'clips', g['clip'], 'audio_events.json')))
            except (OSError, ValueError): continue
            m = SE.window_mix(doc, g['clip_start_s'], g['clip_start_s'] + g['dur_s'], bool(g.get('speech'))); g['sound'] = dict(gain_db=m['gain_db'], why=m['why'])
        return dict(edit=e, techniques=[dict(id=t.id, family=t.family, hero=t.hero, dur=list(t.dur), dialogue_ok=t.dialogue_ok) for t in lib.values()], script=lines)

    @api.post('/api/edit/propose', dependencies=[Depends(auth)])
    def post_propose(body: dict):                                                        # {folder, length_s?, bpm?, seed?, keep?, replace?}: the beat planner's film (it replaces a film planned from the script only with `replace`)
        from strata360.edit import project as PJ, optimise as O
        f = folder_of(body.get('folder'))
        if ((PJ.load(f).get('plan') or {}).get('source') == 'script') and not body.get('replace'): raise HTTPException(409, 'the film is planned from the script: this would replace it with the beat planner\'s arrangement of the clips (send replace to do that)')
        try: return dict(edit=PJ.propose(f, {k: body.get(k) for k in ('length_s', 'bpm', 'seed')}, keep=bool(body.get('keep', True))))
        except O.Infeasible as e: raise HTTPException(400, str(e))

    @api.post('/api/edit/override', dependencies=[Depends(auth)])
    def post_override(body: dict):                                                       # {folder, action: technique|lock|weight|ban|transition|reset, ...}
        from strata360.edit import project as PJ, optimise as O
        f = folder_of(body.get('folder')); act = body.get('action')
        try:
            if act == 'technique': e = PJ.set_technique(f, body['wid'], body.get('technique'))
            elif act == 'lock': e = PJ.set_lock(f, body['wid'], bool(body.get('locked', True)))
            elif act == 'transition': e = PJ.set_transition(f, body['wid'], body.get('transition'))
            elif act == 'weight': e = PJ.set_clip_weight(f, body['clip'], body.get('factor'))
            elif act == 'ban': e = PJ.ban(f, body['kind'], body['key'], bool(body.get('on', True)))
            elif act == 'reset': e = PJ.reset_overrides(f)
            else: raise HTTPException(400, 'unknown action')
        except (KeyError, ValueError) as ex: raise HTTPException(400, str(ex))
        except O.Infeasible as ex: raise HTTPException(400, str(ex))
        return dict(edit=e)

    @api.get('/api/script2', dependencies=[Depends(auth)])
    def get_script2(folder: str, name: str = ''):                                        # the whole-race script: the newest (or the named) draft, the list of drafts, your saved pins, whether a draft is being written, and the lines the draft plays (a white word is yellow when its line is in `used`)
        from strata360.edit import script_draft as SD
        f = folder_of(folder); j = SCRIPT2_JOBS.get(f); running = bool(j and j.poll() is None); doc = SD.load_draft(f, name or None); lp = os.path.join(SD._dir(f), 'job.log')
        used = sorted({i for it in (doc or {}).get('items') or [] if it.get('type') == 'clip' for i in it.get('lines') or []})          # the lines the draft plays, as resolved when it was written (cheap: no pack is built here)
        from strata360.edit import project as PJ
        pj = PLAN_JOBS.get(f); plan = (PJ.load(f).get('plan') or {}); ppath = os.path.join(SD._dir(f), 'plan.log')
        plan_info = dict(source=plan.get('source', 'beats'), script=plan.get('script'), windows=len(plan.get('segments') or []), length_s=(plan.get('film') or {}).get('length_s'), warnings=plan.get('warnings') or [], generated_at=plan.get('generated_at')) if plan else None
        return dict(draft=doc, drafts=SD.list_drafts(f), pins=SD.load_pins(f), running=running, plan=plan_info, plan_running=bool(pj and pj.poll() is None), plan_exit=(None if pj is None or pj.poll() is None else pj.returncode), plan_log=(clean_log(open(ppath).read().splitlines())[-6:] if os.path.exists(ppath) else []), last_exit=(None if running or j is None else j.returncode), log=(clean_log(open(lp).read().splitlines())[-12:] if os.path.exists(lp) else []), used=used, key_configured=_llm_key(f))

    def _llm_key(f):
        from strata360.edit import llm_remote
        return llm_remote.key_configured('gemini')

    @api.post('/api/script2/pins', dependencies=[Depends(auth)])
    def post_script2_pins(body: dict):                                                   # {folder, include?, exclude?, vo?, vo_never?}: your own pins (the transcript marks and the notes' narration fields are added automatically when a draft is written)
        from strata360.edit import script_draft as SD
        f = folder_of(body.get('folder')); vo = body.get('vo') or []
        if not isinstance(vo, list) or any(not isinstance(p, dict) or not str(p.get('text', '')).strip() or p.get('mode', 'anywhere') not in ('clip', 'ordered', 'anywhere') or (p.get('mode') == 'clip' and not p.get('clip')) for p in vo): raise HTTPException(400, 'vo: [{id, text, mode: clip | ordered | anywhere, clip? (for mode clip)}]')
        return SD.save_pins(f, body)

    @api.post('/api/script2/generate', dependencies=[Depends(auth)])
    def post_script2_generate(body: dict):                                               # {folder, revise?, target_s?, wpm?, auto?}: write a new draft, or revise the newest one, in the background (about 1 to 3 minutes)
        f = folder_of(body.get('folder')); j = SCRIPT2_JOBS.get(f)
        if j and j.poll() is None: return dict(started=False, reason='a draft is already being written')
        args = [*oslib.cli_command(), 'script-draft', f] + (['--revise'] if body.get('revise') else []) + (['--target-s', str(float(body['target_s']))] if body.get('target_s') else []) + (['--wpm', str(float(body['wpm']))] if body.get('wpm') else []) + (['--auto'] if body.get('auto') else [])
        d = os.path.join(config.race_dir(f), 'script2'); os.makedirs(d, exist_ok=True); log = open(os.path.join(d, 'job.log'), 'wb')
        SCRIPT2_JOBS[f] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/script2/plan', dependencies=[Depends(auth)])
    def post_script2_plan(body: dict):                                                   # {folder, draft?}: make the film's plan from a draft (the newest by default) and speak the narration, in the background (`strata360 script-plan --voice`)
        f = folder_of(body.get('folder')); j = PLAN_JOBS.get(f)
        if j and j.poll() is None: return dict(started=False, reason='the film is already being planned')
        args = [*oslib.cli_command(), 'script-plan', f, '--voice'] + (['--draft', os.path.basename(str(body['draft']))] if body.get('draft') else [])
        d = os.path.join(config.race_dir(f), 'script2'); os.makedirs(d, exist_ok=True); log = open(os.path.join(d, 'plan.log'), 'wb')
        PLAN_JOBS[f] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    def gap_rows(f):
        """The gaps between clips on the track with the generated clip planned for each (and for stretches of them), whether it is rendering, and its progress."""
        from strata360.gps import gaps as GP
        from strata360.edit import synthetic as SY
        cfg = config.load(f); tz = cfg.get('timezone', 'Europe/Brussels'); gaps = GP.find_gaps(GP.load_spans(f), loaded_raw_track(f), 1200.0, tz); docs = SY.load(f)['clips']; rd = config.race_dir(f)
        job = GAP_JOBS.get(f); running = job[0] if job and job[1].poll() is None else None
        def log_lines(cid):
            try: return open(os.path.join(rd, 'synthetic', cid + '.log'), errors='replace').read().strip().splitlines()
            except OSError: return []
        def prog(cid):                                                               # the newest "n/m frames" line (the log also holds start-up warnings that say nothing about the render)
            for l in reversed(log_lines(cid)):
                if re.search(r'\d+/\d+ frames', l): return l.strip()
            return 'starting…'
        def failure(cid):                                                            # why the last render stopped: the last real error line, not the interpreter's hashlib warnings
            for l in reversed(log_lines(cid)):
                if re.match(r'^[\w.]*(Error|Exception|Busy|MissingKey)\b', l) and 'unsupported hash type' not in l: return l.strip()[:300]
            return ''
        for c in docs:
            c['rendering'] = c['id'] == running; c['progress'] = prog(c['id']) if c['id'] == running else ''; c['exists'] = bool(c.get('file')) and os.path.exists(os.path.join(rd, c['file']))
            c['error'] = '' if c['rendering'] or c['exists'] else failure(c['id'])
        from strata360.edit import script_draft as SD
        draft = SD.load_draft(f) or {}; said = {}
        for n, it in enumerate(draft.get('items') or []):                                   # what the newest script draft does with each gap: the narration over it and its length
            gid = norm_label(it.get('clip', ''))
            if gid.startswith('G'): said.setdefault(gid, []).append(dict(n=n + 1, type=it.get('type'), text=(it.get('text') or '').strip(), seconds=it.get('seconds'), kind=it.get('kind')))
        used = in_film(f)
        for g in gaps: g['in_film'] = g['id'] in used; g['default_seconds'] = SY.default_seconds(g['duration_s']); g['clips'] = [c for c in docs if c.get('gap') == g['id']]; g['settings'] = SY.gap_settings(f, g['id']); g['script'] = said.get(g['id'], [])
        return gaps

    def loaded_raw_track(f):
        from strata360.gps import track
        cfg = config.load(f); p = config.track_path(f, cfg)
        if not p: raise HTTPException(404, 'there is no race track yet')
        return track.load(p)

    def photo_rows(f):
        """The photos with when and where each was taken (photos.py `located`) and the clip or gap its time falls in."""
        from strata360 import photos as PH
        from strata360.gps import track
        cfg = config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else {}; p = config.track_path(f, cfg); run = track.load(p) if p else None; rd = config.race_dir(f); clips = []
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json')
            if c: clips.append(dict(id=c['clip_id'], start_utc=c['time']['start_utc'], duration_s=c['video']['source_frames'] / c['video']['nominal_fps']))
        try: gaps = gap_rows(f) if run is not None else []
        except HTTPException: gaps = []
        from strata360.analysis import photo_analysis as PA
        out = []
        for e in PH.load(rd)['photos']:
            r = PH.located(e, run); r['where'] = PH.assign(e['taken_utc'], clips, gaps); r['analysis'] = PA.summary(PA.load_doc(rd, e['id'])); r['motion'] = PH.motion_of(e); out.append(r)
        return sorted(out, key=lambda x: x['taken_utc'])

    def photo_job(f):
        """The state of the photo analysis: whether it is running, the end of its log, and the last failure (a stage that could not run says why)."""
        from strata360.analysis import photo_analysis as PA
        job = PHOTO_JOBS.get(f); running = bool(job and job.poll() is None); lines = []
        try: lines = open(os.path.join(PA.adir(config.race_dir(f)), 'run.log'), errors='replace').read().strip().splitlines()
        except OSError: pass
        lines = [l for l in lines if 'unsupported hash type' not in l and not l.startswith(('Traceback', '  File', '    ', 'ValueError: unsupported', 'ERROR:root'))]
        fail = next((l for l in reversed(lines) if 'FAILED' in l or l.startswith('photos-analyse:')), '')
        return dict(running=running, log=lines[-6:], error='' if running else fail[:400])

    def streetview_job(f):
        """Whether the street view stages are running, the end of their log and the last failure."""
        from strata360 import streetview as SV
        job = STREETVIEW_JOBS.get(f); running = bool(job and job.poll() is None); lines = []
        try: lines = open(os.path.join(SV.adir(config.race_dir(f)), 'run.log'), errors='replace').read().strip().splitlines()
        except OSError: pass
        fail = next((l for l in reversed(lines) if l.startswith('streetview:')), '')
        return dict(running=running, log=lines[-6:], error='' if running else fail[:400])

    def sv_footage(f):
        """(clips, gaps) for placing a street view section among the footage: [{label, t0, t1}] of the camera clips and [{id, t0, t1}] of the gaps in them (empty lists when there is no track yet)."""
        import datetime as dt
        rd = config.race_dir(f); clips = []
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json')
            if not c: continue
            t0 = dt.datetime.fromisoformat(c['time']['start_utc'].replace('Z', '+00:00')).timestamp(); m = re.search(r'_(\d{4})_D$', c['clip_id'])
            clips.append(dict(label=m.group(1) if m else c['clip_id'], t0=t0, t1=t0 + c['video']['source_frames'] / c['video']['nominal_fps']))
        try: gaps = [dict(id=g['id'], t0=g['t0'], t1=g['t1']) for g in gap_rows(f)]
        except HTTPException: gaps = []
        return clips, gaps

    def sv_track(f):
        """The race track for working out the light at a section, or None when there is none."""
        try: return loaded_raw_track(f)
        except HTTPException: return None

    @api.get('/api/streetview', dependencies=[Depends(auth)])
    def get_streetview(folder: str):                                                     # the road stretches, each provider's sections of imagery, what stage is done, the running job, and which keys are set
        from strata360 import streetview as SV
        from strata360.edit import llm_remote as LR
        f = folder_of(folder); rd = config.race_dir(f); docs = {p: SV.load(rd, p) for p in SV.PROVIDERS}
        return dict(status=SV.status(rd), roads=SV.load(rd, 'roads'), providers={p: (dict(frames=d['frames'], km=d['km']) if d else None) for p, d in docs.items()}, sections=SV.annotate(rd, docs, sv_track(f), *sv_footage(f)), job=streetview_job(f), keys=dict(mapillary=bool(LR.secret('MAPILLARY_TOKEN')), google=bool(LR.secret('GOOGLE_MAPS_API_KEY'))))

    @api.post('/api/streetview/run', dependencies=[Depends(auth)])
    def post_streetview_run(body: dict):                                                 # {folder, stages?: [..], force?}: make the stages in the background at the lowest priority
        from strata360 import streetview as SV
        f = folder_of(body.get('folder')); stages = [str(s) for s in body.get('stages') or []]; bad = [s for s in stages if s not in SV.STAGES]
        if bad: raise HTTPException(400, f'unknown street view stage(s) {", ".join(bad)}: one of {", ".join(SV.STAGES)}')
        job = STREETVIEW_JOBS.get(f)
        if job and job.poll() is None: return dict(started=False, reason='street view is already being worked out')
        cmd = [*oslib.cli_command(), 'streetview', f] + (['--stages', ','.join(stages)] if stages else []) + (['--force'] if body.get('force') else [])
        d = SV.adir(config.race_dir(f)); os.makedirs(d, exist_ok=True); log = open(os.path.join(d, 'run.log'), 'wb')
        STREETVIEW_JOBS[f] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/streetview/choice', dependencies=[Depends(auth)])
    def post_streetview_choice(body: dict):                                              # {folder, key, choice: 'none' | 'possible' | 'must'}: whether the film may use this section (the writer is only told about the ones you chose)
        from strata360 import streetview as SV
        f = folder_of(body.get('folder')); rd = config.race_dir(f); key = str(body.get('key') or '')
        if not any(x['key'] == key for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS})): raise HTTPException(404, 'no such street view section')
        choice = str(body.get('choice') or '')
        try: SV.set_choice(rd, key, choice)
        except ValueError as ex: raise HTTPException(400, str(ex))
        return dict(key=key, choice=None if choice == 'none' else choice)

    @api.post('/api/streetview/promote', dependencies=[Depends(auth)])
    def post_streetview_promote(body: dict):                                             # {folder, provider, id, sequence, lat, lon}: make a capture run found by the nearest-street-view search a section like the others
        from strata360 import streetview as SV
        from strata360.edit import llm_remote as LR
        f = folder_of(body.get('folder')); rd = config.race_dir(f); prov = str(body.get('provider') or '')
        if prov not in SV.PROVIDERS: raise HTTPException(400, f'provider is one of {", ".join(SV.PROVIDERS)}')
        try: lat, lon = float(body['lat']), float(body['lon'])
        except (KeyError, TypeError, ValueError): raise HTTPException(400, 'lat and lon are needed')
        try: s = SV.promote(rd, prov, str(body.get('id') or ''), str(body.get('sequence') or ''), lat, lon, sv_track(f), token=LR.secret('MAPILLARY_TOKEN'), gkey=LR.secret('GOOGLE_MAPS_API_KEY'))
        except ValueError as ex: raise HTTPException(400, str(ex))
        return dict(key=SV.section_key(s), id=s['id'])

    @api.post('/api/streetview/unpromote', dependencies=[Depends(auth)])
    def post_streetview_unpromote(body: dict):                                           # {folder, key}: take a section made that way out again
        from strata360 import streetview as SV
        f = folder_of(body.get('folder'))
        if not SV.unpromote(config.race_dir(f), str(body.get('key') or '')): raise HTTPException(404, 'no such promoted section')
        return dict(removed=True)

    def sv_section(f, key):
        """The annotated street view section with this key, or a 404."""
        from strata360 import streetview as SV
        rd = config.race_dir(f); s = next((x for x in SV.annotate(rd, {p: SV.load(rd, p) for p in SV.PROVIDERS}) if x['key'] == key), None)
        if s is None: raise HTTPException(404, 'no such street view section')
        return rd, s

    def sv_video_state(f, key):
        from strata360 import streetview as SV
        rd, s = sv_section(f, key); job = STREETVIEW_VIDEO_JOBS.get((f, key)); running = bool(job and job.poll() is None); lines = []
        try: lines = open(os.path.splitext(SV.video_path(rd, s))[0] + '.log', errors='replace').read().strip().splitlines()
        except OSError: pass
        fail = next((l for l in reversed(lines) if l.startswith('streetview-video:')), '')
        return dict(exists=os.path.exists(SV.video_path(rd, s)), running=running, log=lines[-4:], error='' if running else fail[:400], seconds=SV.default_seconds(s))

    @api.get('/api/streetview/video', dependencies=[Depends(auth)])
    def get_streetview_video(folder: str, key: str):                                      # whether the section's preview video exists, is being made, or failed
        return sv_video_state(folder_of(folder), key)

    @api.post('/api/streetview/video', dependencies=[Depends(auth)])
    def post_streetview_video(body: dict):                                                # {folder, key}: make the preview video in the background (nothing to do when it exists)
        from strata360 import streetview as SV
        f = folder_of(body.get('folder')); key = str(body.get('key') or ''); rd, s = sv_section(f, key)
        if os.path.exists(SV.video_path(rd, s)): return dict(started=False, reason='the video is already made')
        if any(p.poll() is None for (ff, _), p in STREETVIEW_VIDEO_JOBS.items() if ff == f): return dict(started=False, reason='another preview video is being made')
        out = SV.video_path(rd, s); os.makedirs(os.path.dirname(out), exist_ok=True); log = open(os.path.splitext(out)[0] + '.log', 'wb')
        STREETVIEW_VIDEO_JOBS[(f, key)] = subprocess.Popen([*oslib.cli_command(), 'streetview-video', f, key], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.get('/api/streetview/video/file')
    def get_streetview_video_file(request: Request, folder: str, key: str):               # the video itself (a <video> cannot send headers: the cookie / query token authenticates)
        from strata360 import streetview as SV
        auth(request); rd, s = sv_section(folder_of(folder), key); p = SV.video_path(rd, s)
        if not os.path.exists(p): raise HTTPException(404, 'the video is not made yet')
        return FileResponse(p, media_type='video/mp4', headers={'Cache-Control': 'max-age=3600'})

    @api.get('/api/streetview/near', dependencies=[Depends(auth)])
    def get_streetview_near(folder: str, lat: float, lon: float, n: int = 5):               # the street view nearest (as the crow flies) to a point clicked on the map, from each provider, each with the rules that would rule it out; no filters
        from strata360 import streetview as SV
        from strata360.edit import llm_remote as LR
        f = folder_of(folder); rd = config.race_dir(f); n = max(1, min(int(n), 12)); clips, gaps = sv_footage(f)
        res = SV.near_point(rd, lat, lon, n, sv_track(f), clips, gaps, token=LR.secret('MAPILLARY_TOKEN'), gkey=LR.secret('GOOGLE_MAPS_API_KEY'))
        for prov, block in res['providers'].items():
            for it in block['items']: STREETVIEW_NEAR[(f, prov, it['id'])] = dict(id=it['id'], url=it.get('url'), compass=it.get('compass'))        # only pictures found here can be asked for (the page's thumbnails)
        return res

    @api.get('/api/streetview/near/image')
    def get_streetview_near_image(request: Request, folder: str, provider: str, id: str, w: int = 256):   # the picture of one of those (an <img> cannot send headers: the cookie / query token authenticates)
        from strata360 import streetview as SV
        auth(request); f = folder_of(folder); item = STREETVIEW_NEAR.get((f, provider, id))
        if item is None: raise HTTPException(404, 'no such picture: click the map again')
        try: data = SV.image_near(config.race_dir(f), provider, item, w)
        except RuntimeError as ex: raise HTTPException(502, str(ex))
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})

    @api.get('/api/streetview/image')
    def get_streetview_image(request: Request, folder: str, provider: str, id: str, w: int = 640):   # one frame as a JPEG (an <img> cannot send headers: the cookie / query token authenticates); only frames the stage found can be asked for
        from strata360 import streetview as SV
        auth(request); rd = config.race_dir(folder_of(folder))
        if provider not in SV.PROVIDERS: raise HTTPException(400, f'provider is one of {", ".join(SV.PROVIDERS)}')
        try: data = SV.image(rd, provider, SV.load(rd, provider), id, w)
        except KeyError: raise HTTPException(404, 'no such frame')
        except RuntimeError as ex: raise HTTPException(502, str(ex))
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})

    def start_photo_job(f, stages=(), photo=(), force=False):
        """Start `photos-analyse` in the background (one at a time per project); {started, reason?}."""
        from strata360.analysis import photo_analysis as PA
        job = PHOTO_JOBS.get(f)
        if job and job.poll() is None: return dict(started=False, reason='the photos are already being analysed')
        cmd = [*oslib.cli_command(), 'photos-analyse', f] + (['--stages', ','.join(stages)] if stages else []) + [x for p in photo for x in ('--photo', p)] + (['--force'] if force else [])
        d = PA.adir(config.race_dir(f)); os.makedirs(d, exist_ok=True); log = open(os.path.join(d, 'run.log'), 'wb')
        PHOTO_JOBS[f] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    def overlays_changed(f):
        """What the overlay shows has changed (a cut-off, a track, a checkpoint): forget the thumbnails with the overlay (clips and photos, so no old one is shown) and start making them again. The film preview is out of date by its own key; it is not remade
        until asked (it is big)."""
        from strata360 import photos as PH
        from strata360.analysis import photo_analysis as PA
        from strata360.pipeline import runner
        rd = config.race_dir(f); library = config.load(f).get('library') if os.path.exists(os.path.join(rd, 'race.json')) else None
        if library: runner.clear(f, 'thumb_overlay')
        for pth in glob.glob(os.path.join(rd, 'clips', '*', 'thumb_overlay.*')) + glob.glob(os.path.join(PA.adir(rd), '*-overlay.jpg')):
            try: os.remove(pth)
            except OSError: pass
        if library: start_job(f, ('run', '--stages', 'thumb_overlay'))
        if PH.load(rd)['photos']: start_photo_job(f, ['thumb_overlay'])

    @api.get('/api/photos', dependencies=[Depends(auth)])
    def get_photos(folder: str):                                                         # the photos with their time, place (own GPS first, else the run's position at that time), whether those disagree, and the clip or gap they fall in
        f = folder_of(folder); return dict(photos=photo_rows(f), job=photo_job(f), tz=(config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else {}).get('timezone') or 'Europe/Brussels')

    @api.post('/api/photos', dependencies=[Depends(auth)])
    async def post_photo(request: Request, folder: str, filename: str):                  # one photo as the raw request body (the page sends several one after the other)
        from strata360 import photos as PH
        f = folder_of(folder); data = await request.body(); cfg = config.load(f) if os.path.exists(os.path.join(config.race_dir(f), 'race.json')) else {}
        try: e = PH.add(config.race_dir(f), filename, data, cfg.get('timezone') or 'Europe/Brussels')
        except ValueError as ex: raise HTTPException(400, f'{filename}: {ex}')
        return next(x for x in photo_rows(f) if x['id'] == e['id'])

    def photo_plan(f, pid, style=None, seconds=None, seed=None):
        """The pan and zoom for a photo: its saved settings (or those asked for) applied to what the analysis found in it: the plan (edit/photo_motion.py) with the first and last windows as fractions of the picture, for drawing on it."""
        from strata360 import photos as PH
        from strata360.analysis import photo_analysis as PA
        from strata360.edit import photo_motion as PM
        rd = config.race_dir(f); e = next((x for x in PH.load(rd)['photos'] if x['id'] == pid), None)
        if e is None: raise HTTPException(404, 'no such photo')
        m = PH.motion_of(e); st = style or m['style']; doc = PA.load_doc(rd, pid); sec = float(seconds if seconds is not None else (m['seconds'] if m['seconds'] is not None else PA.auto_seconds(doc))); sd = int(seed if seed is not None else m['seed'])
        path = os.path.join(rd, e['file']); size = PH.oriented_size(path)
        try: pl = PM.plan(size, sec, st, PM.focals(doc, PA.read_bgr(path, 480)), sd)
        except ValueError as ex: raise HTTPException(400, str(ex))
        w, h = pl['size']; pl['windows'] = [[round(v / d, 4) for v, d in zip(PM.crop_at(pl, t), (w, h, w, h))] for t in (0.0, pl['duration_s'])]; pl['settings'] = m; return pl

    @api.get('/api/photos/motion', dependencies=[Depends(auth)])
    def get_photo_motion(folder: str, id: str, style: str = '', seconds: float | None = None, seed: int | None = None):   # the pan and zoom plan for a photo (the saved settings unless style / seconds / seed are given), to show its path
        return photo_plan(folder_of(folder), id, style or None, seconds, seed)

    @api.post('/api/photos/motion', dependencies=[Depends(auth)])
    def post_photo_motion(body: dict):                                                   # {folder, id, style?, seconds?, seed?}: save the pan and zoom chosen for a photo; returns the plan
        from strata360 import photos as PH
        f = folder_of(body.get('folder')); pid = str(body.get('id') or '')
        try: PH.set_motion(config.race_dir(f), pid, **{k: body[k] for k in ('style', 'seconds', 'seed') if k in body})
        except KeyError: raise HTTPException(404, 'no such photo')
        except ValueError as ex: raise HTTPException(400, str(ex))
        return photo_plan(f, pid)

    @api.get('/api/photos/motion/video')
    def get_photo_motion_video(request: Request, folder: str, id: str, style: str = '', seconds: float | None = None, seed: int | None = None, w: int = 960):   # the move as a small MP4 to watch (made when first asked for, kept); a <video> cannot send headers: the cookie / query token authenticates
        import hashlib
        from strata360 import photos as PH
        from strata360.analysis import photo_analysis as PA
        from strata360.edit import photo_motion as PM
        auth(request); f = folder_of(folder); rd = config.race_dir(f); pl = photo_plan(f, id, style or None, seconds, seed); w = max(320, min(int(w), 1920)); w -= w % 2; h = int(round(w / pl['aspect'])) // 2 * 2
        e = next(x for x in PH.load(rd)['photos'] if x['id'] == id); src = os.path.join(rd, e['file'])
        key = hashlib.sha1(json.dumps([pl['keys'], w, h, os.path.getmtime(src), pl['size']]).encode()).hexdigest()[:12]; out = os.path.join(rd, 'photos', 'motion', f'{id}-{key}.mp4')
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True); tmp = out + '.part.mp4'
            try: PM.write_video(tmp, PA.read_bgr(src, 2400), pl, (w, h)); os.replace(tmp, out)
            except RuntimeError as ex: raise HTTPException(500, str(ex))
        return FileResponse(out, media_type='video/mp4', headers={'Cache-Control': 'max-age=86400'})

    @api.post('/api/photos/settings', dependencies=[Depends(auth)])
    def post_photo_settings(body: dict):                                                 # {folder, id, must}: use this photo in the film (the plan adds it where its time falls if the script leaves it out)
        from strata360 import photos as PH
        f = folder_of(body.get('folder')); pid = str(body.get('id') or '')
        try: return dict(id=pid, must=PH.set_must(config.race_dir(f), pid, bool(body.get('must'))))
        except KeyError: raise HTTPException(404, 'no such photo')

    @api.post('/api/photos/analyse', dependencies=[Depends(auth)])
    def post_photos_analyse(body: dict):                                                 # {folder, stages?: [..], photo?: [ids], force?}: run the clip stages that make sense for a photo over the photos, in the background at the lowest priority (`strata360 photos-analyse`)
        from strata360.analysis import photo_analysis as PA
        f = folder_of(body.get('folder')); stages = [str(s) for s in body.get('stages') or []]; bad = [s for s in stages if s not in PA.VERSIONS]
        if bad: raise HTTPException(400, f'unknown photo stage(s) {", ".join(bad)}: one of {", ".join(PA.ORDER)}')
        return start_photo_job(f, stages, [str(p) for p in body.get('photo') or []], bool(body.get('force')))

    @api.delete('/api/photos', dependencies=[Depends(auth)])
    def delete_photo(folder: str, id: str):                                              # take a photo out (its files are kept under photos/removed)
        from strata360 import photos as PH
        f = folder_of(folder)
        try: PH.remove(config.race_dir(f), id)
        except KeyError: raise HTTPException(404, 'no such photo')
        from strata360.edit import synthetic as SY
        SY.remove(f, PH.label_of(id))                                                    # its clip in the plan goes too
        return dict(photos=photo_rows(f))

    @api.get('/api/photos/thumb')
    def get_photo_thumb(request: Request, folder: str, id: str, w: int = 480, overlay: bool = False):  # a small copy, the right way up (an <img> cannot send headers: the cookie / query token authenticates); overlay=1: the picture with the race overlay as it was then, once the thumb_overlay stage has made it
        from strata360 import photos as PH
        from strata360.analysis import photo_analysis as PA
        auth(request); rd = config.race_dir(folder_of(folder))
        if overlay:
            o = os.path.join(PA.adir(rd), f'{id}-overlay.jpg')
            if os.path.exists(o): return FileResponse(o, media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
            raise HTTPException(404, 'no overlay version of this photo yet')
        p = PH.thumb(rd, id, w)
        if not p: raise HTTPException(404, 'no such photo')
        return FileResponse(p, media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})

    @api.get('/api/photos/file')
    def get_photo_file(request: Request, folder: str, id: str, original: bool = False):  # the photo to look at: a JPEG up to 3000 px wide whatever the format it came in (a browser cannot show a TIFF or a HEIC); original=1 sends the uploaded file as it was
        from strata360 import photos as PH
        auth(request); rd = config.race_dir(folder_of(folder)); e = next((x for x in PH.load(rd)['photos'] if x['id'] == id), None)
        if e is None or not os.path.exists(os.path.join(rd, e['file'])): raise HTTPException(404, 'no such photo')
        if original: return FileResponse(os.path.join(rd, e.get('original') or e['file']), headers={'Cache-Control': 'max-age=86400'})
        return FileResponse(PH.thumb(rd, id, 3000), media_type='image/jpeg', headers={'Cache-Control': 'max-age=86400'})

    @api.get('/api/gaps', dependencies=[Depends(auth)])
    def get_gaps(folder: str):                                                           # the stretches of the race with no clip, each with its generated map clips
        from strata360.overlay import flyover as FO
        f = folder_of(folder)
        try: FO.find_mbgl(); flyover = dict(available=True, note='')
        except FO.FlyoverError as e: flyover = dict(available=False, note=str(e))
        return dict(gaps=gap_rows(f), flyover=flyover)

    @api.post('/api/gaps/settings', dependencies=[Depends(auth)])
    def post_gap_settings(body: dict):                                                   # {folder, gap, kind?: 'map' | 'flyover' | null, mode?: 'set' | 'min' | null, seconds?, must?}: what you chose for a gap (kind, a set or a minimum length, must-use); only the fields sent change
        from strata360.edit import synthetic as SY
        f = folder_of(body.get('folder')); gid = str(body.get('gap') or '')
        if not any(g['id'] == gid for g in gap_rows(f)): raise HTTPException(404, 'no such gap')
        try: return SY.set_settings(f, gid, **{k: body[k] for k in ('kind', 'mode', 'seconds', 'must') if k in body})
        except ValueError as e: raise HTTPException(400, str(e))

    @api.post('/api/gaps/clip', dependencies=[Depends(auth)])
    def post_gap_clip(body: dict):                                                       # {folder, gap, kind? ('map' | 'flyover'), size?, seconds? | speedup?, from?, to?, id?}: plan a generated clip (the 2D map or the 3D flyover, 4K) for a gap (or a stretch of it); rendering is a separate step
        import datetime as dt
        from strata360.edit import synthetic as SY
        f = folder_of(body.get('folder')); gap = next((g for g in gap_rows(f) if g['id'] == body.get('gap')), None)
        if gap is None: raise HTTPException(404, 'no such gap')
        def when(x):
            if x in (None, ''): return None
            try: return float(x) if isinstance(x, (int, float)) else dt.datetime.fromisoformat(str(x).replace('Z', '+00:00')).timestamp()
            except ValueError: raise HTTPException(400, 'from/to: epoch seconds or an ISO time')
        t0, t1 = when(body.get('from')), when(body.get('to')); cid = body.get('id') or (gap['id'] if t0 is None and t1 is None else None)
        if not cid: raise HTTPException(400, 'a stretch of a gap needs an id')
        try: clip = SY.make(gap, seconds=body.get('seconds'), speedup=body.get('speedup'), t0=t0, t1=t1, id=cid, kind=body.get('kind') or 'map', size=body.get('size'), by='user')
        except ValueError as e: raise HTTPException(400, str(e))
        return SY.upsert(f, clip)

    @api.post('/api/gaps/approve', dependencies=[Depends(auth)])
    def post_gap_approve(body: dict):                                                    # {folder, id}: approve a clip the script planned (a 3D flyover is not rendered until you do)
        from strata360.edit import synthetic as SY
        f = folder_of(body.get('folder')); doc = SY.load(f); c = next((c for c in doc['clips'] if c['id'] == body.get('id')), None)
        if c is None: raise HTTPException(404, 'no such planned clip')
        c['approved'] = True; SY.save(f, doc); return c

    @api.post('/api/gaps/render', dependencies=[Depends(auth)])
    def post_gap_render(body: dict):                                                     # {folder, id}: render a planned generated clip in the background (`strata360 gap-clip --clip`)
        from strata360.edit import synthetic as SY
        f = folder_of(body.get('folder')); cid = str(body.get('id') or '')
        c = next((c for c in SY.load(f)['clips'] if c['id'] == cid), None)
        if c is None: raise HTTPException(404, 'no such planned clip')
        job = GAP_JOBS.get(f)
        if job and job[1].poll() is None: return dict(started=False, reason=f'{job[0]} is already being rendered')
        d = os.path.join(config.race_dir(f), 'synthetic'); os.makedirs(d, exist_ok=True); log = open(os.path.join(d, cid + '.log'), 'wb')
        GAP_JOBS[f] = (cid, subprocess.Popen([*oslib.cli_command(), 'gap-clip', f, '--clip', cid], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True)); return dict(started=True)

    @api.delete('/api/gaps/clip', dependencies=[Depends(auth)])
    def delete_gap_clip(folder: str, id: str):                                           # forget a planned clip and its video
        from strata360.edit import synthetic as SY
        f = folder_of(folder); doc = SY.load(f); c = next((c for c in doc['clips'] if c['id'] == id), None)
        if c is None: raise HTTPException(404, 'no such planned clip')
        job = GAP_JOBS.get(f)
        if job and job[1].poll() is None and job[0] == id: raise HTTPException(409, 'it is being rendered')
        SY.remove(f, id); p = os.path.join(config.race_dir(f), c.get('file') or '-')
        if c.get('file') and os.path.exists(p): os.remove(p)
        return dict(removed=True)

    @api.get('/api/gaps/video')
    def get_gap_video(request: Request, folder: str, id: str):                           # the rendered video (Range requests are handled; <video> cannot send headers, so the cookie authenticates)
        from strata360.edit import synthetic as SY
        auth(request); f = folder_of(folder); c = next((c for c in SY.load(f)['clips'] if c['id'] == id), None); p = os.path.join(config.race_dir(f), (c or {}).get('file') or '-')
        if not c or not os.path.exists(p): raise HTTPException(404, 'that clip has not been rendered yet')
        return FileResponse(p, media_type='video/mp4', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/lyrics', dependencies=[Depends(auth)])
    def get_lyrics(folder: str):                                                         # the words found in the music track: where it is sung, with your corrections, and whether a run is going or failed
        from strata360.edit import lyrics as LY
        f = folder_of(folder); job = LYRICS_JOBS.get(f); running = bool(job and job.poll() is None); log = os.path.join(config.race_dir(f), 'lyrics.log')
        try: lines = [l for l in open(log, errors='replace').read().strip().splitlines() if 'unsupported hash type' not in l]
        except OSError: lines = []
        err = ''
        if job and not running and job.returncode: err = next((l for l in reversed(lines) if l.strip() and not l.startswith(('Traceback', '  File', '    '))), 'failed')[:300]
        v = LY.view(f) or {}
        return dict(LY.status(f), building=running, error=err, log=lines[-1] if lines else '', phrases_list=v.get('phrases', []), vocal_spans=v.get('vocal_spans', []))

    @api.post('/api/lyrics', dependencies=[Depends(auth)])
    def post_lyrics(body: dict):                                                         # {folder}: listen to the track in the background (`strata360 lyrics`)
        from strata360.edit import lyrics as LY
        f = folder_of(body.get('folder')); job = LYRICS_JOBS.get(f)
        if job and job.poll() is None: return dict(started=False, reason='the lyrics are already being found')
        if not LY.status(f)['has_track']: return dict(started=False, reason='there is no music track yet: add one first')
        log = open(os.path.join(config.race_dir(f), 'lyrics.log'), 'wb')
        LYRICS_JOBS[f] = subprocess.Popen([*oslib.cli_command(), 'lyrics', f], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.post('/api/lyrics/phrase', dependencies=[Depends(auth)])
    def post_lyrics_phrase(body: dict):                                                  # {folder, key, text?, deleted?, keep?}: correct one phrase (new words, not sung, or counts as sung after all)
        from strata360.edit import lyrics as LY
        p = LY.edit(folder_of(body.get('folder')), str(body.get('key') or ''), body.get('text'), body.get('deleted'), body.get('keep'))
        if p is None: raise HTTPException(404, 'no such phrase')
        return p

    @api.delete('/api/lyrics', dependencies=[Depends(auth)])
    def delete_lyrics(folder: str, corrections: bool = False):                           # reset: forget the record (and your corrections with ?corrections=true)
        from strata360.edit import lyrics as LY
        f = folder_of(folder); job = LYRICS_JOBS.get(f)
        if job and job.poll() is None: raise HTTPException(409, 'the lyrics are being found')
        return dict(reset=LY.reset(f, corrections))

    @api.get('/api/script2/mix', dependencies=[Depends(auth)])
    def get_rough_mix(folder: str):                                                      # the rough mix of the film plan: whether there is one, whether it is out of date, whether it is being made and how the last try went
        from strata360.edit import roughmix as RM
        f = folder_of(folder); job = MIX_JOBS.get(f); running = bool(job and job.poll() is None); log = os.path.join(RM.dir_of(f), 'mix.log')
        try: lines = [l for l in open(log, errors='replace').read().strip().splitlines() if 'unsupported hash type' not in l]
        except OSError: lines = []
        err = ''
        if job and not running and job.returncode: err = next((l for l in reversed(lines) if l.strip() and not l.startswith(('Traceback', '  File', '    '))), 'failed')[:300]
        return dict(RM.status(f), building=running, error=err, log=lines[-1] if lines else '')

    @api.post('/api/script2/mix', dependencies=[Depends(auth)])
    def post_rough_mix(body: dict):                                                      # {folder}: make the rough mix in the background (`strata360 rough-mix`)
        from strata360.edit import roughmix as RM
        f = folder_of(body.get('folder')); job = MIX_JOBS.get(f)
        if job and job.poll() is None: return dict(started=False, reason='the rough mix is already being made')
        if not RM.status(f)['has_plan']: return dict(started=False, reason='there is no film plan yet: make the film from a script first')
        os.makedirs(RM.dir_of(f), exist_ok=True); log = open(os.path.join(RM.dir_of(f), 'mix.log'), 'wb')
        MIX_JOBS[f] = subprocess.Popen([*oslib.cli_command(), 'rough-mix', f], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT_DIR, start_new_session=True); return dict(started=True)

    @api.delete('/api/script2/mix', dependencies=[Depends(auth)])
    def delete_rough_mix(folder: str):                                                   # reset: forget the mix, so it is made again from scratch
        from strata360.edit import roughmix as RM
        f = folder_of(folder); job = MIX_JOBS.get(f)
        if job and job.poll() is None: raise HTTPException(409, 'the rough mix is being made')
        return dict(reset=RM.reset(f))

    @api.get('/api/script2/mix/audio')
    def get_rough_mix_audio(request: Request, folder: str):                              # the mix (Range requests are handled, so seeking works); <audio> cannot send headers, so the cookie authenticates
        from strata360.edit import roughmix as RM
        auth(request); p = RM.path_of(folder_of(folder))
        if not os.path.exists(p): raise HTTPException(404, 'the rough mix has not been made yet')
        return FileResponse(p, media_type='audio/mp4', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/script', dependencies=[Depends(auth)])
    def get_script(folder: str):                                                         # key status (never the key), the model list, whether a run is going, and the newest script
        from strata360.edit import llm_remote as LR
        f = folder_of(folder); rd = config.race_dir(f); j = SCRIPT_JOBS.get(f); running = bool(j and j.poll() is None)
        files = sorted(glob.glob(os.path.join(rd, 'scripts', 'script-*.json'))); latest = None
        if files:
            try:
                latest = json.load(open(files[-1])); said = {f['index']: f.get('wearer_says') or [] for f in latest.get('facts', [])}
                for l in latest.get('lines', []): l.setdefault('says', said.get(l['seg'], []))                 # scripts written before the field existed: take it from the saved facts
                latest.pop('facts', None); latest['file'] = os.path.basename(files[-1])
            except ValueError: latest = None
        log = ''
        try: log = '\n'.join(clean_log(open(os.path.join(rd, 'script_job.log')).read().splitlines()))[-600:]
        except OSError: pass
        cfg = config.load(f).get('llm', {}) if os.path.exists(os.path.join(rd, 'race.json')) else {}
        prov = cfg.get('provider', 'vertex'); providers = {k: dict(models=v['models'], default=v['default'], configured=LR.key_configured(k)) for k, v in LR.PROVIDERS.items()}
        return dict(key_configured=providers.get(prov, {}).get('configured', False), providers=providers, models=LR.PROVIDERS.get(prov, LR.PROVIDERS['vertex'])['models'], llm=dict(provider=prov, model=cfg.get('model') or LR.PROVIDERS[prov]['default']), running=running,
                    last_exit=None if (j is None or running) else j.returncode, log=log, latest=latest, scripts=len(files))

    @api.post('/api/llm/key', dependencies=[Depends(auth)])
    def post_key(body: dict):                                                            # write-only: the key is stored server-side (mode 600) and never returned
        from strata360.edit import llm_remote as LR
        prov = body.get('provider') if body.get('provider') in LR.PROVIDERS else 'vertex'
        try: return dict(configured=LR.set_key(str(body.get('key') or ''), prov))
        except LR.LLMError as e: raise HTTPException(400, str(e))

    @api.post('/api/script/generate', dependencies=[Depends(auth)])
    def post_generate(body: dict):                                                       # {folder, length, wpm?, style?, model?}: runs `strata360 script` in the background
        f = folder_of(body.get('folder')); j = SCRIPT_JOBS.get(f)
        if j and j.poll() is None: return dict(started=False)
        args = [*oslib.cli_command(), 'script', f, '--length', str(float(body.get('length') or 90))]
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


def app_from_env():
    return create_app([r for r in os.environ.get('STRATA360_SERVER_ROOTS', '').split(os.pathsep) if r], os.environ.get('STRATA360_SERVER_TOKEN') or None)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='strata360 serve'); ap.add_argument('--root', action='append', help='folder the browser may look inside (repeatable)'); ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8360); ap.add_argument('--token', help='shared secret (required when --host is not 127.0.0.1; generated if omitted)'); ap.add_argument('--reload', action='store_true', help='restart the server when the code changes (workers and renders keep running: they are separate processes)'); a = ap.parse_args(argv)
    roots = load_roots(a.root)
    if not roots: sys.exit('no allowed folders: give --root PATH (repeatable) or list them in ~/.strata360/server.json {"roots": [...]}')
    token = a.token if a.token else (secrets.token_urlsafe(16) if a.host not in ('127.0.0.1', 'localhost') else None)
    print(f'strata360 server on http://{a.host}:{a.port}/' + (f'?token={token}' if token else '')); print('allowed folders:', ', '.join(roots))
    import uvicorn
    if a.reload:                                                                          # the app is rebuilt from the environment after each restart
        os.environ['STRATA360_SERVER_ROOTS'] = os.pathsep.join(roots); os.environ['STRATA360_SERVER_TOKEN'] = token or ''
        uvicorn.run('strata360.server.app:app_from_env', factory=True, host=a.host, port=a.port, log_level='warning', reload=True, reload_dirs=[os.path.dirname(os.path.dirname(os.path.abspath(__file__)))], reload_includes=['*.py'])
    else: uvicorn.run(create_app(roots, token), host=a.host, port=a.port, log_level='warning')


if __name__ == '__main__':
    main()
