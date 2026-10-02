"""The voice-over track: the script spoken by a local synthetic voice (Kokoro, an open neural model that runs locally on macOS, Windows and Linux), placed on the film timeline, so timings and previews are realistic. Any line can later be replaced by your own
recording; the mix then uses the recording for that line and the synthetic voice for the rest.

Files in `<project>/voiceover/`:
  synth/<seg>-<hash>.wav   one spoken line (hash of voice, rate and text: a changed line is spoken again, an unchanged one is reused)
  recorded/<seg>.wav       your recording of a line (any audio file is converted)
  state.json               {voice, rate, use: {seg: 'synth' | 'recorded'}}  (a recording is used when there is one, unless the line is set to 'synth')
  timings.json             per line: source, film start, length, the window it has, tempo applied, fit ('ok' | 'sped' | 'over'); and the measured speaking rate
  voiceover.wav            the mix at the film's length: the audio the final render takes

A line starts a moment after its window starts and may run on into following windows that have no line of their own. A synthetic line that still does not fit is sped up (at most 1.25x);
a recording is never changed. What cannot fit is cut at the next line's start with a short fade, and reported as 'over'."""
import glob, hashlib, json, os, re, subprocess, time
from strata360.pipeline import config

LEAD_S = 0.12; GAP_S = 0.15; MAX_TEMPO = 1.25; SR = 48000
DEFAULT_STATE = dict(engine=None, voice=None, rate=150, use={})
_TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'


def base(folder): return os.path.join(config.race_dir(folder), 'voiceover')


def _state_path(folder): return os.path.join(base(folder), 'state.json')


def load_state(folder):
    try: s = json.load(open(_state_path(folder)))
    except (OSError, ValueError): s = {}
    return dict(engine=s.get('engine'), voice=s.get('voice'), rate=int(s.get('rate') or DEFAULT_STATE['rate']), use=dict(s.get('use') or {}))


def save_state(folder, s):
    os.makedirs(base(folder), exist_ok=True); json.dump(s, open(_state_path(folder), 'w'), indent=1)


# ---- the speech engine: Kokoro-82M (Apache 2.0), an open neural voice that runs locally on any platform (ONNX); one engine, British male voices ----------------------------------------------------
MODEL_DIR = os.environ.get('STRATA360_KOKORO') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'kokoro')
MODEL_FILES = {'kokoro-v1.0.onnx': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx', 'voices-v1.0.bin': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin'}
GROUPS = {'bm': 'British male', 'bf': 'British female', 'am': 'American male', 'af': 'American female'}   # English voices; British male first
DEFAULT_VOICES = ['bm_lewis', 'bm_george', 'bm_fable', 'bm_daniel']          # British male first; the first is the default
BASE_WPM = 150.0                                  # the voice at speed 1.0 speaks about this fast; `rate` (words per minute) sets the speed relative to it
_K = {}


def model_ready(): return all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in MODEL_FILES)


def fetch_model(log=print):
    """Download the model files (about 350 MB) into models/kokoro; skips files that are there."""
    import urllib.request
    os.makedirs(MODEL_DIR, exist_ok=True)
    for f, url in MODEL_FILES.items():
        dest = os.path.join(MODEL_DIR, f)
        if os.path.exists(dest): continue
        log(f'downloading {f} ...'); urllib.request.urlretrieve(url, dest + '.part'); os.replace(dest + '.part', dest)


def _kokoro():
    if 'k' not in _K:
        import logging; logging.getLogger('phonemizer').setLevel(logging.ERROR)             # its 'words count mismatch' warnings are harmless
        from kokoro_onnx import Kokoro
        _K['k'] = Kokoro(os.path.join(MODEL_DIR, 'kokoro-v1.0.onnx'), os.path.join(MODEL_DIR, 'voices-v1.0.bin'))
    return _K['k']


def voices():
    """The English voices in the model's voice file: [{name, label, group, lang}], British male first (the default is bm_lewis)."""
    try:
        import numpy as np
        names = [n for n in np.load(os.path.join(MODEL_DIR, 'voices-v1.0.bin')).files if n[:2] in GROUPS]
    except (OSError, ValueError): names = DEFAULT_VOICES
    order = list(GROUPS); names = sorted(names, key=lambda n: (order.index(n[:2]), DEFAULT_VOICES.index(n) if n in DEFAULT_VOICES else 99, n))
    return [dict(name=n, label=n[3:].title(), group=GROUPS[n[:2]], lang='en_GB' if n[0] == 'b' else 'en_US') for n in names]


