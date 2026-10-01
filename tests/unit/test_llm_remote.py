"""Claude / Gemini / Vertex clients against a scripted HTTP layer (no key, no network)."""
import json, os
import pytest
from fakes import http_error
from strata360.edit import llm_remote as L, script as S

USER = [dict(role='user', content='x')]
CLAUDE_OK = dict(content=[dict(type='text', text='ok')], usage={})
GEMINI_OK = dict(candidates=[dict(content=dict(parts=[dict(text='ok')]))], usageMetadata=dict(promptTokenCount=1, candidatesTokenCount=1))


def err(code, message): return http_error(code, {'error': {'message': message}})


@pytest.fixture(autouse=True)
def llm(tmp_path, monkeypatch, no_sleep):
    """The module with its key files in tmp (never the repo's secrets.env), no keys in the environment, no waiting, and the free-tier cooldown cleared."""
    monkeypatch.setattr(L, 'KEY_FILE', str(tmp_path / 'k')); monkeypatch.setattr(L, 'VARS_FILE', str(tmp_path / 'secrets.env'))
    for name in ('ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_PAID_API_KEY', 'VERTEX_API_KEY', 'GOOGLE_CLOUD_API_KEY'): monkeypatch.delenv(name, raising=False)
    L._FREE_DOWN.clear(); yield L; L._FREE_DOWN.clear()


@pytest.fixture
def claude_key(monkeypatch): monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-' + 'k' * 40)


def is_private(path): return os.name == 'nt' or oct(os.stat(path).st_mode & 0o777) == '0o600'


class TestClaude:
    def test_without_a_key_chat_refuses(self):
        with pytest.raises(L.LLMError, match='no Anthropic API key'): L.chat([dict(role='user', content='hi')])

    def test_a_malformed_key_is_not_stored(self):
        with pytest.raises(L.LLMError): L.set_key('nope')

    def test_a_stored_key_is_private_and_can_be_removed(self):
        L.set_key('sk-ant-' + 'x' * 40)
        assert is_private(L.VARS_FILE) and L.key_configured() and 'ANTHROPIC_API_KEY=sk-ant-' in open(L.VARS_FILE).read()
        L.set_key(''); assert not L.key_configured()

    def test_request_shape(self, fake_urlopen):
        L.set_key('sk-ant-' + 'x' * 40)
        fake_urlopen.reply(dict(content=[dict(type='text', text='{"a": 1}')], usage=dict(input_tokens=5, output_tokens=3), model='m'))
        r = L.chat([dict(role='system', content='be brief'), dict(role='user', content='hi')], model='claude-sonnet-5-5')
        c = fake_urlopen.calls[0]
        assert c['url'].endswith('/v1/messages') and c['headers']['x-api-key'].startswith('sk-ant-') and c['headers']['anthropic-version'] == '2023-06-01'
        assert c['body']['system'] == 'be brief' and c['body']['messages'] == [dict(role='user', content='hi')]
        assert r['text'] == '{"a": 1}' and r['tokens']['output'] == 3

    def test_an_overloaded_service_is_retried(self, claude_key, fake_urlopen, no_sleep):
        fake_urlopen.reply(err(529, 'overloaded'), CLAUDE_OK)
        assert L.chat(USER)['text'] == 'ok' and len(fake_urlopen.calls) == 2 and no_sleep.delays

    def test_an_unsupported_parameter_is_dropped_and_retried(self, claude_key, fake_urlopen):
        fake_urlopen.reply(err(400, 'temperature is not supported'), CLAUDE_OK); L.chat(USER)
        assert 'temperature' not in fake_urlopen.calls[1]['body']

    def test_a_rejected_key_is_reported_without_the_key(self, claude_key, fake_urlopen):
        fake_urlopen.reply(err(401, 'bad key'))
        with pytest.raises(L.LLMError) as e: L.chat(USER)
        assert 'rejected' in str(e.value) and 'sk-ant' not in str(e.value)


class TestGemini:
    def test_without_a_key_chat_refuses(self):
        with pytest.raises(L.LLMError, match='no Gemini API key'): L.chat_gemini(USER)

    def test_a_malformed_key_is_not_stored(self):
        with pytest.raises(L.LLMError): L.set_key('not-a-key', 'gemini')

    def test_request_shape_keeps_the_key_out_of_the_url(self, fake_urlopen):
        L.set_key('AIza' + 'z' * 35, 'gemini'); assert L.key_configured('gemini') and is_private(L.VARS_FILE)
        fake_urlopen.reply(dict(candidates=[dict(content=dict(parts=[dict(text='{"a": 2}')]), finishReason='STOP')], usageMetadata=dict(promptTokenCount=4, candidatesTokenCount=2), modelVersion='g'))
        r = L.chat([dict(role='system', content='sys'), dict(role='user', content='hi'), dict(role='assistant', content='yo'), dict(role='user', content='more')], model='gemini-flash-latest', provider='gemini')
        c = fake_urlopen.calls[0]
        assert 'gemini-flash-latest:generateContent' in c['url'] and 'key=' not in c['url'] and c['headers']['x-goog-api-key'].startswith('AIza')
        assert c['body']['systemInstruction']['parts'][0]['text'] == 'sys' and [m['role'] for m in c['body']['contents']] == ['user', 'model', 'user']
        assert r['text'] == '{"a": 2}' and c['body']['generationConfig']['responseMimeType'] == 'application/json'

    def test_a_quota_error_is_retried(self, monkeypatch, fake_urlopen):
        monkeypatch.setenv('GEMINI_API_KEY', 'AIza' + 'z' * 35); fake_urlopen.reply(err(429, 'quota'), GEMINI_OK)
        assert L.chat_gemini(USER)['text'] == 'ok'

    def test_a_rejected_key_is_reported_without_the_key(self, monkeypatch, fake_urlopen):
        monkeypatch.setenv('GEMINI_API_KEY', 'AIza' + 'z' * 35); fake_urlopen.reply(err(400, 'API key not valid. Please pass a valid API key.'))
        with pytest.raises(L.LLMError) as e: L.chat_gemini(USER)
        assert 'rejected' in str(e.value) and 'AIza' not in str(e.value)


