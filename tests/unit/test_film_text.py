"""Text cards through the film (edit/film_text.py): the checks on what the model offers, the score and the planner's pick, and drawing the cards."""
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
