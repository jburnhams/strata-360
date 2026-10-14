"""The read-only MCP tools (server/mcp_tools.py): the trimming, the token guard, the tool set (every one read only, none that writes), the tools run against a real app in-process, and the /mcp mount."""
import asyncio, json

import pytest

pytest.importorskip('mcp')
from strata360.server import mcp_tools as MT
from projects import CLIP_ID


def run(coro): return asyncio.run(coro)


def refused(coro, *words):
    """The tool refuses with a message (called directly the SDK raises it; over the protocol the client gets it as an error result)."""
    with pytest.raises(MT.ToolError) as e: asyncio.run(coro)
    assert all(w in str(e.value) for w in words)


def text_of(result):
    assert not result.is_error, result
    return json.loads(result.content[0].text)


class TestShrink:
    def test_long_lists_are_cut_and_say_how_many_are_left(self):
        out = MT.shrink(list(range(100)), items=5)
        assert out[:5] == [0, 1, 2, 3, 4] and out[5] == '... 95 more'

    def test_long_text_is_cut(self):
        assert MT.shrink('x' * 1000, chars=10) == 'xxxxxxxxxx... (990 more characters)'

    def test_bulky_keys_are_dropped_at_any_depth(self):
        assert MT.shrink({'a': {'words': [1, 2], 'text': 'hi'}, 'techniques': [1]}) == {'a': {'text': 'hi'}}

    def test_deep_nesting_is_cut(self):
        d = cur = {}
        for _ in range(20): cur['k'] = {}; cur = cur['k']
        assert '...' in json.dumps(MT.shrink(d, depth=3))


class TestToken:
    def test_no_token_means_open(self): assert MT.token_ok(None, {}, {})

    def test_bearer_or_query(self):
        assert MT.token_ok('t', {'authorization': 'Bearer t'}, {}) and MT.token_ok('t', {}, {'token': 't'})
        assert not MT.token_ok('t', {'authorization': 'Bearer x'}, {'token': 'y'}) and not MT.token_ok('t', {}, {})


class FakeBackend:
    def __init__(self, **routes): self.routes, self.calls = routes, []
    async def get(self, path, **params): self.calls.append((path, params)); return self.routes[path]
    async def get_bytes(self, path, **params): self.calls.append((path, params)); return b'\xff\xd8\xff\xd9'


