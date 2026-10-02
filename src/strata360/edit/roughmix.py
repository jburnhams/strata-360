"""The rough mix: the film's sound without its picture, to hear a script plan in a minute (implementation plan V6 preview). The music quietly, the clips' own background sound quietly under narration and b-roll,
the voice-over, and the runner's own speech in the windows where the script plays it: the same `render.preview.build_audio` as the film, with the music and the background turned down.

build(folder) -> the status dict; writes `<project>/roughmix/mix.m4a` and `mix.json` (the key of what it was made from, so a changed plan, voice-over or music is noticed: `status(folder)['stale']`)."""
import hashlib, json, os, subprocess, time

from strata360.pipeline import config

MUSIC_GAIN = 0.25            # the music, quietly (the film's own mix has it at 0.5)
BG_GAIN = 0.3                # a clip's background sound under narration and b-roll


def dir_of(folder): return os.path.join(config.race_dir(folder), 'roughmix')


def path_of(folder): return os.path.join(dir_of(folder), 'mix.m4a')


def _mtime(p): return os.path.getmtime(p) if p and os.path.exists(p) else 0


def key_of(folder, plan):
    """What the mix is made from: the windows, the voice-over track, the music file and the levels."""
    rd = config.race_dir(folder); mus = (plan.get('film') or {}).get('music'); h = hashlib.sha1(json.dumps([plan['segments'], MUSIC_GAIN, BG_GAIN], sort_keys=True, default=str).encode())
    h.update(str(_mtime(os.path.join(rd, 'voiceover', 'voiceover.wav'))).encode()); h.update(str(_mtime(os.path.join(rd, mus['file']) if mus else None)).encode()); return h.hexdigest()[:12]


def status(folder):
    """{has_plan, exists, stale, key, length_s, made_at}: whether a plan exists to mix, whether there is a mix, and whether it no longer matches the plan."""
    from strata360.edit import project as PJ
    plan = PJ.load(folder).get('plan'); doc = {}
    try: doc = json.load(open(os.path.join(dir_of(folder), 'mix.json')))
    except (OSError, ValueError): pass
    has = bool(plan and plan.get('segments')); exists = os.path.exists(path_of(folder)) and bool(doc)
    return dict(has_plan=has, exists=exists, stale=bool(has and exists and doc.get('key') != key_of(folder, plan)), length_s=doc.get('length_s'), made_at=doc.get('made_at'), source=(plan or {}).get('source'))


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
    os.replace(out + '.part.m4a', out); json.dump(dict(key=key, length_s=round(total, 2), made_at=time.strftime('%Y-%m-%dT%H:%M:%S'), gains=dict(music=MUSIC_GAIN, background=BG_GAIN)), open(os.path.join(d, 'mix.json'), 'w'))
    log(f'rough mix: {total:.0f} s'); return status(folder)
