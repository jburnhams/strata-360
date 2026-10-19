"""One narration line recorded again, and only its block re-fitted (implementation plan V6, P5-35).

  refit(segs, lines, seg, speak_s, beat_s, clip_len, dur_range=None, grid=None, seek=0.0) -> dict or None
  refit_project(folder, seg, log=print) -> dict(mode, ...)

A new take of a narration line has its own length. Planning the whole film again for it would reshuffle shots far from the line (the planner's search, the beat sync), so here only the line's block (its script
item: the windows of footage under it) changes. The block grows or shrinks by as many whole beats as the line's rounding to beats changed (the line needs LEAD_S + its speech + TAIL_S, as script_plan sizes it),
so any room the music fit gave the block is kept. The time is taken from the block's own windows, the last first: a window runs on in its clip (or starts earlier in it), never into footage another window shows,
past its clip or past its technique's length range; a shorter take shortens them, never below their technique's shortest. Every window outside the block keeps its footage and technique and only moves in film time,
so the cut before the block stays where it is and the cut after it moves with it. With the music's beat grid the block's end moves to a real beat; the cuts after it move by the same time, and any that leave their
beat (the track's tempo drifts) are reported off the beat until the film is planned again.

A block that is a generated clip (narration over a gap) cannot grow without the clip being made again: refit returns None and refit_project plans the film again from the script."""
import datetime as dt, json, math, os

from strata360.edit import script_plan as SPL

MIN_SHOT_S = 0.3
OFF_MS = 1.0                 # a cut this far from its nearest beat is off it (beat_sync's warning threshold)


def _beats_for(speak_s, beat_s): return max(1, int(math.ceil((SPL.LEAD_S + float(speak_s) + SPL.TAIL_S) / beat_s - 1e-9)))


def _utc(s, d):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00')) + dt.timedelta(seconds=d); return t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _room(segs, block, clip_len, dur_range):
    """[(i, after, before, grow, shrink)] for the block's windows, the last first: how far each may run on in its clip, start earlier in it, grow in all (its technique's longest) and shrink (to its shortest)."""
    out = []
    for i in reversed(block):
        g = segs[i]; cs = float(g['clip_start_s']); d = float(g['dur_s']); ce = cs + d; lo, hi = (dur_range or {}).get(g.get('technique'), (MIN_SHOT_S, math.inf))
        if g.get('ramp') or g.get('synthetic'): out.append((i, 0.0, 0.0, 0.0, 0.0)); continue                       # (a speed ramp keeps its shape)
        busy = [(float(x['clip_start_s']), float(x['clip_start_s']) + float(x['dur_s'])) for j, x in enumerate(segs) if j != i and x['clip'] == g['clip'] and not x.get('synthetic')]
        nxt = min([a for a, _ in busy if a >= ce - 1e-6] + [float(clip_len.get(g['clip'], ce))]); prv = max([b for _, b in busy if b <= cs + 1e-6] + [0.0])
        out.append((i, max(nxt - ce, 0.0), max(cs - prv, 0.0), max(max(hi, d) - d, 0.0), max(d - max(lo, MIN_SHOT_S), 0.0)))
    return out


def _end_after(t_end, k, beat_s, grid, seek):
    """Film time k beats after (or before) the cut at t_end: on the track's real beats when there is a grid, else k nominal beats."""
    if grid is None or k == 0: return t_end + k * beat_s
    j = min(range(len(grid.t)), key=lambda n: abs(grid.t[n] - seek - t_end))
    return float(grid.t[j + k]) - seek if 0 <= j + k < len(grid.t) else t_end + k * beat_s


