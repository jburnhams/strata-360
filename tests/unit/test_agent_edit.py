"""The edit tier of the project assistant (server/agent_edit.py): argument checks, the approval gate (the model cannot grant it), backups before and after changes, the journal, the `edit` tool only in write mode, and real changes through the app."""
import asyncio, json, os, time

import pytest

pytest.importorskip('mcp')
from strata360.server import agent as AG, agent_edit as AE, mcp_tools as MT
from projects import CLIP_ID


def run(coro): return asyncio.run(coro)


class Post:
    """A write backend's post: records what it was sent and answers {}, or raises."""
    def __init__(self, fail=None): self.calls, self.fail = [], fail
    async def __call__(self, path, body):
        self.calls.append((path, body))
        if self.fail: raise MT.ToolError(self.fail)
        return {'ok': True}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    AE.PENDING.clear(); AE._last_write.clear(); yield; AE.PENDING.clear(); AE._last_write.clear()


@pytest.fixture
def backups(monkeypatch):
    """The backups the edit tier asks for: [(force)] instead of real archives."""
    calls = []; monkeypatch.setattr(AE, '_backup', lambda folder, force: calls.append(force) or f'meta-{len(calls)}.tar.gz'); return calls


class TestCheck:
    def test_unknown_actions_and_arguments_say_what_is_expected(self):
        with pytest.raises(MT.ToolError, match='unknown action') as e: AE.check('plan.fly', {})
        assert 'plan.lock' in str(e.value)
        with pytest.raises(MT.ToolError, match="unknown argument 'speed'.*wid"): AE.check('plan.lock', dict(wid='s1', speed=3))

    def test_required_arguments_and_types(self):
        with pytest.raises(MT.ToolError, match='wid is required'): AE.check('plan.lock', {})
        with pytest.raises(MT.ToolError, match='locked has the wrong type'): AE.check('plan.lock', dict(wid='s1', locked='yes'))
        with pytest.raises(MT.ToolError, match='seg has the wrong type'): AE.check('transcript.reviewed', dict(clip='c', seg=True))      # a bool is not a number

    def test_the_folder_is_never_taken_from_the_arguments(self): assert AE.check('plan.lock', dict(wid='s1', folder='C:/elsewhere')) == dict(wid='s1')

    def test_the_model_cannot_pass_an_approval(self):
        with pytest.raises(MT.ToolError, match="unknown argument 'approved'"): AE.check('final.render', dict(approved=True))

    def test_the_override_actions_become_the_one_route_with_their_operation(self):
        assert AE.body_of('plan.lock', dict(wid='s1')) == dict(wid='s1', locked=True, action='lock') and AE.body_of('plan.technique', dict(wid='s1')) == dict(wid='s1', technique=None, action='technique')
        assert AE.body_of('plan.ban', dict(kind='techniques', key='x')) == dict(kind='techniques', key='x', action='ban') and AE.body_of('plan.reset', {}) == dict(action='reset') and AE.body_of('plan.propose', dict(length_s=60)) == dict(length_s=60)

    def test_what_is_offered(self):
        assert AE.GATED == {'plan.reset', 'script.generate', 'transcript.check', 'analysis.redo', 'final.render'}
        text = AE.usage(); assert 'plan.lock(wid, locked?)' in text and 'final.render(size?, fps?, bitrate?) [needs approval]' in text and 'film.preview() [background job]' in text

    def test_nothing_that_deletes_uploads_or_touches_the_clock_the_face_or_keys_is_offered(self):
        for name, (route, *_rest) in AE.ACTIONS.items():
            assert not any(w in route for w in ('/music', '/tracks', '/photos', '/record', '/clock', '/who', '/llm', '/lyrics', '/pointcams', '/streetview', '/gaps')), name
            assert not any(w in name for w in ('delete', 'remove', 'upload', 'clock', 'who', 'key'))


