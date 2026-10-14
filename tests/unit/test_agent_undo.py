"""Batching of backups, one-click undo of the assistant's changes, and edits by outside agents (the MCP mount and the stdio backend) through the server (server/agent_edit.py, server/mcp_tools.py)."""
import asyncio, json, os

import pytest

pytest.importorskip('mcp')
from strata360.server import agent_edit as AE, mcp_tools as MT


def run(coro): return asyncio.run(coro)


class Post:
    async def __call__(self, path, body): return {'ok': True}


@pytest.fixture(autouse=True)
def clean():
    AE.PENDING.clear(); AE._last_write.clear(); yield; AE.PENDING.clear(); AE._last_write.clear()


class TestBatching:
    def test_backups_after_changes_batch_for_five_minutes(self): assert AE.BACKUP_S == 300.0

    def test_after_a_change_the_backup_is_throttled_by_that_interval(self, monkeypatch):
        seen = []
        import strata360.pipeline.backup as B
        monkeypatch.setattr(B, 'backup', lambda folder, force=False, interval=0.0, **k: seen.append((force, interval)) or None); monkeypatch.setattr(AE, 'journal', lambda *a: None)
        run(AE.execute(Post(), '/p', 'plan.lock', dict(wid='s1'))); run(AE.execute(Post(), '/p', 'plan.lock', dict(wid='s2')))
        assert seen == [(True, 0.0), (False, 300.0), (False, 300.0), (False, 300.0)]


class TestUndo:
    def edit(self, client, project, text, **kw):
        post = MT.WriteAsgiBackend(client.app).post; return run(AE.execute(post, project.folder, 'notes.set', dict(text=text, **kw)))

    def note(self, client, project): return client.get('/api/notes', params=dict(folder=project.folder)).json()['folder']

    def test_nothing_to_undo_at_first(self, make_client, project):
        assert AE.undo_state(project.folder) == dict(available=False, restore_point=None, since=None, changes=0, sessions=0)
        with pytest.raises(MT.ToolError, match='no assistant change'): AE.undo(project.folder)

    def test_undo_puts_the_project_back_to_before_the_session_and_saves_the_state_it_replaced(self, make_client, project):
        c = make_client(); project.write_json('notes.json', dict(folder='my own note', clips={}, updated={}))
        assert self.note(c, project) == 'my own note'
        self.edit(c, project, 'assistant 1'); self.edit(c, project, 'assistant 2'); assert self.note(c, project) == 'assistant 2'
        st = AE.undo_state(project.folder); assert st['available'] and st['changes'] == 2 and st['sessions'] == 1 and st['restore_point'].startswith('meta-')
        out = AE.undo(project.folder); assert out['undone'] == 2 and out['files'] >= 1 and out['checkpoint']
        assert self.note(c, project) == 'my own note' and not AE.undo_state(project.folder)['available']
        j = AE.read_journal(project.folder); assert j[-1]['action'] == 'agent.undo' and sum(e['status'] == 'done' for e in j) == 2           # the journal survived the restore
        from strata360.pipeline import backup as B
        assert out['checkpoint'] in [n for n, _, _ in B.list_backups(project.folder)]                                                         # the state just before the undo is a backup too

    def test_a_new_change_after_an_undo_starts_a_new_session(self, make_client, project):
        c = make_client(); self.edit(c, project, 'one'); AE.undo(project.folder); self.edit(c, project, 'two')
        st = AE.undo_state(project.folder); assert st['available'] and st['changes'] == 1 and st['sessions'] == 1
        AE.undo(project.folder); assert not AE.undo_state(project.folder)['available']

    def test_sessions_undo_one_at_a_time(self, make_client, project):
        c = make_client(); project.write_json('notes.json', dict(folder='orig', clips={}, updated={})); self.edit(c, project, 'first'); AE._last_write[project.folder] -= AE.SESSION_S + 1; self.edit(c, project, 'second')
        assert AE.undo_state(project.folder)['sessions'] == 2 and self.note(c, project) == 'second'
        AE.undo(project.folder); assert self.note(c, project) == 'first' and AE.undo_state(project.folder)['sessions'] == 1
        AE.undo(project.folder); assert self.note(c, project) == 'orig'

    def test_a_pruned_backup_is_a_clear_refusal(self, make_client, project):
        c = make_client(); self.edit(c, project, 'x'); from strata360.pipeline import backup as B
        os.remove(os.path.join(B.backup_dir(project.folder), AE.undo_state(project.folder)['restore_point']))
        with pytest.raises(MT.ToolError, match='is gone'): AE.undo(project.folder)

    def test_the_undo_route_and_the_journal_state(self, make_client, project):
        c = make_client(); self.edit(c, project, 'via route')
        j = c.get('/api/agent/journal', params=dict(folder=project.folder)).json(); assert j['undo']['available'] is True and j['undo']['changes'] == 1
        r = c.post('/api/agent/undo', json=dict(folder=project.folder)); assert r.status_code == 200 and r.json()['undone'] == 1
        assert c.post('/api/agent/undo', json=dict(folder=project.folder)).status_code == 409 and c.get('/api/agent/journal', params=dict(folder=project.folder)).json()['undo']['available'] is False

    def test_the_undo_route_needs_the_token_and_the_roots(self, make_client, project, tmp_path):
        c = make_client(token='s3cret'); assert c.post('/api/agent/undo', json=dict(folder=project.folder)).status_code == 401
        assert c.post('/api/agent/undo', json=dict(folder=str(tmp_path.parent)), headers={'Authorization': 'Bearer s3cret'}).status_code == 403