def _kokoro_available():
    try: import kokoro_onnx  # noqa: F401
    except ImportError: return False
    return model_ready()


def _kokoro_speak(voice, rate, text, out):
    import numpy as np
    from scipy.io import wavfile
    speed = float(min(max(rate / BASE_WPM, 0.6), 1.4)); samples, sr = _kokoro().create(text, voice=voice or DEFAULT_VOICES[0], speed=speed, lang='en-gb' if (voice or 'b')[0] == 'b' else 'en-us')
    wavfile.write(out, sr, (np.clip(samples, -1, 1) * 32767).astype(np.int16))


ENGINES = {'kokoro': ('Kokoro (open model, British male)', _kokoro_available, voices, _kokoro_speak)}


def available_engines():
    res = []
    for k, (label, ok, vs, _) in ENGINES.items():
        try:
            if ok(): res.append(dict(id=k, label=label, voices=vs()))
        except (OSError, subprocess.SubprocessError, RuntimeError, ImportError): pass
    return res


def pick(state):
    """(engine id, voice) to use: the saved ones if still available, else the first available engine and its first voice."""
    av = available_engines()
    if not av: raise RuntimeError('the voice model is not installed: run `strata360 fetch-models --voice` (about 350 MB, Kokoro, Apache 2.0) and `pip install kokoro-onnx`')
    e = next((x for x in av if x['id'] == state.get('engine')), av[0]); names = [v['name'] for v in e['voices']]
    v = state.get('voice') if state.get('voice') in names else (names[0] if names else None)
    return e['id'], v


SCRIPT2_LINES = os.path.join('script2', 'lines.json')       # the narration of the whole-race script's plan (edit/script_plan.py): {draft, lines: [{seg, text, film_start_s, seconds, ...}]}


def script2_lines(folder):
    """(name, lines) of the script plan's narration when it is newer than any beat-planner script, else None. The name changes whenever the words or their places change, so a finished track is rebuilt."""
    p = os.path.join(config.race_dir(folder), SCRIPT2_LINES)
    if not os.path.exists(p): return None
    legacy = sorted(glob.glob(os.path.join(config.race_dir(folder), 'scripts', 'script-*.json')))
    if legacy and os.path.getmtime(legacy[-1]) > os.path.getmtime(p): return None
    try: d = json.load(open(p))
    except (OSError, ValueError): return None
    lines = [dict(seg=l['seg'], text=l['text'].strip(), film_start_s=float(l['film_start_s']), seconds=float(l['seconds'])) for l in d.get('lines', []) if (l.get('text') or '').strip()]
    return 'script2-' + hashlib.sha1(json.dumps([[l['seg'], l['text'], l['film_start_s'], l['seconds']] for l in lines]).encode()).hexdigest()[:10], lines


def measured_wpm(folder):
    """How fast the voice-over really speaks, words a minute: the spoken narration of the newest script plan (script2/lines.json: its measured `speak_s` per line, not the estimated ones), or None when there is none yet."""
    try: d = json.load(open(os.path.join(config.race_dir(folder), SCRIPT2_LINES)))
    except (OSError, ValueError): return None
    ls = [l for l in d.get('lines', []) if not l.get('estimated') and float(l.get('speak_s') or 0) > 0 and (l.get('text') or '').strip()]
    words = sum(len(l['text'].split()) for l in ls); sec = sum(float(l['speak_s']) for l in ls)
    return round(words * 60.0 / sec) if sec >= 10.0 and words >= 20 else None


def line_durations(folder, lines, log=print):
    """{seg: seconds} how long each narration line takes at its natural pace: your recording of it if there is one, else the synthetic voice (reused when its words did not change). {} when no voice is installed
    (the planner then estimates from the words)."""
    st = load_state(folder)
    try: engine, voice = pick(st)
    except RuntimeError as e: log(f'no voice: {e}'); return {}
    out = {}
    for l in lines:
        rp = recorded_path(folder, l['seg']); sp = synth_line(folder, l['seg'], l['text'], engine, voice, st['rate']); a, b = speech_span(rp if source_for(st, l['seg'], os.path.exists(rp)) == 'recorded' else sp); out[l['seg']] = b - a
    return out


def script_lines(folder):
    """(file name, [{seg, text, film_start_s, seconds}]) of the newest script; lines with no words are left out."""
    s2 = script2_lines(folder)
    if s2: return s2
    files = sorted(glob.glob(os.path.join(config.race_dir(folder), 'scripts', 'script-*.json')))
    if not files: return None, []
    d = json.load(open(files[-1]))
    return os.path.basename(files[-1]), [dict(seg=l['seg'], text=l['text'].strip(), film_start_s=float(l['film_start_s']), seconds=float(l['seconds'])) for l in d.get('lines', []) if (l.get('text') or '').strip()]


