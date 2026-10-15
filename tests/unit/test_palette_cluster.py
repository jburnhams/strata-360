"""Project colour schemes (analysis/palette_cluster.py): the loss between a clip and a scheme, the facility-location solver, refitting a group, the cost sweep, the files and the CLI."""
import json, os

import numpy as np
import pytest

from strata360.analysis import palette as P
from strata360.analysis import palette_cluster as PC

GREEN, BLUE, MAGENTA, ORANGE, GREY = (30, 110, 40), (40, 70, 170), (150, 40, 130), (210, 120, 30), (110, 110, 112)


def doc(rgb, dark=(12, 12, 14)):
    """A palette document of footage that is `rgb` in its brighter part and near black in its darker part."""
    f = np.zeros((60, 120, 3), np.uint8); f[:, :90] = rgb; f[:, 90:] = dark
    return P.analyse_pixels([f] * 2)


def docs_of(**groups):
    """{clip id: palette doc}: `green=3` makes clips green1..green3."""
    colour = dict(green=GREEN, blue=BLUE, magenta=MAGENTA, orange=ORANGE, grey=GREY); out = {}
    for name, n in groups.items():
        for i in range(n): out[f'{name}{i + 1}'] = doc(tuple(int(np.clip(v + 6 * i, 0, 255)) for v in colour[name]))
    return out


class TestFeaturesAndLoss:
    def test_features_read_the_hue_and_whether_there_is_one(self):
        g = PC.features(doc(GREEN)); assert 95 < g['hue'] < 150 and g['found'] and g['chroma'] > 20 and len(g['swatches']) == 22
        assert not PC.features(doc(GREY))['found'] and PC.features(doc(GREY))['chroma'] == 0.0

    def test_hue_differences_wrap_round_the_circle(self):
        assert PC._hue_diff(350, 10) == 20 and PC._hue_diff(10, 350) == 20 and PC._hue_diff(0, 180) == 180

    def test_a_clip_costs_nothing_with_its_own_scheme_and_more_with_a_far_hue(self):
        g, g2, b = (PC.features(doc(x)) for x in (GREEN, (36, 116, 46), BLUE))
        assert PC.loss(g, g) == 0.0 and PC.loss(g, g2) < 0.1 and PC.loss(g, b) > 0.8 and PC.loss(g, b) > 8 * PC.loss(g, g2)

    def test_a_grey_clip_barely_cares_which_hue_its_scheme_has(self):
        grey, g, b = (PC.features(doc(x)) for x in (GREY, GREEN, BLUE))
        assert PC.loss(grey, g) < 0.4 and abs(PC.loss(grey, g) - PC.loss(grey, b)) < 0.3 and PC.loss(PC.features(doc(GREEN)), b) > PC.loss(grey, b)

    def test_the_loss_is_not_symmetric_and_the_matrix_has_a_zero_diagonal(self):
        fs = [PC.features(doc(x)) for x in (GREEN, GREY, BLUE)]; D = PC.matrix(fs)
        assert D.shape == (3, 3) and not D.diagonal().any() and (D >= 0).all() and D[0, 1] != D[1, 0]

    def test_the_names_of_hues(self):
        assert [PC.name_of(h, True) for h in (5, 35, 60, 120, 180, 230, 265, 290, 320, 350)] == ['red', 'orange', 'yellow', 'green', 'teal', 'blue', 'indigo', 'violet', 'magenta', 'red'] and PC.name_of(120, False) == 'neutral'


class TestSolve:
    def two_groups(self, n=5, within=0.1, between=3.0):
        D = np.full((2 * n, 2 * n), between); D[:n, :n] = within; D[n:, n:] = within; np.fill_diagonal(D, 0.0); return D

    def test_two_obvious_groups_become_two_schemes_unless_a_scheme_costs_more_than_merging(self):
        D = self.two_groups(); fac, assign, total = PC.solve(D, cost=0.5); assert len(fac) == 2 and len({assign[i] for i in range(5)}) == 1 and len({assign[i] for i in range(5, 10)}) == 1 and assign[0] != assign[5]
        fac, assign, total = PC.solve(D, cost=100.0); assert len(fac) == 1 and len(set(assign)) == 1

    def test_a_free_scheme_per_clip_gives_every_clip_its_own(self):
        D = self.two_groups(3); fac, assign, _ = PC.solve(D, cost=0.0, max_k=12); assert len(fac) >= 2 and sum(D[i, assign[i]] for i in range(6)) == pytest.approx(0.0, abs=1e-9) or len(fac) == 6

    def test_more_cost_never_means_more_schemes(self):
        rng = np.random.default_rng(1); pts = rng.random((20, 2)); D = np.linalg.norm(pts[:, None] - pts[None], axis=2)
        ks = [len(PC.solve(D, c)[0]) for c in (0.01, 0.05, 0.2, 0.5, 1.0, 5.0)]; assert ks == sorted(ks, reverse=True) and ks[-1] == 1

    def test_the_total_is_what_is_minimised_and_beats_any_single_scheme(self):
        D = self.two_groups(); fac, assign, total = PC.solve(D, cost=0.5)
        assert total == pytest.approx(sum(D[i, assign[i]] for i in range(10)) + 0.5 * len(fac)) and total < min(D[:, j].sum() + 0.5 for j in range(10))

    def test_the_number_of_schemes_is_capped(self):
        D = np.ones((8, 8)); np.fill_diagonal(D, 0.0); assert len(PC.solve(D, cost=0.0, max_k=3)[0]) <= 3

    def test_one_clip_is_one_scheme(self): assert PC.solve(np.zeros((1, 1)), 1.0)[:2] == ([0], [0])


