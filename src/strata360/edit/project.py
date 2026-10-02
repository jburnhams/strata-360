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
from strata360.edit.script_pack import norm_label
from strata360.pipeline import config
from strata360.edit import techniques as TQ, chrono as CH, optimise as O

DEFAULT_SETTINGS = dict(length_s=90.0, bpm=120.0, bar_beats=4, seed=1, wpm=145.0, style='', music=None)      # music: a file inside the project folder (music/track.*): tempo, bars and energy then come from it
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
        try: clips[-1]['alignment'] = json.load(open(d + 'alignment.json')).get('segments') or []         # exact speech spans for the rough plan (edit/blocks.py)
        except (OSError, ValueError): pass
    return clips, missing


def music_record(folder, settings):
    """The project's music.json record (file, name, analysis, waveform; edit/music.py), or None when there is no track (or it cannot be read)."""
    from strata360.edit import music as MU
    f = settings.get('music')
    if not f: return None
    rd = config.race_dir(folder)
    if not os.path.exists(os.path.join(rd, f)): return None
    try: return MU.info(rd, f)
    except (RuntimeError, OSError): return None


def music_info(folder, settings):
    """The analysis of the project's music track (edit/music.py), or None when there is none (or it cannot be read)."""
    r = music_record(folder, settings); return r['analysis'] if r else None


def rough_blocks(folder, target_s=None, auto=False):
    """The rough plan (edit/blocks.py, implementation plan V1) for the saved overrides, written to <race dir>/blocks.json and returned. The film length guide (D8): `target_s` if given, else the music
    track's length from its first downbeat (D7), else automatic from the usable footage; `auto` ignores the track. Does not touch the saved plan: the beat planner still makes the film."""
    from strata360.edit import blocks as BL
    edit = load(folder); s = edit['settings']; o = edit['overrides']; clips, missing = load_clips(folder); mus = None if auto else music_info(folder, s)
    if target_s is not None: source, target = 'target', float(target_s)
    elif mus: source, target = 'music', max(float(mus['duration_s']) - float(mus['offset_s']), 0.0)
    else: source, target = 'automatic', None
    bpm = float(mus['bpm']) if mus else float(s['bpm'])
    st = CH.Settings(seed=int(s['seed']), locked=tuple(o['locked']), tech_force=dict(o['tech_force']), bans_cands=frozenset(o['bans_cands']), bans_techs=frozenset(o['bans_techs']), clip_weight={k: float(v) for k, v in o['clip_weight'].items()})
    rp = BL.plan_blocks(clips, target, st, 60.0 / bpm)
    out = dict(generated_at=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), target_source=source, music=(dict(file=s['music'], duration_s=mus['duration_s'], offset_s=mus['offset_s']) if mus else None),
               clips_without_candidates=missing, plan=BL.asdict(rp))
    rd = config.race_dir(folder); os.makedirs(rd, exist_ok=True); p = os.path.join(rd, 'blocks.json'); tmp = f'{p}.{os.getpid()}.tmp'; json.dump(out, open(tmp, 'w'), indent=1); os.replace(tmp, p); return out


def _planner(edit, lib, prev_plan, mus=None):
    s = edit['settings']; o = edit['overrides']; bpm = float(mus['bpm']) if mus else float(s['bpm']); bar = int(mus['bar_beats']) if mus else int(s['bar_beats'])
    beats = int(round(s['length_s'] * bpm / 60.0)); beats -= beats % bar                              # a whole number of bars
    if mus: beats = min(beats, int(mus['usable_beats']))                                               # never longer than the track
    music = O.Music(bpm=bpm, beats=beats, bar_beats=bar, sections=[tuple(x) for x in mus['sections']] if mus else [(0, 10 ** 9, 0.5)])
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