def film_length(folder):
    try: return float(json.load(open(os.path.join(config.race_dir(folder), 'project.json')))['edit']['plan']['film']['length_s'])
    except (OSError, ValueError, KeyError, TypeError): return None


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise RuntimeError((r.stderr or r.stdout)[-400:])
    return r


def duration(path):
    return float(_run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).stdout.strip())


def speech_span(path):
    """(start_s, end_s) of the speech in a take: the silence before and after it is not part of the line (edit/vo_measure.speech_runs: energy within 35 dB of the loudest, a breath of margin), so a line starts where its first word does
    and its length is the speech's. The whole file when no speech is found or the file cannot be read."""
    from strata360.edit import vo_measure as M
    try: x, sr = M.read_audio(path); runs = M.speech_runs(x, sr)
    except Exception: runs = []
    return (float(runs[0][0]), float(runs[-1][1])) if runs else (0.0, duration(path))


def _spoken(text): return re.sub(r'\s+', ' ', text.replace('—', ', ').replace('…', '...')).strip()


def _name(seg): return f'{int(seg):03d}' if str(seg).isdigit() else str(seg)         # script lines are numbered; the lines of a block script have keys such as 003b0


def synth_path(folder, seg, text, engine, voice, rate):
    h = hashlib.sha1(f'{engine}|{voice}|{rate}|{text}'.encode()).hexdigest()[:10]
    return os.path.join(base(folder), 'synth', f'{_name(seg)}-{h}.wav')


def synth_line(folder, seg, text, engine, voice, rate):
    p = synth_path(folder, seg, text, engine, voice, rate)
    if os.path.exists(p): return p
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + '.raw.wav'
    ENGINES[engine][3](voice, rate, _spoken(text), tmp)
    _run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', _TRIM, '-ar', str(SR), '-ac', '1', p + '.part.wav']); os.replace(p + '.part.wav', p); os.remove(tmp)
    return p


def recorded_path(folder, seg): return os.path.join(base(folder), 'recorded', f'{_name(seg)}.wav')


def save_recording(folder, seg, raw_path):
    """Convert an uploaded audio file to the line's recording (mono wav, silence trimmed at both ends)."""
    p = recorded_path(folder, seg); os.makedirs(os.path.dirname(p), exist_ok=True)
    _run(['ffmpeg', '-y', '-v', 'error', '-i', raw_path, '-af', _TRIM, '-ar', str(SR), '-ac', '1', p + '.part.wav']); os.replace(p + '.part.wav', p); return p


def delete_recording(folder, seg):
    p = recorded_path(folder, seg)
    if os.path.exists(p): os.remove(p)


def source_for(state, seg, has_recording):
    u = state['use'].get(str(seg))
    return 'recorded' if has_recording and u != 'synth' else 'synth'


def build(folder, engine=None, voice=None, rate=None, progress=None):
    """Speak every line (reusing unchanged ones), place them on the timeline and mix `voiceover.wav`; progress is kept in status.json (the GUI shows it). Returns the timings document."""
    write_status(folder, 'speaking', 0, 0)
    def prog(i, n):
        write_status(folder, 'speaking', i, n); progress and progress(i, n)
    try: doc = _build(folder, engine, voice, rate, prog)
    except BaseException as e: write_status(folder, 'error', error=f'{type(e).__name__}: {e}'); raise
    write_status(folder, 'done', len(doc['lines']), len(doc['lines'])); return doc


def track_key(engine, voice, rate): return f'{engine}-{voice}-{int(rate)}'


def track_dir(folder, key): return os.path.join(base(folder), 'tracks', key)


def signature(folder, script, st, total):
    """What a finished track depends on: the script, the voice and speed, your recordings and which take each line uses, and the film length. A track with this signature is still right."""
    rec = {os.path.basename(p): int(os.path.getmtime(p)) for p in sorted(glob.glob(os.path.join(base(folder), 'recorded', '*.wav')))}
    return hashlib.sha1(json.dumps([script, st['engine'], st['voice'], st['rate'], rec, st['use'], round(total, 2)], sort_keys=True).encode()).hexdigest()[:12]


def _publish(folder, key):
    """Make a finished track the active one: its mix and timings become voiceover.wav / timings.json (what the film's sound and the app use)."""
    import shutil
    d = track_dir(folder, key)
    for n in ('voiceover.wav', 'timings.json'):
        shutil.copyfile(os.path.join(d, n), os.path.join(base(folder), n + '.part')); os.replace(os.path.join(base(folder), n + '.part'), os.path.join(base(folder), n))


