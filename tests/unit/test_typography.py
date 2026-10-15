"""Typography (render/typography.py): the font library and its tags, vibes from a project's signals, the choice of one font per role, applying it to title elements, the project file, the specimens and the CLI."""
import argparse, json, os

import numpy as np
import pytest
from PIL import ImageFont

from strata360.render import titles as TT
from strata360.render import typography as TY


class TestLibrary:
    def test_there_are_at_least_ten_new_fonts_and_the_old_ones(self):
        assert len(TY.FONT_TABLE) >= 20 and {'bebas', 'anton', 'dm_serif', 'inter', 'oswald', 'fraunces', 'plex_mono', 'caveat', 'special_elite'} <= set(TY.FONT_TABLE)

    def test_every_font_file_exists_and_opens_at_any_size(self):
        for fid in TY.FONT_TABLE:
            assert os.path.exists(TY.path_of(fid)), fid
            for px in (12, 80): assert TY.load_font(fid, px).getlength('Day 2') > 0, fid

    def test_every_tag_is_in_the_vocabulary_and_every_entry_is_complete(self):
        for fid, f in TY.FONT_TABLE.items():
            assert 2 <= len(f['vibes']) <= 6 and set(f['vibes']) <= set(TY.VIBES), fid
            assert f['roles'] and set(f['roles']) <= set(TY.ROLES), fid
            assert f['category'] in ('sans', 'serif', 'slab', 'mono', 'hand', 'typewriter') and 0.02 <= f['min_em'] <= 0.1 and 0.0 < f['outline'] <= 1.0 and f['desc'], fid

    def test_every_role_has_several_fonts_and_every_vibe_at_least_one(self):
        for r in TY.ROLES: assert sum(r in f['roles'] for f in TY.FONT_TABLE.values()) >= 3, r
        used = {v for f in TY.FONT_TABLE.values() for v in f['vibes']}; assert set(TY.VIBES) - used == set(), set(TY.VIBES) - used

    def test_every_font_has_its_licence_text_beside_it(self):
        files = set(os.listdir(TY.FONT_DIR)); fams = {f['file'] for f in TY.FONT_TABLE.values() if not f['file'].startswith('..')}
        for f in fams:
            stem = f.split('-')[0].lower(); assert any(n.lower().startswith(stem) and ('OFL' in n or 'LICENSE' in n) for n in files), f

    def test_every_font_covers_accented_letters_numerals_and_punctuation(self):
        sample = 'ÉÈÀÖÜÄÅßçñ0123456789:·–’'
        for fid in TY.FONT_TABLE:
            f = TY.load_font(fid, 64); notdef = bytes(f.getmask('￿')); assert [c for c in sample if bytes(f.getmask(c)) == notdef] == [], fid

    def test_variable_fonts_are_pinned_to_the_weight_of_their_entry(self):
        w = lambda fid: TY.load_font(fid, 80).getlength('Kilometre')
        base = dict(TY.FONT_TABLE['oswald']); try_light = dict(base, axes=dict(wght=200)); heavy = dict(base, axes=dict(wght=700))
        assert w('oswald') == pytest.approx(TY.load_font('oswald', 80).getlength('Kilometre'))
        TY.FONT_TABLE['oswald'] = try_light; light = w('oswald'); TY.FONT_TABLE['oswald'] = heavy; bold = w('oswald'); TY.FONT_TABLE['oswald'] = base
        assert bold > light * 1.05 and light < w('oswald') < bold

    def test_the_inter_font_is_found(self):
        assert os.path.exists(TY.path_of('inter')) and TT.font('inter', 40).getlength('x') > 0

    def test_an_unknown_font_id_is_the_neutral_sans_not_a_crash(self):
        assert TT.font('no_such_font', 40).getlength('x') == pytest.approx(TT.font('inter', 40).getlength('x'))

    def test_the_title_renderer_offers_every_font_with_its_description(self):
        assert set(TT.FONTS) == set(TY.FONT_TABLE) and all(TT.FONTS[k][1] == TY.FONT_TABLE[k]['desc'] for k in TT.FONTS)


