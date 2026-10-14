"""The read-only MCP tools (server/mcp_tools.py): the trimming, the token guard, the tool set (every one read only, none that writes), each composite tool's digest, the tools against a real app in-process, and the /mcp mount."""
import asyncio, json

import pytest

pytest.importorskip('mcp')
from strata360.server import mcp_tools as MT
from projects import CLIP_ID

NAMES = {'project', 'clips', 'clip', 'transcript', 'plan', 'script', 'film', 'picture'}


def run(coro): return asyncio.run(coro)


def text_of(result):
    assert not result.is_error, result
    return json.loads(result.content[0].text)


def refused(coro, *words):
    """The tool refuses with a message (called directly the SDK raises it; over the protocol the client gets it as an error result)."""
    with pytest.raises(MT.ToolError) as e: asyncio.run(coro)
    assert all(w in str(e.value) for w in words)


class FakeBackend:
    """Answers the routes it was given; any other route fails like a missing stage would."""
    def __init__(self, **routes): self.routes, self.calls = routes, []
    async def get(self, path, **params):
        self.calls.append((path, params))
        if path not in self.routes: raise MT.ToolError(f'{path}: 404 not there')
        return self.routes[path]
    async def get_bytes(self, path, **params): self.calls.append((path, params)); return b'\xff\xd8\xff\xd9'


def call(srv, name, **args): return text_of(run(srv.call_tool(name, args)))


CLIPS = [dict(id='a', start_utc='2026-01-01T10:00:00Z', duration_s=30.0, steady=0.5, in_film=True, has_note=False, thumb='best', audio_original=True),
         dict(id='b', start_utc='2026-01-01T09:00:00Z', duration_s=90.0, steady=0.9, in_film=False, has_note=True, thumb='quick'),
         dict(id='c', start_utc='2026-01-01T11:00:00Z', duration_s=10.0, steady=0.1, in_film=True, has_note=False)]
SEGS = [dict(index=i, id=f's{i}', clip='a' if i % 2 else 'b', clip_start_s=1.5 * i, dur_s=4.0, film_start_s=4.0 * i, technique='free_view', family='hold', kind='best', view='ahead', options=[dict(tech='x', score=1.0), dict(tech='y', score=0.5)], **({'locked': True} if i == 0 else {})) for i in range(30)]
EDIT = dict(edit=dict(settings=dict(length_s=120), overrides=dict(locked=['s0'], bans_techs=[]), plan=dict(source='script', film={'length_s': 120}, segments=SEGS, clips_in_plan=2, missing_clips=[], technique_seconds=dict(free_view=100.0, hold=20.0), warnings=['w1'], text_cards=[1, 2])), script={'s1': dict(text='Hello there')}, techniques=[1] * 40)
CLIP = dict(id='a', time=dict(start_utc='2026-01-01T10:00:00Z', end_utc='2026-01-01T10:00:30Z'), video=dict(source_frames=900, nominal_fps=30.0), camera=dict(model='OSMO 360'), motion=dict(steady=0.5), note='my note',
            transcript=[dict(t0=1.0, t1=2.0, text='Hello', who='wearer', flagged=False, words=[1, 2]), dict(t0=3.0, t1=4.0, text='Bye', who='other', flagged=True, words=[3])], scenes=dict(summary=dict(setting='road'), items=[dict(t_s=1, description='a road')] * 20),
            audio=dict(summary=dict(speech=0.4), segments=[1] * 30), objects=dict(moments=3, items=[1]))
SCRIPT = dict(draft=dict(title='The Run', story='x' * 900, target_s=120.0, items=[dict(id=f'i{n}', text='t' * 300) for n in range(30)], skipped=[1], warnings=['w'], problems=[], pins={}), drafts=['script-1.json'], pins={}, running=False, plan=dict(source='script'))


