"""The project assistant (server/agent.py): the tool loop with a scripted model (no network), what is sent to the model, and the two routes."""
import io, json, urllib.error

import pytest

pytest.importorskip('mcp')
from strata360.server import agent as AG
from projects import CLIP_ID

NAMES = {'projects', 'project_overview', 'list_clips', 'get_clip', 'search_transcript', 'transcript_review', 'edit_plan', 'get_script', 'get_notes', 'track_summary', 'music_state', 'film_stills', 'final_render_status', 'recent_log', 'clip_thumbnail', 'film_still_image'}
CLIPS = {'/api/clips': dict(clips=[dict(id=f'c{i}', duration_s=10.0) for i in range(3)])}


class FakeBackend:
    def __init__(self, **routes): self.routes, self.calls = routes, []
    async def get(self, path, **params): self.calls.append((path, params)); return self.routes[path]
    async def get_bytes(self, path, **params): return b'\xff\xd8'


def tool_call(name, args, id='c1'): return dict(id=id, type='function', function=dict(name=name, arguments=json.dumps(args)))


class Script:
    """A model that answers with the given replies in turn and remembers what it was sent."""
    def __init__(self, *replies): self.replies, self.sent = list(replies), []
    def __call__(self, messages, tools, model, key): self.sent.append(dict(messages=[dict(m) for m in messages], tools=tools, model=model, key=key)); return self.replies.pop(0)


class TestHistory:
    def test_only_user_and_assistant_text_survives_and_it_ends_with_a_question(self):
        h = [dict(role='system', content='x'), dict(role='assistant', content='old'), dict(role='user', content=' Hi '), dict(role='tool', content='t'), dict(role='assistant', content='a'), dict(role='user', content='Q?'), dict(role='user', content='  ')]
        assert AG.clean_history(h) == [dict(role='user', content='Hi'), dict(role='assistant', content='a'), dict(role='user', content='Q?')]

    def test_only_the_recent_turns_are_kept(self):
        h = [dict(role='user' if i % 2 == 0 else 'assistant', content=str(i)) for i in range(41)]
        out = AG.clean_history(h); assert len(out) <= AG.HISTORY_TURNS and out[0]['role'] == 'user' and out[-1]['content'] == '40'

    def test_a_conversation_not_ending_in_a_question_is_refused(self):
        for h in ([], [dict(role='assistant', content='hi')], [dict(role='user', content='q'), dict(role='assistant', content='a')]):
            with pytest.raises(AG.AgentError): AG.clean_history(h)


class TestLoop:
    def run(self, model, backend=None, **kw): return AG.run(backend or FakeBackend(**CLIPS), '/proj', [dict(role='user', content='How many clips?')], 'KEY', chat=model, **kw)

    def test_the_model_calls_a_tool_and_then_answers(self):
        m = Script(dict(content='', tool_calls=[tool_call('list_clips', dict(limit=2))]), dict(content='There are 3 clips.')); out = self.run(m)
        assert out['answer'] == 'There are 3 clips.' and [s['tool'] for s in out['steps']] == ['list_clips'] and out['steps'][0]['args'] == dict(limit=2)
        tool_msg = m.sent[1]['messages'][-1]; assert tool_msg['role'] == 'tool' and tool_msg['tool_call_id'] == 'c1' and '"total": 3' in tool_msg['content']
        assert m.sent[0]['key'] == 'KEY' and m.sent[0]['messages'][0]['role'] == 'system' and '/proj' in m.sent[0]['messages'][0]['content']

    def test_the_tools_offered_are_the_read_only_set(self):
        m = Script(dict(content='ok')); self.run(m); names = {t['function']['name'] for t in m.sent[0]['tools']}
        assert names == NAMES and all(t['type'] == 'function' and t['function']['parameters']['type'] == 'object' for t in m.sent[0]['tools'])

    def test_the_folder_is_always_the_projects_whatever_the_model_asks(self):
        b = FakeBackend(**CLIPS); self.run(Script(dict(content='', tool_calls=[tool_call('list_clips', dict(folder='C:/elsewhere'))]), dict(content='x')), b)
        assert b.calls == [('/api/clips', dict(folder='/proj'))]

    def test_a_failing_tool_is_told_to_the_model_not_raised(self):
        m = Script(dict(content='', tool_calls=[tool_call('get_clip', dict(clip='nope'))]), dict(content='It does not exist.'))
        out = self.run(m, FakeBackend()); assert out['answer'] == 'It does not exist.' and out['steps'][0]['error'] and m.sent[1]['messages'][-1]['content'].startswith('error:')

    def test_unreadable_arguments_become_no_arguments(self):
        m = Script(dict(content='', tool_calls=[dict(id='c', function=dict(name='list_clips', arguments='{broken'))]), dict(content='done'))
        assert self.run(m)['answer'] == 'done'

    def test_a_long_tool_answer_is_cut(self):
        b = FakeBackend(**{'/api/clips': dict(clips=[dict(id='x' * 300 + str(i), a='y' * 300) for i in range(25)])}); m = Script(dict(content='', tool_calls=[tool_call('list_clips', dict(limit=25))]), dict(content='ok'))
        self.run(m, b); assert len(m.sent[1]['messages'][-1]['content']) <= AG.RESULT_CHARS + 200

    def test_a_picture_is_never_sent(self):
        m = Script(dict(content='', tool_calls=[tool_call('clip_thumbnail', dict(clip='c0'))]), dict(content='ok')); self.run(m)
        assert 'does not see pictures' in m.sent[1]['messages'][-1]['content']

    def test_endless_tool_calls_stop_at_the_step_limit_with_an_answer(self):
        m = Script(*[dict(content='', tool_calls=[tool_call('list_clips', {})]) for _ in range(3)], dict(content='Partial answer.'))
        out = self.run(m, max_steps=3); assert out['answer'] == 'Partial answer.' and len(out['steps']) == 3 and m.sent[-1]['tools'] == []

    def test_an_empty_reply_still_answers(self): assert self.run(Script(dict(content=None)))['answer']


