"""MCP tools for the strata360 server: what an agent may look at in a project. READ ONLY: the backend has a `get` and nothing else, so no tool can change a project, start a job or delete anything (writing tools, if they ever come, are a separate registry behind a flag).

The tools do not touch the project files themselves: each is one or two GETs of the server's own API (`/api/...`), so the folder allow-list (roots), the token and the shapes the web app sees apply unchanged. Answers are trimmed for a small context (`shrink`): lists are cut with a count of what was left out, long text is cut, the per-word timing of the transcript is dropped.

  build_server(backend, default_folder)   -> MCPServer with the tools below
  AsgiBackend(app, token)                  in-process, for the server's own /mcp (no network hop)
  HttpBackend(url, token)                  over HTTP, for `strata360 mcp` (stdio) talking to a running server

Folder: every tool takes an optional `folder`; without it the project last opened in the server (`/api/last`) is used."""
import re

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


def build_server(backend, default_folder=None):
    """The MCPServer (mcp 2.x `MCPServer`) with every tool bound to `backend`."""
    from mcp.server.mcpserver import MCPServer, Image
    from mcp.types import ToolAnnotations
    ro = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    srv = MCPServer('strata360', instructions='Read-only access to a strata360 film project: its clips, what was found in them (transcript, scenes, palette, quality), the edit plan, the script and the film stills. Start with `projects`, then `project_overview`. Nothing here changes the project.')

    async def folder_of(folder):
        if folder: return folder
        if default_folder: return default_folder
        last = (await backend.get('/api/last')).get('folder')
        if not last: raise ToolError('no project is open in the server: pass `folder` (see `projects` for the allowed roots)')
        return last

    def tool(fn): srv.add_tool(fn, annotations=ro); return fn

    @tool
    async def projects() -> dict:
        """The folders the server may look in (roots) and the project opened last, which is the default `folder` of every other tool."""
        return dict(roots=(await backend.get('/api/roots')).get('roots'), last=(await backend.get('/api/last')).get('folder'))

    @tool
    async def project_overview(folder: str | None = None) -> dict:
        """Where the project stands: per-stage progress over the clips, and which analysis is missing and which decisions that blocks."""
        f = await folder_of(folder); return shrink(dict(folder=f, progress=await backend.get('/api/progress', folder=f), coverage=await backend.get('/api/coverage', folder=f)))

    @tool
    async def list_clips(offset: int = 0, limit: int = 30, folder: str | None = None) -> dict:
        """The clips in time order: id, start (UTC), length, whether it has a note, the thumbnail, the sound files and a few facts. `offset`/`limit` page through them."""
        f = await folder_of(folder); cs = (await backend.get('/api/clips', folder=f))['clips']; keep = ('id', 'start_utc', 'duration_s', 'has_note', 'in_film', 'steady', 'candidates')        # the rows are slimmed: the thumbnail and file flags are noise to an agent, and a whole project's list must fit its context
        return dict(total=len(cs), offset=offset, clips=[{k: c[k] for k in keep if k in c} for c in cs[offset:offset + limit]])

    @tool
    async def get_clip(clip: str, folder: str | None = None) -> dict:
        """Everything known about one clip (by id): time, video and camera facts, note, and what each analysis stage found. Long lists are cut."""
        return shrink(await backend.get('/api/clip', folder=await folder_of(folder), clip=clip))

    @tool
    async def search_transcript(query: str = '', clip: str | None = None, limit: int = 20, folder: str | None = None) -> dict:
        """Phrases of the running transcript (the speech with the user's corrections applied) whose text contains `query` (case-insensitive; empty matches all), optionally of one clip. Each: clip, start and end second in the clip, text, English text, speaker (wearer/other)."""
        f = await folder_of(folder); segs = (await backend.get('/api/transcript', folder=f))['segments']; q = query.lower().strip()
        hit = [s for s in segs if (not clip or s.get('clip') == clip) and (not q or q in (s.get('text') or '').lower() or q in (s.get('text_en') or '').lower())]
        return dict(total=len(hit), phrases=[dict(clip=s.get('clip'), t0=round(s['t0'], 2), t1=round(s['t1'], 2), text=s.get('text'), text_en=s.get('text_en') if s.get('lang') != 'en' else None, who=s.get('who'), flagged=s.get('flagged')) for s in hit[:limit]])

    @tool
    async def transcript_review(limit: int = 15, folder: str | None = None) -> dict:
        """The phrases most likely to be misrecognised (low confidence, fast speech, the recogniser's flags), worst first, with how many are still to review."""
        d = await backend.get('/api/transcript/review', folder=await folder_of(folder)); return dict(todo=d['todo'], total=d['total'], items=shrink(d['items'][:limit], items=limit))

    @tool
    async def edit_plan(folder: str | None = None) -> dict:
        """The film plan: settings, overrides (locks, bans, weights), and the segments in film order (clip, where in the clip, length, technique, transition, speech, script line). The technique catalogue is left out."""
        e = (await backend.get('/api/edit', folder=await folder_of(folder)))['edit']; plan = e.get('plan') or {}
        return dict(settings=shrink(e.get('settings')), overrides=shrink(e.get('overrides')), source=plan.get('source'), length_s=plan.get('length_s'), segments=len(plan.get('segments', [])), plan=shrink(plan.get('segments', []), items=60, chars=160))

    @tool
    async def get_script(folder: str | None = None) -> dict:
        """The newest whole-race script draft: the lines (voice-over and the runner's own), their order and the clip each belongs to."""
        return shrink(await backend.get('/api/script2', folder=await folder_of(folder)), items=60, chars=300)

    @tool
    async def get_notes(folder: str | None = None) -> dict:
        """The user's own notes on the project and on each clip."""
        return shrink(await backend.get('/api/notes', folder=await folder_of(folder)), items=80, chars=500)

    @tool
    async def track_summary(folder: str | None = None) -> dict:
        """The race GPS track: distance, climb, times, and the clips placed on it."""
        f = await folder_of(folder); return shrink(dict(track=await backend.get('/api/track', folder=f), clips=(await backend.get('/api/track/clips', folder=f))))

    @tool
    async def music_state(folder: str | None = None) -> dict:
        """The music track of the project and what was found in it (tempo, sections, vocals)."""
        return shrink(await backend.get('/api/music', folder=await folder_of(folder)))

    @tool
    async def film_stills(folder: str | None = None) -> dict:
        """The stills rendered from the film so far (name, film time, size) and the renders in progress; `film_still_image` shows one."""
        return shrink(await backend.get('/api/film/stills', folder=await folder_of(folder)))

    @tool
    async def final_render_status(folder: str | None = None) -> dict:
        """State of the final film render of the current plan: not started, running with progress, or finished."""
        return shrink(await backend.get('/api/final', folder=await folder_of(folder)))

    @tool
    async def recent_log(folder: str | None = None) -> dict:
        """The last lines of the project's run log (what the analysis stages did, and what failed)."""
        return await backend.get('/api/log', folder=await folder_of(folder))

    @tool
    async def clip_thumbnail(clip: str, overlay: bool = False, folder: str | None = None) -> Image:
        """The picture the app shows for a clip (JPEG); `overlay` for the one with the race overlay drawn on it."""
        return Image(data=await backend.get_bytes('/api/thumb', folder=await folder_of(folder), clip=clip, overlay=str(bool(overlay)).lower()), format='jpeg')

    @tool
    async def film_still_image(name: str, folder: str | None = None) -> Image:
        """A rendered film still (a name from `film_stills`) as a JPEG about 960 px wide, to look at the film's picture."""
        if not re.match(r'^[\w.-]+$', name): raise ToolError('not a still name')
        return Image(data=await backend.get_bytes('/api/film/still/thumb', folder=await folder_of(folder), name=name, w=960), format='jpeg')

    return srv


def tool_names(srv):
    import asyncio
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
