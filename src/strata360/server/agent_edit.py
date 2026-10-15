"""The edit tier of the project assistant: what an agent may CHANGE, with the same effect as the user doing it in the web app, behind safeguards.

One nested tool, `edit(action, args)`, is offered only in write mode. Each action is one (or a few) of the server's own POST routes, with its arguments checked here first. The safeguards:

  Backups     before the first change of a session (and again whenever the last agent change is over SESSION_S old) a backup of the project metadata is forced, so the state before the agent touched anything can be restored; changes then BATCH: another
              backup is made after a change only when the last one is over BACKUP_S (5 minutes) old (pipeline/backup.py: every backup of the last 3 hours is kept).
  Journal     every change is appended to <project>/strata360/agent_log.jsonl: time, action, arguments, result or error, the backup that preceded it; the first change of a session records the `restore_point` that undo goes back to.
  Undo        `undo(folder)` puts the project metadata back to the restore point of the latest session of agent changes (after saving the current state as a backup, so the undo can itself be undone). One click, one session at a time.
  Approval    some actions (`GATED`) never run on the model's say-so: they create a pending approval that only the user can grant (the Approve button of the Ask page, `POST /api/agent/approve`), because they cost money, send data out, throw work away
              or take hours. The model is told "needs the user's approval" and cannot grant it. Pending approvals expire after PENDING_S.
  Not offered at all: deleting anything, uploading files (music, tracks, photos, recordings), the camera clock, the wearer's face profile, API keys.

  execute(post, folder, action, args, approved=False)  ->  dict(ok, result) | dict(needs_approval, id, summary) ; raises ToolError on a bad request"""
import json, os, threading, time, uuid

BACKUP_S = 300.0                 # changes batch: after a change a backup is made only when the last one is older than this (5 minutes)
SESSION_S = 20 * 60              # a pause this long between agent changes starts a new session (a forced backup of the state before the next change)
PENDING_S = 30 * 60              # how long an approval can wait
MAX_PENDING = 20
LOG = 'agent_log.jsonl'

try: from mcp.server.mcpserver.exceptions import ToolError
except ImportError: ToolError = type('ToolError', (Exception,), {})

_lock = threading.Lock()
_last_write = {}                 # folder -> time of the last agent change
PENDING = {}                     # id -> dict(folder, action, args, summary, why, created)


def _s(v): return isinstance(v, str) and bool(v.strip())
def _n(v): return isinstance(v, (int, float)) and not isinstance(v, bool)
def _b(v): return isinstance(v, bool)
def _i(v): return isinstance(v, int) and not isinstance(v, bool)
def _l(v): return isinstance(v, list)
def _d(v): return isinstance(v, dict)


