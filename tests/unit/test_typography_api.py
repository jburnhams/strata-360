"""Vibes and typography through the app: the script writer is asked for vibes, the scheme follows them unless the user chose their own, fonts can be overridden per role, and the routes the Style panel uses."""
import io, json

import numpy as np
import pytest
from PIL import Image

from strata360.edit import script_draft as SD
from strata360.render import typography as TY

PNG = b'\x89PNG\r\n\x1a\n'


class TestScriptWriterVibes:
    def test_the_prompt_lists_the_vocabulary_and_the_schema_asks_for_vibes(self):
        assert '__VIBES__' not in SD.SYSTEM and all(v in SD.SYSTEM for v in TY.VIBES) and '14. THE LOOK AND FEEL' in SD.SYSTEM and '"vibes": [' in SD.SCHEMA and 'rule 14' in SD.SCHEMA
        assert SD.PROMPT_VERSION >= 16

    def test_the_writers_vibes_are_kept_to_the_vocabulary(self):
        assert SD.clean_vibes(['Rugged', 'nonsense', 'rugged', ' warm ', 'cinematic', 'quiet', 'refined', 'elegant']) == ['rugged', 'warm', 'cinematic', 'quiet', 'refined'] and SD.clean_vibes(None) == [] and SD.clean_vibes('rugged') == []

    def test_a_revision_carries_the_current_vibes(self):
        from test_script_draft import PACK
        msgs = SD.build_messages(PACK, 30, 150, None, dict(title='T', story='S', vibes=['rugged'], items=[], skipped=[]))[0]
        user = ' '.join(m['content'] for m in msgs if m['role'] == 'user'); assert 'CURRENT DRAFT' in user and '"vibes": [' in user.split('CURRENT DRAFT')[1] and 'rugged' in user.split('CURRENT DRAFT')[1]


class TestCombine:
    def test_the_user_replaces_the_writer_who_outweighs_the_project(self):
        inferred = dict(athletic=1.0, outdoors=0.8)
        assert list(TY.combine(inferred, script=['elegant', 'quiet']))[:2] == ['elegant', 'quiet'] and TY.combine(inferred, script=['elegant'])['athletic'] < 0.5
        u = TY.combine(inferred, script=['elegant', 'quiet'], user=['rugged']); assert list(u)[0] == 'rugged' and 'elegant' not in u and u['athletic'] < u['rugged']

    def test_without_choices_the_project_speaks_and_the_weights_are_normalised(self):
        v = TY.combine(dict(athletic=0.5, clean=0.25)); assert v == dict(athletic=1.0, clean=0.5) and TY.combine({}) == {}

    def test_words_are_cleaned(self):
        assert TY.clean_words('Rugged, warm nonsense;rugged') == ['rugged', 'warm'] and TY.clean_words(['QUIET', 'x']) == ['quiet'] and TY.clean_words(None) == []


class TestSample:
    def test_a_sample_is_a_transparent_png_of_the_words_in_the_font(self):
        b = TY.sample_png('oswald', 'DAY 2', 80, '#f9ffb7'); im = Image.open(io.BytesIO(b)); assert b.startswith(PNG) and im.mode == 'RGBA' and im.getpixel((0, 0))[3] == 0 and im.size[0] > 100 and int(np.asarray(im)[..., 3].max()) > 200

    def test_a_background_colour_fills_it(self):
        im = Image.open(io.BytesIO(TY.sample_png('inter', 'x', 40, '#ffffff', bg='#102030'))); assert im.getpixel((0, 0))[:3] == (16, 32, 48)

    def test_a_longer_text_or_a_bigger_size_makes_a_bigger_picture(self):
        w = lambda t, px: Image.open(io.BytesIO(TY.sample_png('oswald', t, px))).size[0]; assert w('DAY 2 AND MORE', 80) > w('DAY', 80) and w('DAY', 160) > w('DAY', 80)


@pytest.fixture
def folder(project): return project.folder


