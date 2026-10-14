"""The project assistant (server/agent.py): the tool loop with a scripted model (no network), the pictures it shows and the optional vision description, what is sent to the model, the clip-frame route and the two chat routes."""
import io, json, os, urllib.error

import pytest

pytest.importorskip('mcp')
from strata360.server import agent as AG
from projects import CLIP_ID

NAMES = {'project', 'clips', 'clip', 'transcript', 'plan', 'script', 'film', 'picture'}
CLIPS = {'/api/clips': dict(clips=[dict(id=f'c{i}', duration_s=10.0 + i, start_utc=f'2026-01-01T0{i}:00:00Z') for i in range(3)])}


class FakeBackend:
    def __init__(self, **routes): self.routes, self.calls = routes, []
    async def get(self, path, **params): self.calls.append((path, params)); return self.routes[path]
    async def get_bytes(self, path, **params): self.calls.append((path, params)); return b'\xff\xd8JPEG'


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
        m = Script(dict(content='', tool_calls=[tool_call('clips', dict(sort='longest', limit=2))]), dict(content='There are 3 clips.')); out = self.run(m)
        assert out['answer'] == 'There are 3 clips.' and [s['tool'] for s in out['steps']] == ['clips'] and out['steps'][0]['args'] == dict(sort='longest', limit=2) and out['images'] == []
        tool_msg = m.sent[1]['messages'][-1]; assert tool_msg['role'] == 'tool' and tool_msg['tool_call_id'] == 'c1' and '"total": 3' in tool_msg['content']
        assert m.sent[0]['key'] == 'KEY' and m.sent[0]['messages'][0]['role'] == 'system' and '/proj' in m.sent[0]['messages'][0]['content']

    def test_the_tools_offered_are_the_read_only_set(self):
        m = Script(dict(content='ok')); self.run(m); names = {t['function']['name'] for t in m.sent[0]['tools']}
        assert names == NAMES and all(t['type'] == 'function' and t['function']['parameters']['type'] == 'object' for t in m.sent[0]['tools'])

    def test_the_folder_is_always_the_projects_whatever_the_model_asks(self):
        b = FakeBackend(**CLIPS); self.run(Script(dict(content='', tool_calls=[tool_call('clips', dict(folder='C:/elsewhere'))]), dict(content='x')), b)
        assert b.calls == [('/api/clips', dict(folder='/proj'))]

    def test_a_failing_tool_is_told_to_the_model_not_raised(self):
        m = Script(dict(content='', tool_calls=[tool_call('clip', dict(clip='nope'))]), dict(content='It does not exist.')); b = FakeBackend()
        b.get = lambda *a, **k: (_ for _ in ()).throw(AG_ToolError('no such clip'))
        out = self.run(m, b); assert out['answer'] == 'It does not exist.' and out['steps'][0]['error'] and m.sent[1]['messages'][-1]['content'].startswith('error:')

    def test_unreadable_arguments_become_no_arguments(self):
        m = Script(dict(content='', tool_calls=[dict(id='c', function=dict(name='clips', arguments='{broken'))]), dict(content='done'))
        assert self.run(m)['answer'] == 'done'

    def test_a_long_tool_answer_is_cut(self):
        class Big(FakeBackend):
            async def get(self, path, **params): return dict(lines=['x' * 300] * 200)
        m = Script(dict(content='', tool_calls=[tool_call('project', dict(view='log'))]), dict(content='ok'))
        self.run(m, Big()); assert len(m.sent[1]['messages'][-1]['content']) <= AG.RESULT_CHARS + 200

    def test_endless_tool_calls_stop_at_the_step_limit_with_an_answer(self):
        m = Script(*[dict(content='', tool_calls=[tool_call('clips', {})]) for _ in range(3)], dict(content='Partial answer.'))
        out = self.run(m, max_steps=3); assert out['answer'] == 'Partial answer.' and len(out['steps']) == 3 and m.sent[-1]['tools'] == []

    def test_an_empty_reply_still_answers(self): assert self.run(Script(dict(content=None)))['answer']


from strata360.server.mcp_tools import ToolError as AG_ToolError  # noqa: E402


