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
    L.KEY_FILE = os.path.join(tempfile.mkdtemp(), 'k'); os.environ.pop('ANTHROPIC_API_KEY', None)
    try: L.chat([dict(role='user', content='hi')]); assert False
    except L.LLMError as e: assert 'no Anthropic API key' in str(e)
    try: L.set_key('nope'); assert False
    except L.LLMError: pass
    L.set_key('sk-ant-' + 'x' * 40); assert oct(os.stat(L.KEY_FILE).st_mode & 0o777) == '0o600' and L.key_configured()
    calls = []; L.urllib.request.urlopen = fake(calls, [dict(content=[dict(type='text', text='{"a": 1}')], usage=dict(input_tokens=5, output_tokens=3), model='m')])
    r = L.chat([dict(role='system', content='be brief'), dict(role='user', content='hi')], model='claude-sonnet-5-5')
    c = calls[0]; assert c['url'].endswith('/v1/messages') and c['headers']['x-api-key'].startswith('sk-ant-') and c['headers']['anthropic-version'] == '2023-06-01'
    assert c['body']['system'] == 'be brief' and c['body']['messages'] == [dict(role='user', content='hi')] and r['text'] == '{"a": 1}' and r['tokens']['output'] == 3
    L.set_key(''); assert not L.key_configured()


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


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]; bad = 0
    for f in fns:
        try: f(); print('ok  ', f.__name__)
        except AssertionError as e: bad += 1; print('FAIL', f.__name__, e)
    print(f'{len(fns) - bad}/{len(fns)} passed'); sys.exit(bad)
