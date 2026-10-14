"""Text cards through the film (edit/film_text.py): the checks on what the model offers, the score and the planner's pick, and drawing the cards."""
import os
import numpy as np
from strata360.edit import film_text as F
from strata360.render import captions as C

FACTS = [dict(t=20.0, clip='x', day=2, local_time='20:08', km=75.2, percent=20.5, elapsed_h=13.5, altitude_m=310.0, daylight='night', gradient_pct=1.0), dict(t=90.0, clip='y', day=3, local_time='06:30', km=190.0, percent=52.9, elapsed_h=37.4, altitude_m=420.0, daylight='day', gradient_pct=-2.0)]
QUOTES = [dict(id='q1', t=50.0, kind='speech', text="the last one lost my mind basically overnight, um"), dict(id='q2', t=120.0, kind='vo', text='I pushed through the second night.')]


def test_progress_cards_may_only_use_numbers_the_track_gives():
    opts, drop = F.validate([dict(type='progress', t=20.4, title='DAY 2', meta='KM 75 | 20.5%', worth=7), dict(type='progress', t=20.0, title='DAY 9', meta='KM 75'), dict(type='progress', t=90.0, lines=[dict(role='title', text='HALFWAY'), dict(role='meta', text='06:30')], worth=9)], FACTS, QUOTES, 250.0)
    assert [o['t'] for o in opts] == [20.0, 90.0] and opts[0]['type'] == 'progress' and opts[0]['worth'] == 7.0 and opts[1]['lines'][0]['text'] == 'HALFWAY' and any('9' in d for d in drop)     # (20.4 is moved to the fact's own time)


def test_a_quote_must_be_a_run_of_the_words_of_its_candidate():
    ok, drop = F.validate([dict(type='quote', t=50.0, id='q1', title='The last one lost my mind', worth=8), dict(type='quote', t=50.0, id='q1', title='lost my mind completely'), dict(type='quote', t=120.0, id='nope', title='x y z w'), dict(type='quote', t=120.0, id='q2', title='I pushed', worth=3)], FACTS, QUOTES, 250.0)
    assert len(ok) == 1 and ok[0]['source'] == 'q1' and ok[0]['dur_s'] >= 2.6 and len(drop) == 3


def test_cards_in_the_first_and_last_seconds_are_refused():
    ok, drop = F.validate([dict(type='progress', t=3.0, title='DAY 1'), dict(type='progress', t=249.0, title='DAY 9')], FACTS, QUOTES, 250.0); assert ok == [] and len(drop) == 2


def test_one_broken_option_costs_only_itself():
    got = F.parse_options('{"options": [{"t": 1, "lines": [{"role": "meta": "x"}]}, {"t": 2, "title": "A", },]}'); assert got == [{'t': 2, 'title': 'A'}]
    assert F.parse_options('{"options": [{"t": 5}]}') == [{'t': 5}]


def _o(t, worth, verdict='ok', exc=3.0, risk=3.0, dur=3.0): return dict(id=f'o{t}', type='quote', t=t, dur_s=dur, lines=[dict(role='title', text='x')], worth=worth, shot=dict(verdict=verdict, excitement=exc, obscure_risk=risk, calm='top'))


def test_the_score_rewards_worth_and_penalises_covering_an_exciting_shot():
    calm = F.score(_o(10, 8, exc=2, risk=2)); busy = F.score(_o(10, 8, exc=9, risk=8)); avoid = F.score(_o(10, 8, 'avoid', 9, 9))
    assert calm > busy > avoid and avoid < 4.0 and calm > 7.0


def test_the_planner_picks_the_best_apart_and_weighs_an_avoid_rather_than_vetoing_it():
    opts = [dict(o, score=F.score(o)) for o in (_o(20, 9), _o(22, 8), _o(60, 7), _o(100, 9, 'avoid', 9, 9), _o(140, 6), _o(143, 5))]
    chosen = F.pick(opts, 250.0, per_minute=2.0, gap=12.0)
    assert [c['t'] for c in chosen if c['t'] != 100] == [20, 60, 140] and len(chosen) <= 8 and F.score(opts[3]) < F.score(_o(100, 9, 'ok', 9, 9))
    assert F.pick(opts, 250.0, per_minute=0.25, gap=12.0)[0]['t'] == 20 and len(F.pick(opts, 250.0, per_minute=0.25)) == 1