class TestMergedHue:
    def test_the_hue_of_a_group_is_taken_from_the_window_with_most_weight(self):
        h, c, found = PC.merged_hue([doc(GREEN), doc((36, 118, 46)), doc((26, 104, 36)), doc(BLUE)]); assert found and 95 < h < 150

    def test_grey_footage_has_no_hue_of_its_own(self):
        h, c, found = PC.merged_hue([doc(GREY), doc((100, 100, 102))]); assert not found and h == P.FALLBACK_HUE and c == 0.0

    def test_hues_either_side_of_the_wrap_are_averaged_across_it(self):
        mk = lambda h: dict(colours=[dict(hex='#000000', share=0.5, L=50.0, C=40.0, h=h)])
        h, c, found = PC.merged_hue([mk(350.0), mk(10.0)]); assert found and min(h, 360 - h) < 5


class TestCluster:
    def test_two_hue_families_become_two_schemes_each_near_its_hue(self):
        r = PC.cluster(docs_of(green=4, blue=4), cost=2.0); assert r['k'] == 2 and sorted(len(s['members']) for s in r['schemes']) == [4, 4]
        by = {s['label']: s for s in r['schemes']}; assert any('green' in k for k in by) and any('blue' in k or 'violet' in k for k in by)
        for cid, i in r['assignment'].items(): assert (cid.startswith('green')) == ('green' in r['schemes'][i]['label'])
        assert r['loss_mean'] < 0.3

    def test_a_high_cost_gives_one_scheme_for_everything(self):
        r = PC.cluster(docs_of(green=3, blue=3), cost=1000.0); assert r['k'] == 1 and set(r['assignment'].values()) == {0} and len(r['schemes'][0]['members']) == 6

    def test_the_schemes_are_complete_palette_documents(self):
        s = PC.cluster(docs_of(green=3), cost=2.0)['schemes'][0]
        assert {'colours', 'backgrounds', 'mood', 'scheme', 'members', 'label', 'mean_loss'} <= set(s) and len(s['scheme']['swatches']) == 22 and s['scheme']['base'].startswith('#')

    def test_a_group_is_refit_so_its_scheme_serves_the_whole_group(self):
        docs = docs_of(green=3); one = PC.cluster(docs, cost=100.0)['schemes'][0]
        assert abs(PC._hue_diff(one['scheme']['hue'], PC.features(docs['green1'])['hue'])) < 25

    def test_a_scheme_is_named_by_its_hue_family_not_by_tone(self):
        r = PC.cluster(docs_of(green=3), cost=2.0); assert [x['label'] for x in r['schemes']] == ['green']

    def test_every_label_is_unique_even_for_two_schemes_of_one_hue_family(self):
        docs = docs_of(green=3); docs.update({f'lime{i}': doc((60 + 5 * i, 130, 20)) for i in range(3)}); r = PC.cluster(docs, cost=0.01)
        labels = [s['label'] for s in r['schemes']]; assert len(labels) == len(set(labels))

    def test_without_palettes_it_says_so(self):
        with pytest.raises(ValueError, match='palette stage'): PC.cluster({})

    def test_the_sweep_never_shows_more_schemes_for_more_cost(self):
        s = PC.sweep(docs_of(green=3, blue=3, magenta=2), costs=(0.1, 1.0, 3.0, 50.0)); ks = [k for _, k, _ in s]
        assert ks == sorted(ks, reverse=True) and ks[-1] == 1 and [l for *_, l in s] == sorted(l for *_, l in s)

    def test_a_single_clip_is_one_scheme(self): assert PC.cluster(docs_of(green=1))['k'] == 1