class TestShrink:
    def test_long_lists_are_cut_and_say_how_many_are_left(self):
        out = MT.shrink(list(range(100)), items=5)
        assert out[:5] == [0, 1, 2, 3, 4] and out[5] == '... 95 more'

    def test_long_text_is_cut(self): assert MT.shrink('x' * 1000, chars=10) == 'xxxxxxxxxx... (990 more characters)'

    def test_bulky_keys_are_dropped_at_any_depth(self): assert MT.shrink({'a': {'words': [1, 2], 'text': 'hi'}, 'techniques': [1]}) == {'a': {'text': 'hi'}}

    def test_deep_nesting_is_cut(self):
        d = cur = {}
        for _ in range(20): cur['k'] = {}; cur = cur['k']
        assert '...' in json.dumps(MT.shrink(d, depth=3))


class TestToken:
    def test_no_token_means_open(self): assert MT.token_ok(None, {}, {})

    def test_bearer_or_query(self):
        assert MT.token_ok('t', {'authorization': 'Bearer t'}, {}) and MT.token_ok('t', {}, {'token': 't'})
        assert not MT.token_ok('t', {'authorization': 'Bearer x'}, {'token': 'y'}) and not MT.token_ok('t', {}, {})


class TestToolSet:
    def test_the_tool_set_is_the_small_read_only_one(self):
        srv = MT.build_server(FakeBackend()); assert set(MT.tool_names(srv)) == NAMES
        for t in run(srv.list_tools()): assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name

    def test_the_definitions_stay_small(self):
        srv = MT.build_server(FakeBackend()); size = sum(len(json.dumps(dict(d=t.description, p=t.input_schema))) for t in run(srv.list_tools()))
        assert size < 9000, f'{size} characters of tool definitions are sent with every request'

    def test_the_backends_can_only_read(self):
        for b in (MT.AsgiBackend(None), MT.HttpBackend('http://x')): assert not any(hasattr(b, n) for n in ('post', 'put', 'delete', 'patch'))

    def test_the_last_project_is_the_default_folder_and_an_explicit_one_wins(self):
        b = FakeBackend(**{'/api/last': dict(folder='F'), '/api/clips': dict(clips=CLIPS)}); srv = MT.build_server(b); call(srv, 'clips'); call(srv, 'clips', folder='G')
        assert [c for c in b.calls if c[0] == '/api/clips'] == [('/api/clips', {'folder': 'F'}), ('/api/clips', {'folder': 'G'})]

    def test_no_project_open_is_a_clear_error(self): refused(MT.build_server(FakeBackend(**{'/api/last': dict(folder=None)})).call_tool('clips', {}), 'no project is open')


class TestProject:
    ROUTES = {'/api/last': dict(folder='F'), '/api/progress': dict(state='complete', percent=100.0, stages=[dict(name='ingest', done=3, total=3, note=''), dict(name='scenes', done=1, total=3, note='slow')], needs=[]),
              '/api/coverage': dict(clips=3, complete=False, totals=dict(ingest=3, scenes=1), blocked={'scenes': ['view choice']}), '/api/clips': dict(clips=CLIPS), '/api/edit': EDIT, '/api/script2': SCRIPT,
              '/api/music': dict(file='music/t.mp3', name='t.mp3', analysis=dict(bpm=120, duration_s=200.0)), '/api/track': dict(present=True, distance_km=100.0, ascent_m=500, duration_h=20.0, start_utc='x', line=[[1, 2]] * 400),
              '/api/film/stills': dict(stills=[1, 2]), '/api/final': dict(state='idle'), '/api/notes': dict(folder='A note for the folder', clips={})}

    def test_the_overview_is_one_digest_of_everything(self):
        out = call(MT.build_server(FakeBackend(**self.ROUTES)), 'project')
        assert out['clips'] == dict(count=3, footage_min=2.2, first='2026-01-01T09:00:00Z', last='2026-01-01T11:00:00Z', in_film=2)
        assert out['analysis']['unfinished'] == {'scenes': '1/3'} and out['analysis']['blocks'] == {'scenes': ['view choice']}
        assert out['plan']['segments'] == 30 and out['plan']['overrides'] == {'locked': 1} and 'free_view' in out['plan']['technique_seconds'] and out['plan']['text_cards'] == 2
        assert out['script']['items'] == 30 and out['music']['bpm'] == 120 and out['track'] == dict(distance_km=100.0, ascent_m=500, duration_h=20.0, start='x') and out['stills'] == 2 and out['final_render'] == 'idle' and out['note'] == 'A note for the folder'
        assert out['failed_parts'] is None and len(json.dumps(out)) < 2500

    def test_a_missing_part_is_named_and_does_not_spoil_the_rest(self):
        routes = dict(self.ROUTES); del routes['/api/music']; del routes['/api/edit']; out = call(MT.build_server(FakeBackend(**routes)), 'project')
        assert set(out['failed_parts']) == {'music', 'edit'} and out['clips']['count'] == 3 and 'music' not in out

    def test_stages_log_and_roots(self):
        srv = MT.build_server(FakeBackend(**self.ROUTES, **{'/api/roots': dict(roots=['R']), '/api/log': dict(lines=['x'])}))
        assert call(srv, 'project', view='stages')['stages'] == {'ingest': '3/3', 'scenes': '1/3 (slow)'} and call(srv, 'project', view='log') == dict(lines=['x']) and call(srv, 'project', view='roots') == dict(roots=['R'], last='F')