# action -> (route, {argument: (check, required, what)}, summary(args), gated reason or None, background job?)
ACTIONS = {
    'plan.technique': ('/api/edit/override', dict(wid=(_s, True, 'segment id'), technique=(_s, False, 'technique id, or omit to let the planner choose')), lambda a: f"set the technique of segment {a['wid']} to {a.get('technique') or 'automatic'}", None, False),
    'plan.lock': ('/api/edit/override', dict(wid=(_s, True, 'segment id'), locked=(_b, False, 'true (default) or false')), lambda a: f"{'lock' if a.get('locked', True) else 'unlock'} segment {a['wid']}", None, False),
    'plan.transition': ('/api/edit/override', dict(wid=(_s, True, 'segment id'), transition=(_s, False, 'transition id, or omit for the default')), lambda a: f"set the transition of segment {a['wid']}", None, False),
    'plan.weight': ('/api/edit/override', dict(clip=(_s, True, 'clip id'), factor=(_n, False, 'how much more (above 1) or less (below 1) the planner uses it')), lambda a: f"weight clip {a['clip']} by {a.get('factor')}", None, False),
    'plan.ban': ('/api/edit/override', dict(kind=(_s, True, 'candidates or techniques'), key=(_s, True, 'what to ban'), on=(_b, False, 'true (default) or false')), lambda a: f"{'ban' if a.get('on', True) else 'allow'} {a['kind']} {a['key']}", None, False),
    'plan.reset': ('/api/edit/override', {}, lambda a: 'forget every override of the plan (locks, bans, weights, techniques)', 'throws away all the plan overrides', False),
    'plan.propose': ('/api/edit/propose', dict(length_s=(_n, False, 'film length in seconds'), bpm=(_n, False, 'tempo'), seed=(_i, False, 'variety seed'), keep=(_b, False, 'keep locked segments (default true)'), replace=(_b, False, 'also replace a film planned from the script')), lambda a: 'plan the film with the beat planner' + (' (replacing the script plan)' if a.get('replace') else ''), None, False),
    'transcript.edit': ('/api/transcript/edit', dict(clip=(_s, True, 'clip id'), seg=(_i, True, 'phrase number'), word=(_i, True, 'word number'), text=(_s, False, 'the corrected word'), action=(_s, False, '"clear" drops a correction')), lambda a: f"correct word {a['word']} of phrase {a['seg']} in {a['clip']}", None, False),
    'transcript.mark': ('/api/transcript/mark', dict(clip=(_s, True, 'clip id'), spans=(_l, True, 'list of {seg, from, to}'), state=(_s, True, 'must, never or none')), lambda a: f"mark {len(a['spans'])} span(s) of {a['clip']} as {a['state']}", None, False),
    'transcript.reviewed': ('/api/transcript/reviewed', dict(clip=(_s, True, 'clip id'), seg=(_i, True, 'phrase number'), state=(_b, False, 'true (default) or false')), lambda a: f"mark phrase {a['seg']} of {a['clip']} as reviewed", None, False),
    'notes.set': ('/api/notes', dict(text=(_s, True, 'the note'), clip=(_s, False, 'a clip id; omit for the folder note'), kind=(_s, False, '"vo" for the voice-over MUST INCLUDE text'), ordered=(_b, False, 'with kind vo: keep the order written')), lambda a: f"write the {'note of ' + a['clip'] if a.get('clip') else 'folder note'}", None, False),
    'meta.set': ('/api/meta', dict(title=(_s, False, 'film title'), date=(_s, False, 'date text'), results=(_d, False, '{starters, finishers, finished, position}')), lambda a: 'set the film details', None, False),
    'script.edit': ('/api/script/edit', dict(texts=(_d, True, '{segment: new text}')), lambda a: f"rewrite {len(a['texts'])} script line(s)", None, False),
    'script.pins': ('/api/script2/pins', dict(include=(_l, False, 'clips or lines to include'), exclude=(_l, False, 'to exclude'), vo=(_l, False, 'narration to include'), vo_never=(_l, False, 'narration never to use')), lambda a: 'set the script pins', None, False),
    'style.vibes': ('/api/typography', dict(vibes=(_l, True, 'vibes of the library, e.g. rugged, outdoors, cinematic; an empty list gives the choice back to the script writer')), lambda a: 'set the vibes of the film to ' + (', '.join(a['vibes']) or 'the script writer\'s choice') + ' (the fonts follow)', None, False),
    'style.font': ('/api/typography', dict(role=(_s, True, 'display, subtitle, meta, numerals or quote'), font=(lambda v: v is None or _s(v), False, 'a font id of the library, or omit to give the role back to the automatic choice')), lambda a: f"{'set the ' + a['role'] + ' font to ' + str(a['font']) if a.get('font') else 'give the ' + a['role'] + ' font back to the automatic choice'}", None, False),
    'voiceover.use': ('/api/voiceover/use', dict(seg=(_i, True, 'line number'), use=(_s, True, 'synth or recorded')), lambda a: f"use the {a['use']} voice for line {a['seg']}", None, False),
    # background jobs (they start and return at once; see project(view="stages") and the log)
    'script.plan': ('/api/script2/plan', dict(draft=(_s, False, 'a draft file name (default: the newest)')), lambda a: 'make the film plan from the script draft and speak the narration', None, True),
    'voiceover.build': ('/api/voiceover/build', dict(engine=(_s, False, 'engine'), voice=(_s, False, 'voice'), rate=(_n, False, 'speed')), lambda a: 'speak the script and mix the voice-over track', None, True),
    'film.preview': ('/api/film/start', {}, lambda a: 'render the preview of the saved plan', None, True),
    'film.still': ('/api/film/still', dict(size=(_s, True, '1920x1080, 2560x1440 or 3840x2160'), t=(_n, False, 'film time in seconds'), times=(_l, False, 'several film times'), auto=(_b, False, 'a series of differing moments'), upscale=(_s, False, 'off, 1080p, 1440p or full')), lambda a: 'render film still(s)', None, True),
    'rough_mix': ('/api/script2/mix', {}, lambda a: 'make the rough mix of the sound', None, True),
    'analysis.run': ('/api/run', {}, lambda a: 'continue the analysis of the footage', None, True),
    # approval needed: the user grants these, never the model
    'script.generate': ('/api/script2/generate', dict(revise=(_b, False, 'revise the newest draft'), target_s=(_n, False, 'target length'), wpm=(_n, False, 'words per minute'), auto=(_b, False, 'automatic length')), lambda a: 'write a new script draft with the language model (sends your notes, transcript and race facts to the model service; costs money)', 'sends project text to a paid model service', True),
    'transcript.check': ('/api/transcript/suggest', {}, lambda a: 'check the whole transcript against the audio with Gemini (paid, sends audio excerpts)', 'sends audio to a paid service', True),
    'analysis.redo': ('/api/clear', dict(items=(_l, True, 'list of {clip, stage}')), lambda a: f"forget {len(a['items'])} analysis result(s) so they are processed again (can take hours)", 'throws away analysis results that take hours to rebuild', True),
    'final.render': ('/api/final/start', dict(size=(_s, False, 'e.g. 3840x2160'), fps=(_n, False, 'frames a second'), bitrate=(_s, False, 'e.g. 100M')), lambda a: 'start the final film render (hours of work, large files)', 'a long, heavy render', True),
}
GATED = {k for k, v in ACTIONS.items() if v[3]}