class TestFilesAndLookup:
    @pytest.fixture
    def proj(self, make_project):
        p = make_project(config=True)
        for cid, rgb in (('CLIP_A', GREEN), ('CLIP_B', (36, 116, 46)), ('CLIP_C', BLUE), ('CLIP_D', (46, 76, 176))):
            p.add_clip(cid); json.dump(doc(rgb), open(p.path('clips', cid, 'palette.json'), 'w'))
        return p

    def test_it_reads_the_clips_that_have_a_palette(self, proj):
        assert sorted(PC.load_docs(proj.folder)) == ['CLIP_A', 'CLIP_B', 'CLIP_C', 'CLIP_D']

    def test_run_writes_the_file_and_a_clip_gets_its_project_scheme(self, proj):
        r = PC.run(proj.folder, cost=2.0); assert os.path.exists(proj.path(PC.FILE)) and PC.load(proj.folder)['k'] == r['k'] == 2
        a, b, c = (PC.for_clip(proj.folder, x) for x in ('CLIP_A', 'CLIP_B', 'CLIP_C')); assert a['cluster'] == b['cluster'] != c['cluster'] and 'green' in a['label'] and a['scheme']['base'] == b['scheme']['base']
        assert {'scheme', 'mood', 'colours', 'backgrounds'} <= set(a)

    def test_the_document_works_wherever_a_palette_is_used(self, proj):
        PC.run(proj.folder); d = PC.for_clip(proj.folder, 'CLIP_A'); assert 'complement' in P.for_prompt(d) and d['scheme']['base'] in P.for_prompt(d)

    def test_a_clip_that_is_not_in_the_file_keeps_its_own_palette(self, proj):
        PC.run(proj.folder); proj.add_clip('CLIP_NEW'); json.dump(doc(ORANGE), open(proj.path('clips', 'CLIP_NEW', 'palette.json'), 'w'))
        d = PC.for_clip(proj.folder, 'CLIP_NEW'); assert 'cluster' not in d and d['scheme']['base'] == doc(ORANGE)['scheme']['base']

    def test_without_the_file_each_clip_has_its_own_and_without_either_none(self, proj):
        assert PC.for_clip(proj.folder, 'CLIP_A')['scheme']['base'] == doc(GREEN)['scheme']['base'] and 'cluster' not in PC.for_clip(proj.folder, 'CLIP_A') and PC.for_clip(proj.folder, 'CLIP_NOPE') is None and PC.load(proj.folder) is None

    def test_a_damaged_file_is_ignored(self, proj):
        open(proj.path(PC.FILE), 'w').write('{broken'); assert PC.load(proj.folder) is None and 'cluster' not in PC.for_clip(proj.folder, 'CLIP_A')

    def test_the_file_is_replaced_whole(self, proj):
        PC.run(proj.folder, cost=0.1); PC.run(proj.folder, cost=1000.0); assert PC.load(proj.folder)['k'] == 1 and not os.path.exists(proj.path(PC.FILE + '.tmp'))


class TestCli:
    def args(self, folder, cost=2.0, sweep=False):
        import argparse
        return argparse.Namespace(name=folder, cost=cost, sweep=sweep)

    @pytest.fixture
    def proj(self, make_project):
        p = make_project(config=True)
        for cid, rgb in (('CLIP_A', GREEN), ('CLIP_B', BLUE)): p.add_clip(cid); json.dump(doc(rgb), open(p.path('clips', cid, 'palette.json'), 'w'))
        return p

    def test_it_clusters_prints_the_schemes_and_writes_the_file(self, proj, capsys):
        from strata360 import cli
        cli.cmd_palette_schemes(self.args(proj.folder, cost=0.5)); out = capsys.readouterr().out
        assert '2 schemes for 2 clips at cost 0.5' in out and 'green' in out and os.path.exists(proj.path(PC.FILE))

    def test_two_clips_do_not_justify_two_schemes_at_the_default_cost(self, proj, capsys):
        from strata360 import cli
        cli.cmd_palette_schemes(self.args(proj.folder)); assert '1 schemes for 2 clips at cost 2.0' in capsys.readouterr().out

    def test_the_sweep_prints_and_writes_nothing(self, proj, capsys):
        from strata360 import cli
        cli.cmd_palette_schemes(self.args(proj.folder, sweep=True)); out = capsys.readouterr().out
        assert 'what a scheme costs' in out and 'cost  0.10' in out and not os.path.exists(proj.path(PC.FILE))

    def test_without_palettes_it_says_which_stage_makes_them(self, make_project):
        from strata360 import cli
        p = make_project(config=True)
        with pytest.raises(SystemExit, match='palette stage'): cli.cmd_palette_schemes(self.args(p.folder))
