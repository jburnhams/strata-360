"""The edit in `<project>/project.json` (section `edit`): settings, the current plan, and the user's overrides.

The plan is a pure function of (candidates, settings, overrides, seed): `propose` recomputes it, and everything the user changes is recorded as an override so a re-plan never loses it.

  edit.settings   length_s, bpm, bar_beats, seed, wpm, style
  edit.overrides  locked       windows kept exactly: {wid, clip, start_s, beats, cand_id, tech}
                  tech_force   {wid: technique}: this window must use that technique
                  bans_cands   stretches (candidate ids) never to use
                  bans_techs   techniques never to use
                  clip_weight  {clip id: factor}: more (>1) or less (<1) of a clip
                  transitions  {wid of the incoming window: cut | dissolve | dip | whip}: the transition into that window (otherwise chosen by rule, edit/transitions.py)
  edit.plan       the ordered segments (with the techniques that fit each, for the GUI), totals and warnings

A window's id (`wid`) is "<clip id>@<start in the clip, seconds, 2 decimals>"; overrides whose window no longer exists are reported as orphaned, not silently applied."""
import datetime as dt, glob, json, os
from strata360.pipeline import config
from strata360.edit import techniques as TQ, chrono as CH, optimise as O

DEFAULT_SETTINGS = dict(length_s=90.0, bpm=120.0, bar_beats=4, seed=1, wpm=145.0, style='')
EMPTY_OVERRIDES = dict(locked=[], tech_force={}, bans_cands=[], bans_techs=[], clip_weight={}, transitions={})


def _path(folder): return os.path.join(config.race_dir(folder), 'project.json')


def _read(folder):
    p = _path(folder)
    try: return json.load(open(p)) if os.path.exists(p) else {}
    except ValueError: return {}


def load(folder):
    e = _read(folder).get('edit') or {}
    return dict(settings={**DEFAULT_SETTINGS, **(e.get('settings') or {})}, overrides={**json.loads(json.dumps(EMPTY_OVERRIDES)), **(e.get('overrides') or {})}, plan=e.get('plan'))


def save(folder, edit):
    d = _read(folder); d['edit'] = edit; p = _path(folder); os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f'{p}.{os.getpid()}.tmp'; json.dump(d, open(tmp, 'w'), indent=1); os.replace(tmp, p); return edit


def load_clips(folder):
    """Clip dicts for the planner from the per-clip candidates.json; (clips, ids of clips that have no candidates yet)."""
    rd = config.race_dir(folder); clips = []; missing = []
    for d in sorted(glob.glob(os.path.join(rd, 'clips', '*', ''))):
        try: cj = json.load(open(d + 'clip.json'))
        except (OSError, ValueError): continue
        cp = d + 'candidates.json'
        if not os.path.exists(cp): missing.append(cj['clip_id']); continue
        cd = json.load(open(cp)); clips.append(dict(id=cj['clip_id'], start_utc=cj['time']['start_utc'], duration_s=cj['video']['source_frames'] / cj['video']['nominal_fps'], candidates=cd['candidates'], unusable=cd.get('unusable') or []))
    return clips, missing


def _planner(edit, lib, prev_plan):
    s = edit['settings']; o = edit['overrides']; beats = int(round(s['length_s'] * s['bpm'] / 60.0)); beats -= beats % int(s['bar_beats'])            # a whole number of bars
    music = O.Music(bpm=float(s['bpm']), beats=beats, bar_beats=int(s['bar_beats']))
    prefer = {g['id']: g['technique'] for g in (prev_plan or {}).get('segments', [])}
    st = CH.Settings(seed=int(s['seed']), locked=tuple(o['locked']), tech_force=dict(o['tech_force']), prefer=prefer, bans_cands=frozenset(o['bans_cands']), bans_techs=frozenset(o['bans_techs']),
                     clip_weight={k: float(v) for k, v in o['clip_weight'].items()})
    return music, st


def serialise(segs, clips, music, lib, locked_wids=()):
    info = {c['id']: c for c in clips}; out = []
    for i, sg in enumerate(segs):
        c = info[sg.cand.clip]; t0 = dt.datetime.fromisoformat(c['start_utc'].replace('Z', '+00:00')) + dt.timedelta(seconds=sg.clip_start_s); dur = sg.beats * music.beat_s
        out.append(dict(id=sg.parts['wid'], index=i, clip=sg.cand.clip, cand_id=sg.cand.id, cand_start_s=sg.cand.start_s, cand_end_s=sg.cand.end_s, film_start_s=round(sg.start * music.beat_s, 3), start_beat=sg.start, beats=sg.beats,
                        dur_s=round(dur, 3), clip_start_s=sg.clip_start_s, in_s=sg.in_s, utc_start=t0.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z', utc_end=(t0 + dt.timedelta(seconds=dur)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                        energy=round(float(sg.cand.energy), 3), technique=sg.tech.id, family=sg.tech.family, hero=sg.tech.hero, variant_seed=sg.variant_seed, forced=sg.forced, speech=bool(sg.parts.get('speech', sg.cand.speech)), kind=getattr(sg.cand, 'kind', 'span'), view=getattr(sg.cand, 'view', 'ahead'), locked=sg.parts['wid'] in locked_wids,
                        options=sg.parts['options']))
    return out


