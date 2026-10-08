"""The rough mix: the film's sound without its picture, to hear a script plan in a minute (implementation plan V6 preview). The music quietly, the clips' own background sound quietly under narration and b-roll,
the voice-over, and the runner's own speech in the windows where the script plays it: the same `render.preview.build_audio` as the film, with the music and the background turned down.

build(folder) -> the status dict; writes `<project>/roughmix/mix.m4a` and `mix.json` (the key of what it was made from, so a changed plan, voice-over or music is noticed: `status(folder)['stale']`)."""
import hashlib, json, os, subprocess, time

from strata360.pipeline import config

VERSION = 2                  # bump when the way the mix is made changes what it sounds like: every earlier mix is then out of date
MUSIC_GAIN = 0.25            # the music, quietly (the film's own mix has it at 0.5)
BG_GAIN = 0.3                # a clip's background sound under narration and b-roll


def dir_of(folder): return os.path.join(config.race_dir(folder), 'roughmix')


def path_of(folder): return os.path.join(dir_of(folder), 'mix.m4a')


def _mtime(p): return os.path.getmtime(p) if p and os.path.exists(p) else 0


def parts_of(folder, plan):
    """What the mix is made from, one short fingerprint per input: the windows (`plan`), the voice-over track (`voice-over`), the music file (`music`) and how it is made (`settings`: the version and the levels)."""
    rd = config.race_dir(folder); mus = (plan.get('film') or {}).get('music'); fp = lambda x: hashlib.sha1(str(x).encode()).hexdigest()[:8]
    at = f"@{mus['offset_s']}+{mus.get('delay_s', 0)}" if mus and mus.get('synced') else ''                  # where the cuts put the music's start (edit/beat_sync.py), once they chose it
    return dict(plan=fp(json.dumps(plan['segments'], sort_keys=True, default=str)), **{'voice-over': fp(_mtime(os.path.join(rd, 'voiceover', 'voiceover.wav')))}, music=fp(f"{mus['file'] if mus else ''}{_mtime(os.path.join(rd, mus['file']) if mus else None)}" + at), settings=fp([VERSION, MUSIC_GAIN, BG_GAIN]))


def key_of(folder, plan): return hashlib.sha1(json.dumps(parts_of(folder, plan), sort_keys=True).encode()).hexdigest()[:12]


def status(folder):
    """{has_plan, exists, stale, stale_because, length_s, made_at, source}: whether a plan exists to mix, whether there is a mix, and whether it no longer matches its inputs (`stale_because` names the inputs that changed:
    plan, voice-over, music, settings)."""
    from strata360.edit import project as PJ
    plan = PJ.load(folder).get('plan'); doc = {}
    try: doc = json.load(open(os.path.join(dir_of(folder), 'mix.json')))
    except (OSError, ValueError): pass
    has = bool(plan and plan.get('segments')); exists = os.path.exists(path_of(folder)) and bool(doc)
    now = parts_of(folder, plan) if has else {}; why = [k for k in now if (doc.get('parts') or {}).get(k) != now[k]] if has and exists else []
    return dict(has_plan=has, exists=exists, stale=bool(why), stale_because=why, length_s=doc.get('length_s'), made_at=doc.get('made_at'), source=(plan or {}).get('source'))


def build(folder, log=print):
    """Speak the voice-over (reused when unchanged), mix and encode. Raises RuntimeError with the reason (no plan, no voice installed ...)."""
    from strata360.edit import project as PJ, voiceover as VO
    from strata360.render import preview as PV
    plan = PJ.load(folder).get('plan')
    if not plan or not plan.get('segments'): raise RuntimeError('there is no film plan yet: make the film from a script first')
    total = float((plan.get('film') or {}).get('length_s') or sum(g['dur_s'] for g in plan['segments'])); d = dir_of(folder); os.makedirs(d, exist_ok=True)
    if VO.script_lines(folder)[1]: log('voice-over'); VO.build(folder)                              # (quick when the lines and the voice are unchanged)
    key = key_of(folder, plan); wav = os.path.join(d, 'mix.part.wav'); log('mixing'); PV.build_audio(folder, plan, wav, total, music_gain=MUSIC_GAIN, bg_gain=BG_GAIN)
    out = path_of(folder); r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out + '.part.m4a'], capture_output=True, text=True); os.remove(wav)
    if r.returncode: raise RuntimeError('encoding the mix failed: ' + r.stderr[-300:])
    os.replace(out + '.part.m4a', out); json.dump(dict(key=key, parts=parts_of(folder, plan), length_s=round(total, 2), made_at=time.strftime('%Y-%m-%dT%H:%M:%S'), gains=dict(music=MUSIC_GAIN, background=BG_GAIN)), open(os.path.join(d, 'mix.json'), 'w'))
    log(f'rough mix: {total:.0f} s'); return status(folder)


def reset(folder):
    """Forget the mix (the file and its record), so it is made again from scratch the next time; returns whether there was one."""
    had = False
    for n in ('mix.m4a', 'mix.json', 'mix.part.wav', 'mix.m4a.part.m4a'):
        p = os.path.join(dir_of(folder), n)
        if os.path.exists(p): os.remove(p); had = True
    return had