class TestTools:
    EXPECTED = {'projects', 'project_overview', 'list_clips', 'get_clip', 'search_transcript', 'transcript_review', 'edit_plan', 'get_script', 'get_notes', 'track_summary', 'music_state', 'film_stills', 'final_render_status', 'recent_log', 'clip_thumbnail', 'film_still_image'}

    def test_the_tool_set_is_the_read_only_one(self):
        srv = MT.build_server(FakeBackend()); assert set(MT.tool_names(srv)) == self.EXPECTED
        for t in run(srv.list_tools()): assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name

    def test_the_backends_can_only_read(self):
        for b in (MT.AsgiBackend(None), MT.HttpBackend('http://x')): assert not any(hasattr(b, n) for n in ('post', 'put', 'delete', 'patch'))

    def test_the_last_project_is_the_default_folder(self):
        b = FakeBackend(**{'/api/last': dict(folder='F'), '/api/clips': dict(clips=[dict(id=f'c{i}') for i in range(50)])}); srv = MT.build_server(b)
        out = text_of(run(srv.call_tool('list_clips', dict(offset=2, limit=3))))
        assert out['total'] == 50 and [c['id'] for c in out['clips']] == ['c2', 'c3', 'c4'] and ('/api/clips', {'folder': 'F'}) in b.calls

    def test_an_explicit_folder_wins(self):
        b = FakeBackend(**{'/api/clips': dict(clips=[])}); run(MT.build_server(b).call_tool('list_clips', dict(folder='G'))); assert b.calls == [('/api/clips', {'folder': 'G'})]

    def test_no_project_open_is_a_clear_error(self):
        refused(MT.build_server(FakeBackend(**{'/api/last': dict(folder=None)})).call_tool('list_clips', {}), 'no project is open')

    def test_transcript_search_filters_and_drops_the_words(self):
        segs = [dict(clip='a', t0=1.0, t1=2.0, text='Hello Alps', text_en='Hello Alps', lang='en', who='wearer', words=[1]), dict(clip='b', t0=3.0, t1=4.0, text='bonjour', text_en='hello', lang='fr', who='other')]
        srv = MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/transcript': dict(segments=segs)}))
        out = text_of(run(srv.call_tool('search_transcript', dict(query='alps'))))
        assert out['total'] == 1 and out['phrases'][0]['clip'] == 'a' and 'words' not in out['phrases'][0]
        assert text_of(run(srv.call_tool('search_transcript', dict(query='hello', clip='b'))))['phrases'][0]['text_en'] == 'hello'     # the English text is searched too

    def test_the_plan_is_summarised_without_the_technique_catalogue(self):
        e = dict(edit=dict(settings={}, overrides={}, plan=dict(source='script', length_s=60, segments=[dict(id=f's{i}', clip='c') for i in range(100)])), techniques=[1] * 50)
        out = text_of(run(MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/edit': e})).call_tool('edit_plan', {})))
        assert out['segments'] == 100 and len(out['plan']) == 61 and 'techniques' not in json.dumps(out)

    def test_images_come_back_as_images(self):
        r = run(MT.build_server(FakeBackend(**{'/api/last': dict(folder='F')})).call_tool('clip_thumbnail', dict(clip='c')))
        assert r.content[0].type == 'image' and r.content[0].mime_type == 'image/jpeg'

    def test_a_still_name_is_checked(self):
        refused(MT.build_server(FakeBackend(**{'/api/last': dict(folder='F')})).call_tool('film_still_image', dict(name='../x')), 'not a still name')


class TestAgainstTheApp:
    def test_tools_read_a_project_through_the_servers_own_api(self, make_client, project):
        client = make_client(); srv = MT.build_server(MT.AsgiBackend(client.app))
        assert text_of(run(srv.call_tool('projects', {})))['roots']
        out = text_of(run(srv.call_tool('list_clips', dict(folder=project.folder))))
        assert out['total'] == 1 and out['clips'][0]['id'] == CLIP_ID

    def test_a_folder_outside_the_roots_is_refused(self, make_client, tmp_path):
        srv = MT.build_server(MT.AsgiBackend(make_client().app)); refused(srv.call_tool('list_clips', dict(folder=str(tmp_path.parent))), '403')

    def test_the_token_is_sent_to_the_api(self, make_client, project):
        srv = MT.build_server(MT.AsgiBackend(make_client(token='s3cret').app, 's3cret')); assert text_of(run(srv.call_tool('list_clips', dict(folder=project.folder))))['total'] == 1
        bad = MT.build_server(MT.AsgiBackend(make_client(token='s3cret').app, 'wrong')); refused(bad.call_tool('list_clips', dict(folder=project.folder)), '401')


class TestMount:
    INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}
    HEAD = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json', 'Host': '127.0.0.1:8360'}       # the SDK only answers the names this machine is known by (its DNS rebinding check stays on)

    def test_mcp_needs_the_token(self, make_client):
        with make_client(token='s3cret') as c:
            assert c.post('/mcp/', json=self.INIT, headers=self.HEAD).status_code == 401

    def test_mcp_answers_an_initialize_with_the_token(self, make_client):
        with make_client(token='s3cret') as c:
            r = c.post('/mcp/', json=self.INIT, headers={**self.HEAD, 'Authorization': 'Bearer s3cret'})
        assert r.status_code == 200 and 'strata360' in r.text

    def test_the_mount_can_be_switched_off(self, make_client, monkeypatch):
        monkeypatch.setenv('STRATA360_MCP', '0')
        with make_client() as c: assert c.post('/mcp/', json=self.INIT, headers=self.HEAD).status_code in (404, 405)
