"""MCP tools for the strata360 server: what an agent may look at in a project. READ ONLY: the backend has a `get` and nothing else, so no tool can change a project, start a job or delete anything (writing tools, if they ever come, are a separate registry behind a flag).

The tools are NOT a map of the HTTP API. They are a few task-shaped tools whose answers are digests, built to cost an agent little context:
  project     where the project stands (one digest over progress, coverage, plan, script, music, track, stills), or its stage table, log or the allowed roots
  clips       the clip list, sorted and filtered, in slim rows
  clip        one clip, in `sections` chosen by the caller (summary, transcript, scenes, audio, objects, plan); the answer lists the sections not asked for
  transcript  read, search or (uncertain) the doubtful phrases, over the whole project or one clip
  plan        the edit plan as a summary, a page of segment rows, or one segment in full
  script      the voice-over script as a summary or a page of its items
  film        the rendered outputs and the facts around them: stills, final render, music, GPS track
  picture     one picture: a frame of the footage at a time, a clip's thumbnail, or a rendered film still
One tool call may fetch several endpoints (concurrently) and cut them down; each answer says what else can be asked for (`more`). Everything goes through the server's own API (`/api/...`), so the folder allow-list (roots), the token and the shapes the web app sees apply unchanged. Answers are trimmed (`shrink`): lists are cut with a count of what was left out, long text is cut, per-word timing is dropped.

  build_server(backend, default_folder)   -> MCPServer with the tools above
  AsgiBackend(app, token)                  in-process, for the server's own /mcp (no network hop)
  HttpBackend(url, token)                  over HTTP, for `strata360 mcp` (stdio) talking to a running server

Folder: every tool takes an optional `folder`; without it the project last opened in the server (`/api/last`) is used."""
import asyncio, re
from typing import Literal

CHARS = 400                       # longest text kept as it is
ITEMS = 25                        # longest list kept whole
DEPTH = 7