class TestGeminiTiers:
    @pytest.fixture(autouse=True)
    def both_keys(self):
        open(L.VARS_FILE, 'w').write('GEMINI_API_KEY=AIza' + 'f' * 35 + '\nGEMINI_PAID_API_KEY=AQ.' + 'p' * 40 + '\n')

    def ask(self, model='gemini-3.8-flash'): return L.chat_gemini(USER, model=model, provider='gemini', json_mode=False)
    def sent_with(self, fake_urlopen): return [c['headers']['x-goog-api-key'][:3] for c in fake_urlopen.calls]

    def test_the_free_key_goes_first(self, fake_urlopen):
        fake_urlopen.reply(GEMINI_OK)
        assert self.ask()['tier'] == 'free' and self.sent_with(fake_urlopen) == ['AIz']

    def test_the_paid_key_takes_over_at_a_limit(self, fake_urlopen):
        fake_urlopen.reply(err(429, 'You exceeded your current quota'), GEMINI_OK)
        assert self.ask()['tier'] == 'paid' and self.sent_with(fake_urlopen) == ['AIz', 'AQ.']
        assert L._FREE_DOWN['gemini-3.8-flash'] > L.time.time()

    def test_a_cooling_free_key_is_not_asked(self, fake_urlopen):
        L._FREE_DOWN['gemini-3.8-flash'] = L.time.time() + 600; fake_urlopen.reply(GEMINI_OK)
        assert self.ask()['tier'] == 'paid' and len(fake_urlopen.calls) == 1

    def test_pro_uses_only_the_paid_key(self, fake_urlopen):
        fake_urlopen.reply(GEMINI_OK)
        assert self.ask('gemini-3.1-pro-preview')['tier'] == 'paid' and self.sent_with(fake_urlopen) == ['AQ.']

    def test_busy_on_both_keys_is_retryable_and_leaks_no_key(self, fake_urlopen):
        fake_urlopen.reply(*[err(503, 'high demand')] * 5)
        with pytest.raises(L.LLMBusy) as e: self.ask()
        assert 'AIza' not in str(e.value) and 'AQ.' not in str(e.value)


class TestVertex:
    def test_a_gemini_style_key_is_not_a_vertex_key(self):
        with pytest.raises(L.LLMError): L.set_key('AIza' + 'z' * 35, 'vertex')

    def test_key_and_endpoint(self, fake_urlopen):
        L.set_key('AQ.' + 'Z' * 40, 'vertex'); assert L.key_configured('vertex') and 'VERTEX_API_KEY=AQ.' in open(L.VARS_FILE).read()
        fake_urlopen.reply(dict(candidates=[dict(content=dict(parts=[dict(text='{}')]))])); L.chat(USER, model='gemini-2.5-pro', provider='vertex')
        c = fake_urlopen.calls[0]
        assert c['url'].startswith('https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-pro:generateContent') and 'key=' not in c['url'] and c['headers']['x-goog-api-key'].startswith('AQ.')


def test_script_writer_uses_the_remote_provider_and_enforces_budgets(claude_key, fake_urlopen):
    facts = [dict(index=0, film_start_s=0.0, seconds=4.0, clip='A', track='x'), dict(index=1, film_start_s=4.0, seconds=6.0, clip='B', wearer_says=['hello there'])]
    long = 'This is a very long line that runs well past the budget for such a short segment of film. And another sentence.'
    reply = lambda lines: dict(content=[dict(type='text', text=json.dumps({'title': 'T', 'lines': lines}))], usage={})
    fake_urlopen.reply(reply([{'seg': 0, 'text': long}, {'seg': 1, 'text': 'talking over you'}]), reply([{'seg': 0, 'text': 'A short line.'}, {'seg': 1, 'text': ''}]))
    d = S.write_script(facts, 'notes', 10.0, provider='anthropic', model='claude-sonnet-5-5')
    assert len(fake_urlopen.calls) == 2 and 'Fix these problems' in fake_urlopen.calls[1]['body']['messages'][-1]['content'] and d['provider'] == 'anthropic'       # one retry with the exact violations
    l0, l1 = d['lines']; assert l0['text'] == 'A short line.' and l1['text'] == '' and l0['words'] <= l0['budget_words']