class ViaApp(MT.WriteHttpBackend):
    """The stdio shim's backend, talking to the app in-process instead of over a socket."""
    def __init__(self, app, token=None): super().__init__('http://strata360.local', token); self.app = app
    def _client(self):
        import httpx
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://strata360.local', headers={'Authorization': f'Bearer {self.token}'} if self.token else {}, timeout=60)


class TestOutsideAgents:
    """An outside agent (the MCP stdio shim) edits through the server, so approvals and the journal live in the server process."""
    def test_the_edit_route_runs_an_action_and_cannot_be_given_an_approval(self, make_client, project):
        c = make_client(); r = c.post('/api/agent/edit', json=dict(folder=project.folder, action='notes.set', args=dict(text='via the edit route'))); assert r.status_code == 200 and r.json()['ok'] is True
        assert c.get('/api/notes', params=dict(folder=project.folder)).json()['folder'] == 'via the edit route'
        assert c.post('/api/agent/edit', json=dict(folder=project.folder, action='final.render', args=dict(approved=True))).status_code == 400
        gated = c.post('/api/agent/edit', json=dict(folder=project.folder, action='final.render', args={})).json(); assert gated['needs_approval'] and c.get('/api/agent/pending', params=dict(folder=project.folder)).json()['pending'][0]['id'] == gated['needs_approval']
        assert c.post('/api/agent/edit', json=dict(folder=project.folder, action='nope', args={})).status_code == 400

    def test_the_edit_route_needs_the_token_and_the_roots(self, make_client, project, tmp_path):
        c = make_client(token='s3cret'); body = dict(folder=project.folder, action='notes.set', args=dict(text='x'))
        assert c.post('/api/agent/edit', json=body).status_code == 401 and c.post('/api/agent/edit', json=dict(body, folder=str(tmp_path.parent)), headers={'Authorization': 'Bearer s3cret'}).status_code == 403

    def test_the_stdio_backend_edits_through_the_server_and_a_gated_action_waits_there(self, make_client, project):
        c = make_client(); srv = MT.build_server(ViaApp(c.app), project.folder, write=True)
        r = run(srv.call_tool('edit', dict(action='notes.set', args=dict(text='from an outside agent')))); assert json.loads(r.content[0].text)['ok'] is True and c.get('/api/notes', params=dict(folder=project.folder)).json()['folder'] == 'from an outside agent'
        r = run(srv.call_tool('edit', dict(action='final.render', args={}))); assert 'needs_approval' in r.content[0].text and len(c.get('/api/agent/pending', params=dict(folder=project.folder)).json()['pending']) == 1
        with pytest.raises(MT.ToolError, match='400'): run(srv.call_tool('edit', dict(action='nope', args={})))

    def test_the_read_only_stdio_backend_has_no_edit(self): assert not hasattr(MT.HttpBackend('http://x'), 'edit') and hasattr(MT.WriteHttpBackend('http://x'), 'edit')

    def test_the_mcp_mount_offers_edit_by_default_and_can_be_read_only(self, make_client, monkeypatch):
        init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}
        head = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json', 'Host': '127.0.0.1:8360'}

        def tools(c):
            r = c.post('/mcp/', json=init, headers=head); assert r.status_code == 200
            sid = r.headers.get('mcp-session-id'); h2 = dict(head, **({'mcp-session-id': sid} if sid else {})); c.post('/mcp/', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers=h2)
            return c.post('/mcp/', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}, headers=h2).text
        with make_client() as c: assert '"edit"' in tools(c)
        monkeypatch.setenv('STRATA360_MCP_WRITE', '0')
        with make_client() as c: out = tools(c); assert '"edit"' not in out and '"picture"' in out