def test_how_much_a_placed_card_blocks_lowers_its_score_smoothly():
    base = _o(10, 8); scores = [F.score(dict(base, blocking=dict(score=b))) for b in (0.0, 2.5, 5.0, 7.5, 10.0)]
    assert all(x > y for x, y in zip(scores, scores[1:])) and F.score(base) > 0 and scores[0] > scores[-1] + 2.0


def test_a_card_is_drawn_only_while_it_is_on():
    spec = dict(elements=[dict(text='HALFWAY', font='anton', size=0.2, x=0.5, y=0.4, fill=dict(type='solid', c1='#ffffff'), **{'in': 'fade', 'out': 'fade'}, in_s=0.3)], timing=dict(start_s=0.0, end_s=2.6))
    cards = C.Cards([dict(t=10.0, dur_s=2.6, spec=spec)], 320, 180, 25.0); img = np.full((180, 320, 3), 40, np.uint8)
    assert cards.apply(img, 100) is img and cards.apply(img, 500) is img
    on = cards.apply(img, int(11.0 * 25)); assert (on != img).any() and on.max() > 200 and cards.apply(img, int(11.0 * 25), bgr=True).shape == img.shape


# ---- reading the models' answers, the files the planner is given, and the pieces that need the preview

def test_the_models_answer_is_found_inside_chatter_and_trailing_commas_are_forgiven():
    assert F.parse('Sure! {"a": 1, "b": [1, 2,],} Hope that helps') == {'a': 1, 'b': [1, 2]}
    assert F.parse('no object here') is None and F.parse('{"a": ') is None


def test_options_are_read_from_a_cards_key_and_from_a_bare_list():
    assert F.parse_options('{"cards": [{"t": 9}]}') == [{'t': 9}]
    assert F.parse_options('Here you go: [{"t": 1}, {"t": 2}]') == [{'t': 1}, {'t': 2}]
    assert F.parse_options('nothing useful') == []


def test_what_was_heard_is_what_overlaps_the_card():
    cues = [dict(t0=0.0, t1=4.0, kind='speech', text='early'), dict(t0=10.0, t1=14.0, kind='vo', text='middle'), dict(t0=20.0, t1=22.0, kind='speech', text='late')]
    assert F.heard_at(cues, 12.0, 16.0) == 'vo: middle' and F.heard_at(cues, 3.0, 11.0) == 'speech: early | vo: middle'
    assert F.heard_at(cues, 5.0, 9.0) == 'nothing said' and F.heard_at(cues, 4.0, 10.0) == 'nothing said'          # touching is not overlapping
    assert len(F.heard_at([dict(t0=0.0, t1=9.0, kind='speech', text='word ' * 200)], 0.0, 9.0)) == 300


def test_the_latest_preview_is_the_newest_film_folder_with_a_playlist(project):
    import os
    root = project.path('preview'); assert F.latest_preview(project.folder) is None
    for name, with_playlist, mtime in (('film-old', True, 1_000), ('film-new', True, 2_000), ('film-broken', False, 3_000), ('other-new', True, 4_000)):
        d = os.path.join(root, name); os.makedirs(d)
        if with_playlist: open(os.path.join(d, 'index.m3u8'), 'w').write('#EXTM3U'); os.utime(d, (mtime, mtime))
    assert os.path.basename(F.latest_preview(project.folder)) == 'film-new'


def test_the_frames_of_the_preview_are_read_from_ffmpeg(fake_run):
    fake_run.returns['ffmpeg'] = bytes(960 * 540 * 3)
    frames = F.frames_of_film('/key', 10.0, 4.0, n=3)
    assert len(frames) == 3 and frames[0].shape == (540, 960, 3) and frames[0].dtype == np.uint8
    assert [c[c.index('-ss') + 1] for c in fake_run.calls] == ['10.20', '12.00', '13.80'] and all(c[c.index('-i') + 1].endswith('index.m3u8') for c in fake_run.calls)