def refit(segs, lines, seg, speak_s, beat_s, clip_len, dur_range=None, grid=None, seek=0.0):
    """The plan with line `seg` re-timed to a take `speak_s` long. `segs` are the plan's segment dicts in film order, `lines` the script plan's narration (script2/lines.json: seg, item, film_start_s, seconds,
    speak_s), `grid` an optional beat_sync.Grid with the track started at film time -seek. Returns dict(segments, lines, item, beats, delta_s, changed (window ids), warnings), or None when the block is a generated
    clip (or the line has no windows). The inputs are not changed."""
    line = next((l for l in lines if l['seg'] == seg), None)
    if line is None: raise KeyError(f'no narration line {seg} in the plan')
    block = [i for i, g in enumerate(segs) if g.get('item') == line.get('item') and g.get('role') == 'vo']
    if not block or any(segs[i].get('synthetic') for i in block): return None
    want = _beats_for(speak_s, beat_s) - _beats_for(line['speak_s'], beat_s); room = _room(segs, block, clip_len, dur_range); warn = []
    grow = sum(min(a + b, g) for _, a, b, g, _ in room); shrink = sum(s for *_, s in room)
    t0 = float(segs[block[0]]['film_start_s']); t_end = float(segs[block[-1]]['film_start_s']) + float(segs[block[-1]]['dur_s'])
    k = want
    while k != 0:                                                                                 # the most whole beats the block's footage can give (or give back)
        delta = _end_after(t_end, k, beat_s, grid, seek) - t_end
        if (delta > 0 and delta <= grow + 1e-6) or (delta < 0 and -delta <= shrink + 1e-6): break
        k -= 1 if k > 0 else -1
    delta = _end_after(t_end, k, beat_s, grid, seek) - t_end if k else 0.0
    if k < want:
        need = _beats_for(speak_s, beat_s) * beat_s
        warn.append(f"item {line['item'] + 1}: the new take needs {need:.1f} s of picture but clip {segs[block[0]]['clip']} has only {float(sum(float(segs[i]['dur_s']) for i in block)) + delta:.1f} s free for it"
                    ' (choices: record it again shorter, shorten the line, or plan the film again so the next item lends it picture)')
    out = [dict(g) for g in segs]; left = abs(delta); changed = []
    for i, after, before, most, less in room:                                                     # the last window first
        if left <= 1e-9: break
        g = out[i]; cs = float(g['clip_start_s']); d = float(g['dur_s'])
        if delta > 0:
            on = min(left, after, most); back = min(left - on, before, most - on); g['clip_start_s'] = round(cs - back, 4); g['in_s'] = round(float(g.get('in_s') or 0.0) - back, 4); d += on + back; left -= on + back
            if back and g.get('utc_start'): g['utc_start'] = _utc(g['utc_start'], -back)
        else: cut = min(left, less); d -= cut; left -= cut
        g['dur_s'] = round(d, 4); g['beats'] = max(1, int(round(d / beat_s))); changed.append(g['id'])
        if g.get('utc_start'): g['utc_end'] = _utc(g['utc_start'], d)
    t = t0
    for i in block: out[i]['film_start_s'] = round(t, 4); t += float(out[i]['dur_s'])
    delta = t - t_end                                                                             # (exactly what the windows took)
    for g in out[block[-1] + 1:]:
        g['film_start_s'] = round(float(g['film_start_s']) + delta, 4)
        if g.get('start_beat') is not None: g['start_beat'] = int(g['start_beat']) + k
    new_lines = []; at = float(line['film_start_s'])
    for l in lines:
        l = dict(l)
        if l['seg'] == seg: l.update(speak_s=round(float(speak_s), 3), estimated=False, seconds=round(float(l['seconds']) + delta, 3))
        elif float(l['film_start_s']) > at + 1e-6: l['film_start_s'] = round(float(l['film_start_s']) + delta, 3)
        new_lines.append(l)
    return dict(segments=out, lines=new_lines, item=line['item'], beats=k, delta_s=round(delta, 4), changed=sorted(set(changed)), first=block[0], last=block[-1], warnings=warn)