def usage():
    """One line per action, for the tool's description: name(args) with required ones first, and a mark on those that need the user's approval."""
    out = []
    for name, (_, spec, _, gated, job) in ACTIONS.items():
        args = ', '.join(f"{k}{'' if req else '?'}" for k, (_, req, _) in spec.items()); out.append(f"{name}({args})" + (' [needs approval]' if gated else '') + (' [background job]' if job and not gated else ''))
    return '; '.join(out)


def check(action, args):
    """The cleaned arguments of `action`, or ToolError saying what is wrong and what is expected."""
    if action not in ACTIONS: raise ToolError(f'unknown action {action!r}: one of ' + ', '.join(ACTIONS))
    spec = ACTIONS[action][1]; args = dict(args or {}); args.pop('folder', None)
    for k in args:
        if k not in spec: raise ToolError(f'{action}: unknown argument {k!r}; it takes ' + (', '.join(f'{n} ({w})' for n, (_, _, w) in spec.items()) or 'no arguments'))
    for k, (ok, req, what) in spec.items():
        if k not in args:
            if req: raise ToolError(f'{action}: {k} is required ({what})')
        elif not ok(args[k]): raise ToolError(f'{action}: {k} has the wrong type ({what})')
    return args


def body_of(action, args):
    """The body the route takes. The override routes share one path and tell the operation apart by `action`."""
    body = dict(args)
    if action.startswith('plan.') and action not in ('plan.propose',): body['action'] = action.split('.')[1]
    if action == 'plan.technique' and 'technique' not in body: body['technique'] = None
    if action == 'style.vibes': body = dict(style=list(args['vibes']))
    if action == 'style.font': body = dict(fonts={args['role']: args.get('font')})
    if action == 'plan.lock' and 'locked' not in body: body['locked'] = True
    return body


def journal(folder, entry):
    from strata360.pipeline import config
    rd = config.race_dir(folder); os.makedirs(rd, exist_ok=True)
    with open(os.path.join(rd, LOG), 'a', encoding='utf8') as f: f.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def read_journal(folder, limit=50):
    from strata360.pipeline import config
    p = os.path.join(config.race_dir(folder), LOG)
    if not os.path.exists(p): return []
    out = []
    for line in open(p, encoding='utf8').read().splitlines()[-limit:]:
        try: out.append(json.loads(line))
        except ValueError: pass
    return out


def _backup(folder, force):
    from strata360.pipeline import backup as B
    try: p = B.backup(folder, force=force, interval=0.0 if force else BACKUP_S); return os.path.basename(p) if p else None
    except Exception: return None                         # a backup problem must not stop an edit the user asked for; the journal says there was none


def _latest(folder):
    from strata360.pipeline import backup as B
    bk = B.list_backups(folder); return bk[-1][0] if bk else None


def undo_state(folder):
    """What an undo would do: dict(available, restore_point, since, changes, sessions). Sessions are counted from the journal: each session's first change records its `restore_point`, and an undo takes the latest one away."""
    stack = []
    for e in read_journal(folder, 5000):
        if e.get('action') == 'agent.undo' and e.get('status') == 'undone':
            if stack: stack.pop()
        elif e.get('session_start') and e.get('status') in ('done', 'failed') and e.get('restore_point'): stack.append(dict(restore_point=e['restore_point'], since=e['t'], changes=0))
        if stack and e.get('status') == 'done' and e.get('action') != 'agent.undo': stack[-1]['changes'] += 1
    top = stack[-1] if stack else None
    return dict(available=bool(top and top['changes']), restore_point=top and top['restore_point'], since=top and top['since'], changes=top['changes'] if top else 0, sessions=len(stack))