class TestVibes:
    def test_without_anything_a_race_film_is_athletic_confident_and_clean(self):
        v = TY.infer_vibes(); assert list(v)[:3] == ['athletic', 'confident', 'clean'] and v['athletic'] == 1.0

    def test_words_of_the_project_move_the_vibes(self):
        alps = TY.infer_vibes(text='Crossing Switzerland: a trail through the alps at night'); fam = TY.infer_vibes(text="baby's first birthday with the family")
        assert alps['outdoors'] > 0.5 and alps['rugged'] > 0.4 and alps['cinematic'] > 0.3 and fam['warm'] > fam['athletic'] and fam['personal'] > 0.5

    def test_repeated_words_count_more_but_not_without_limit(self):
        one = TY.infer_vibes(text='trail'); few = TY.infer_vibes(text='trail ' * 8); many = TY.infer_vibes(text='trail ' * 50); assert few['outdoors'] > one['outdoors'] and many == few          # the count of a word is capped

    def test_the_mood_of_the_colour_palettes_counts(self):
        warm = dict(mood=dict(tone='bright', saturation='vivid', temperature='warm')); cool = dict(mood=dict(tone='dark', saturation='grey', temperature='cool'))
        a, b = TY.infer_vibes(palettes=[warm] * 3), TY.infer_vibes(palettes=[cool] * 3)
        assert a['warm'] > b.get('warm', 0) and a['energetic'] > b.get('energetic', 0) and b['cinematic'] > a.get('cinematic', 0)

    def test_the_users_words_weigh_in_full_and_unknown_words_are_ignored(self):
        v = TY.infer_vibes(style='elegant, quiet nonsense refined'); assert v['elegant'] == v['quiet'] == v['refined'] == 1.0 and 'nonsense' not in v

    def test_weights_are_between_zero_and_one_with_the_top_at_one(self):
        v = TY.infer_vibes(text='mountain trail night family', style='bold'); assert max(v.values()) == 1.0 and min(v.values()) > 0

    def test_a_font_fits_a_project_that_shares_its_vibes(self):
        v = dict(athletic=1.0, rugged=0.8, outdoors=0.7); assert TY.fit('oswald', v) > TY.fit('caveat', v) and TY.fit('caveat', v) == 0.0 and 0 <= TY.fit('league_gothic', v) <= 1.0


class TestChoice:
    def test_every_role_gets_a_font_that_suits_it_and_that_can_be_that_small(self):
        s = TY.choose(TY.infer_vibes(text='trail'))
        for r in TY.ROLES: f = TY.FONT_TABLE[s['fonts'][r]]; assert r in f['roles'] and f['min_em'] <= TY.ROLE_EM[r] + 1e-9, r

    def test_the_pairing_rules_hold_for_every_vibe(self):
        for vibe in TY.VIBES:
            s = TY.choose(TY.infer_vibes(style=vibe)); fam = lambda r: TY.FONT_TABLE[s['fonts'][r]]['family']; assert len(s['families']) <= TY.MAX_FAMILIES, vibe
            assert fam('subtitle') != fam('display'), vibe

    def test_the_meta_line_and_the_numerals_stay_in_the_subtitles_family_where_they_can(self):
        s = TY.choose(TY.infer_vibes(text='trail alps')); fam = lambda r: TY.FONT_TABLE[s['fonts'][r]]['family']; assert fam('meta') == fam('subtitle')

    def test_numerals_prefer_a_font_whose_figures_align(self):
        for vibe in ('athletic', 'elegant', 'technical', 'warm'): assert TY.FONT_TABLE[TY.choose(TY.infer_vibes(style=vibe))['fonts']['numerals']]['tabular'] or vibe == 'elegant'

    def test_different_projects_get_different_voices(self):
        race = TY.choose(TY.infer_vibes(text='ultra trail mountain race', style='rugged athletic'))['fonts']; wedding = TY.choose(TY.infer_vibes(text='wedding family love', style='elegant warm personal'))['fonts']
        assert race['display'] != wedding['display'] and TY.FONT_TABLE[wedding['display']]['category'] == 'serif' and TY.FONT_TABLE[race['display']]['category'] in ('sans', 'slab')

    def test_a_handmade_project_quotes_in_handwriting_or_typewriter(self):
        assert TY.FONT_TABLE[TY.choose(TY.infer_vibes(style='handmade personal'))['fonts']['quote']]['category'] in ('hand', 'typewriter')

    def test_a_technical_project_reads_its_numbers_in_a_technical_face(self):
        s = TY.choose(TY.infer_vibes(style='data technical')); assert 'technical' in TY.FONT_TABLE[s['fonts']['numerals']]['vibes'] or 'data' in TY.FONT_TABLE[s['fonts']['numerals']]['vibes']

    def test_the_choice_is_deterministic_and_explains_itself(self):
        v = TY.infer_vibes(text='trail'); a, b = TY.choose(v), TY.choose(v); assert a == b and set(a['why']) == set(TY.ROLES) and all(a['fonts'][r] in a['alternatives'][r] or a['alternatives'][r] for r in TY.ROLES)
        assert 'matches' in a['why']['display'] and a['families'] == sorted(set(a['families']))

    def test_a_font_can_be_excluded(self):
        first = TY.choose(TY.infer_vibes(style='rugged'))['fonts']['display']; assert TY.choose(TY.infer_vibes(style='rugged'), exclude=(first,))['fonts']['display'] != first

    def test_the_scheme_is_json(self): json.dumps(TY.choose(TY.infer_vibes()))


