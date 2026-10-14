"""A chat assistant for a film project: a hosted model (NVIDIA's OpenAI-compatible API, plain HTTPS, no SDK) that answers questions about the project by calling the READ-ONLY tools of server/mcp_tools.py (clips, transcript, edit plan, script, stills ...). It cannot change anything: those tools only read.

The loop runs on the server so the API key never reaches the browser: the key is read from the environment (`NVIDIA_API_KEY`) or the gitignored secrets.env, like the other keys (edit/llm_remote.py), and is never returned by any route.

Privacy: a request to the model carries your question and what the tools returned while answering it (clip ids and times, transcript phrases, plan and script text, notes; a picture is never sent, the image tools answer with a note instead). It goes to NVIDIA's service.

  run(backend, folder, history, key, model=DEFAULT_MODEL)  ->  dict(answer, steps=[dict(tool, args, seconds, chars, error)], model, seconds)"""
import asyncio, json, os, re, time, urllib.error, urllib.request

URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
DEFAULT_MODEL = 'nvidia/nemotron-3-super-120b-a12b'            # tested with tool calls: answers in about 3 s; others of the catalogue timed out or are not enabled for the account
MAX_STEPS = 8                                                  # model calls per question (each may ask for several tools)
RESULT_CHARS = 6000                                            # longest tool answer given to the model
HISTORY_TURNS = 12                                             # the last turns of the conversation that are sent
SYSTEM = """You are the assistant of a film editing project: a 360 camera film of a long race, with its clips, what the analysis found in them (speech transcript, scenes, quality, colour), the edit plan, the voice-over script and rendered stills. You can only LOOK at the project, with your tools; you cannot change it.
Answer from the tools' results, never from guesses: when you need a fact (a clip, a time, what was said, what the plan does) call a tool. Name clips by their id and give times in seconds into the clip. Be brief and concrete. If something is missing (a stage not run, no transcript), say so and say which stage would make it. The project folder is already set for the tools: do not ask for it."""


class AgentError(Exception):
    retryable = False


def key_for_nvidia():
    """The NVIDIA API key from the environment or secrets.env, or None."""
    if os.environ.get('NVIDIA_API_KEY'): return os.environ['NVIDIA_API_KEY'].strip()
    from strata360.edit import llm_remote as LR
    return (LR._read_vars().get('NVIDIA_API_KEY') or '').strip() or None


def chat_nvidia(messages, tools, model, key, timeout=120, url=URL):
    """One chat completion with tools: the reply message dict (`content`, `tool_calls`). AgentError on a refused key, a bad request or an unreachable service."""
    body = dict(model=model, messages=messages, tools=tools, max_tokens=1500, temperature=0.2)
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try: r = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        why = e.read()[:300].decode('utf8', 'replace'); err = AgentError(f'the model service answered {e.code}: {why}'); err.retryable = e.code in (429, 500, 502, 503, 504); raise err
    except (urllib.error.URLError, TimeoutError, OSError) as e: err = AgentError(f'the model service could not be reached: {e}'); err.retryable = True; raise err
    try: return r['choices'][0]['message']
    except (KeyError, IndexError, TypeError): raise AgentError('the model service gave no answer')


def openai_tools(tools):
    """The MCP tools as the OpenAI `tools` list."""
    return [dict(type='function', function=dict(name=t.name, description=t.description or '', parameters=t.input_schema or dict(type='object', properties={}))) for t in tools]


def clean_history(history):
    """The conversation as it may be sent: only user and assistant turns with text, the last HISTORY_TURNS of them, ending with a user turn."""
    turns = [dict(role=m['role'], content=m['content'].strip()) for m in history if isinstance(m, dict) and m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str) and m['content'].strip()]
    turns = turns[-HISTORY_TURNS:]
    while turns and turns[0]['role'] != 'user': turns.pop(0)
    if not turns or turns[-1]['role'] != 'user': raise AgentError('the conversation must end with a question')
    return turns


def result_text(res):
    """What a tool result is told to the model as: its text, a note instead of a picture, an error as such."""
    parts = []
    for c in res.content:
        if c.type == 'text': parts.append(c.text)
        else: parts.append(f'[a {c.type} was made; this assistant does not see pictures]')
    text = '\n'.join(parts)
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + f'\n... ({len(text) - RESULT_CHARS} more characters left out: ask for less or a part)'


async def _loop(srv, folder, history, key, model, chat, max_steps):
    tools = openai_tools(await srv.list_tools()); msgs = [dict(role='system', content=SYSTEM + f'\nProject folder (already given to every tool): {folder}')] + clean_history(history); steps = []
    for _ in range(max_steps):
        reply = await asyncio.to_thread(chat, msgs, tools, model, key); calls = reply.get('tool_calls') or []
        if not calls: return (reply.get('content') or '').strip() or 'I have no answer for that.', steps
        msgs.append(dict(role='assistant', content=reply.get('content') or '', tool_calls=calls))
        for c in calls:
            name = c['function']['name']; t0 = time.time(); err = None
            try: args = json.loads(c['function'].get('arguments') or '{}') or {}
            except ValueError: args = {}
            args = {k: v for k, v in args.items() if k != 'folder'}; args['folder'] = folder                       # the folder is the project's, whatever the model asks for
            try: text = result_text(await srv.call_tool(name, args))
            except Exception as e: err = str(e); text = f'error: {err}'
            steps.append(dict(tool=name, args={k: v for k, v in args.items() if k != 'folder'}, seconds=round(time.time() - t0, 2), chars=len(text), error=err)); msgs.append(dict(role='tool', tool_call_id=c.get('id'), content=text))
    msgs.append(dict(role='user', content='Answer now with what you have found; say what you could not find out.'))
    reply = await asyncio.to_thread(chat, msgs, [], model, key); return (reply.get('content') or '').strip() or 'I could not finish the research in the steps allowed.', steps


def run(backend, folder, history, key, model=DEFAULT_MODEL, chat=None, max_steps=MAX_STEPS):
    """Answer the last question of `history` ([{role, content}]) about the project in `folder`: the model calls the read-only tools through `backend` until it can answer. Returns dict(answer, steps, model, seconds)."""
    from strata360.server import mcp_tools as MT
    t0 = time.time(); answer, steps = asyncio.run(_loop(MT.build_server(backend, folder), folder, history, key, model, chat or chat_nvidia, max_steps))
    return dict(answer=answer, steps=steps, model=model, seconds=round(time.time() - t0, 1))


def valid_model(m): return bool(m) and bool(re.match(r'^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.:-]*$', m))