class TestClips:
    def srv(self): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/clips': dict(clips=CLIPS)}))

    def test_sorted_and_slim(self):
        out = call(self.srv(), 'clips', sort='longest'); assert [c['id'] for c in out['clips']] == ['b', 'a', 'c'] and 'thumb' not in out['clips'][0] and 'audio_original' not in out['clips'][0]
        assert [c['id'] for c in call(self.srv(), 'clips', sort='steadiest')['clips']] == ['b', 'a', 'c'] and [c['id'] for c in call(self.srv(), 'clips')['clips']] == ['b', 'a', 'c']

    def test_filtered_by_use_in_the_film_and_paged(self):
        out = call(self.srv(), 'clips', in_film=True); assert out['total'] == 2 and {c['id'] for c in out['clips']} == {'a', 'c'}
        assert [c['id'] for c in call(self.srv(), 'clips', limit=1, offset=1)['clips']] == ['a']


class TestClip:
    def srv(self): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/clip': CLIP, '/api/edit': EDIT}))

    def test_the_default_is_a_small_summary_that_says_what_else_there_is(self):
        out = call(self.srv(), 'clip', clip='a'); assert out['duration_s'] == 30.0 and out['note'] == 'my note' and out['has']['transcript'] == 2 and 'transcript' not in out and out['more'] == ['transcript', 'scenes', 'audio', 'objects', 'plan']

    def test_sections_are_chosen_by_the_caller(self):
        out = call(self.srv(), 'clip', clip='a', sections=['transcript', 'plan'])
        assert [p['text'] for p in out['transcript']] == ['Hello', 'Bye'] and out['transcript'][1]['flagged'] is True and 'words' not in json.dumps(out['transcript']) and 'summary' in out['more'] and 'transcript' not in out['more']
        assert {r['clip'] for r in out['plan']} == {'a'} and len(out['plan']) == 15

    def test_scenes_audio_and_objects_are_cut(self):
        out = call(self.srv(), 'clip', clip='a', sections=['scenes', 'audio', 'objects']); assert len(out['scenes']['items']) <= 13 and len(out['audio']['segments']) <= 13 and out['objects']['moments'] == 3