def cached_tracks(folder):
    """The voices that already have a finished track for the CURRENT script and recordings: [{engine, voice, rate, key, measured_wpm, over, sped, active}], to swap between and compare."""
    script, lines = script_lines(folder)
    if not lines: return []
    st = load_state(folder); total = film_length(folder) or max(l['film_start_s'] + l['seconds'] for l in lines); out = []; active = (load_timings(folder) or {})
    for p in sorted(glob.glob(os.path.join(base(folder), 'tracks', '*', 'timings.json'))):
        try: d = json.load(open(p))
        except (OSError, ValueError): continue
        s2 = dict(st, engine=d['engine'], voice=d['voice'], rate=d['rate'])
        if d.get('sig') == signature(folder, script, s2, total) and os.path.exists(os.path.join(os.path.dirname(p), 'voiceover.wav')):
            out.append(dict(engine=d['engine'], voice=d['voice'], rate=d['rate'], key=os.path.basename(os.path.dirname(p)), measured_wpm=d.get('measured_wpm'), over=len(d.get('over', [])), sped=len(d.get('sped', [])),
                            active=(active.get('voice'), active.get('rate'), active.get('sig')) == (d['voice'], d['rate'], d.get('sig'))))
    return out


def _build(folder, engine=None, voice=None, rate=None, progress=None):
    st = load_state(folder)
    if engine or voice or rate:                                                          # an explicit request is the user's choice: kept (the job never writes the voice back, so a newer request is not lost)
        if engine: st['engine'] = engine
        if voice: st['voice'] = voice
        if rate: st['rate'] = int(rate)
        save_state(folder, st)
    st['engine'], st['voice'] = pick(st); script, lines = script_lines(folder)
    if not lines: raise RuntimeError('there is no script yet: write one first')
    lines.sort(key=lambda l: l['film_start_s']); total = film_length(folder) or max(l['film_start_s'] + l['seconds'] for l in lines)
    key = track_key(st['engine'], st['voice'], st['rate']); sig = signature(folder, script, st, total); tj = os.path.join(track_dir(folder, key), 'timings.json')
    try:
        done = json.load(open(tj))
        if done.get('sig') == sig and os.path.exists(os.path.join(track_dir(folder, key), 'voiceover.wav')):         # this voice was already made for this script: swapping to it is instant
            _publish(folder, key); return done
    except (OSError, ValueError): pass
    wins = sorted({round(l['film_start_s'], 3) for l in lines}); out = []
    for i, l in enumerate(lines):
        sp = synth_line(folder, l['seg'], l['text'], st['engine'], st['voice'], st['rate']); rp = recorded_path(folder, l['seg']); has_rec = os.path.exists(rp)
        src = source_for(st, l['seg'], has_rec); path = rp if src == 'recorded' else sp
        nxt = lines[i + 1]['film_start_s'] if i + 1 < len(lines) else total
        start = l['film_start_s'] + LEAD_S; avail = max(0.3, min(nxt - GAP_S, total) - start); ta, tb = speech_span(path); d = tb - ta; tempo = 1.0; fit = 'ok'
        if d > avail:
            if src == 'synth' and d / avail <= MAX_TEMPO: tempo = round(d / avail + 0.005, 3); fit = 'sped'
            elif src == 'synth': tempo = MAX_TEMPO; fit = 'over'
            else: fit = 'over'
        played = d / tempo
        out.append(dict(seg=l['seg'], text=l['text'], source=src, has_recording=has_rec, recorded=has_rec, path=os.path.relpath(path, base(folder)), film_start_s=round(start, 3), window_s=l['seconds'], room_s=round(avail, 3),
                        natural_s=round(d, 3), trim=[round(ta, 3), round(tb, 3)], choices=overflow_choices(src, d / tempo - avail), played_s=round(min(played, avail) if fit == 'over' else played, 3), overrun_s=round(max(0.0, played - avail), 3), tempo=tempo, fit=fit,
                        synth_s=round(duration(sp), 3)))
        if progress: progress(i + 1, len(lines))
    os.makedirs(track_dir(folder, key), exist_ok=True); _mix(folder, out, total, os.path.join(track_dir(folder, key), 'voiceover.wav'))
    words = sum(len(o['text'].split()) for o in out); syn = sum(o['synth_s'] for o in out)
    doc = dict(script=script, sig=sig, engine=st['engine'], voice=st['voice'], rate=st['rate'], film_length_s=round(total, 3), lines=out, measured_wpm=round(words / syn * 60, 1) if syn else None,
               over=[o['seg'] for o in out if o['fit'] == 'over'], sped=[o['seg'] for o in out if o['fit'] == 'sped'])
    json.dump(doc, open(tj, 'w'), indent=1); _publish(folder, key); return doc


