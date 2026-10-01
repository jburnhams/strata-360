"""Remote language-model clients for the voice-over script writer (Google Gemini and the Claude API; plain HTTPS, no SDK dependency).

An API key is never stored in the project or the repository. It is read from the environment (`GEMINI_API_KEY` / `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`) or from `~/.strata360/gemini_key` /
`anthropic_key` (created by `strata360 set-key` or the web app, mode 600). The web app can set it but never shows it again. Privacy: a request carries the text the writer is given (your notes, the words you
say on camera and their translations, race facts such as pace, climb and time of day, place names, and short scene descriptions). No video, audio, pictures or faces are sent."""
import json, os, time, urllib.error, urllib.request

URL = 'https://api.anthropic.com/v1/messages'
VERSION = '2023-06-01'
KEY_FILE = os.path.expanduser('~/.strata360/anthropic_key')             # legacy location (still read)
VARS_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'secrets.env')    # the project's gitignored variables file: NAME=value lines, mode 600
DEFAULT_MODEL = 'claude-sonnet-5-5'
MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-fable-5-1']
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
GEMINI_MODELS = ['gemini-flash-latest', 'gemini-3.8-flash', 'gemini-2.5-flash', 'gemini-pro-latest', 'gemini-2.5-pro']
GEMINI_DEFAULT = 'gemini-flash-latest'          # the free tier has no quota for the pro models (limit 0); flash works. Switch when billing is enabled
VERTEX_URL = 'https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent'      # Vertex AI express mode: keys that start with AQ.
VERTEX_MODELS = ['gemini-3.1-pro-preview', 'gemini-3.8-flash', 'gemini-2.5-pro']      # the only 3.x pro this key can reach (3.0, 3.5-3.8 pro, -latest aliases: 404)
PROVIDERS = dict(vertex=dict(models=VERTEX_MODELS, default='gemini-3.1-pro-preview', env=('VERTEX_API_KEY', 'GOOGLE_CLOUD_API_KEY')), gemini=dict(models=GEMINI_MODELS, default=GEMINI_DEFAULT, env=('GEMINI_API_KEY', 'GOOGLE_API_KEY')), anthropic=dict(models=MODELS, default=DEFAULT_MODEL, env=('ANTHROPIC_API_KEY',)))


class LLMError(Exception): pass


def _key_file(provider):
    return KEY_FILE if provider == 'anthropic' else os.path.join(os.path.dirname(KEY_FILE), f'{provider}_key')


def _read_vars():
    out = {}
    try:
        for line in open(VARS_FILE):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line: k, v = line.split('=', 1); out[k.strip()] = v.strip().strip('"\'')
    except OSError: pass
    return out