class TestTranscript:
    SEGS = [dict(clip='a', t0=1.0, t1=2.0, text='Hello Alps', text_en='Hello Alps', lang='en', who='wearer', words=[1]), dict(clip='b', t0=3.0, t1=4.0, text='bonjour', text_en='hello', lang='fr', who='other', flagged=True)]

    def srv(self, **extra): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/transcript': dict(segments=self.SEGS), **extra}))

    def test_search_filters_and_drops_the_words(self):
        out = call(self.srv(), 'transcript', query='alps'); assert out['total'] == 1 and out['phrases'][0]['clip'] == 'a' and 'words' not in out['phrases'][0]
        assert call(self.srv(), 'transcript', query='hello', clip='b')['phrases'][0] == dict(clip='b', t0=3.0, t1=4.0, text='bonjour', english='hello', who='other', flagged=True)

    def test_the_review_queue_worst_first_without_the_reviewed(self):
        items = [dict(clip='a', text='x', reviewed=False), dict(clip='a', text='y', reviewed=True), dict(clip='b', text='z', reviewed=False)]
        out = call(self.srv(**{'/api/transcript/review': dict(items=items, todo=2, total=3)}), 'transcript', uncertain=True, clip='a'); assert out['todo'] == 2 and [i['text'] for i in out['shown']] == ['x']


class TestPlan:
    def srv(self, edit=EDIT): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/edit': edit}))

    def test_summary(self):
        out = call(self.srv(), 'plan'); assert out['segments'] == 30 and out['source'] == 'script' and out['technique_seconds']['hold'] == 20.0 and out['text_cards'] == 2 and 'techniques' not in json.dumps(out) and len(json.dumps(out)) < 2000

    def test_rows_are_paged_and_carry_the_script_line(self):
        out = call(self.srv(), 'plan', view='segments', first=1, count=2); assert out['total'] == 30 and [r['id'] for r in out['segments']] == ['s1', 's2'] and out['segments'][0]['says'] == 'Hello there' and 'options' not in out['segments'][0]
        assert call(self.srv(), 'plan', view='segments', count=1)['segments'][0]['locked'] is True

    def test_one_segment_in_full_by_id_or_index_with_its_alternatives(self):
        out = call(self.srv(), 'plan', view='segment', segment='s3'); assert out['segment']['id'] == 's3' and out['alternatives'] == [dict(tech='x', score=1.0), dict(tech='y', score=0.5)]
        assert call(self.srv(), 'plan', view='segment', segment='4')['segment']['id'] == 's4'
        refused(self.srv().call_tool('plan', dict(view='segment', segment='nope')), 'no segment')

    def test_no_plan_is_said_not_an_error(self): assert call(self.srv(dict(edit=dict(settings={}, overrides={}, plan=None), script={})), 'plan')['plan'] is None


class TestScript:
    def srv(self, d=SCRIPT): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/script2': d}))

    def test_summary_and_items(self):
        out = call(self.srv(), 'script'); assert out['title'] == 'The Run' and out['items'] == 30 and len(out['story']) < 700 and out['drafts'] == ['script-1.json']
        out = call(self.srv(), 'script', view='items', first=2, count=3); assert out['total'] == 30 and [i['id'] for i in out['items']] == ['i2', 'i3', 'i4'] and len(out['items'][0]['text']) < 300

    def test_no_draft(self): assert call(self.srv(dict(draft=None, running=False)), 'script')['draft'] is None


class TestFilm:
    def srv(self): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), '/api/film/stills': dict(stills=[dict(name='still-1.png', t=3.0, size=[1920, 1080], current=True, bytes=99)], active=[]), '/api/final': dict(state='idle', progress=None),
                                                         '/api/music': dict(file='m.mp3', analysis=dict(bpm=120, duration_s=100.0, sections=[1, 2, 3], bar_beats=4, confidence=0.9), waveform=[0.1] * 1000), '/api/track': dict(present=True, distance_km=5.0, line=[[1, 2]] * 100, bbox=[1, 2, 3, 4])}))

    def test_views(self):
        s = self.srv(); assert call(s, 'film')['stills'] == [dict(name='still-1.png', t=3.0, size=[1920, 1080], current=True)] and call(s, 'film', view='final')['state'] == 'idle'
        assert call(s, 'film', view='music') == dict(file='m.mp3', bpm=120, duration_s=100.0, bar_beats=4, sections=3, confidence=0.9) and call(s, 'film', view='track') == dict(present=True, distance_km=5.0)