class TestExecute:
    def go(self, post, action, args, folder='/p', **kw): return run(AE.execute(post, folder, action, args, **kw))

    def test_an_edit_is_posted_with_the_folder_and_reported(self, backups, tmp_path, monkeypatch):
        monkeypatch.setattr(AE, 'journal', lambda *a: None); post = Post(); out = self.go(post, 'plan.lock', dict(wid='s1'))
        assert post.calls == [('/api/edit/override', dict(wid='s1', locked=True, action='lock', folder='/p'))] and out['ok'] is True and out['did'] == 'lock segment s1' and out['job'] is None

    def test_a_background_job_says_so(self, backups, monkeypatch):
        monkeypatch.setattr(AE, 'journal', lambda *a: None); assert self.go(Post(), 'film.preview', {})['job'] is True

    def test_the_first_change_of_a_session_forces_a_backup_of_the_state_before_it_and_one_follows_each_change(self, backups, monkeypatch):
        monkeypatch.setattr(AE, 'journal', lambda *a: None); post = Post()
        self.go(post, 'plan.lock', dict(wid='s1')); self.go(post, 'plan.lock', dict(wid='s2'))
        assert backups == [True, False, False, False]                              # before (forced), after, then before and after as plain throttled backups

    def test_a_long_pause_starts_a_new_session_with_a_forced_backup(self, backups, monkeypatch):
        monkeypatch.setattr(AE, 'journal', lambda *a: None); post = Post(); self.go(post, 'plan.lock', dict(wid='s1')); AE._last_write['/p'] -= AE.SESSION_S + 1; self.go(post, 'plan.lock', dict(wid='s2'))
        assert backups == [True, False, True, False]

    def test_each_folder_has_its_own_session(self, backups, monkeypatch):
        monkeypatch.setattr(AE, 'journal', lambda *a: None); post = Post(); self.go(post, 'plan.lock', dict(wid='s1'), '/a'); self.go(post, 'plan.lock', dict(wid='s1'), '/b'); assert backups[0] is True and backups[2] is True

    def test_a_failed_edit_raises_and_is_journalled(self, backups, monkeypatch):
        seen = []; monkeypatch.setattr(AE, 'journal', lambda folder, e: seen.append(e))
        with pytest.raises(MT.ToolError, match='plan.lock failed: /api/edit/override: 400 no such segment'): self.go(Post(fail='/api/edit/override: 400 no such segment'), 'plan.lock', dict(wid='nope'))
        assert seen[-1]['status'] == 'failed' and 'no such segment' in seen[-1]['error'] and backups == [True]           # no backup after a failure

    def test_a_bad_request_does_nothing(self, backups, monkeypatch):
        seen = []; monkeypatch.setattr(AE, 'journal', lambda folder, e: seen.append(e)); post = Post()
        with pytest.raises(MT.ToolError): self.go(post, 'plan.lock', {})
        assert post.calls == [] and backups == [] and seen == []


class TestApproval:
    def go(self, post, action, args, folder='/p', **kw): return run(AE.execute(post, folder, action, args, **kw))

    @pytest.fixture(autouse=True)
    def quiet(self, monkeypatch, backups): monkeypatch.setattr(AE, 'journal', lambda *a: None)

    def test_a_gated_action_waits_and_nothing_is_posted(self):
        post = Post(); out = self.go(post, 'final.render', dict(size='3840x2160'))
        assert post.calls == [] and out['needs_approval'] and out['why'] and 'cannot approve' in out['note'] and AE.pending_for('/p')[0]['action'] == 'final.render' and AE.pending_for('/p')[0]['id'] == out['needs_approval']

    def test_asking_again_for_the_same_thing_gives_the_same_approval(self):
        a = self.go(Post(), 'analysis.redo', dict(items=[dict(clip='c', stage='scenes')])); b = self.go(Post(), 'analysis.redo', dict(items=[dict(clip='c', stage='scenes')]))
        assert b['needs_approval'] == a['needs_approval'] and len(AE.PENDING) == 1

    def test_approving_runs_it_once(self):
        post = Post(); pid = self.go(post, 'analysis.redo', dict(items=[dict(clip='c', stage='scenes')]))['needs_approval']
        out = run(AE.approve(post, '/p', pid)); assert out['ok'] is True and post.calls == [('/api/clear', dict(items=[dict(clip='c', stage='scenes')], folder='/p'))] and AE.pending_for('/p') == []
        with pytest.raises(MT.ToolError, match='gone'): run(AE.approve(post, '/p', pid))

    def test_an_approval_belongs_to_its_project(self):
        pid = self.go(Post(), 'final.render', {})['needs_approval']
        with pytest.raises(MT.ToolError, match='gone'): run(AE.approve(Post(), '/other', pid))
        assert AE.pending_for('/other') == [] and len(AE.pending_for('/p')) == 1

    def test_denying_drops_it(self):
        pid = self.go(Post(), 'final.render', {})['needs_approval']; assert AE.deny('/p', pid) == dict(denied=True) and AE.pending_for('/p') == []
        with pytest.raises(MT.ToolError): AE.deny('/p', pid)

    def test_an_old_approval_expires(self):
        pid = self.go(Post(), 'final.render', {})['needs_approval']; AE.PENDING[pid]['created'] -= AE.PENDING_S + 1
        assert AE.pending_for('/p') == []
        with pytest.raises(MT.ToolError, match='gone'): run(AE.approve(Post(), '/p', pid))

    def test_too_many_waiting_is_refused(self):
        for i in range(AE.MAX_PENDING): self.go(Post(), 'analysis.redo', dict(items=[dict(clip=f'c{i}', stage='x')]))
        with pytest.raises(MT.ToolError, match='too many'): self.go(Post(), 'analysis.redo', dict(items=[dict(clip='z', stage='x')]))

    def test_the_edit_tool_cannot_run_a_gated_action_by_any_argument(self):
        post = Post(); srv = MT.build_server(type('B', (), {'post': post, 'get': None})(), '/p', write=True)
        r = run(srv.call_tool('edit', dict(action='final.render', args=dict(size='3840x2160')))); assert post.calls == [] and 'needs_approval' in r.content[0].text
        with pytest.raises(MT.ToolError): run(srv.call_tool('edit', dict(action='final.render', args=dict(approved=True))))