def off_beat(segs, length_s, grid, seek, old, from_cut, why):
    """beat_sync's off_beat list after a refit: cuts before `from_cut` (1-based: cut k is the start of shot k, the last one the film's end) keep their entries; the later ones moved, so each is checked against the grid
    again, keeping its old reason if it was off before and `why` if the move took it off."""
    ends = [float(g['film_start_s']) for g in segs[1:]] + [float(length_s)]; was = {o['cut']: o for o in old or []}; out = []
    for k, x in enumerate(ends, 1):
        if k < from_cut:
            if k in was: out.append(was[k])
            continue
        n, _ = grid.nearest(x, seek); ms = abs(x - n) * 1000.0
        if ms >= OFF_MS: out.append(dict(cut=k, film_s=round(x, 3), off_ms=round(ms, 1), why=was[k]['why'] if k in was else why))
    return out


def measure(folder, seg, text):
    """How long the line's current take speaks (the recording if it is the one used, else the synthetic voice), or None when there is no take and no voice to make one."""
    from strata360.edit import voiceover as VO
    st = VO.load_state(folder); rp = VO.recorded_path(folder, seg)
    if VO.source_for(st, seg, os.path.exists(rp)) == 'recorded': a, b = VO.speech_span(rp); return b - a
    return VO.line_durations(folder, [dict(seg=seg, text=text)], lambda *_: None).get(seg)


def refit_project(folder, seg, log=print):
    """After a line's take changed (recorded, removed, or switched between your recording and the voice): re-fit only its block in the saved plan and script2/lines.json. Returns dict(mode, ...): 'refit' (with
    item, delta_s, changed, warnings), 'same' (the block's length in beats did not change: only the line's length is updated), 'replan' (a generated clip under the line: the film was planned again), or 'none' (no
    script plan, the line is not in it, or there is no voice to measure)."""
    from strata360.edit import beat_sync as BS, project as PJ, techniques as TQ, voiceover as VO
    from strata360.pipeline import config
    edit = PJ.load(folder); plan = edit.get('plan')
    if not plan or plan.get('source') != 'script': return dict(mode='none', reason='the film is not planned from the script')
    lp = os.path.join(config.race_dir(folder), VO.SCRIPT2_LINES)
    try: doc = json.load(open(lp))
    except (OSError, ValueError): return dict(mode='none', reason='the script plan has no narration lines')
    line = next((l for l in doc.get('lines', []) if l['seg'] == seg), None)
    if line is None: return dict(mode='none', reason='that line is not in the planned film')
    speak = measure(folder, seg, line['text'])
    if speak is None: return dict(mode='none', reason='no voice to measure the line with')
    beat_s = 60.0 / float(plan['film']['bpm']); mus = PJ.music_info(folder, edit['settings']); sync = plan.get('beat_sync') or {}; grid = None; seek = float(sync.get('seek_s') or 0.0) - float(sync.get('delay_s') or 0.0)
    if sync:
        try: g = PJ.beat_list(folder, edit['settings'], mus); grid = BS.Grid(g['beats'], g['downbeats']) if g and len(g['beats']) > 1 else None
        except (RuntimeError, OSError, ValueError) as e: log(f'the beats of the music could not be read ({e}): the block moves by whole beats of the average tempo')
    clips, _ = PJ.load_clips(folder); lib = TQ.with_cams(TQ.load(), folder)
    res = refit(plan['segments'], doc['lines'], seg, speak, beat_s, {c['id']: float(c['duration_s']) for c in clips}, {t.id: (t.dmin, t.dmax) for t in lib.values()}, grid, seek)
    if res is None:
        log(f'line {seg} is spoken over a generated clip: planning the film again'); PJ.plan_from_script(folder, plan.get('script'), log); return dict(mode='replan', seg=seg)
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'); d = res['delta_s']
    plan['segments'] = res['segments']; plan['film']['length_s'] = round(float(plan['film']['length_s']) + d, 3); plan['film']['beats'] = int(plan['film']['beats']) + res['beats']
    if sync:
        sync['length_s'] = round(float(sync.get('length_s') or 0.0) + d, 4)
        if grid is not None and d: sync['off_beat'] = off_beat(plan['segments'], plan['film']['length_s'], grid, seek, sync.get('off_beat'), res['last'] + 1, f"moved with the new take of item {res['item'] + 1}'s narration: plan the film again to put it back on the beat")
    plan['warnings'] = [w for w in plan.get('warnings', []) if not w.startswith(f"item {res['item'] + 1}: the new take")] + res['warnings']
    plan['refit'] = dict(seg=seg, item=res['item'], delta_s=d, beats=res['beats'], changed=res['changed'], at=now)
    PJ.save(folder, edit); doc['lines'] = res['lines']; doc['generated_at'] = now
    json.dump(doc, open(lp + '.tmp', 'w'), indent=1); os.replace(lp + '.tmp', lp)
    return dict(mode='refit' if res['beats'] else 'same', seg=seg, item=res['item'], delta_s=d, beats=res['beats'], changed=res['changed'], warnings=res['warnings'])