def test_a_preview_that_cannot_be_read_is_an_error(fake_run):
    import pytest
    fake_run.returns['ffmpeg'] = b'short'
    with pytest.raises(RuntimeError, match='could not read the preview'): F.frames_of_film('/key', 0.0, 1.0)


class _Model:
    def __init__(self, text): self.text, self.asked = text, []
    def chat(self, messages, max_tokens, temperature): self.asked.append(messages[0]['content']); return self.text
    def ask(self, prompt, images, max_tokens): self.asked.append((prompt, list(images))); return self.text


def test_the_text_model_is_given_the_facts_and_quotes_and_its_answer_is_checked():
    model = _Model('{"options": [{"type": "progress", "t": 20.0, "title": "DAY 2", "meta": "KM 75", "worth": 8, "why": "a milestone"}, {"type": "progress", "t": 20.0, "title": "KM 999"}]}')
    opts, drop = F.propose(FACTS, QUOTES, 250.0, model, n=5)
    prompt = model.asked[0]
    assert 'day 2 20:08 km 75.2' in prompt and 'q1 t=50.0s speech: the last one lost my mind' in prompt and 'up to 5 options' in prompt and '250 seconds' in prompt
    assert [o['lines'][0]['text'] for o in opts] == ['DAY 2'] and opts[0]['worth_why'] == 'a milestone' and len(drop) == 1


def test_a_film_without_facts_or_quotes_says_so_to_the_model():
    model = _Model('{"options": []}'); assert F.propose([], [], 100.0, model) == ([], []) and model.asked[0].count('(none)') == 2


def test_a_card_with_no_time_or_a_bad_worth_is_handled():
    ok, drop = F.validate([dict(type='progress', title='DAY 2'), dict(type='progress', t='soon', title='DAY 2'), dict(type='progress', t=20.0, title='DAY 2', worth='lots'), dict(type='progress', t=20.0, title='DAY 2', worth=99), dict(type='progress', t=20.0)], FACTS, QUOTES, 250.0)
    assert drop[:2] == ['no time', 'no time'] and len(drop) == 3 and [o['worth'] for o in ok] == [5.0, 10.0]


def test_a_progress_card_far_from_any_fact_is_refused():
    ok, drop = F.validate([dict(type='progress', t=60.0, title='DAY 2')], FACTS, QUOTES, 250.0); assert ok == [] and 'no facts near' in drop[0]
    ok, drop = F.validate([dict(type='progress', t=20.0, title='DAY 2')], [], QUOTES, 250.0); assert ok == [] and 'no facts near' in drop[0]


def test_a_quote_card_lasts_longer_for_more_words_but_not_without_limit():
    q = dict(id='q', t=30.0, kind='vo', text=' '.join(f'w{i}' for i in range(40)))
    short, _ = F.validate([dict(type='quote', t=30.0, id='q', title='w1 w2 w3')], [], [q], 250.0); long, _ = F.validate([dict(type='quote', t=30.0, id='q', title=' '.join(f'w{i}' for i in range(12)))], [], [q], 250.0)
    too_many, drop = F.validate([dict(type='quote', t=30.0, id='q', title=' '.join(f'w{i}' for i in range(13)))], [], [q], 250.0)
    assert short[0]['dur_s'] == 2.6 and long[0]['dur_s'] == 5.7 and too_many == [] and 'not a run' in drop[0]


class _Shots:
    """frames_of_film stand-in: three blank frames."""
    def __call__(self, key_dir, t0, dur, n=5): return [np.zeros((540, 960, 3), np.uint8) for _ in range(n)]


