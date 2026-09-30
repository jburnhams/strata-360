"""Claude API client for the voice-over script writer (plain HTTPS, no SDK dependency).

The API key is never stored in the project or the repository. It is read from the environment (`ANTHROPIC_API_KEY`) or from `~/.strata360/anthropic_key` (created by
`strata360 set-key` or the web app, mode 600). The web app can set it but never shows it again. Privacy: a request carries the text the writer is given (your notes, the words you
say on camera and their translations, race facts such as pace, climb and time of day, place names, and short scene descriptions). No video, audio, pictures or faces are sent."""
import json, os, time, urllib.error, urllib.request

URL = 'https://api.anthropic.com/v1/messages'
VERSION = '2023-06-01'
KEY_FILE = os.path.expanduser('~/.strata360/anthropic_key')
DEFAULT_MODEL = 'claude-sonnet-5-5'
MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-fable-5-1']


class LLMError(Exception): pass


def api_key():
    k = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not k and os.path.exists(KEY_FILE): k = open(KEY_FILE).read().strip()
    return k or None


def key_configured(): return api_key() is not None


def set_key(key):
    """Store (or, with an empty string, remove) the key: mode 600, in the user's home. Returns whether one is configured now."""
    if not key:
        if os.path.exists(KEY_FILE): os.remove(KEY_FILE)
        return key_configured()
    key = key.strip()
    if not key.startswith('sk-ant-') or len(key) < 30 or any(c.isspace() for c in key): raise LLMError('that does not look like an Anthropic API key (it starts with sk-ant-)')
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600); os.write(fd, key.encode()); os.close(fd); os.chmod(KEY_FILE, 0o600); return True


def chat(messages, model=DEFAULT_MODEL, max_tokens=3000, temperature=0.7, timeout=240, url=URL):
    """One request. `messages` in the OpenAI-style list (system / user / assistant); system turns are joined into the API's `system` field. Returns {text, seconds, tokens, model}."""
    key = api_key()
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
