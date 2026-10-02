"""strata360 web server: run it on the machine that holds the footage, open it from any browser.

    ./strata360 serve --root ~/footage --root /Volumes/Expansion [--host 127.0.0.1] [--port 8360] [--token SECRET]

Built on FastAPI (interactive API docs at /api/docs). Security model: the server can only see inside the whitelisted roots (`--root`, repeatable, or `~/.strata360/server.json` {"roots": [...]}); every path from the browser is resolved
(symlinks included) and refused if it leaves a root. It binds to 127.0.0.1 unless told otherwise; when bound to another address a token is required (sent as a cookie after
`?token=` on first visit, or as `Authorization: Bearer`). Nothing here deletes or modifies footage; the only writes are the project folders (`<footage>/strata360/`).

API (JSON):  GET /api/roots, /api/browse?path=, /api/progress?folder=, /api/log?folder=;  POST /api/open {folder, languages?, gps?}, /api/run {folder}, /api/stop {folder}."""
import argparse, glob, json, os, secrets, subprocess, sys, threading, time

from strata360 import oslib
from strata360.pipeline import config, clips as clipmod
from strata360.analysis import thumbs as TH, transcript_edits as TE, transcript_fix as TF

STATIC = os.path.join(os.path.dirname(__file__), 'static')
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
JOBS = {}                     # folder -> [Popen] of workers started by this server (workers started elsewhere are found through the project's registry)
MAX_WORKERS = 3
FINAL_JOBS = {}; FILM_JOBS = {}
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

    @api.get('/api/clips', dependencies=[Depends(auth)])
    def get_clips(folder: str):                                                          # the clip list: id, time, length, a note flag, whether a thumbnail exists and a few facts
        from strata360.pipeline import notes as N
        f = folder_of(folder); rd = config.race_dir(f); out = []; nt = N.load(f)
        for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
            c = _j(d, 'clip.json')
            if not c: continue
            mo = _j(d, 'motion.json'); cd = _j(d, 'candidates.json'); thumb = 'best' if os.path.exists(d + 'thumb.jpg') else 'quick' if os.path.exists(d + 'thumb_quick.jpg') else None
            if thumb and TH.overlay_fresh(d): thumb += '+overlay'                                                     # the version also busts the browser cache when the overlay one appears
            out.append(dict(id=c['clip_id'], start_utc=c['time']['start_utc'], duration_s=round(c['video']['source_frames'] / c['video']['nominal_fps'], 1), has_note=bool(nt['clips'].get(c['clip_id'])),
                            thumb=thumb and thumb.split('+')[0], thumb_overlay=bool(thumb and thumb.endswith('+overlay')), audio_original=os.path.exists(d + 'audio_original.flac'), audio_clean=os.path.exists(d + 'audio_clean.flac'), steady=None if not mo else mo['summary']['steady'], candidates=None if not cd else cd['summary']['n']))
        return dict(clips=out)

    def word_view(s):                                                                    # the words of a phrase for the editable view: shown text, timing, and the correction (if any)
        return [dict(i=i, w=w['w'], t0=w['t0'], t1=w['t1'], p=w.get('p'), **({'e': w['edit']} if w.get('edit') else {})) for i, w in enumerate(s.get('words') or [])]

    def phrase_parts(s, si, who, **extra):                                               # the displayed phrases of one segment: a long phrase comes in parts (only at sentence ends, every part over 5 s)
        res = []; ps = TE.parts(s); whole = len(ps) == 1
        for p in ps:
            ws = [dict(i=w['i'], w=w['w'], t0=w['t0'], t1=w['t1'], p=w.get('p'), **({'e': w['edit']} if w.get('edit') else {})) for w in p['words']]
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
            c = _j(d, 'clip.json'); tr = TE.load_effective(d)
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
    def get_clip_audio(request: Request, folder: str, clip: str, kind: str = 'original'):  # the clip's stored sound: original (lossless) or cleaned (Range requests work); <audio> cannot send headers, so the cookie/query token authenticates
        auth(request); f = folder_of(folder); name = 'audio_clean.flac' if kind == 'clean' else 'audio_original.flac'; p = os.path.join(_cd(f, clip), name)
        if not os.path.exists(p): raise HTTPException(404, 'not made yet')
        return FileResponse(p, media_type='audio/flac', headers={'Cache-Control': 'no-cache'})

    @api.get('/api/clip', dependencies=[Depends(auth)])
    def get_clip(folder: str, clip: str):                                                # everything known about one clip, for its detail view
        from strata360.pipeline import notes as N
        f = folder_of(folder); d = _cd(f, clip); c = _j(d, 'clip.json'); out = dict(id=c['clip_id'], time=c['time'], video=c['video'], camera=c.get('camera'), audio_info=c.get('audio'), note=N.load(f)['clips'].get(c['clip_id'], ''))
        mo = _j(d, 'motion.json'); out['motion'] = None if not mo else mo['summary']
        au = _j(d, 'audio.json'); out['audio'] = None if not au else dict(summary=au.get('summary'), segments=au.get('segments', [])[:40])
        tr = TE.load_effective(d); sp = _j(d, 'speakers.json'); lab = {(round(s['t0'], 2), round(s['t1'], 2)): s.get('label') for s in (sp or {}).get('segments', [])}
        out['transcript'] = [x for si, s in enumerate((tr or {}).get('segments', [])) for x in phrase_parts(s, si, lab.get((round(s['t0'], 2), round(s['t1'], 2))), flagged=bool(s.get('flags')))]
        sc = _j(d, 'scenes.json'); out['scenes'] = None if not sc else dict(summary=sc['summary'], items=[i for i in sc['items'] if i['ok'] and i['view'] == 'front'][:60])
        idn = _j(d, 'identity.json'); out['identity'] = None if not idn else idn['summary']
        cd = _j(d, 'candidates.json'); out['candidates'] = None if not cd else [{k: v for k, v in x.items() if k not in ('transcript', 'cuts')} for x in cd['candidates']]
        ev = _j(d, 'audio_events.json')
        if ev:
            from strata360.analysis import sound_events as SE
            out['sounds'] = dict(seconds=SE.category_seconds(ev), windows=[dict(t0=w['t0'], t1=w['t1'], cats={k: v for k, v in w['cats'].items() if v >= 0.2}, top=w['top'][:3]) for w in ev['windows']], hints={c: list(h) for c, h in SE.HINTS.items()})
        out['audio_files'] = dict(original=os.path.exists(os.path.join(d, 'audio_original.flac')), clean=os.path.exists(os.path.join(d, 'audio_clean.flac')))
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

    @api.get('/api/music', dependencies=[Depends(auth)])
    def get_music(folder: str):                                                          # the music track of the project and what was found in it
        from strata360.edit import project as PJ
        f = folder_of(folder); s = PJ.load(f)['settings']; return dict(file=s.get('music'), analysis=PJ.music_info(f, s))

    @api.post('/api/music', dependencies=[Depends(auth)])
    async def post_music(request: Request, folder: str, filename: str = 'track.mp3'):    # the audio file is the raw request body; saved as music/track.<ext> and used for tempo, bars, energy and the film's sound
        from strata360.edit import project as PJ, optimise as O
        f = folder_of(folder); ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'): raise HTTPException(400, 'an audio file: mp3, wav, m4a, aac, flac or ogg')
        data = await request.body()
        if len(data) < 5000 or len(data) > 300 * 1024 * 1024: raise HTTPException(400, 'the file is empty or too large')
        d = os.path.join(config.race_dir(f), 'music'); os.makedirs(d, exist_ok=True)
        for old in os.listdir(d):
            if old.startswith('track.'): os.replace(os.path.join(d, old), os.path.join(d, old + '.replaced'))
        open(os.path.join(d, 'track' + ext), 'wb').write(data)
        try: PJ.set_music(f, 'music/track' + ext)
        except O.Infeasible as e: return dict(file='music/track' + ext, analysis=PJ.music_info(f, PJ.load(f)['settings']), warning=str(e))
        except RuntimeError as e: raise HTTPException(400, str(e))
        return dict(file='music/track' + ext, analysis=PJ.music_info(f, PJ.load(f)['settings']))

    @api.delete('/api/music', dependencies=[Depends(auth)])
    def delete_music(folder: str):
        from strata360.edit import project as PJ, optimise as O
        f = folder_of(folder)
        try: PJ.set_music(f, None)
        except O.Infeasible: pass
        return dict(file=None, analysis=None)

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
    def post_propose(body: dict):                                                        # {folder, length_s?, bpm?, seed?, keep?}
        from strata360.edit import project as PJ, optimise as O
        f = folder_of(body.get('folder'))
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
        try: log = open(os.path.join(rd, 'script_job.log')).read()[-600:]
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