def apply_gap_items(folder, draft, log=print):
    """Plan, in synthetic.json, the generated clip each `gap` item of the draft asks for (its kind and length), so that it can be rendered afterwards (rendering is its own step; a 3D flyover asked for by the script waits for your
    approval). A clip already planned for the same kind and length is left as it is; one with another kind or length is planned again (a render of the old one no longer matches). Returns the clips planned."""
    from strata360.edit import synthetic as SY
    from strata360.gps import gaps as GP, track
    from strata360.pipeline import config
    items = [it for it in draft.get('items') or [] if it.get('type') == 'gap']
    if not items: return []
    cfg = config.load(folder); tp = config.track_path(folder, cfg); tz = cfg.get('timezone', 'Europe/Brussels')
    if not tp: raise O.Infeasible('the script has gap items but there is no race track')
    gaps = {g['id']: g for g in GP.find_gaps(GP.load_spans(folder), track.load(tp), 1200.0, tz)}; made = []; docs = {c['id']: c for c in SY.load(folder)['clips']}
    for it in items:
        gid = norm_label(it.get('clip', ''))
        if gid not in gaps: log(f'gap item {gid}: no such gap; skipped'); continue
        kind = it.get('kind') or 'map'; sec = round(float(it.get('seconds') or 0), 2); old = docs.get(gid)
        if old and old['kind'] == kind and abs(old['seconds'] - sec) < 0.05: continue
        try: clip = SY.make(gaps[gid], seconds=sec, kind=kind, approved=kind != 'flyover')
        except ValueError as e: log(f'gap item {gid}: {e}; skipped'); continue
        made.append(SY.upsert(folder, clip)); log(f'planned {kind} clip {gid} for {sec:g} s' + (' (waiting for your approval)' if made[-1]['approved'] is False else ''))
    return made


def insert_synthetic(folder, ser, specs, beat_s):
    """The plan's segments with the generated clips (edit/synthetic.py) put in their places: each is a window of the whole clip, played from its start, `synthetic` naming the video file (the film's sources play it as it is)."""
    from strata360.edit import synthetic as SY
    if not specs: return ser
    docs = {c['id']: c for c in SY.load(folder)['clips']}; rd = config.race_dir(folder); out = list(ser)
    for sp in specs:
        c = docs[sp['clip']]; dur = round(sp['beats'] * beat_s, 3); c.setdefault('file', os.path.join('synthetic', c['id'] + '.mp4'))        # a clip not rendered yet has its file named already
        out.append(dict(id=f"{c['id']}@0.00", index=0, clip=c['id'], cand_id=f"{c['id']}:map", cand_start_s=0.0, cand_end_s=c['seconds'], film_start_s=round(sp['start_beat'] * beat_s, 3), start_beat=sp['start_beat'], beats=sp['beats'], dur_s=dur,
                        clip_start_s=0.0, in_s=0.0, utc_start=c['t0'], utc_end=c['t1'], energy=0.5, technique='map', family='generated', hero=False, variant_seed=0, forced=False, speech=False, kind='synthetic', view=None, options=[],
                        synthetic=os.path.normpath(os.path.join(rd, c['file'])), role=sp['role'], item=sp['item'], energy_hi=False))
    out.sort(key=lambda g: g['start_beat'])
    for i, g in enumerate(out): g['index'] = i
    return out


