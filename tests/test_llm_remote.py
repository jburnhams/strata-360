"""Claude API client with a fake HTTP layer (no key, no network). Run: .venv/bin/python tests/test_llm_remote.py"""
import io, json, os, sys, tempfile, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from strata360.edit import llm_remote as L, script as S


class Resp:
    def __init__(self, obj): self.b = json.dumps(obj).encode()
    def read(self): return self.b


def fake(calls, replies):
    def urlopen(req, timeout=0):
        calls.append(dict(url=req.full_url, headers={k.lower(): v for k, v in req.header_items()}, body=json.loads(req.data)))
        r = replies.pop(0)
        if isinstance(r, tuple): raise urllib.error.HTTPError(req.full_url, r[0], 'x', {}, io.BytesIO(json.dumps({'error': {'message': r[1]}}).encode()))
        return Resp(r)
    return urlopen


def test_request_shape_and_key_handling():
    d = tempfile.mkdtemp(); L.KEY_FILE = os.path.join(d, 'k'); L.VARS_FILE = os.path.join(d, 'secrets.env'); os.environ.pop('ANTHROPIC_API_KEY', None)
    try: L.chat([dict(role='user', content='hi')]); assert False
    except L.LLMError as e: assert 'no Anthropic API key' in str(e)
    try: L.set_key('nope'); assert False
    except L.LLMError: pass
    L.set_key('sk-ant-' + 'x' * 40); assert oct(os.stat(L.VARS_FILE).st_mode & 0o777) == '0o600' and L.key_configured() and 'ANTHROPIC_API_KEY=sk-ant-' in open(L.VARS_FILE).read()
    calls = []; L.urllib.request.urlopen = fake(calls, [dict(content=[dict(type='text', text='{"a": 1}')], usage=dict(input_tokens=5, output_tokens=3), model='m')])
    r = L.chat([dict(role='system', content='be brief'), dict(role='user', content='hi')], model='claude-sonnet-5-5')
    c = calls[0]; assert c['url'].endswith('/v1/messages') and c['headers']['x-api-key'].startswith('sk-ant-') and c['headers']['anthropic-version'] == '2023-06-01'
    assert c['body']['system'] == 'be brief' and c['body']['messages'] == [dict(role='user', content='hi')] and r['text'] == '{"a": 1}' and r['tokens']['output'] == 3
    L.set_key(''); assert not L.key_configured()


def test_gemini_keys_request_shape_and_errors():
    d = tempfile.mkdtemp(); L.KEY_FILE = os.path.join(d, 'k'); L.VARS_FILE = os.path.join(d, 'secrets.env')
    for e in ('GEMINI_API_KEY', 'GOOGLE_API_KEY'): os.environ.pop(e, None)
    try: L.chat_gemini([dict(role='user', content='x')]); assert False
    except L.LLMError as e: assert 'no Gemini API key' in str(e)
    try: L.set_key('not-a-key', 'gemini'); assert False
    except L.LLMError: pass
    L.set_key('AIza' + 'z' * 35, 'gemini'); assert L.key_configured('gemini') and oct(os.stat(L.VARS_FILE).st_mode & 0o777) == '0o600'
    calls = []; L.urllib.request.urlopen = fake(calls, [dict(candidates=[dict(content=dict(parts=[dict(text='{"a": 2}')]), finishReason='STOP')], usageMetadata=dict(promptTokenCount=4, candidatesTokenCount=2), modelVersion='g')])
    r = L.chat([dict(role='system', content='sys'), dict(role='user', content='hi'), dict(role='assistant', content='yo'), dict(role='user', content='more')], model='gemini-flash-latest', provider='gemini')
    c = calls[0]; assert 'gemini-flash-latest:generateContent' in c['url'] and 'key=' not in c['url'] and c['headers']['x-goog-api-key'].startswith('AIza')              # the key is in a header, not the URL
    assert c['body']['systemInstruction']['parts'][0]['text'] == 'sys' and [m['role'] for m in c['body']['contents']] == ['user', 'model', 'user'] and r['text'] == '{"a": 2}'
    assert c['body']['generationConfig']['responseMimeType'] == 'application/json'
    L.time.sleep = lambda s: None; calls = []; L.urllib.request.urlopen = fake(calls, [(429, 'quota'), dict(candidates=[dict(content=dict(parts=[dict(text='ok')]))])]); assert L.chat_gemini([dict(role='user', content='x')])['text'] == 'ok'
    calls = []; L.urllib.request.urlopen = fake(calls, [(400, 'API key not valid. Please pass a valid API key.')])
    try: L.chat_gemini([dict(role='user', content='x')]); assert False
    except L.LLMError as e: assert 'rejected' in str(e) and 'AIza' not in str(e)


def test_vertex_key_and_endpoint():
    d = tempfile.mkdtemp(); L.KEY_FILE = os.path.join(d, 'k'); L.VARS_FILE = os.path.join(d, 'secrets.env')
    for e in ('VERTEX_API_KEY', 'GOOGLE_CLOUD_API_KEY'): os.environ.pop(e, None)
    try: L.set_key('AIza' + 'z' * 35, 'vertex'); assert False
    except L.LLMError: pass
    L.set_key('AQ.' + 'Z' * 40, 'vertex'); assert L.key_configured('vertex') and 'VERTEX_API_KEY=AQ.' in open(L.VARS_FILE).read()
    calls = []; L.urllib.request.urlopen = fake(calls, [dict(candidates=[dict(content=dict(parts=[dict(text='{}')]))])]); L.chat([dict(role='user', content='x')], model='gemini-2.5-pro', provider='vertex')
    assert calls[0]['url'].startswith('https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-pro:generateContent') and 'key=' not in calls[0]['url'] and calls[0]['headers']['x-goog-api-key'].startswith('AQ.')