class TestHttp:
    def test_http_errors_are_agent_errors_and_say_whether_to_retry(self, monkeypatch):
        def boom(code):
            def f(req, timeout=None): raise urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(b'no'))
            return f
        for code, retry in ((401, False), (429, True), (503, True)):
            monkeypatch.setattr(AG.urllib.request, 'urlopen', boom(code))
            with pytest.raises(AG.AgentError) as e: AG.chat_nvidia([], [], 'm', 'k')
            assert e.value.retryable is retry and str(code) in str(e.value)

    def test_the_reply_message_is_returned_and_the_key_is_a_bearer_header(self, monkeypatch):
        seen = {}
        def fake(req, timeout=None): seen['auth'] = req.headers['Authorization']; seen['body'] = json.loads(req.data); return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content='hi'))])).encode())
        monkeypatch.setattr(AG.urllib.request, 'urlopen', fake)
        assert AG.chat_nvidia([dict(role='user', content='q')], [], 'a/b', 'SECRET') == dict(content='hi') and seen['auth'] == 'Bearer SECRET' and seen['body']['model'] == 'a/b'

    def test_model_names_are_checked(self):
        assert AG.valid_model('nvidia/nemotron-3-super-120b-a12b') and not any(AG.valid_model(m) for m in ('', 'x', '../etc/passwd', 'a b/c'))


class TestRoutes:
    def test_status_never_shows_the_key(self, make_client, monkeypatch):
        monkeypatch.setenv('NVIDIA_API_KEY', 'nvapi-SECRET'); r = make_client().get('/api/agent')
        assert r.json()['configured'] is True and r.json()['read_only'] is True and 'SECRET' not in r.text

    def test_no_key_means_a_clear_refusal(self, make_client, project, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: None)
        r = make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='hi')])); assert r.status_code == 409 and 'NVIDIA_API_KEY' in r.json()['detail']

    def test_a_folder_outside_the_roots_is_refused(self, make_client, tmp_path, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k')
        assert make_client().post('/api/agent/chat', json=dict(folder=str(tmp_path.parent), messages=[dict(role='user', content='hi')])).status_code == 403

    def test_the_chat_answers_from_the_projects_own_clips(self, make_client, project, monkeypatch):
        m = Script(dict(content='', tool_calls=[tool_call('list_clips', {})]), dict(content='One clip.')); monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'chat_nvidia', m)
        r = make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='How many clips?')]))
        assert r.status_code == 200 and r.json()['answer'] == 'One clip.' and CLIP_ID in m.sent[1]['messages'][-1]['content']

    def test_a_bad_model_name_and_a_bad_conversation_are_400(self, make_client, project, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); c = make_client()
        assert c.post('/api/agent/chat', json=dict(folder=project.folder, model='../x', messages=[dict(role='user', content='q')])).status_code == 400
        assert c.post('/api/agent/chat', json=dict(folder=project.folder, messages=[])).status_code == 400

    def test_a_service_outage_is_a_503(self, make_client, project, monkeypatch):
        def down(*a, **k): e = AG.AgentError('down'); e.retryable = True; raise e
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'chat_nvidia', down)
        assert make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='q')])).status_code == 503