class TestTool:
    def test_the_edit_tool_exists_only_in_write_mode(self):
        class B:
            async def get(self, *a, **k): return {}
        assert 'edit' not in MT.tool_names(MT.build_server(B(), '/p')) and 'edit' in MT.tool_names(MT.build_server(type('W', (B,), {'post': Post()})(), '/p', write=True))

    def test_the_description_lists_the_actions_and_the_rule_about_approval(self):
        srv = MT.build_server(type('W', (), {'post': Post(), 'get': None})(), '/p', write=True); t = next(t for t in run(srv.list_tools()) if t.name == 'edit')
        assert 'plan.lock(wid, locked?)' in t.description and 'needs approval' in t.description and 'USER' in t.description and len(t.description) < 2500 and t.annotations.read_only_hint is False

    def test_the_read_only_backend_cannot_post(self): assert not hasattr(MT.AsgiBackend(None), 'post') and hasattr(MT.WriteAsgiBackend(None), 'post')


class TestAgainstTheApp:
    def test_an_edit_changes_the_project_and_leaves_a_backup_and_a_journal_entry(self, make_client, project):
        client = make_client(); post = MT.WriteAsgiBackend(client.app).post
        out = run(AE.execute(post, project.folder, 'notes.set', dict(text='Written by the assistant')))
        assert out['ok'] is True and client.get('/api/notes', params=dict(folder=project.folder)).json()['folder'] == 'Written by the assistant'
        entries = AE.read_journal(project.folder); assert entries[-1]['action'] == 'notes.set' and entries[-1]['status'] == 'done' and entries[-1]['args'] == dict(text='Written by the assistant')
        from strata360.pipeline import backup as B
        assert B.list_backups(project.folder), 'a backup of the project was made'

    def test_a_clip_note_and_the_voice_over_text(self, make_client, project):
        client = make_client(); post = MT.WriteAsgiBackend(client.app).post
        run(AE.execute(post, project.folder, 'notes.set', dict(text='clip note', clip=CLIP_ID))); run(AE.execute(post, project.folder, 'notes.set', dict(text='say this', kind='vo')))
        n = client.get('/api/notes', params=dict(folder=project.folder)).json(); assert n['clips'][CLIP_ID] == 'clip note' and n['vo_must']['folder'] == 'say this'

    def test_a_refusal_by_the_server_is_a_clear_error_and_is_journalled(self, make_client, project):
        post = MT.WriteAsgiBackend(make_client().app).post
        with pytest.raises(MT.ToolError, match='plan.lock failed'): run(AE.execute(post, project.folder, 'plan.lock', dict(wid='nope')))
        assert AE.read_journal(project.folder)[-1]['status'] == 'failed'

    def test_a_folder_outside_the_roots_is_refused_by_the_server(self, make_client, tmp_path):
        post = MT.WriteAsgiBackend(make_client().app).post
        with pytest.raises(MT.ToolError, match='403'): run(AE.execute(post, str(tmp_path.parent), 'notes.set', dict(text='x')))