class TestPictures:
    def frame(self, **a): return tool_call('picture', dict(of='frame', clip='c1', t=4.5, **a))

    def test_a_picture_tool_adds_the_picture_to_the_answer_for_the_user(self):
        m = Script(dict(content='', tool_calls=[self.frame(yaw=180)]), dict(content='Here it is.')); out = AG.run(FakeBackend(), '/proj', [dict(role='user', content='Show me c1 at 4.5 s')], 'K', chat=m)
        assert out['images'] == [dict(url='/api/clip/frame?folder=%2Fproj&clip=c1&t=4.5&yaw=180', caption='c1 at 4.5 s')]
        told = m.sent[1]['messages'][-1]['content']; assert 'shown to the user' in told and 'cannot see it' in told and 'JPEG' not in told        # the model is only told that it was shown

    def test_the_same_picture_is_shown_once_and_there_is_a_limit(self):
        calls = [tool_call('picture', dict(of='frame', clip='c1', t=1.0), id='a'), tool_call('picture', dict(of='frame', clip='c1', t=1.0), id='b')] + [tool_call('picture', dict(of='frame', clip='c1', t=float(i)), id=f'x{i}') for i in range(2, 12)]
        out = AG.run(FakeBackend(), '/proj', [dict(role='user', content='q')], 'K', chat=Script(dict(content='', tool_calls=calls), dict(content='ok'))); assert len(out['images']) == AG.MAX_IMAGES and len({i['url'] for i in out['images']}) == AG.MAX_IMAGES

    def test_the_urls_of_each_kind(self):
        assert AG.image_of('picture', dict(of='thumbnail', clip='c', overlay=True), '/p')['url'] == '/api/thumb?folder=%2Fp&clip=c&overlay=true'
        assert AG.image_of('picture', dict(of='still', name='s.png'), '/p') == dict(url='/api/film/still/thumb?folder=%2Fp&name=s.png&w=960', caption='film still s.png')
        for bad in (('clips', dict(of='frame')), ('picture', dict(of='frame', clip='c')), ('picture', dict(of='still')), ('picture', dict(of='nope'))): assert AG.image_of(*bad, '/p') is None

    def test_vision_off_sends_nothing_to_a_vision_model(self):
        seen = []; m = Script(dict(content='', tool_calls=[self.frame()]), dict(content='ok'))
        AG.run(FakeBackend(), '/proj', [dict(role='user', content='q')], 'K', chat=m, see=lambda jpeg, q: seen.append(jpeg)); assert seen == []

    def test_vision_on_puts_a_description_of_the_picture_in_the_tool_result(self):
        seen = []
        def see(jpeg, question): seen.append((jpeg, question)); return 'A runner on a road at dusk.'
        m = Script(dict(content='', tool_calls=[self.frame()]), dict(content='The runner is on a road.')); out = AG.run(FakeBackend(), '/proj', [dict(role='user', content='What is happening at 4.5 s in c1?')], 'K', chat=m, vision=True, see=see)
        assert seen == [(b'\xff\xd8JPEG', 'What is happening at 4.5 s in c1?')] and 'A runner on a road at dusk.' in m.sent[1]['messages'][-1]['content'] and out['vision'] is True and len(out['images']) == 1

    def test_the_default_vision_call_is_made_with_the_vision_model_and_the_picture(self, monkeypatch):
        sent = []
        def fake(messages, tools, model, key, timeout=0, url=None): sent.append((messages, tools, model, key)); return dict(content=' A road. ')
        monkeypatch.setattr(AG, 'chat_nvidia', fake)
        assert AG.describe_nvidia(b'\xff\xd8JPEG', 'where?', 'v/model', 'K') == 'A road.'
        msgs, tools, model, key = sent[0]; parts = msgs[0]['content']; assert tools is None and model == 'v/model' and key == 'K' and 'where?' in parts[0]['text'] and parts[1]['image_url']['url'].startswith('data:image/jpeg;base64,')


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
        assert AG.chat_nvidia([dict(role='user', content='q')], [], 'a/b', 'SECRET') == dict(content='hi') and seen['auth'] == 'Bearer SECRET' and seen['body']['model'] == 'a/b' and 'tools' not in seen['body']

    def test_model_names_are_checked(self):
        assert AG.valid_model('nvidia/nemotron-3-super-120b-a12b') and not any(AG.valid_model(m) for m in ('', 'x', '../etc/passwd', '../x', 'a b/c'))


