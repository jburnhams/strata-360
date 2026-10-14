"""A chat assistant for a film project: a hosted model (NVIDIA's OpenAI-compatible API, plain HTTPS, no SDK) that answers questions about the project by calling the READ-ONLY tools of server/mcp_tools.py (clips, transcript, edit plan, script, stills ...). It cannot change anything: those tools only read.

The loop runs on the server so the API key never reaches the browser: the key is read from the environment (`NVIDIA_API_KEY`) or the gitignored secrets.env, like the other keys (edit/llm_remote.py), and is never returned by any route.

Privacy: a request to the model carries your question and what the tools returned while answering it (clip ids and times, transcript phrases, plan and script text, notes). A picture is shown to YOU and the model is only told that it was shown. Only with `vision` on (your choice, per question) is the picture also sent, to a vision model that describes it in words; the description is what the model reads. It all goes to NVIDIA's service.

  run(backend, folder, history, key, model=DEFAULT_MODEL)  ->  dict(answer, steps=[dict(tool, args, seconds, chars, error)], images=[dict(url, caption)], model, seconds)"""
import asyncio, json, os, re, time, urllib.error, urllib.request

URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
VISION_MODEL = 'meta/llama-3.2-11b-vision-instruct'            # describes a picture (tested on the account: 5 s; nvidia/nemotron-3-nano-omni-30b-a3b-reasoning also works; 90b timed out, gemma-3 and phi-3-vision are not enabled)
DEFAULT_MODEL = 'nvidia/nemotron-3-super-120b-a12b'            # tested with tool calls: answers in about 3 s; others of the catalogue timed out or are not enabled for the account
MAX_STEPS = 8                                                  # model calls per question (each may ask for several tools)
MAX_IMAGES = 6                                                 # pictures shown with one answer
RESULT_CHARS = 6000                                            # longest tool answer given to the model
HISTORY_TURNS = 12                                             # the last turns of the conversation that are sent
SYSTEM = """You are the assistant of a film editing project: a 360 camera film of a long race, with its clips, what the analysis found in them (speech transcript, scenes, quality, colour), the edit plan, the voice-over script and rendered stills. You can only LOOK at the project, with your tools; you cannot change it.
Answer from the tools' results, never from guesses: when you need a fact (a clip, a time, what was said, what the plan does) call a tool. Start broad (`project`), then narrow (`clip` with only the sections you need, `transcript` with a query, `plan` rows); every answer says what more can be asked for. Name clips by their id and give times in seconds into the clip. Be brief and concrete. If something is missing (a stage not run, no transcript), say so and say which stage would make it. When the user asks to see something (a frame, a still, a moment, a clip's thumbnail), call `picture`: the picture is shown to the user below your answer, but you cannot see it yourself, so describe only what the tools' text tells you. The project folder is already set for the tools: do not ask for it."""


class AgentError(Exception):
    retryable = False


def key_for_nvidia():
    """The NVIDIA API key from the environment or secrets.env, or None."""
    if os.environ.get('NVIDIA_API_KEY'): return os.environ['NVIDIA_API_KEY'].strip()
    from strata360.edit import llm_remote as LR
    return (LR._read_vars().get('NVIDIA_API_KEY') or '').strip() or None


def chat_nvidia(messages, tools, model, key, timeout=120, url=URL):
    """One chat completion with tools: the reply message dict (`content`, `tool_calls`). AgentError on a refused key, a bad request or an unreachable service."""
    body = dict(model=model, messages=messages, max_tokens=1500, temperature=0.2, **({'tools': tools} if tools else {}))
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try: r = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        why = e.read()[:300].decode('utf8', 'replace'); err = AgentError(f'the model service answered {e.code}: {why}'); err.retryable = e.code in (429, 500, 502, 503, 504); raise err
    except (urllib.error.URLError, TimeoutError, OSError) as e: err = AgentError(f'the model service could not be reached: {e}'); err.retryable = True; raise err
    try: return r['choices'][0]['message']
    except (KeyError, IndexError, TypeError): raise AgentError('the model service gave no answer')


def describe_nvidia(jpeg, question, model, key, timeout=90, url=URL):
    """What a vision model says is in the picture (JPEG bytes), told for the question being worked on: a few sentences. AgentError like chat_nvidia."""
    import base64
    prompt = f'This is a frame from a 360 camera film of a long race (a flat view cut from the footage). Describe what is in it in two or three plain sentences, for someone who cannot see it: the place, the people and what they do, the light and weather, anything written. What matters for this question: {question}'
    msg = dict(role='user', content=[dict(type='text', text=prompt), dict(type='image_url', image_url=dict(url='data:image/jpeg;base64,' + base64.b64encode(jpeg).decode()))])
    return (chat_nvidia([msg], None, model, key, timeout, url).get('content') or '').strip()


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