def plan_from_script(folder, draft_name=None, log=print):
    """Make the film's plan from the whole-race script (edit/script_draft.py, edit/script_plan.py) and save it as the plan: the script's dialogue, narration and b-roll in order, in windows of whole beats, the
    narration timed by how long the voice takes to say it. Also writes script2/lines.json, the narration the voice-over builder speaks and places. Raises O.Infeasible with the reason."""
    from strata360.edit import script_draft as SD, script_pack as SP, script_plan as SPL, synthetic as SY, transitions as TR, voiceover as VO
    edit = load(folder); clips, missing = load_clips(folder); names = SD.list_drafts(folder); name = draft_name or (names[-1] if names else None); draft = SD.load_draft(folder, name)
    if not draft: raise O.Infeasible('there is no script draft yet: write one first (strata360 script-draft)')
    if not clips: raise O.Infeasible('no candidates yet: the candidates stage has to finish for at least one clip')
    lib = TQ.load(); mus = music_info(folder, edit['settings']); bpm = float(mus['bpm']) if mus else float(edit['settings']['bpm']); bar = int(mus['bar_beats']) if mus else int(edit['settings']['bar_beats'])
    music = O.Music(bpm=bpm, beats=1, bar_beats=bar, sections=[tuple(x) for x in mus['sections']] if mus else [(0, 10 ** 9, 0.5)])
    apply_gap_items(folder, draft, log); pack = SP.build(folder); vo_items = [(n, it) for n, it in enumerate(draft['items']) if it.get('type') == 'vo' and (it.get('text') or '').strip()]
    by_label = {c['label']: c['clip'] for c in pack['clips']}; seg_of = {n: SPL.seg_id(by_label.get(norm_label(it.get('clip', '')), ''), it['text']) for n, it in vo_items}
    spoken = VO.line_durations(folder, [dict(seg=seg_of[n], text=it['text'].strip()) for n, it in vo_items], log); voice_s = {n: spoken[seg_of[n]] for n, _ in vo_items if seg_of[n] in spoken}
    o = edit['overrides']; st = CH.Settings(seed=int(edit['settings']['seed']), tech_force=dict(o['tech_force']), bans_techs=frozenset(o['bans_techs']))
    res = SPL.build(draft, pack, clips, lib, music, voice_s, wpm=float(draft.get('wpm') or 150.0), st=st)
    music = O.Music(bpm=bpm, beats=res['beats'], bar_beats=bar, sections=music.sections); ser = serialise(res['segs'], clips, music, lib)
    for g, role, k in zip(ser, res['roles'], res['piece_of']): g['role'] = role; g['item'] = res['pieces'][k]['n']; g['energy_hi'] = g['energy'] >= 0.6
    ser = insert_synthetic(folder, ser, res.get('synthetic') or [], music.beat_s)
    for g in ser:
        if g.get('synthetic') and not os.path.exists(g['synthetic']): res['warnings'].append(f"{g['clip']}: the generated clip is not rendered yet" + (' (a 3D flyover the script asked for: approve it in the Gaps panel)' if (next((c for c in SY.load(folder)['clips'] if c['id'] == g['clip']), {}).get('approved') is False) else '') + '; the film shows a card until it is')
    TR.choose(ser, music.beat_s, music.bar_beats, forced={k: v for k, v in o.get('transitions', {}).items() if v in TR.TYPES})
    used = {}
    for g in ser: used[g['technique']] = used.get(g['technique'], 0) + g['dur_s']
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    edit['plan'] = dict(generated_at=now, source='script', script=name, film=dict(length_s=round(music.beats * music.beat_s, 3), beats=music.beats, bpm=bpm, bar_beats=bar, music=(dict(file=edit['settings']['music'], offset_s=mus['offset_s']) if mus else None)),
                        segments=ser, clips_in_plan=len({g['clip'] for g in ser}), missing_clips=missing, orphaned_overrides=[], technique_seconds={k: round(v, 2) for k, v in used.items()}, warnings=res['warnings'])
    save(folder, edit); rd = config.race_dir(folder); os.makedirs(os.path.join(rd, 'script2'), exist_ok=True); p = os.path.join(rd, VO.SCRIPT2_LINES); json.dump(dict(draft=name, generated_at=now, lines=res['lines']), open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p)
    return edit


def propose(folder, settings=None, overrides=None, keep=True):
    """(Re)compute the plan from the saved settings and overrides (optionally updated by the arguments) and save it. With `keep` the previous techniques are preferred, so a small change does
    not reshuffle the whole film. Returns the saved edit dict; raises O.Infeasible with the reason when the film cannot be made."""
    edit = load(folder); prev = edit.get('plan') if keep else None
    if settings: edit['settings'].update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS and v is not None})
    if overrides: edit['overrides'].update(overrides)
    clips, missing = load_clips(folder)
    if not clips: raise O.Infeasible('no candidates yet: the candidates stage has to finish for at least one clip')
    lib = TQ.load(); mus = music_info(folder, edit['settings']); music, st = _planner(edit, lib, prev, mus)
    segs = CH.plan(clips, lib, music, st); bad = CH.violations(segs, lib, music, clips)
    if bad: raise O.Infeasible('the plan broke its own rules: ' + '; '.join(bad[:4]))
    locked_w = {g['wid'] for g in edit['overrides']['locked']}; ser = serialise(segs, clips, music, lib, locked_w); wids = {g['id'] for g in ser}
    from strata360.edit import transitions as TR
    for g in ser: g['energy_hi'] = g['energy'] >= 0.6
    TR.choose(ser, music.beat_s, music.bar_beats, forced={k: v for k, v in edit['overrides'].get('transitions', {}).items() if v in TR.TYPES})
    orphaned = sorted((set(edit['overrides']['tech_force']) | locked_w) - wids)
    used = {}
    for g in ser: used[g['technique']] = used.get(g['technique'], 0) + g['dur_s']
    edit['plan'] = dict(generated_at=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), film=dict(length_s=round(music.beats * music.beat_s, 3), beats=music.beats, bpm=music.bpm, bar_beats=music.bar_beats, music=(dict(file=edit['settings']['music'], offset_s=mus['offset_s']) if mus else None)),
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


def set_music(folder, rel):
    """Use the audio file `rel` (inside the project folder) as the film's music, or None for no music; re-plans around its tempo and energy."""
    edit = load(folder); edit['settings']['music'] = rel; save(folder, edit); return propose(folder)


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
