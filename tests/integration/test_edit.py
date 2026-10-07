"""Tests for the edit technique library and the joint optimiser (README 16, tests P5-24 to P5-31 and P5-37). Synthetic data only.
Run with the project venv:  .venv/bin/python tests/test_edit.py"""
import json, os, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))
import numpy as np
from strata360.edit import techniques as T, optimise as O

LIB = {k: v for k, v in T.load().items() if k != 'person_hold'}      # person_hold is offered only where a clip's camera list has a person camera (chrono.assign_techniques); this older optimiser has no camera lists


def music(bpm=120, seconds=64):
    beats = int(seconds * bpm / 60)
    return O.Music(bpm=bpm, beats=beats, bar_beats=4, sections=[(0, beats // 8, 0.3), (beats // 8, beats * 3 // 8, 0.5), (beats * 3 // 8, beats * 3 // 4, 0.85), (beats * 3 // 4, beats, 0.3)])


def cands(n=45, seed=3):
    rng = np.random.default_rng(seed); out = []
    for i in range(n):
        speech = 1.0 if rng.random() < 0.08 else 0.0
        f = dict(steady=float(rng.uniform(0.2, 1.0)), clear_nadir=float(rng.uniform(0.6, 1.0) if rng.random() < 0.55 else rng.uniform(0, 0.4)),
                 open_ground=float(rng.uniform(0.2, 1.0)), canopy=float(rng.uniform(0.5, 1.0) if rng.random() < 0.3 else rng.uniform(0, 0.4)),
                 subject=float(rng.uniform(0.4, 1.0) if rng.random() < 0.6 else rng.uniform(0, 0.3)), speech=speech, protagonist=float(rng.uniform(0, 1)),
                 low_obstruction=float(rng.uniform(0.3, 1.0)), resolution=float(rng.uniform(0.5, 1.0)))
        if speech: f['steady'] = 0.8
        out.append(O.Candidate(id=f'c{i:02d}', clip=f'clip{i // 3}', quality=float(rng.uniform(0.3, 1.0)), energy=float(rng.uniform(0.2, 0.9)),
                               min_dur=3.0 if speech else float(rng.uniform(1.0, 3.0)), max_dur=12.0 if speech else float(rng.uniform(4.0, 14.0)), features=f))
    return out


def test_library_validates_and_every_technique_makes_a_path():
    from strata360.render.camera import CameraPath, limits_report
    assert T.validate(LIB) and len(LIB) >= 14
    rng = np.random.default_rng(1)
    for t in LIB.values():
        d = T.instantiate(t, t.dideal, rng); f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False); json.dump(d, f); f.close()
        ts = np.arange(0, t.dideal + 1e-6, 0.02); p = CameraPath.from_json(f.name).evaluate(ts, [np.eye(3)] * len(ts), 50.0); r = limits_report(p, 50.0)
        assert all(np.isfinite(list(r.values()))), t.id
        if t.dialogue_ok: assert r['max_yaw_rate_deg_s'] < 1 and r['max_roll_rate_deg_s'] < 1 and r['max_fov_rate_deg_s'] < 12, (t.id, r)      # no showy motion on dialogue


def test_plan_is_valid_exact_and_on_beats():
    m = music(); cs = cands(); p = O.plan(cs, LIB, m, O.Settings(seed=1))
    assert O.violations(p, LIB, m) == [], O.violations(p, LIB, m)
    assert sum(s.beats for s in p) == m.beats and p[0].start == 0
    assert all(s.start == sum(x.beats for x in p[:i]) for i, s in enumerate(p))
    for s in p:
        assert s.tech.dmin - 1e-9 <= s.beats * m.beat_s <= s.tech.dmax + 1e-9
        if s.tech.beats == 'bar': assert s.beats % m.bar_beats == 0
        assert s.parts and 'total' in s.parts


def test_variety_beats_a_greedy_baseline_and_respects_limits():
    m = music(); ents_p, ents_g, runs_p, runs_g = [], [], [], []
    for seed in range(6):
        cs = cands(seed=10 + seed); p = O.plan(cs, LIB, m, O.Settings(seed=seed)); g = O.baseline_greedy(cs, LIB, m)
        assert O.violations(p, LIB, m) == []
        vp, vg = O.variety_report(p, LIB, m), O.variety_report(g, LIB, m); ents_p.append(vp['entropy']); ents_g.append(vg['entropy']); runs_p.append(vp['longest_run']); runs_g.append(vg['longest_run'])
        for tid, share in vp['shares'].items(): assert share <= LIB[tid].max_share * 1.25 + 1e-9, (tid, share)
        assert vp['hero_count'] <= 6 and (vp['min_repeat_distance'] is None or vp['min_repeat_distance'] >= 1)
    print(f'    entropy: planner {np.mean(ents_p):.2f} vs greedy {np.mean(ents_g):.2f};  longest run: {np.mean(runs_p):.1f} vs {np.mean(runs_g):.1f}')
    assert np.mean(ents_p) > np.mean(ents_g) + 0.15, (ents_p, ents_g)


def test_pacing_follows_the_music_and_the_toolbox_is_used():
    m = music(); calm, busy, distinct, heroes, dlg = [], [], [], [], []
    for seed in range(6):
        cs = cands(seed=20 + seed); p = O.plan(cs, LIB, m, O.Settings(seed=seed))
        for s in p:
            (busy if m.energy_at(s.start) >= 0.8 else calm if m.energy_at(s.start) <= 0.35 else []).append(s.beats * m.beat_s)
        v = O.variety_report(p, LIB, m); distinct.append(v['distinct']); heroes.append(v['hero_count']); dlg.append(v['shares'].get('dialogue_hold', 0.0))
    print(f'    mean shot length: calm {np.mean(calm):.1f} s, chorus {np.mean(busy):.1f} s;  distinct techniques {np.mean(distinct):.1f};  hero shots {np.mean(heroes):.1f};  dialogue share {np.mean(dlg):.2f}')
    assert np.mean(busy) < 0.8 * np.mean(calm), 'cuts should be faster when the music is intense'
    assert np.mean(distinct) >= 7 and np.mean(heroes) >= 2, 'the toolbox (including hero effects) should actually be used'
    assert max(dlg) <= 0.15 * 1.25 + 1e-9, 'dialogue is capped in a music-driven edit'


def test_seeds_reproduce_and_differ():
    m = music(); cs = cands()
    a, b = O.plan(cs, LIB, m, O.Settings(seed=5)), O.plan(cs, LIB, m, O.Settings(seed=5))
    assert [(s.cand.id, s.tech.id, s.beats, s.variant_seed) for s in a] == [(s.cand.id, s.tech.id, s.beats, s.variant_seed) for s in b], 'same seed must give the same plan'
    plans = [O.plan(cs, LIB, m, O.Settings(seed=i)) for i in range(1, 7)]
    diffs = [O.difference(x, y) for i, x in enumerate(plans) for y in plans[i + 1:]]
    scores = [O.evaluate(p, LIB, m)['score'] for p in plans]
    print(f'    mean pairwise difference {np.mean(diffs):.2f}; scores {min(scores):.1f}..{max(scores):.1f}')
    assert np.mean(diffs) > 0.4, 'different seeds should give visibly different edits'
    assert min(scores) > 0.85 * max(scores), 'while their objective stays close to the best'


def test_annealing_never_makes_a_plan_worse():
    m = music(); cs = cands()
    p0 = O.plan(cs, LIB, m, O.Settings(seed=2, sa_iters=0)); p1 = O.plan(cs, LIB, m, O.Settings(seed=2, sa_iters=1200))
    assert O.evaluate(p1, LIB, m)['score'] >= O.evaluate(p0, LIB, m)['score'] - 1e-9 and O.violations(p1, LIB, m) == []


def test_hard_content_rules():
    m = music(); cs = cands(); by = {c.id: c for c in cs}
    for seed in range(4):
        for s in O.plan(cs, LIB, m, O.Settings(seed=seed)):
            f = s.cand.features
            if s.tech.family == 'planet' and s.tech.id != 'tunnel_up': assert f['clear_nadir'] >= 0.6 and f['steady'] >= 0.3, (s.tech.id, f)
            if s.tech.id == 'tunnel_up': assert f['canopy'] >= 0.5
            if s.tech.id == 'spin_roll': assert f['low_obstruction'] >= 0.5
            if s.tech.id == 'hold_wide': assert f['steady'] >= 0.3
            if s.cand.speech: assert s.tech.dialogue_ok, (s.cand.id, s.tech.id)
            if s.tech.id == 'dialogue_hold': assert s.cand.speech and f['steady'] >= 0.5


def test_pins_bans_budgets_and_locked_sections():
    m = music(); cs = cands(); base = O.plan(cs, LIB, m, O.Settings(seed=3))
    p = O.plan(cs, LIB, m, O.Settings(seed=3, bans_techs=frozenset({'planet_fill', 'spin_roll'}), budgets={'planet_globe': 0}))
    assert not {s.tech.id for s in p} & {'planet_fill', 'spin_roll', 'planet_globe'}
    used = {s.cand.id for s in base}; ban = frozenset(list(used)[:5]); p2 = O.plan(cs, LIB, m, O.Settings(seed=3, bans_cands=ban))
    assert not {s.cand.id for s in p2} & ban
    lock = {s.start: (s.cand.id, s.tech.id, s.beats) for s in base[:3]}                                # lock the first three segments and re-plan the rest
    p3 = O.plan(cs, LIB, m, O.Settings(seed=99, fixed=lock))
    assert [(s.cand.id, s.tech.id, s.beats) for s in p3[:3]] == [(s.cand.id, s.tech.id, s.beats) for s in base[:3]], 'locked sections must be kept exactly'
    assert O.violations(p3, LIB, m) == [] and sum(s.beats for s in p3) == m.beats


def test_infeasible_requests_name_the_binding_constraint():
    m = music(seconds=600); short = cands(n=6)
    try: O.plan(short, LIB, m, O.Settings(seed=1)); raise SystemExit('expected Infeasible')
    except O.Infeasible as e: assert 'not enough footage' in str(e), str(e)
    try: O.plan(cands(), LIB, music(), O.Settings(bans_techs=frozenset(LIB.keys()))); raise SystemExit('expected Infeasible')
    except O.Infeasible as e: assert 'no feasible' in str(e), str(e)


def test_alternatives_differ():
    m = music(); alts = O.alternatives(cands(), LIB, m, O.Settings(seed=0), n=3, min_diff=0.3)
    assert len(alts) == 3 and all(O.difference(a, b) >= 0.3 for i, a in enumerate(alts) for b in alts[i + 1:]) and all(O.violations(a, LIB, m) == [] for a in alts)


def test_speed():
    t0 = time.time(); O.plan(cands(n=100, seed=8), LIB, music(seconds=120), O.Settings(seed=1)); el = time.time() - t0
    print(f'    100 candidates, 120 s of music: {el:.1f} s'); assert el < 90


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]; fails = 0
    for f in fns:
        t0 = time.time()
        try: f(); print(f'ok   {f.__name__} ({time.time() - t0:.1f} s)')
        except (AssertionError, O.Infeasible) as e: fails += 1; print(f'FAIL {f.__name__}: {e!r}'[:400])
    print(f'{len(fns) - fails}/{len(fns)} passed'); sys.exit(1 if fails else 0)