def image_of(tool, args, folder):
    """The picture a `picture` tool call stands for, as dict(url, caption) for the browser (the server's own URL, same origin, the user's cookie authenticates it), or None."""
    from urllib.parse import urlencode
    if tool != 'picture': return None
    of, clip = args.get('of'), args.get('clip')
    if of == 'frame' and clip and args.get('t') is not None:
        q = dict(folder=folder, clip=clip, t=args['t'], **{k: args[k] for k in ('yaw', 'pitch', 'fov') if k in args}); return dict(url='/api/clip/frame?' + urlencode(q), caption=f"{clip} at {float(args['t']):g} s")
    if of == 'thumbnail' and clip: return dict(url='/api/thumb?' + urlencode(dict(folder=folder, clip=clip, overlay=str(bool(args.get('overlay'))).lower())), caption=f'{clip} (thumbnail)')
    if of == 'still' and args.get('name'): return dict(url='/api/film/still/thumb?' + urlencode(dict(folder=folder, name=args['name'], w=960)), caption=f"film still {args['name']}")
    return None


def pictures_in(res):
    """The JPEG/PNG bytes of the pictures in a tool result."""
    import base64
    return [base64.b64decode(c.data) for c in res.content if c.type == 'image']


def result_text(res):
    """What a tool result is told to the model as: its text, a note instead of a picture, an error as such."""
    parts = []
    for c in res.content:
        if c.type == 'text': parts.append(c.text)
        else: parts.append(f'[a {c.type} was made and is shown to the user; you cannot see it]')
    text = '\n'.join(parts)
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + f'\n... ({len(text) - RESULT_CHARS} more characters left out: ask for less or a part)'


async def _loop(srv, folder, history, key, model, chat, max_steps, see=None):
    tools = openai_tools(await srv.list_tools()); msgs = [dict(role='system', content=SYSTEM + f'\nProject folder (already given to every tool): {folder}')] + clean_history(history); steps = []; images = []; question = clean_history(history)[-1]['content']
    for _ in range(max_steps):
        reply = await asyncio.to_thread(chat, msgs, tools, model, key); calls = reply.get('tool_calls') or []
        if not calls: return (reply.get('content') or '').strip() or 'I have no answer for that.', steps, images
        msgs.append(dict(role='assistant', content=reply.get('content') or '', tool_calls=calls))
        for c in calls:
            name = c['function']['name']; t0 = time.time(); err = None
            try: args = json.loads(c['function'].get('arguments') or '{}') or {}
            except ValueError: args = {}
            args = {k: v for k, v in args.items() if k != 'folder'}; args['folder'] = folder                       # the folder is the project's, whatever the model asks for
            try:
                res = await srv.call_tool(name, args); text = result_text(res); img = image_of(name, args, folder)
                if see and img:                                                                                          # vision on: the model reads a description of the picture, never the picture
                    for pic in pictures_in(res)[:1]: text += '\nWhat the picture shows (described by a vision model): ' + (await asyncio.to_thread(see, pic, question) or 'no description')
                if img and img not in images and len(images) < MAX_IMAGES: images.append(img)
            except Exception as e: err = str(e); text = f'error: {err}'
            steps.append(dict(tool=name, args={k: v for k, v in args.items() if k != 'folder'}, seconds=round(time.time() - t0, 2), chars=len(text), error=err)); msgs.append(dict(role='tool', tool_call_id=c.get('id'), content=text))
    msgs.append(dict(role='user', content='Answer now with what you have found; say what you could not find out.'))
    reply = await asyncio.to_thread(chat, msgs, [], model, key); return (reply.get('content') or '').strip() or 'I could not finish the research in the steps allowed.', steps, images


def run(backend, folder, history, key, model=DEFAULT_MODEL, chat=None, max_steps=MAX_STEPS, vision=False, vision_model=VISION_MODEL, see=None):
    """Answer the last question of `history` ([{role, content}]) about the project in `folder`: the model calls the read-only tools through `backend` until it can answer. `vision`: the pictures the tools make are also described by `vision_model` (`see(jpeg, question)` replaces that call, for tests). Returns dict(answer, steps, images, model, vision, seconds)."""
    from strata360.server import mcp_tools as MT
    if vision and see is None: see = lambda jpeg, question: describe_nvidia(jpeg, question, vision_model, key)
    t0 = time.time(); answer, steps, images = asyncio.run(_loop(MT.build_server(backend, folder), folder, history, key, model, chat or chat_nvidia, max_steps, see if vision else None))
    return dict(answer=answer, steps=steps, images=images, model=model, vision=bool(vision), seconds=round(time.time() - t0, 1))


def valid_model(m): return bool(m) and bool(re.match(r'^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.:-]*$', m))