def test_the_vision_model_rates_the_shot_under_a_card(tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'frames_of_film', _Shots())
    model = _Model('{"excitement": 8, "obscure_risk": 99, "calm": "top", "verdict": "avoid", "why": "a fall"}')
    cues = [dict(t0=9.0, t1=12.0, kind='speech', text='oh no')]; opt = dict(t=10.0, dur_s=3.0, lines=[dict(role='title', text='HALFWAY'), dict(role='meta', text='KM 183')])
    got = F.judge_shot(opt, '/key', cues, model, str(tmp_path))
    assert got == dict(excitement=8.0, obscure_risk=10.0, calm='top', verdict='avoid', why='a fall')                    # (a rating above 10 is held at 10)
    prompt, images = model.asked[0]; assert 'HALFWAY / KM 183' in prompt and 'speech: oh no' in prompt and len(images) == 3 and all(os.path.exists(p) for p in images)


def test_an_unreadable_answer_about_the_shot_means_an_ordinary_one(tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'frames_of_film', _Shots())
    for text in ('I cannot tell', '{"excitement": "high", "verdict": "perfect"}'):
        got = F.judge_shot(dict(t=10.0, dur_s=3.0, lines=[dict(role='title', text='x')]), '/key', [], _Model(text), str(tmp_path))
        assert got['excitement'] == 5.0 and got['obscure_risk'] == 5.0 and got['verdict'] == 'ok' and got['calm'] == 'none'


def _stored(project, plan_key='K', picked=()):
    opts = [dict(id=f'o{i}', type='quote', t=20.0 + 40 * i, dur_s=2.6, lines=[dict(role='title', text=f'line {i}')], worth=6.0, score=6.5, shot=dict(verdict='good', excitement=3.0, obscure_risk=2.0, calm='top', why='x'), blocking=dict(score=1.5, what='the hand') if i == 0 else None) for i in range(3)]
    project.write_json('film_text_options.json', dict(plan_key=plan_key, options=opts))
    project.write_json('film_text.json', dict(cards=[dict(t=opts[i]['t'], lines=opts[i]['lines']) for i in picked]))


def test_the_planner_is_given_the_options_and_which_were_picked(project, monkeypatch):
    from strata360.render import preview as PVW
    monkeypatch.setattr(PVW, 'plan_key', lambda folder, plan: 'K'); _stored(project, picked=(1,))
    got = F.for_plan(project.folder, {})
    assert [o['id'] for o in got['text_options']] == ['o0', 'o1', 'o2'] and got['text_cards'] == ['o1']
    assert got['text_options'][0]['blocking'] == dict(score=1.5, what='the hand') and got['text_options'][1]['blocking'] is None and got['text_options'][0]['shot']['calm'] == 'top'


def test_options_made_for_another_plan_are_flagged_and_missing_files_give_nothing(project, monkeypatch):
    from strata360.render import preview as PVW
    assert F.for_plan(project.folder, {}) == {}
    monkeypatch.setattr(PVW, 'plan_key', lambda folder, plan: 'NEW'); _stored(project, plan_key='OLD'); assert F.for_plan(project.folder, {}) == dict(text_options_stale=True)


def test_no_film_text_file_yet_means_nothing_is_picked(project, monkeypatch):
    import os
    from strata360.render import preview as PVW
    monkeypatch.setattr(PVW, 'plan_key', lambda folder, plan: 'K'); _stored(project); os.remove(project.path('film_text.json'))
    got = F.for_plan(project.folder, {}); assert len(got['text_options']) == 3 and got['text_cards'] == []


def test_attaching_puts_the_options_in_the_saved_plan_and_drops_the_old_ones(project, monkeypatch):
    from strata360.edit import project as PJ
    from strata360.render import preview as PVW
    monkeypatch.setattr(PVW, 'plan_key', lambda folder, plan: 'K'); _stored(project, picked=(2,))
    PJ.save(project.folder, dict(plan=dict(segments=[], text_options_stale=True, text_cards=['old']), settings={}, overrides={}))
    F.attach(project.folder); plan = PJ.load(project.folder)['plan']
    assert plan['text_cards'] == ['o2'] and len(plan['text_options']) == 3 and 'text_options_stale' not in plan


def test_attaching_without_a_plan_changes_nothing(project):
    from strata360.edit import project as PJ
    F.attach(project.folder); assert PJ.load(project.folder)['plan'] is None