class TestRoles:
    def test_sizes_map_to_roles(self):
        assert [TY.role_for_size(s) for s in (0.22, 0.14, 0.12, 0.075, 0.07, 0.03)] == ['display', 'display', 'subtitle', 'subtitle', 'meta', 'meta'] and TY.role_for_size(0.2, 'quote') == 'quote'

    def scheme(self): return TY.choose(TY.infer_vibes(text='trail'))

    def test_an_element_takes_the_font_of_its_role_and_the_old_one_is_returned(self):
        s = self.scheme(); big, small = dict(text='DAY 2', size=0.2, font='caveat'), dict(text='SUN', size=0.05, font='anton')
        assert TY.apply_to_element(big, s) == 'caveat' and big['font'] == s['fonts']['display'] and TY.apply_to_element(small, s) == 'anton' and small['font'] == s['fonts']['meta']

    def test_a_quote_cards_words_take_the_quote_font(self):
        s = self.scheme(); el = dict(text='Keep going', size=0.2, font='anton'); TY.apply_to_element(el, s, kind='quote'); assert el['font'] == s['fonts']['quote']

    def test_a_line_of_figures_takes_the_numerals_font(self):
        s = self.scheme(); el = dict(text='3:45:12', size=0.07, font='anton'); TY.apply_to_element(el, s); assert el['font'] == s['fonts']['numerals']
        words = dict(text='KILOMETRE', size=0.07, font='anton'); TY.apply_to_element(words, s); assert words['font'] == s['fonts']['meta']


class TestInTheTitleDesigner:
    def frame(self): f = np.zeros((90, 160, 3), np.uint8); f[:] = (20, 30, 50); return f

    def spec(self): return dict(elements=[dict(text='DAY 2', font='caveat', size=0.2, x=0.5, y=0.4), dict(text='KILOMETRE 84', font='anton', size=0.06, x=0.5, y=0.62)])

    def test_enforce_sets_every_element_to_its_roles_font_before_placing_it(self):
        from strata360.edit import title_design as TD
        s = TY.choose(TY.infer_vibes(text='trail')); out, notes = TD.enforce(self.spec(), [dict(role='title', text='DAY 2'), dict(role='meta', text='KILOMETRE 84')], [self.frame()], [3.0], [[]], 6.0, typography=s)
        big, small = out['elements']; assert big['font'] == s['fonts']['display'] and small['font'] == s['fonts']['meta'] and sum('for its role' in n for n in notes) == 2

    def test_without_a_scheme_the_models_fonts_stand(self):
        from strata360.edit import title_design as TD
        out, notes = TD.enforce(self.spec(), [dict(role='title', text='DAY 2'), dict(role='meta', text='KILOMETRE 84')], [self.frame()], [3.0], [[]], 6.0); assert [e['font'] for e in out['elements']] == ['caveat', 'anton'] and not any('for its role' in n for n in notes)

    def test_the_model_is_offered_only_the_projects_fonts(self, monkeypatch, tmp_path):
        from strata360.edit import title_design as TD
        s = TY.choose(TY.infer_vibes(text='trail')); sent = {}
        class Srv:
            def ask(self, prompt, paths, n, temperature=0.0): sent['prompt'] = prompt; return '{}'
        monkeypatch.setattr(TD, 'face_boxes', lambda f, m: [[] for _ in f]); monkeypatch.setattr(TD, 'person_boxes', lambda f, m: [[] for _ in f])
        TD.design([self.frame()] * 5, [dict(role='title', text='DAY 2')], 'a card', 6.0, Srv(), tmp_dir=str(tmp_path), rounds=0, typography=s)
        listed = [k for k in TY.FONT_TABLE if f'{k} (' in sent['prompt']]; assert set(listed) == set(s['fonts'].values()) and len(listed) < len(TY.FONT_TABLE) // 2