class TestRoutes:
    def get(self, client, folder): return client.get('/api/typography', params=dict(folder=folder)).json()

    def test_the_scheme_comes_with_the_library_and_the_vocabulary(self, make_client, folder):
        d = self.get(make_client(), folder)
        assert set(d['scheme']['fonts']) == set(TY.ROLES) and len(d['library']) == len(TY.FONT_TABLE) and d['vibes'] == list(TY.VIBES) and d['roles'] == list(TY.ROLES) and d['script_vibes'] == []
        assert {'id', 'family', 'category', 'desc', 'vibes', 'roles', 'caps', 'min_em'} <= set(d['library'][0]) and d['scheme']['basis'] == 'project'

    def test_the_script_writers_vibes_are_the_default(self, make_client, folder):
        SD.save_draft(folder, dict(vibes=['elegant', 'refined', 'quiet'], items=[])); s = self.get(make_client(), folder)
        assert s['script_vibes'] == ['elegant', 'refined', 'quiet'] and s['scheme']['sources']['script'] == ['elegant', 'refined', 'quiet'] and s['scheme']['basis'] == 'script' and s['scheme']['sources']['user'] == []
        assert TY.FONT_TABLE[s['scheme']['fonts']['display']]['category'] == 'serif'

    def test_a_newer_draft_with_other_vibes_changes_the_scheme(self, make_client, folder):
        c = make_client(); SD.save_draft(folder, dict(vibes=['elegant', 'refined'], items=[])); a = self.get(c, folder)['scheme']['fonts']['display']
        SD.save_draft(folder, dict(vibes=['rugged', 'athletic', 'outdoors'], items=[])); b = self.get(c, folder)['scheme']; assert b['sources']['script'] == ['rugged', 'athletic', 'outdoors'] and b['fonts']['display'] != a

    def test_a_newer_draft_without_vibes_does_not_hide_the_vibes_of_an_older_one(self, make_client, folder):
        c = make_client(); SD.save_draft(folder, dict(vibes=['elegant', 'refined'], items=[])); SD.save_draft(folder, dict(title='no vibes here', items=[]))
        assert self.get(c, folder)['script_vibes'] == ['elegant', 'refined']; SD.save_draft(folder, dict(vibes=['rugged'], items=[])); assert self.get(c, folder)['script_vibes'] == ['rugged']

    def test_the_users_vibes_replace_the_writers_and_survive_a_new_draft(self, make_client, folder):
        c = make_client(); SD.save_draft(folder, dict(vibes=['elegant', 'refined'], items=[]))
        r = c.post('/api/typography', json=dict(folder=folder, style=['rugged', 'athletic'])).json()['scheme']; assert r['basis'] == 'user' and r['sources']['user'] == ['rugged', 'athletic'] and r['style'] == ['rugged', 'athletic'] and set(list(r['vibes'])[:2]) == {'rugged', 'athletic'}
        SD.save_draft(folder, dict(vibes=['warm', 'personal'], items=[])); again = self.get(c, folder)['scheme']; assert again['basis'] == 'user' and again['sources']['user'] == ['rugged', 'athletic'] and again['fonts'] == r['fonts']

    def test_an_empty_style_gives_the_choice_back_to_the_writer(self, make_client, folder):
        c = make_client(); SD.save_draft(folder, dict(vibes=['elegant', 'refined'], items=[])); c.post('/api/typography', json=dict(folder=folder, style=['rugged']))
        s = c.post('/api/typography', json=dict(folder=folder, style=[])).json()['scheme']; assert s['basis'] == 'script' and s['style'] == []

    def test_a_font_can_be_chosen_for_a_role_and_given_back(self, make_client, folder):
        c = make_client(); s = c.post('/api/typography', json=dict(folder=folder, fonts=dict(display='caveat'))).json()['scheme']
        assert s['fonts']['display'] == 'caveat' and s['overrides'] == dict(display='caveat') and 'chosen by you' in s['why']['display'] and 'Caveat' in s['families'] and s['fonts']['subtitle'] != 'caveat'
        back = c.post('/api/typography', json=dict(folder=folder, fonts=dict(display=None))).json()['scheme']; assert back['overrides'] == {} and back['fonts']['display'] != 'caveat'

    def test_overrides_survive_new_vibes_and_a_refresh(self, make_client, folder):
        c = make_client(); c.post('/api/typography', json=dict(folder=folder, fonts=dict(meta='plex_mono'))); s = c.post('/api/typography', json=dict(folder=folder, style=['elegant'], refresh=True)).json()['scheme']
        assert s['fonts']['meta'] == 'plex_mono' and s['overrides'] == dict(meta='plex_mono')

    def test_anything_outside_the_library_is_refused(self, make_client, folder):
        c = make_client(); post = lambda **b: c.post('/api/typography', json=dict(folder=folder, **b))
        assert post(style=['nonsense']).status_code == 400 and post(fonts=dict(display='comic_sans')).status_code == 400 and post(fonts=dict(headline='anton')).status_code == 400
        assert post(style=['rugged', 'nonsense']).status_code == 400 and self.get(c, folder)['scheme']['overrides'] == {}                               # a refused request changes nothing

    def test_the_scheme_is_written_to_the_project(self, make_client, folder, project):
        make_client().post('/api/typography', json=dict(folder=folder, style=['quiet'])); saved = json.load(open(project.path(TY.FILE))); assert saved['style'] == ['quiet'] and set(saved['fonts']) == set(TY.ROLES)

    def test_font_samples_are_png_pictures_with_limits(self, make_client):
        c = make_client(); r = c.get('/api/typography/sample', params=dict(font='oswald', text='DAY 2', px=80, color='#f9ffb7')); assert r.status_code == 200 and r.headers['content-type'] == 'image/png' and r.content.startswith(PNG)
        assert c.get('/api/typography/sample', params=dict(font='nope')).status_code == 404 and c.get('/api/typography/sample', params=dict(font='oswald', color='red')).status_code == 400
        big = c.get('/api/typography/sample', params=dict(font='oswald', text='x' * 500, px=9999)); h = Image.open(io.BytesIO(big.content)).size; assert big.status_code == 200 and h[1] < 600       # the text and the size are capped

    def test_the_routes_need_the_token_and_the_roots(self, make_client, folder, tmp_path):
        c = make_client(token='s3cret'); h = {'Authorization': 'Bearer s3cret'}
        assert c.get('/api/typography', params=dict(folder=folder)).status_code == 401 and c.post('/api/typography', json=dict(folder=folder)).status_code == 401 and c.get('/api/typography/sample', params=dict(font='oswald')).status_code == 401
        assert c.get('/api/typography/sample', params=dict(font='oswald'), headers=h).status_code == 200 and c.get('/api/typography', params=dict(folder=str(tmp_path.parent)), headers=h).status_code == 403 and c.get('/api/palette-schemes', params=dict(folder=folder)).status_code == 401