def propose(folder, settings=None, overrides=None, keep=True):
    """(Re)compute the plan from the saved settings and overrides (optionally updated by the arguments) and save it. With `keep` the previous techniques are preferred, so a small change does
    not reshuffle the whole film. Returns the saved edit dict; raises O.Infeasible with the reason when the film cannot be made."""
    edit = load(folder); prev = edit.get('plan') if keep else None
    if settings: edit['settings'].update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS and v is not None})
    if overrides: edit['overrides'].update(overrides)
    clips, missing = load_clips(folder)
    if not clips: raise O.Infeasible('no candidates yet: the candidates stage has to finish for at least one clip')
    lib = TQ.load(); music, st = _planner(edit, lib, prev)
    segs = CH.plan(clips, lib, music, st); bad = CH.violations(segs, lib, music, clips)
    if bad: raise O.Infeasible('the plan broke its own rules: ' + '; '.join(bad[:4]))
    locked_w = {g['wid'] for g in edit['overrides']['locked']}; ser = serialise(segs, clips, music, lib, locked_w); wids = {g['id'] for g in ser}
    from strata360.edit import transitions as TR
    for g in ser: g['energy_hi'] = g['energy'] >= 0.6
    TR.choose(ser, music.beat_s, music.bar_beats, forced={k: v for k, v in edit['overrides'].get('transitions', {}).items() if v in TR.TYPES})
    orphaned = sorted((set(edit['overrides']['tech_force']) | locked_w) - wids)
    used = {}
    for g in ser: used[g['technique']] = used.get(g['technique'], 0) + g['dur_s']
    edit['plan'] = dict(generated_at=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), film=dict(length_s=round(music.beats * music.beat_s, 3), beats=music.beats, bpm=music.bpm, bar_beats=music.bar_beats),
                        segments=ser, clips_in_plan=len({g['clip'] for g in ser}), missing_clips=missing, orphaned_overrides=orphaned, technique_seconds={k: round(v, 2) for k, v in used.items()},
                        warnings=(segs[0].parts.get('warnings') if segs else []) or [])
    return save(folder, edit)


# ---- overrides: each one changes the record and re-plans around it ---------------------------------------------------------------------------------------------------------------
def _segment(edit, wid):
    g = next((g for g in (edit.get('plan') or {}).get('segments', []) if g['id'] == wid), None)
    if g is None: raise KeyError(f'no such segment {wid}')
    return g


def set_technique(folder, wid, technique):
    edit = load(folder)
    if technique is None: edit['overrides']['tech_force'].pop(wid, None)
    else:
        g = _segment(edit, wid)
        if technique not in [o['tech'] for o in g['options']]: raise ValueError(f"{technique} does not fit this window (it fits: {', '.join(o['tech'] for o in g['options'])})")
        edit['overrides']['tech_force'][wid] = technique
    save(folder, edit); return propose(folder)


def set_transition(folder, wid, kind):
    """Force the transition into window `wid` (None = back to the rule). Only the effects change: the windows and techniques stay as they are."""
    from strata360.edit import transitions as TR
    edit = load(folder)
    if kind is None: edit['overrides'].setdefault('transitions', {}).pop(wid, None)
    else:
        if kind not in TR.TYPES: raise ValueError(f"transition: one of {', '.join(TR.TYPES)}")
        _segment(edit, wid); edit['overrides'].setdefault('transitions', {})[wid] = kind
    save(folder, edit); return propose(folder)


def set_lock(folder, wid, locked):
    edit = load(folder); L = [g for g in edit['overrides']['locked'] if g['wid'] != wid]
    if locked:
        g = _segment(edit, wid); L.append(dict(wid=wid, clip=g['clip'], start_s=g['clip_start_s'], beats=g['beats'], cand_id=g['cand_id'], tech=g['technique']))
    edit['overrides']['locked'] = L; save(folder, edit); return propose(folder)


def set_clip_weight(folder, clip, factor):
    edit = load(folder)
    if factor is None or abs(float(factor) - 1.0) < 1e-9: edit['overrides']['clip_weight'].pop(clip, None)
    else: edit['overrides']['clip_weight'][clip] = float(max(0.2, min(5.0, factor)))
    save(folder, edit); return propose(folder)


def ban(folder, kind, key, on=True):
    """kind: 'moment' (a stretch / candidate id) or 'technique'."""
    edit = load(folder); name = 'bans_cands' if kind == 'moment' else 'bans_techs'; cur = [x for x in edit['overrides'][name] if x != key]
    if on: cur.append(key)
    edit['overrides'][name] = cur; save(folder, edit); return propose(folder)


def reset_overrides(folder):
    edit = load(folder); edit['overrides'] = json.loads(json.dumps(EMPTY_OVERRIDES)); save(folder, edit); return propose(folder, keep=False)