def timeline(folder):
    """What the timeline draws over the film's windows (V6): the narration lines where their speech starts with their measured length, which take each uses and how it fits (from the last voice-over build when it was made
    for this script), and the music's beats and bar lines in film time (the real beats when the plan was synced to them, else the plan's own tempo). dict(lines, beats, bars, synced, length_s)."""
    from strata360.edit import beat_sync as BS, project as PJ, voiceover as VO
    from strata360.pipeline import config
    edit = PJ.load(folder); plan = edit.get('plan') or {}; film = plan.get('film') or {}; length = float(film.get('length_s') or 0.0); out = dict(lines=[], beats=[], bars=[], synced=False, length_s=length)
    if not plan: return out
    if plan.get('source') == 'script':
        try: doc = json.load(open(os.path.join(config.race_dir(folder), VO.SCRIPT2_LINES)))
        except (OSError, ValueError): doc = {}
        st = VO.load_state(folder); tm = VO.load_timings(folder) or {}; built = {o['seg']: o for o in tm.get('lines', [])} if tm.get('script') and tm.get('script') == VO.newest_script(folder) else {}
        for l in sorted(doc.get('lines', []), key=lambda l: float(l['film_start_s'])):
            has = os.path.exists(VO.recorded_path(folder, l['seg'])); b = built.get(l['seg']) or {}
            out['lines'].append(dict(seg=l['seg'], text=l['text'], item=l.get('item'), clip=l.get('clip'), start_s=round(float(l['film_start_s']) + VO.LEAD_S, 3), speak_s=round(float(b.get('played_s') or l.get('speak_s') or 0.0), 3),
                                     room_s=round(float(l['seconds']), 3), estimated=bool(l.get('estimated')) and not b, has_recording=has, source=VO.source_for(st, l['seg'], has), fit=b.get('fit'), overrun_s=b.get('overrun_s', 0.0)))
    sync = plan.get('beat_sync'); bar_beats = int(film.get('bar_beats') or edit['settings'].get('bar_beats') or 4)
    if sync:
        try: g = PJ.beat_list(folder, edit['settings'], PJ.music_info(folder, edit['settings']))
        except (RuntimeError, OSError, ValueError): g = None
        if g and len(g['beats']) > 1:
            grid = BS.Grid(g['beats'], g['downbeats']); seek = float(sync.get('seek_s') or 0.0) - float(sync.get('delay_s') or 0.0)
            for x, bar in grid.within(0.0, length, seek):
                out['beats'].append(round(x, 3))
                if bar: out['bars'].append(round(x, 3))
            out['synced'] = True; return out
    if film.get('bpm'):
        beat_s = 60.0 / float(film['bpm']); n = int(length / beat_s + 1e-6)
        out['beats'] = [round(i * beat_s, 3) for i in range(n + 1)]; out['bars'] = out['beats'][::bar_beats]
    return out