class TestFrameRoute:
    @pytest.fixture
    def proxied(self, project):
        d = project.clip_dir(); open(os.path.join(d, 'proxy.mp4'), 'wb').write(b'x'); json.dump(dict(size=[8, 4], frames=[]), open(os.path.join(d, 'proxy.json'), 'w')); return project

    def get(self, client, project, **q): return client.get('/api/clip/frame', params=dict(folder=project.folder, clip=CLIP_ID, **q))

    def test_a_frame_is_cut_from_the_proxy_at_the_time_and_direction_asked(self, make_client, proxied, monkeypatch):
        from strata360.analysis import views as V
        seen = {}
        def fake(proxy, osv, t, yaw=0.0, pitch=0.0, hfov=100.0, w=960, h=540, **k): seen.update(t=t, yaw=yaw, pitch=pitch, hfov=hfov, w=w, h=h); return b'\xff\xd8frame'
        monkeypatch.setattr(V, 'render_thumb_proxy', fake); r = self.get(make_client(), proxied, t=3.5, yaw=90, fov=200, w=5000)
        assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg' and r.content == b'\xff\xd8frame' and seen == dict(t=3.5, yaw=90.0, pitch=0.0, hfov=120.0, w=1920, h=1080)       # the field of view and the width are clamped

    def test_a_time_outside_the_clip_is_refused(self, make_client, proxied):
        r = self.get(make_client(), proxied, t=99); assert r.status_code == 400 and '10.0 s long' in r.json()['detail']
        assert self.get(make_client(), proxied, t=-1).status_code == 400

    def test_without_a_proxy_it_says_which_stage_makes_one(self, make_client, project):
        r = self.get(make_client(), project, t=1); assert r.status_code == 404 and 'proxy' in r.json()['detail']

    def test_an_unknown_clip_and_a_foreign_folder(self, make_client, project, tmp_path):
        assert make_client().get('/api/clip/frame', params=dict(folder=project.folder, clip='nope', t=1)).status_code == 404
        assert make_client().get('/api/clip/frame', params=dict(folder=str(tmp_path.parent), clip=CLIP_ID, t=1)).status_code == 403

    def test_the_token_is_needed(self, make_client, proxied): assert self.get(make_client(token='s3cret'), proxied, t=1).status_code == 401


class TestRoutes:
    def test_status_never_shows_the_key_and_names_the_vision_model(self, make_client, monkeypatch):
        monkeypatch.setenv('NVIDIA_API_KEY', 'nvapi-SECRET'); r = make_client().get('/api/agent')
        assert r.json()['configured'] is True and r.json()['read_only'] is True and r.json()['vision_model'] == AG.VISION_MODEL and 'SECRET' not in r.text

    def test_no_key_means_a_clear_refusal(self, make_client, project, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: None)
        r = make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='hi')])); assert r.status_code == 409 and 'NVIDIA_API_KEY' in r.json()['detail']

    def test_a_folder_outside_the_roots_is_refused(self, make_client, tmp_path, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k')
        assert make_client().post('/api/agent/chat', json=dict(folder=str(tmp_path.parent), messages=[dict(role='user', content='hi')])).status_code == 403

    def test_the_chat_answers_from_the_projects_own_clips(self, make_client, project, monkeypatch):
        m = Script(dict(content='', tool_calls=[tool_call('clips', {})]), dict(content='One clip.')); monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'chat_nvidia', m)
        r = make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='How many clips?')]))
        assert r.status_code == 200 and r.json()['answer'] == 'One clip.' and r.json()['vision'] is False and CLIP_ID in m.sent[1]['messages'][-1]['content']

    def test_vision_is_only_on_when_asked_for_with_the_boolean_true(self, make_client, project, monkeypatch):
        seen = []
        def fake_run(backend, folder, history, key, model, **kw): seen.append(kw); return dict(answer='a', steps=[], images=[], model=model, vision=kw.get('vision'), seconds=0)
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'run', fake_run); c = make_client(); q = [dict(role='user', content='q')]
        for v in (True, 'yes', 1, None): c.post('/api/agent/chat', json=dict(folder=project.folder, messages=q, **({} if v is None else {'vision': v})))
        assert [k['vision'] for k in seen] == [True, False, False, False] and seen[0]['vision_model'] == AG.VISION_MODEL
        assert c.post('/api/agent/chat', json=dict(folder=project.folder, messages=q, vision=True, vision_model='../x')).status_code == 400

    def test_a_bad_model_name_and_a_bad_conversation_are_400(self, make_client, project, monkeypatch):
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); c = make_client()
        assert c.post('/api/agent/chat', json=dict(folder=project.folder, model='../x', messages=[dict(role='user', content='q')])).status_code == 400
        assert c.post('/api/agent/chat', json=dict(folder=project.folder, messages=[])).status_code == 400

    def test_a_service_outage_is_a_503(self, make_client, project, monkeypatch):
        def down(*a, **k): e = AG.AgentError('down'); e.retryable = True; raise e
        monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'chat_nvidia', down)
        assert make_client().post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='q')])).status_code == 503