class TestColourSchemes:
    def docs(self, project):
        import numpy as np
        from strata360.analysis import palette as P
        for cid, rgb in (('CLIP_A', (30, 110, 40)), ('CLIP_B', (36, 116, 46)), ('CLIP_C', (40, 70, 170)), ('CLIP_D', (46, 76, 176))):
            f = np.zeros((60, 120, 3), np.uint8); f[:, :90] = rgb; project.add_clip(cid); json.dump(P.analyse_pixels([f] * 2), open(project.path('clips', cid, 'palette.json'), 'w'))

    def test_without_schemes_it_says_so(self, make_client, folder): assert make_client().get('/api/palette-schemes', params=dict(folder=folder)).json() == dict(present=False)

    def test_the_schemes_come_with_their_colours_and_clip_counts(self, make_client, folder, project):
        from strata360.analysis import palette_cluster as PC
        self.docs(project); PC.run(folder, cost=0.5); d = make_client().get('/api/palette-schemes', params=dict(folder=folder)).json()
        assert d['present'] and d['clips'] == 4 and sum(s['clips'] for s in d['schemes']) == 4 and len(d['schemes']) == 2 and {'label', 'base', 'accent', 'support', 'light', 'dark', 'outline', 'tone', 'mean_loss'} <= set(d['schemes'][0])
        assert all(s['base'].startswith('#') for s in d['schemes']) and {s['label'] for s in d['schemes']} >= {'green'}