class TestPicture:
    def srv(self, **extra): return MT.build_server(FakeBackend(**{'/api/last': dict(folder='F'), **extra}))

    def test_each_kind_asks_its_own_route_and_returns_an_image(self):
        b = FakeBackend(**{'/api/last': dict(folder='F')}); srv = MT.build_server(b)
        for args, path in ((dict(of='frame', clip='c', t=3.5, yaw=90), '/api/clip/frame'), (dict(of='thumbnail', clip='c', overlay=True), '/api/thumb'), (dict(of='still', name='still-1.png'), '/api/film/still/thumb')):
            r = run(srv.call_tool('picture', args)); assert r.content[0].type == 'image' and r.content[0].mime_type == 'image/jpeg' and b.calls[-1][0] == path
        assert [c for c in b.calls if c[0] == '/api/clip/frame'][0][1] == dict(folder='F', clip='c', t=3.5, yaw=90, pitch=0.0, fov=100.0)

    def test_missing_arguments_and_bad_still_names_are_refused(self):
        refused(self.srv().call_tool('picture', dict(of='frame', clip='c')), 'needs clip and t'); refused(self.srv().call_tool('picture', dict(of='thumbnail')), 'needs clip')
        for bad in ('../x', 'a b', ''): refused(self.srv().call_tool('picture', dict(of='still', name=bad)), 'name of a still')


class TestAgainstTheApp:
    def test_tools_read_a_project_through_the_servers_own_api(self, make_client, project):
        client = make_client(); srv = MT.build_server(MT.AsgiBackend(client.app))
        assert call(srv, 'project', view='roots')['roots']
        out = call(srv, 'clips', folder=project.folder); assert out['total'] == 1 and out['clips'][0]['id'] == CLIP_ID

    def test_a_folder_outside_the_roots_is_refused(self, make_client, tmp_path):
        refused(MT.build_server(MT.AsgiBackend(make_client().app)).call_tool('clips', dict(folder=str(tmp_path.parent))), '403')

    def test_the_token_is_sent_to_the_api(self, make_client, project):
        srv = MT.build_server(MT.AsgiBackend(make_client(token='s3cret').app, 's3cret')); assert call(srv, 'clips', folder=project.folder)['total'] == 1
        refused(MT.build_server(MT.AsgiBackend(make_client(token='s3cret').app, 'wrong')).call_tool('clips', dict(folder=project.folder)), '401')


class TestMount:
    INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}}
    HEAD = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json', 'Host': '127.0.0.1:8360'}       # the SDK only answers the names this machine is known by (its DNS rebinding check stays on)

    def test_mcp_needs_the_token(self, make_client):
        with make_client(token='s3cret') as c: assert c.post('/mcp/', json=self.INIT, headers=self.HEAD).status_code == 401

    def test_mcp_answers_an_initialize_with_the_token(self, make_client):
        with make_client(token='s3cret') as c: r = c.post('/mcp/', json=self.INIT, headers={**self.HEAD, 'Authorization': 'Bearer s3cret'})
        assert r.status_code == 200 and 'strata360' in r.text

    def test_the_mount_can_be_switched_off(self, make_client, monkeypatch):
        monkeypatch.setenv('STRATA360_MCP', '0')
        with make_client() as c: assert c.post('/mcp/', json=self.INIT, headers=self.HEAD).status_code in (404, 405)


def test_a_broken_mcp_package_does_not_stop_the_server_it_just_has_no_mcp(make_client, monkeypatch, capsys):
    def broken(*a, **k): raise TypeError("type 'X' is not subscriptable")
    monkeypatch.setattr(MT, 'build_server', broken)
    with make_client() as c:
        assert c.get('/api/roots').status_code == 200 and c.post('/mcp/', json={}).status_code in (404, 405)
    assert '/mcp is off' in capsys.readouterr().err