class TestProjectFile:
    @pytest.fixture
    def proj(self, make_project):
        p = make_project(config=True); p.add_clip('CLIP_A')
        json.dump(dict(mood=dict(tone='dark', saturation='grey', temperature='cool')), open(p.path('clips', 'CLIP_A', 'palette.json'), 'w')); return p

    def test_it_is_chosen_once_written_and_then_kept(self, proj):
        s = TY.for_project(proj.folder); assert os.path.exists(proj.path(TY.FILE)) and s['fonts'] == json.load(open(proj.path(TY.FILE)))['fonts']
        open(proj.path('notes.json'), 'w').write(json.dumps(dict(folder='wedding family love', clips={}, updated={}))); assert TY.for_project(proj.folder)['fonts'] == s['fonts']      # new notes do not change a scheme that exists

    def test_new_style_words_or_a_refresh_choose_again(self, proj):
        a = TY.for_project(proj.folder); b = TY.for_project(proj.folder, style='elegant refined quiet'); assert b['style'] == ['elegant', 'refined', 'quiet'] and b['fonts']['display'] != a['fonts']['display']
        proj.write_json('notes.json', dict(folder='baby family wedding love', clips={}, updated={})); assert TY.for_project(proj.folder, refresh=True)['style'] == ['elegant', 'refined', 'quiet']       # a refresh keeps the user's own vibes
        TY.update(proj.folder, style=[]); assert TY.for_project(proj.folder, refresh=True)['vibes'].get('warm', 0) > 0.5

    def test_the_projects_palettes_and_notes_and_scene_labels_are_its_signals(self, proj):
        proj.write_json('notes.json', dict(folder='A trail in the mountains', clips={'CLIP_A': 'forest at dawn'}, updated={}))
        json.dump(dict(items=[dict(setting='mountain trail', description='a runner on a ridge', tags=['alpine'])]), open(proj.path('clips', 'CLIP_A', 'scenes.json'), 'w'))
        pal, text = TY.signals(proj.folder); assert len(pal) == 1 and 'mountains' in text and 'ridge' in text and 'forest' in text

    def test_a_damaged_file_is_replaced(self, proj):
        open(proj.path(TY.FILE), 'w').write('{broken'); assert 'fonts' in TY.for_project(proj.folder) and 'fonts' in json.load(open(proj.path(TY.FILE)))


class TestSpecimens:
    def test_the_scheme_specimen_is_a_picture_of_the_roles(self, tmp_path):
        from PIL import Image
        out = TY.specimen(TY.choose(TY.infer_vibes(text='trail')), str(tmp_path / 's.png'), dict(bg='#102030')); im = Image.open(out); assert im.size == (1400, 90 + 150 * len(TY.ROLES)) and im.getpixel((5, 5)) == (16, 32, 48)

    def test_the_library_specimen_shows_every_font(self, tmp_path):
        from PIL import Image
        im = Image.open(TY.library_specimen(str(tmp_path / 'l.png'))); assert im.size[0] == 3 * 760 and im.size[1] >= 7 * 190 and len(np.unique(np.asarray(im.convert('L')))) > 20


class TestCli:
    def args(self, name=None, **kw): return argparse.Namespace(**dict(dict(name=name, style=None, refresh=False, fonts=False, specimen=None), **kw))

    def test_fonts_lists_the_library(self, capsys):
        from strata360 import cli
        cli.cmd_typography(self.args(fonts=True)); out = capsys.readouterr().out; assert out.count('\n') == len(TY.FONT_TABLE) and 'oswald' in out and 'rugged' in out

    def test_fonts_can_also_write_the_specimen(self, capsys, tmp_path):
        from strata360 import cli
        cli.cmd_typography(self.args(fonts=True, specimen=str(tmp_path / 'lib.png'))); assert os.path.exists(tmp_path / 'lib.png') and 'specimen:' in capsys.readouterr().out

    def test_a_project_gets_its_scheme_printed_written_and_pictured(self, make_project, capsys):
        from strata360 import cli
        p = make_project(config=True); cli.cmd_typography(self.args(p.folder, style='elegant')); out = capsys.readouterr().out
        assert 'vibes:' in out and 'display' in out and 'numerals' in out and os.path.exists(p.path(TY.FILE)) and os.path.exists(p.path('typography_specimen.png'))


class TestEarlierFiles:
    """A typography.json written by an earlier version lacks the newer fields: it is rebuilt, keeping what the user had set."""
    @pytest.fixture
    def proj(self, make_project): return make_project(config=True)

    def legacy(self, proj, **extra):
        sch = TY.choose(TY.infer_vibes(text='trail')); sch.update(extra); json.dump(sch, open(proj.path(TY.FILE), 'w')); return sch

    def test_a_file_without_the_new_fields_is_rebuilt(self, proj):
        self.legacy(proj); s = TY.for_project(proj.folder); assert TY.REQUIRED <= set(s) and s['basis'] == 'project' and TY.REQUIRED <= set(json.load(open(proj.path(TY.FILE))))

    def test_a_legacy_style_given_as_text_is_kept_as_the_users_vibes(self, proj):
        self.legacy(proj, style='elegant refined'); s = TY.for_project(proj.folder); assert s['style'] == ['elegant', 'refined'] and s['basis'] == 'user'

    def test_a_complete_file_is_returned_as_it_is(self, proj):
        a = TY.for_project(proj.folder); b = TY.for_project(proj.folder); assert a == b