def shrink(obj, items=ITEMS, chars=CHARS, depth=DEPTH, drop=('words', 'techniques')):
    """`obj` made small: lists cut to `items` (the last entry says how many were left out), strings to `chars`, nesting to `depth`, and the keys in `drop` (bulky per-word timing, the technique catalogue) removed."""
    if depth <= 0: return '...'
    if isinstance(obj, dict): return {k: shrink(v, items, chars, depth - 1, drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, (list, tuple)):
        out = [shrink(v, items, chars, depth - 1, drop) for v in obj[:items]]
        if len(obj) > items: out.append(f'... {len(obj) - items} more')
        return out
    if isinstance(obj, str) and len(obj) > chars: return obj[:chars] + f'... ({len(obj) - chars} more characters)'
    return obj


try: from mcp.server.mcpserver.exceptions import ToolError           # what a tool raises on purpose: the client gets the message, not a crash
except ImportError: ToolError = type('ToolError', (Exception,), {})


class AsgiBackend:
    """GETs the server's own API in-process (httpx's ASGI transport): same routes, same checks, no socket."""
    def __init__(self, app, token=None): self.app, self.token = app, token
    def _client(self):
        import httpx
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://strata360.local', headers={'Authorization': f'Bearer {self.token}'} if self.token else {}, timeout=60)
    async def get(self, path, **params): return await _get(self._client(), path, params)
    async def get_bytes(self, path, **params): return await _get(self._client(), path, params, raw=True)


class HttpBackend:
    """GETs a running server over HTTP (the stdio shim)."""
    def __init__(self, url, token=None): self.url, self.token = url.rstrip('/'), token
    def _client(self):
        import httpx
        return httpx.AsyncClient(base_url=self.url, headers={'Authorization': f'Bearer {self.token}'} if self.token else {}, timeout=60)
    async def get(self, path, **params): return await _get(self._client(), path, params)
    async def get_bytes(self, path, **params): return await _get(self._client(), path, params, raw=True)


async def _get(client, path, params, raw=False):
    async with client as c:
        r = await c.get(path, params={k: v for k, v in params.items() if v is not None})
    if r.status_code >= 400:
        try: why = r.json().get('detail', r.text)
        except ValueError: why = r.text
        raise ToolError(f'{path}: {r.status_code} {why}')
    return r.content if raw else r.json()


async def settled(**calls):
    """Await several named coroutines together: {name: result}, a failed one as {'error': message}, so one missing part does not spoil a digest."""
    async def one(c):
        try: return await c
        except Exception as e: return dict(error=str(e)[:200])
    done = await asyncio.gather(*(one(c) for c in calls.values())); return dict(zip(calls, done))


def ok(x): return isinstance(x, dict) and 'error' not in x


def _top(d, n):
    """The n largest entries of a {name: number} dict, as a short string."""
    return ', '.join(f'{k} {round(v, 1)}' for k, v in sorted((d or {}).items(), key=lambda kv: -kv[1])[:n])


def seg_row(g, line=None):
    """One plan segment as a slim row."""
    r = dict(i=g.get('index'), id=g.get('id'), clip=g.get('clip'), at=round(g.get('clip_start_s', 0), 2), dur=round(g.get('dur_s', 0), 2), film_t=round(g.get('film_start_s', 0), 2), technique=g.get('technique'), kind=g.get('kind'), view=g.get('view'))
    for k in ('locked', 'forced', 'speech'):
        if g.get(k): r[k] = True
    if g.get('transition'): r['transition'] = g['transition']
    if line: r['says'] = line.get('text') if isinstance(line, dict) else line
    return r


def build_server(backend, default_folder=None):
    """The MCPServer (mcp 2.x `MCPServer`) with every tool bound to `backend`."""
    from mcp.server.mcpserver import MCPServer, Image
    from mcp.types import ToolAnnotations
    ro = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    srv = MCPServer('strata360', instructions='Read-only access to a strata360 film project: its clips, what the analysis found in them, the edit plan, the script and the film stills. Start with `project`; every answer says what more can be asked for. Nothing here changes the project.')

    async def folder_of(folder):
        if folder: return folder
        if default_folder: return default_folder
        last = (await backend.get('/api/last')).get('folder')
        if not last: raise ToolError('no project is open in the server: pass `folder` (see project(view="roots") for the allowed roots)')
        return last

    def tool(fn): srv.add_tool(fn, annotations=ro); return fn

    @tool
    async def project(view: Literal['overview', 'stages', 'log', 'roots'] = 'overview', folder: str | None = None) -> dict:
        """Where the project stands. overview: one digest (clips and footage length, analysis still to do and what it blocks, the edit plan, the script, music, GPS track, stills and final render, the folder note). stages: every analysis stage with done/total. log: the last lines of the run log. roots: the folders the server may look in and the project opened last."""
        if view == 'roots': return dict(roots=(await backend.get('/api/roots')).get('roots'), last=(await backend.get('/api/last')).get('folder'))
        f = await folder_of(folder)
        if view == 'log': return await backend.get('/api/log', folder=f)
        if view == 'stages':
            pr = await backend.get('/api/progress', folder=f)
            return dict(state=pr.get('state'), percent=pr.get('percent'), eta_s=pr.get('eta_s'), stages={x['name']: f"{x['done']}/{x['total']}" + (f" ({x['note']})" if x.get('note') and x['done'] < x['total'] else '') for x in pr.get('stages', [])}, needs=pr.get('needs'))
        r = await settled(progress=backend.get('/api/progress', folder=f), coverage=backend.get('/api/coverage', folder=f), clips=backend.get('/api/clips', folder=f), edit=backend.get('/api/edit', folder=f), script=backend.get('/api/script2', folder=f),
                          music=backend.get('/api/music', folder=f), track=backend.get('/api/track', folder=f), stills=backend.get('/api/film/stills', folder=f), final=backend.get('/api/final', folder=f), notes=backend.get('/api/notes', folder=f))
        out = dict(folder=f)
        if ok(r['progress']): out['state'] = r['progress'].get('state'); out['analysis_percent'] = r['progress'].get('percent')
        if ok(r['clips']):
            cs = r['clips']['clips']
            out['clips'] = dict(count=len(cs), footage_min=round(sum(c['duration_s'] for c in cs) / 60, 1), first=min((c['start_utc'] for c in cs), default=None), last=max((c['start_utc'] for c in cs), default=None), in_film=sum(bool(c.get('in_film')) for c in cs))
        if ok(r['coverage']):
            cv = r['coverage']; out['analysis'] = dict(complete=cv.get('complete'), unfinished={k: f'{v}/{cv["clips"]}' for k, v in (cv.get('totals') or {}).items() if v < cv['clips']}, blocks=shrink(cv.get('blocked'), items=6, chars=120))
        if ok(r['edit']):
            e = r['edit']['edit']; pl = e.get('plan') or {}; ov = e.get('overrides') or {}
            out['plan'] = dict(source=pl.get('source'), segments=len(pl.get('segments', [])), clips_used=pl.get('clips_in_plan'), technique_seconds=_top(pl.get('technique_seconds'), 5), warnings=len(pl.get('warnings') or []), text_cards=len(pl.get('text_cards') or []), overrides={k: len(v) for k, v in ov.items() if v}) if pl else None
        if ok(r['script']):
            d = r['script'].get('draft') or {}
            out['script'] = dict(draft=True, title=d.get('title'), items=len(d.get('items', [])), target_s=d.get('target_s'), drafts=len(r['script'].get('drafts', [])), warnings=len(d.get('warnings') or []), running=r['script'].get('running')) if d else dict(draft=False)
        if ok(r['music']) and r['music'].get('file'): a = r['music'].get('analysis') or {}; out['music'] = dict(name=r['music'].get('name'), bpm=a.get('bpm'), duration_s=a.get('duration_s'))
        if ok(r['track']) and r['track'].get('present'): t = r['track']; out['track'] = dict(distance_km=t.get('distance_km'), ascent_m=t.get('ascent_m'), duration_h=t.get('duration_h'), start=t.get('start_utc'))
        if ok(r['stills']): out['stills'] = len(r['stills'].get('stills', []))
        if ok(r['final']): out['final_render'] = r['final'].get('state')
        if ok(r['notes']) and r['notes'].get('folder'): out['note'] = r['notes']['folder'][:300]
        out['failed_parts'] = [k for k, v in r.items() if not ok(v)] or None; out['more'] = 'clips, clip, transcript, plan, script, film, picture; project(view="stages") for the analysis table'; return out

    @tool
    async def clips(sort: Literal['time', 'longest', 'shortest', 'steadiest'] = 'time', in_film: bool | None = None, limit: int = 30, offset: int = 0, folder: str | None = None) -> dict:
        """The clips as slim rows (id, start UTC, length in s, steadiness 0..1, in the film plan, has a note). `in_film` filters to the clips the plan uses (true) or not (false). Page with offset/limit; `total` is after filtering."""
        cs = (await backend.get('/api/clips', folder=await folder_of(folder)))['clips']
        if in_film is not None: cs = [c for c in cs if bool(c.get('in_film')) == in_film]
        key = dict(time=lambda c: c['start_utc'], longest=lambda c: -c['duration_s'], shortest=lambda c: c['duration_s'], steadiest=lambda c: -(c.get('steady') or 0))[sort]
        rows = [{k: c[k] for k in ('id', 'start_utc', 'duration_s', 'steady', 'in_film', 'has_note') if k in c} for c in sorted(cs, key=key)[offset:offset + limit]]
        return dict(total=len(cs), offset=offset, clips=rows, more='clip(clip=ID, sections=[...]) for one clip')

    @tool
    async def clip(clip: str, sections: list[Literal['summary', 'transcript', 'scenes', 'audio', 'objects', 'plan']] | None = None, folder: str | None = None) -> dict:
        """One clip by id. `sections` picks what to include (default: summary). summary: time, length, camera, steadiness, note and what each section holds. transcript: its phrases (text, who, times). scenes: what the scene model saw over time. audio: sound classes found. objects: what was passed. plan: where the edit plan uses it. Ask only for the sections you need."""
        f = await folder_of(folder); want = sections or ['summary']; c = await backend.get('/api/clip', folder=f, clip=clip); out = dict(id=c.get('id')); done = set()
        if 'summary' in want:
            t = c.get('time') or {}; v = c.get('video') or {}; m = c.get('motion') or {}
            out.update(start_utc=t.get('start_utc'), end_utc=t.get('end_utc'), duration_s=round(v.get('source_frames', 0) / v['nominal_fps'], 1) if v.get('nominal_fps') else None, camera=(c.get('camera') or {}).get('model'), steady=m.get('steady'), note=c.get('note') or None,
                       has=dict(transcript=len(c.get('transcript') or []), scenes=len((c.get('scenes') or {}).get('items', [])), audio=bool(c.get('audio')), objects=bool((c.get('objects') or {}).get('moments'))))
            if (c.get('scenes') or {}).get('summary'): out['scene_summary'] = shrink(c['scenes']['summary'], items=8, chars=160)
            done.add('summary')
        if 'transcript' in want:
            out['transcript'] = [dict(t0=round(p['t0'], 2), t1=round(p['t1'], 2), text=p.get('text'), who=p.get('who'), **({'flagged': True} if p.get('flagged') else {})) for p in (c.get('transcript') or [])[:40]]; done.add('transcript')
        if 'scenes' in want: sc = c.get('scenes') or {}; out['scenes'] = dict(summary=shrink(sc.get('summary'), items=10, chars=160), items=shrink(sc.get('items', [])[:12], items=12, chars=140)); done.add('scenes')
        if 'audio' in want: a = c.get('audio') or {}; out['audio'] = dict(summary=shrink(a.get('summary'), items=12, chars=100), segments=shrink(a.get('segments', [])[:12], items=12, chars=100)); done.add('audio')
        if 'objects' in want: out['objects'] = shrink(c.get('objects'), items=15, chars=120); done.add('objects')
        if 'plan' in want:
            e = (await backend.get('/api/edit', folder=f))['edit']; out['plan'] = [seg_row(g) for g in (e.get('plan') or {}).get('segments', []) if g.get('clip') == clip] or 'not used by the plan'; done.add('plan')
        out['more'] = [x for x in ('summary', 'transcript', 'scenes', 'audio', 'objects', 'plan') if x not in done]; return out

    @tool
    async def transcript(query: str = '', clip: str | None = None, uncertain: bool = False, limit: int = 20, offset: int = 0, folder: str | None = None) -> dict:
        """The speech transcript with the user's corrections applied: phrases of the whole project or of one `clip`, filtered to those containing `query` (case-insensitive, also the English text). With `uncertain`, only the phrases most likely misrecognised, worst first (the review queue), with how many are still to review."""
        f = await folder_of(folder)
        if uncertain:
            d = await backend.get('/api/transcript/review', folder=f); items = [i for i in d['items'] if (not clip or i.get('clip') == clip) and not i.get('reviewed')]
            return dict(todo=d['todo'], total=d['total'], shown=[shrink(i, items=8, chars=200) for i in items[offset:offset + limit]])
        segs = (await backend.get('/api/transcript', folder=f))['segments']; q = query.lower().strip()
        hit = [s for s in segs if (not clip or s.get('clip') == clip) and (not q or q in (s.get('text') or '').lower() or q in (s.get('text_en') or '').lower())]
        return dict(total=len(hit), offset=offset, phrases=[dict(clip=s.get('clip'), t0=round(s['t0'], 2), t1=round(s['t1'], 2), text=s.get('text'), **({'english': s['text_en']} if s.get('lang') != 'en' and s.get('text_en') else {}), who=s.get('who'), **({'flagged': True} if s.get('flagged') else {})) for s in hit[offset:offset + limit]])

    @tool
    async def plan(view: Literal['summary', 'segments', 'segment'] = 'summary', first: int = 0, count: int = 20, segment: str | None = None, folder: str | None = None) -> dict:
        """The film's edit plan. summary: source, length, settings, overrides (locks, bans, weights), time per technique, warnings, text cards. segments: `count` rows from segment index `first` (clip, where in it, length, film time, technique, speech, the script line). segment: one segment by id or index in full, with the alternatives the planner scored."""
        d = await backend.get('/api/edit', folder=await folder_of(folder)); e = d['edit']; pl = e.get('plan') or {}; segs = pl.get('segments', []); lines = d.get('script') or {}
        if not pl: return dict(plan=None, note='no film plan yet: it is made from the script or by the beat planner')
        if view == 'segments': return dict(total=len(segs), first=first, segments=[seg_row(g, lines.get(g.get('id'))) for g in segs[first:first + count]], more='plan(view="segment", segment=ID) for one in full')
        if view == 'segment':
            g = next((g for g in segs if g.get('id') == segment or str(g.get('index')) == str(segment)), None)
            if not g: raise ToolError(f'no segment {segment!r} (ids look like {segs[0].get("id")})')
            return dict(segment=shrink({k: v for k, v in g.items() if k != 'options'}, items=10, chars=200), says=shrink(lines.get(g.get('id')), chars=400), alternatives=[dict(tech=o.get('tech'), score=o.get('score')) for o in (g.get('options') or [])[:6]])
        return dict(source=pl.get('source'), script=pl.get('script'), film=shrink(pl.get('film'), items=6, chars=100), settings=shrink(e.get('settings'), items=12, chars=100), overrides=shrink(e.get('overrides'), items=10, chars=100), segments=len(segs), clips_in_plan=pl.get('clips_in_plan'), missing_clips=shrink(pl.get('missing_clips'), items=6, chars=80),
                    technique_seconds={k: round(v, 1) for k, v in (pl.get('technique_seconds') or {}).items()}, warnings=shrink(pl.get('warnings'), items=6, chars=200), text_cards=len(pl.get('text_cards') or []), more='plan(view="segments") for the rows')

    @tool
    async def script(view: Literal['summary', 'items'] = 'summary', first: int = 0, count: int = 15, folder: str | None = None) -> dict:
        """The newest whole-race script draft. summary: title, the story, target length, counts, warnings and problems, the drafts that exist and the pins. items: `count` of its items from index `first` (the voice-over and the runner's own lines, with their clips)."""
        d = await backend.get('/api/script2', folder=await folder_of(folder)); dr = d.get('draft')
        if not dr: return dict(draft=None, running=d.get('running'), note='no script draft yet')
        if view == 'items': return dict(total=len(dr.get('items', [])), first=first, items=shrink(dr.get('items', [])[first:first + count], items=count, chars=240))
        return dict(title=dr.get('title'), story=shrink(dr.get('story'), chars=600), target_s=dr.get('target_s'), items=len(dr.get('items', [])), skipped=len(dr.get('skipped', [])), warnings=shrink(dr.get('warnings'), items=6, chars=200), problems=shrink(dr.get('problems'), items=6, chars=200), drafts=d.get('drafts'), pins=len(d.get('pins') or {}), plan=shrink(d.get('plan'), items=5, chars=100), more='script(view="items")')

    @tool
    async def film(view: Literal['stills', 'final', 'music', 'track'] = 'stills', folder: str | None = None) -> dict:
        """The film's outputs and the facts around them. stills: the rendered stills (name, film time, size, whether current; look at one with `picture`). final: state of the final render. music: the track (tempo, length, how many sections). track: the GPS track's totals (distance, climb, times)."""
        f = await folder_of(folder)
        if view == 'stills':
            d = await backend.get('/api/film/stills', folder=f); return dict(stills=[dict(name=s['name'], t=s.get('t'), size=s.get('size'), current=s.get('current')) for s in d.get('stills', [])[-30:]], rendering=len(d.get('active') or []), more='picture(of="still", name=NAME)')
        if view == 'final': return shrink(await backend.get('/api/final', folder=f), items=8, chars=160)
        if view == 'music':
            d = await backend.get('/api/music', folder=f); a = d.get('analysis') or {}
            return dict(file=d.get('file'), bpm=a.get('bpm'), duration_s=a.get('duration_s'), bar_beats=a.get('bar_beats'), sections=len(a.get('sections', [])), confidence=a.get('confidence')) if d.get('file') else dict(music=None)
        d = await backend.get('/api/track', folder=f); return {k: v for k, v in d.items() if k not in ('line', 'bbox')}

    @tool
    async def picture(of: Literal['frame', 'thumbnail', 'still'], clip: str | None = None, t: float | None = None, yaw: float = 0.0, pitch: float = 0.0, fov: float = 100.0, overlay: bool = False, name: str | None = None, folder: str | None = None) -> Image:
        """One picture (JPEG). of=frame: the flat upright view of the footage at `t` seconds into `clip` (yaw: degrees from where the runner was heading, 0 ahead, 90 right, 180 behind, -90 left; pitch up or down; fov 40 to 120; needs the clip's proxy). of=thumbnail: the picture the app shows for `clip` (`overlay` for the one with the race overlay). of=still: a rendered film still by `name` (see film(view="stills"))."""
        f = await folder_of(folder)
        if of == 'frame':
            if not clip or t is None: raise ToolError('of="frame" needs clip and t')
            return Image(data=await backend.get_bytes('/api/clip/frame', folder=f, clip=clip, t=t, yaw=yaw, pitch=pitch, fov=fov), format='jpeg')
        if of == 'thumbnail':
            if not clip: raise ToolError('of="thumbnail" needs clip')
            return Image(data=await backend.get_bytes('/api/thumb', folder=f, clip=clip, overlay=str(bool(overlay)).lower()), format='jpeg')
        if not name or not re.match(r'^[\w.-]+$', name): raise ToolError('of="still" needs the name of a still (see film(view="stills"))')
        return Image(data=await backend.get_bytes('/api/film/still/thumb', folder=f, name=name, w=960), format='jpeg')

    return srv


def tool_names(srv):
    return sorted(t.name for t in asyncio.run(srv.list_tools()))


def token_ok(token, headers, query):
    """Whether a request carries the server's token (Bearer header or ?token=), or the server has none."""
    return not token or headers.get('authorization') == f'Bearer {token}' or query.get('token') == token


def guarded(app, token):
    """The ASGI app `app` that answers 401 to any request without the token (the mount point of the MCP app, which the FastAPI `auth` dependency does not cover)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    async def wrapped(scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            r = Request(scope)
            if not token_ok(token, r.headers, r.query_params): return await JSONResponse({'detail': 'token required'}, status_code=401)(scope, receive, send)
        await app(scope, receive, send)
    return wrapped