def undo(folder):
    """Put the project metadata back to the state before the latest session of agent changes. The current state is backed up first. Returns dict(restored, checkpoint, files, undone)."""
    from strata360.pipeline import backup as B
    st = undo_state(folder)
    if not st['available']: raise ToolError('there is no assistant change to undo')
    if not os.path.exists(os.path.join(B.backup_dir(folder), st['restore_point'])): raise ToolError(f"the backup {st['restore_point']} is gone (backups are thinned over time): it cannot be restored")
    from strata360.pipeline import config
    jp = os.path.join(config.race_dir(folder), LOG); keep = open(jp, 'rb').read() if os.path.exists(jp) else b''                  # the journal is inside the backed-up folder: an undo must not rewind the record of itself
    cp = B.backup(folder, force=True, interval=0.0); n = B.restore_over(folder, st['restore_point'])
    with open(jp, 'wb') as f: f.write(keep)
    journal(folder, dict(t=time.time(), source='user', action='agent.undo', status='undone', restored=st['restore_point'], checkpoint=os.path.basename(cp) if cp else None, files=n, undid=st['changes']))
    with _lock: _last_write.pop(folder, None)                                                                          # the next change starts a new session
    return dict(restored=st['restore_point'], checkpoint=os.path.basename(cp) if cp else None, files=n, undone=st['changes'])


def expire(now=None):
    now = time.time() if now is None else now
    for k in [k for k, v in PENDING.items() if now - v['created'] > PENDING_S]: PENDING.pop(k, None)


def pending_for(folder):
    expire(); return [dict(id=k, action=v['action'], summary=v['summary'], why=v['why'], args=v['args']) for k, v in PENDING.items() if v['folder'] == folder]


async def execute(post, folder, action, args, approved=False, source='agent'):
    """Run an action: check it, ask for approval when it needs it, back up, send the POST, journal. `post(path, body)` is the write backend."""
    args = check(action, args); route, _, summary, why, job = ACTIONS[action]; text = summary(args)
    if why and not approved:
        expire()
        if sum(v['folder'] == folder for v in PENDING.values()) >= MAX_PENDING: raise ToolError('too many approvals are waiting: ask the user to approve or deny some first')
        for k, v in PENDING.items():
            if v['folder'] == folder and v['action'] == action and v['args'] == args: return dict(needs_approval=k, summary=text, why=why, note='already waiting for the user')
        pid = uuid.uuid4().hex[:10]; PENDING[pid] = dict(folder=folder, action=action, args=args, summary=text, why=why, created=time.time())
        journal(folder, dict(t=time.time(), source=source, action=action, args=args, status='needs approval', id=pid))
        return dict(needs_approval=pid, summary=text, why=why, note='the user must approve this in the Ask panel; you cannot approve it. Tell them what it does and why it needs approval.')
    with _lock: first = time.time() - _last_write.get(folder, 0) > SESSION_S; _last_write[folder] = time.time()
    before = _backup(folder, force=first); entry = dict(t=time.time(), source=source, action=action, args=args, summary=text, backup_before=before, approved=bool(approved))
    if first: entry.update(session_start=True, restore_point=before or _latest(folder))                                  # nothing changed since the newest backup: that backup IS the state before
    try: res = await post(route, dict(body_of(action, args), folder=folder))
    except Exception as e:
        entry.update(status='failed', error=str(e)[:300]); journal(folder, entry); raise ToolError(f'{action} failed: {e}')
    after = _backup(folder, force=False); entry.update(status='done', backup_after=after); journal(folder, entry)
    return dict(ok=True, did=text, job=bool(job) or None, result=_trim(res), backup=before or after, undoable=True)


def _trim(res):
    from strata360.server.mcp_tools import shrink
    return shrink(res, items=6, chars=200, depth=3, drop=('words', 'techniques', 'plan', 'edit'))


async def approve(post, folder, pid):
    """Run an approved pending action (the user pressed Approve)."""
    expire(); p = PENDING.get(pid)
    if not p or p['folder'] != folder: raise ToolError('that approval is gone (expired or already answered)')
    PENDING.pop(pid, None); out = await execute(post, folder, p['action'], p['args'], approved=True, source='user-approved'); return out


def deny(folder, pid):
    p = PENDING.get(pid)
    if not p or p['folder'] != folder: raise ToolError('that approval is gone (expired or already answered)')
    PENDING.pop(pid, None); journal(folder, dict(t=time.time(), source='user', action=p['action'], args=p['args'], status='denied')); return dict(denied=True)