def _write_vars(vars_):
    lines = ['# secrets for strata360 (gitignored; never commit). NAME=value, one per line.'] + [f'{k}={v}' for k, v in vars_.items()]
    fd = os.open(VARS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.write(fd, ('\n'.join(lines) + '\n').encode()); os.close(fd); os.chmod(VARS_FILE, 0o600)


def api_key(provider='anthropic'):
    """Order: the environment, the project's secrets.env, then the legacy key file in ~/.strata360."""
    names = PROVIDERS[provider]['env']; k = ''
    for e in names:
        k = os.environ.get(e, '').strip()
        if k: break
    if not k:
        v = _read_vars(); k = next((v[e] for e in names if v.get(e)), '')
    f = _key_file(provider)
    if not k and os.path.exists(f): k = open(f).read().strip()
    return k or None


def key_configured(provider='anthropic'): return api_key(provider) is not None


def _looks_valid(provider, key):
    if any(c.isspace() for c in key): return False
    if provider == 'vertex': return key.startswith('AQ.') and len(key) >= 30
    return (key.startswith('sk-ant-') and len(key) >= 30) if provider == 'anthropic' else (key.startswith('AIza') and len(key) >= 30)


def set_key(key, provider='anthropic'):
    """Store (or, with an empty string, remove) the key in the project's gitignored secrets.env (mode 600). Returns whether one is configured now."""
    name = PROVIDERS[provider]['env'][0]; v = _read_vars()
    if not key:
        v.pop(name, None); _write_vars(v)
        f = _key_file(provider)
        if os.path.exists(f): os.remove(f)
        return key_configured(provider)
    key = key.strip()
    if not _looks_valid(provider, key): raise LLMError(f"that does not look like {'an Anthropic' if provider == 'anthropic' else 'a Google Cloud (Vertex AI)' if provider == 'vertex' else 'a Google Gemini'} API key")
    v[name] = key; _write_vars(v); return True


def chat_gemini(messages, model=GEMINI_DEFAULT, max_tokens=8192, temperature=0.7, timeout=300, url=None, json_mode=True, provider='gemini'):
    """One Gemini request (generateContent). Same message list and result shape as `chat`. The key goes in a header, never in the URL, so it cannot end up in logs or error messages."""
    url = url or (VERTEX_URL if provider == 'vertex' else GEMINI_URL); key = api_key(provider)
    if provider == 'vertex' and not key: raise LLMError('no Google Cloud (Vertex) API key: put VERTEX_API_KEY in secrets.env, or run `strata360 set-key --provider vertex`, or paste it in the app (Script panel)')
    if not key: raise LLMError('no Gemini API key: put GEMINI_API_KEY in secrets.env, or run `strata360 set-key --provider gemini`, or paste it in the app (Script panel)')
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
    contents = [dict(role='model' if m['role'] == 'assistant' else 'user', parts=(m['content'] if isinstance(m['content'], list) else [dict(text=m['content'])])) for m in messages if m['role'] != 'system']      # a list of parts can carry audio: {inlineData: {mimeType, data}}
    gen = dict(temperature=float(temperature), maxOutputTokens=int(max(max_tokens, 4096)))
    if json_mode: gen['responseMimeType'] = 'application/json'
    body = dict(contents=contents, generationConfig=gen)
    if system: body['systemInstruction'] = dict(parts=[dict(text=system)])
    last = None; t0 = time.time()
    for attempt in range(4):
        req = urllib.request.Request(url.format(model=model), data=json.dumps(body).encode(), headers={'x-goog-api-key': key, 'content-type': 'application/json'})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            cands = r.get('candidates') or []
            if not cands: raise LLMError('the model returned nothing' + (f" (blocked: {r['promptFeedback'].get('blockReason')})" if r.get('promptFeedback', {}).get('blockReason') else ''))
            parts = (cands[0].get('content') or {}).get('parts') or []; text = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
            u = r.get('usageMetadata', {}); return dict(text=text, seconds=round(time.time() - t0, 1), tokens=dict(input=u.get('promptTokenCount'), output=u.get('candidatesTokenCount')), model=r.get('modelVersion', model), finish=cands[0].get('finishReason'))
        except urllib.error.HTTPError as e:
            msg = ''
            try: msg = json.loads(e.read().decode()).get('error', {}).get('message', '')
            except Exception: pass
            last = f'HTTP {e.code}: {msg}'
            if e.code in (400, 401, 403) and ('api key' in msg.lower() or e.code in (401, 403)): raise LLMError(f'the Gemini API key was rejected ({e.code}): check it')
            if e.code in (400, 404): raise LLMError(last)
            if e.code in (429, 500, 502, 503, 504): time.sleep(2 * (attempt + 1) ** 2); continue
            raise LLMError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = f'network error: {getattr(e, "reason", e)}'; time.sleep(2 * (attempt + 1))
    raise LLMError(last or 'request failed')


def chat(messages, model=DEFAULT_MODEL, max_tokens=3000, temperature=0.7, timeout=240, url=URL, provider='anthropic'):
    """One request. `messages` in the OpenAI-style list (system / user / assistant); system turns are joined into the API's `system` field. Returns {text, seconds, tokens, model}."""
    if provider in ('gemini', 'vertex'): return chat_gemini(messages, model if (model or '').startswith('gemini') else PROVIDERS[provider]['default'], max_tokens, temperature, timeout, provider=provider)
    key = api_key('anthropic')
    if not key: raise LLMError('no Anthropic API key: set ANTHROPIC_API_KEY, or run `strata360 set-key`, or paste it in the app (Script panel)')
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system'); turns = [dict(role=m['role'], content=m['content']) for m in messages if m['role'] != 'system']
    body = dict(model=model, max_tokens=int(max_tokens), messages=turns, temperature=float(temperature)); 
    if system: body['system'] = system
    last = None; t0 = time.time(); drop_temp = False
    for attempt in range(4):
        b = dict(body)
        if drop_temp: b.pop('temperature', None)
        req = urllib.request.Request(url, data=json.dumps(b).encode(), headers={'x-api-key': key, 'anthropic-version': VERSION, 'content-type': 'application/json'})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            text = ''.join(c.get('text', '') for c in r.get('content', []) if c.get('type') == 'text'); u = r.get('usage', {})
            return dict(text=text, seconds=round(time.time() - t0, 1), tokens=dict(input=u.get('input_tokens'), output=u.get('output_tokens')), model=r.get('model', model))
        except urllib.error.HTTPError as e:
            msg = ''
            try: msg = json.loads(e.read().decode()).get('error', {}).get('message', '')
            except Exception: pass
            last = f'HTTP {e.code}: {msg}'
            if e.code == 401: raise LLMError('the API key was rejected (401): check it')
            if e.code == 400 and 'temperature' in msg.lower() and not drop_temp: drop_temp = True; continue
            if e.code == 400 or e.code == 404: raise LLMError(last)
            if e.code in (429, 500, 502, 503, 529): time.sleep(2 * (attempt + 1) ** 2); continue
            raise LLMError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = f'network error: {getattr(e, "reason", e)}'; time.sleep(2 * (attempt + 1))
    raise LLMError(last or 'request failed')