class TestRoutes:
    def chat(self, client, project, *replies, write=True, monkeypatch=None):
        from test_agent import Script
        m = Script(*replies); monkeypatch.setattr(AG, 'key_for_nvidia', lambda: 'k'); monkeypatch.setattr(AG, 'chat_nvidia', m)
        return m, client.post('/api/agent/chat', json=dict(folder=project.folder, messages=[dict(role='user', content='go')], write=write))

    def tc(self, action, args): return dict(content='', tool_calls=[dict(id='c', type='function', function=dict(name='edit', arguments=json.dumps(dict(action=action, args=args))))])

    def test_chat_without_the_edit_switch_has_no_edit_tool_and_cannot_change_anything(self, make_client, project, monkeypatch):
        c = make_client(); m, r = self.chat(c, project, dict(content='ok'), write=False, monkeypatch=monkeypatch)
        assert r.status_code == 200 and r.json()['write'] is False and 'edit' not in {t['function']['name'] for t in m.sent[0]['tools']}

    def test_chat_with_the_switch_can_edit_and_says_so(self, make_client, project, monkeypatch):
        c = make_client(); m, r = self.chat(c, project, self.tc('notes.set', dict(text='from chat')), dict(content='Done.'), monkeypatch=monkeypatch)
        assert r.status_code == 200 and r.json()['write'] is True and 'edit' in {t['function']['name'] for t in m.sent[0]['tools']} and 'EDITING IS ON' in m.sent[0]['messages'][0]['content']
        assert c.get('/api/notes', params=dict(folder=project.folder)).json()['folder'] == 'from chat' and r.json()['steps'][0]['tool'] == 'edit'

    def test_a_gated_action_comes_back_as_pending_and_only_the_approve_route_runs_it(self, make_client, project, monkeypatch):
        c = make_client(); items = [dict(clip=CLIP_ID, stage='scenes')]
        m, r = self.chat(c, project, self.tc('analysis.redo', dict(items=items)), dict(content='Waiting for your approval.'), monkeypatch=monkeypatch)
        pend = r.json()['pending']; assert len(pend) == 1 and pend[0]['action'] == 'analysis.redo' and 'throws away' in pend[0]['why']
        assert c.get('/api/agent/pending', params=dict(folder=project.folder)).json()['pending'][0]['id'] == pend[0]['id']
        ok = c.post('/api/agent/approve', json=dict(folder=project.folder, id=pend[0]['id'])); assert ok.status_code == 200 and ok.json()['ok'] is True
        assert c.get('/api/agent/pending', params=dict(folder=project.folder)).json()['pending'] == []
        assert c.post('/api/agent/approve', json=dict(folder=project.folder, id=pend[0]['id'])).status_code == 404
        assert [e['status'] for e in AE.read_journal(project.folder) if e['action'] == 'analysis.redo'] == ['needs approval', 'done']

    def test_deny_and_the_journal(self, make_client, project, monkeypatch):
        c = make_client(); m, r = self.chat(c, project, self.tc('final.render', dict(size='1920x1080')), dict(content='ok'), monkeypatch=monkeypatch); pid = r.json()['pending'][0]['id']
        assert c.post('/api/agent/deny', json=dict(folder=project.folder, id=pid)).json() == dict(denied=True) and c.post('/api/agent/deny', json=dict(folder=project.folder, id=pid)).status_code == 404
        j = c.get('/api/agent/journal', params=dict(folder=project.folder)).json()['entries']; assert [e['status'] for e in j] == ['needs approval', 'denied']

    def test_the_new_routes_need_the_token_and_the_roots(self, make_client, project, tmp_path):
        c = make_client(token='s3cret'); h = {'Authorization': 'Bearer s3cret'}
        assert c.get('/api/agent/pending', params=dict(folder=project.folder)).status_code == 401 and c.post('/api/agent/approve', json=dict(folder=project.folder, id='x')).status_code == 401
        assert c.get('/api/agent/pending', params=dict(folder=str(tmp_path.parent)), headers=h).status_code == 403 and c.get('/api/agent/journal', params=dict(folder=project.folder), headers=h).json() == dict(entries=[])

    def test_the_model_cannot_reach_the_approve_route_through_a_tool(self):
        assert 'approve' not in AE.usage() and not any(r.startswith('/api/agent') for r, *_ in AE.ACTIONS.values())