def test_errors_and_retries_never_leak_the_key():
    os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-' + 'k' * 40; L.time.sleep = lambda s: None
    calls = []; L.urllib.request.urlopen = fake(calls, [(529, 'overloaded'), dict(content=[dict(type='text', text='ok')], usage={})]); assert L.chat([dict(role='user', content='x')])['text'] == 'ok' and len(calls) == 2
    calls = []; L.urllib.request.urlopen = fake(calls, [(400, 'temperature is not supported'), dict(content=[dict(type='text', text='ok')], usage={})]); L.chat([dict(role='user', content='x')]); assert 'temperature' not in calls[1]['body'] and 'temperature' in calls[0]['body']
    calls = []; L.urllib.request.urlopen = fake(calls, [(401, 'bad key')])
    try: L.chat([dict(role='user', content='x')]); assert False
    except L.LLMError as e: assert 'rejected' in str(e) and 'sk-ant' not in str(e)


def test_script_writer_uses_the_remote_provider_and_enforces_budgets():
    os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-' + 'k' * 40; L.time.sleep = lambda s: None
    facts = [dict(index=0, film_start_s=0.0, seconds=4.0, clip='A', track='x'), dict(index=1, film_start_s=4.0, seconds=6.0, clip='B', wearer_says=['hello there'])]
    long = 'This is a very long line that runs well past the budget for such a short segment of film. And another sentence.'
    replies = [dict(content=[dict(type='text', text=json.dumps({'title': 'T', 'lines': [{'seg': 0, 'text': long}, {'seg': 1, 'text': 'talking over you'}]}))], usage={}),
               dict(content=[dict(type='text', text=json.dumps({'title': 'T', 'lines': [{'seg': 0, 'text': 'A short line.'}, {'seg': 1, 'text': ''}]}))], usage={})]
    calls = []; L.urllib.request.urlopen = fake(calls, replies); d = S.write_script(facts, 'notes', 10.0, provider='anthropic', model='claude-sonnet-5-5')
    assert len(calls) == 2 and 'Fix these problems' in calls[1]['body']['messages'][-1]['content'] and d['provider'] == 'anthropic'          # one retry with the exact violations
    l0, l1 = d['lines']; assert l0['text'] == 'A short line.' and l1['text'] == '' and l0['words'] <= l0['budget_words']


def test_the_free_key_goes_first_the_paid_key_takes_over_at_a_limit_and_alone_for_pro():
    d = tempfile.mkdtemp(); L.KEY_FILE = os.path.join(d, 'k'); L.VARS_FILE = os.path.join(d, 'secrets.env'); L.time.sleep = lambda s: None
    for e in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_PAID_API_KEY'): os.environ.pop(e, None)
    open(L.VARS_FILE, 'w').write('GEMINI_API_KEY=AIza' + 'f' * 35 + '\nGEMINI_PAID_API_KEY=AQ.' + 'p' * 40 + '\n'); ok = dict(candidates=[dict(content=dict(parts=[dict(text='ok')]))], usageMetadata=dict(promptTokenCount=1, candidatesTokenCount=1))
    L._FREE_DOWN.clear(); calls = []; L.urllib.request.urlopen = fake(calls, [ok]); r = L.chat_gemini([dict(role='user', content='x')], model='gemini-3.8-flash', provider='gemini', json_mode=False)
    assert r['tier'] == 'free' and calls[0]['headers']['x-goog-api-key'].startswith('AIza')                                       # free first
    L._FREE_DOWN.clear(); calls = []; L.urllib.request.urlopen = fake(calls, [(429, 'You exceeded your current quota'), ok]); r = L.chat_gemini([dict(role='user', content='x')], model='gemini-3.8-flash', provider='gemini', json_mode=False)
    assert r['tier'] == 'paid' and [c['headers']['x-goog-api-key'][:3] for c in calls] == ['AIz', 'AQ.'] and L._FREE_DOWN['gemini-3.8-flash'] > L.time.time()           # limit: the paid key at once
    calls = []; L.urllib.request.urlopen = fake(calls, [ok]); r = L.chat_gemini([dict(role='user', content='x')], model='gemini-3.8-flash', provider='gemini', json_mode=False)
    assert r['tier'] == 'paid' and len(calls) == 1                                                                                # while the free key cools down it is not asked
    L._FREE_DOWN.clear(); calls = []; L.urllib.request.urlopen = fake(calls, [ok]); r = L.chat_gemini([dict(role='user', content='x')], model='gemini-3.1-pro-preview', provider='gemini', json_mode=False)
    assert r['tier'] == 'paid' and calls[0]['headers']['x-goog-api-key'].startswith('AQ.')                                         # pro: the paid key only
    L._FREE_DOWN.clear(); calls = []; L.urllib.request.urlopen = fake(calls, [(503, 'high demand')] * 2 + [(503, 'high demand')] * 3); 
    try: L.chat_gemini([dict(role='user', content='x')], model='gemini-3.8-flash', provider='gemini', json_mode=False); assert False
    except L.LLMBusy as e: assert 'AIza' not in str(e) and 'AQ.' not in str(e)                                                      # still busy on both keys: retryable, and no key in the message


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