def overflow_choices(src, over_s):
    """What can be done about a line that is `over_s` seconds longer than the room it has (none: []): the choices as plain sentences, the first being the cheapest."""
    if over_s <= 0.005: return []
    c = [f'shorten the line by about {over_s:.1f} s of speech', 'give the clip more footage for it (a longer b-roll, or the neighbouring clip)', 'let the last frame hold while it finishes (the film gets longer)']
    return c + (['let the voice speak faster (only for the synthetic voice)'] if src == 'synth' else ['record it again, shorter'])


def _mix(folder, out, total, dest):
    inputs = []; chains = []
    for i, o in enumerate(out):
        p = os.path.join(base(folder), o['path']); inputs += ['-i', p]; f = []
        if o.get('trim'): f += [f"atrim={o['trim'][0]:.3f}:{o['trim'][1]:.3f}", 'asetpts=PTS-STARTPTS']
        if o['tempo'] != 1.0: f.append(f"atempo={o['tempo']}")
        if o['fit'] == 'over': f.append(f"atrim=0:{o['played_s']}"); f.append(f"afade=t=out:st={max(0.0, o['played_s'] - 0.08):.3f}:d=0.08")
        f.append(f"adelay={int(round(o['film_start_s'] * 1000))}:all=1"); chains.append(f"[{i}:a]" + ','.join(f) + f'[a{i}]')
    mix = ''.join(f'[a{i}]' for i in range(len(out))) + f'amix=inputs={len(out)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f},alimiter=limit=0.95[m]'
    _run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', ';'.join(chains + [mix]), '-map', '[m]', '-ar', str(SR), '-ac', '1', dest + '.part.wav']); os.replace(dest + '.part.wav', dest)


def newest_script(folder):
    s2 = script2_lines(folder)
    if s2: return s2[0]
    f = sorted(glob.glob(os.path.join(config.race_dir(folder), 'scripts', 'script-*.json')))
    return os.path.basename(f[-1]) if f else None


def alive(pid):
    from strata360 import oslib
    return oslib.pid_alive(pid)


def running(folder):
    """Is a voice-over job working on this project (its own pid is in status.json, so this also holds after the server restarts)."""
    st = load_status(folder); return bool(st and st.get('state') == 'speaking' and alive(st.get('pid')))


def save_edit(folder, texts):
    """Save an edited script as a NEW version (the old ones stay): `texts` maps segment number -> new text. Returns the new file name."""
    import datetime as dt
    files = sorted(glob.glob(os.path.join(config.race_dir(folder), 'scripts', 'script-*.json')))
    if not files: raise RuntimeError('there is no script yet')
    d = json.load(open(files[-1])); wpm = float(d.get('wpm') or 145.0); changed = 0
    for l in d.get('lines', []):
        new = texts.get(str(l['seg']), texts.get(l['seg']))
        if new is not None and new.strip() != (l.get('text') or '').strip():
            l['text'] = new.strip(); l['words'] = len(l['text'].split()); l['est_speak_s'] = round(l['words'] / wpm * 60.0, 1); changed += 1
    if not changed: return None
    d['edited'] = True; d['total_words'] = sum(l.get('words') or 0 for l in d['lines']); d['total_speak_s'] = round(sum(l.get('est_speak_s') or 0 for l in d['lines']), 1)
    name = 'script-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '.json'
    if name <= os.path.basename(files[-1]): name = os.path.basename(files[-1])[:-5] + 'e.json'                     # never sorts before the one it was made from
    json.dump(d, open(os.path.join(config.race_dir(folder), 'scripts', name), 'w'), indent=1); return name


def status_path(folder): return os.path.join(base(folder), 'status.json')


def write_status(folder, state, done=0, total=0, **kw):
    os.makedirs(base(folder), exist_ok=True); tmp = status_path(folder) + '.tmp'; json.dump(dict(state=state, pid=os.getpid(), done=done, total=total, at=time.time(), **kw), open(tmp, 'w')); os.replace(tmp, status_path(folder))


def load_status(folder):
    try: return json.load(open(status_path(folder)))
    except (OSError, ValueError): return None


def load_timings(folder):
    try: return json.load(open(os.path.join(base(folder), 'timings.json')))
    except (OSError, ValueError): return None
