"""The voice-over track: the script spoken by a local synthetic voice (macOS `say`, Windows SAPI, eSpeak NG or Piper: whichever this machine has), placed on the film timeline, so timings and previews are realistic. Any line can later be replaced by your own
recording; the mix then uses the recording for that line and the synthetic voice for the rest.

Files in `<project>/voiceover/`:
  synth/<seg>-<hash>.wav   one spoken line (hash of voice, rate and text: a changed line is spoken again, an unchanged one is reused)
  recorded/<seg>.wav       your recording of a line (any audio file is converted)
  state.json               {voice, rate, use: {seg: 'synth' | 'recorded'}}  (a recording is used when there is one, unless the line is set to 'synth')
  timings.json             per line: source, film start, length, the window it has, tempo applied, fit ('ok' | 'sped' | 'over'); and the measured speaking rate
  voiceover.wav            the mix at the film's length: the audio the final render takes

A line starts a moment after its window starts and may run on into following windows that have no line of their own. A synthetic line that still does not fit is sped up (at most 1.25x);
a recording is never changed. What cannot fit is cut at the next line's start with a short fade, and reported as 'over'."""
import glob, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from strata360.pipeline import config

LEAD_S = 0.12; GAP_S = 0.15; MAX_TEMPO = 1.25; SR = 48000
DEFAULT_STATE = dict(engine=None, voice=None, rate=165, use={})
_TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'


def base(folder): return os.path.join(config.race_dir(folder), 'voiceover')


def _state_path(folder): return os.path.join(base(folder), 'state.json')


def load_state(folder):
    try: s = json.load(open(_state_path(folder)))
    except (OSError, ValueError): s = {}
    return dict(engine=s.get('engine'), voice=s.get('voice'), rate=int(s.get('rate') or DEFAULT_STATE['rate']), use=dict(s.get('use') or {}))


def save_state(folder, s):
    os.makedirs(base(folder), exist_ok=True); json.dump(s, open(_state_path(folder), 'w'), indent=1)


# ---- speech engines: one per platform, all local; each writes a wav for one line -------------------------------------------------------------------------------------------------------
def _ps(script, *args):
    exe = shutil.which('powershell') or shutil.which('pwsh')
    return subprocess.run([exe, '-NoProfile', '-NonInteractive', '-Command', script, *args], capture_output=True, text=True, timeout=120)


_NOVELTY = {'Albert', 'Bad News', 'Bahh', 'Bells', 'Boing', 'Bubbles', 'Cellos', 'Wobble', 'Good News', 'Jester', 'Organ', 'Superstar', 'Trinoids', 'Whisper', 'Zarvox', 'Fred', 'Junior', 'Ralph'}   # macOS joke voices


def _say_voices():
    out = subprocess.run(['say', '-v', '?'], capture_output=True, text=True, timeout=20).stdout; res = []; seen = set()
    for ln in out.splitlines():
        m = re.match(r'^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\s', ln)
        if m and m.group(2).startswith('en_') and m.group(1) not in seen and m.group(1) not in _NOVELTY: seen.add(m.group(1)); res.append(dict(name=m.group(1), lang=m.group(2)))
    return res


def _say_speak(voice, rate, text, out): _run(['say', '-v', voice or 'Daniel', '-r', str(rate), '-o', out, '--', text])


def _sapi_voices():
    r = _ps('Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | % { $_.VoiceInfo.Name + "|" + $_.VoiceInfo.Culture.Name }')
    return [dict(name=a.strip(), lang=b.strip().replace('-', '_')) for a, b in (x.split('|', 1) for x in r.stdout.splitlines() if '|' in x) if b.strip().lower().startswith('en')]


def _sapi_speak(voice, rate, text, out):                                           # rate in words per minute -> SAPI -10..10 (0 = about 175 wpm; each step about 10%)
    step = max(-10, min(10, round((rate / 175.0 - 1) * 10)))
    tf = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8'); tf.write(text); tf.close()
    try:
        sel = f"$s.SelectVoice('{voice}');" if voice else ''
        r = _ps(f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; {sel} $s.Rate = {step}; $s.SetOutputToWaveFile('{out}'); $s.Speak([IO.File]::ReadAllText('{tf.name}')); $s.Dispose()")
        if r.returncode: raise RuntimeError(r.stderr[-300:])
    finally: os.remove(tf.name)


def _espeak_exe(): return shutil.which('espeak-ng') or shutil.which('espeak')


def _espeak_voices():
    r = subprocess.run([_espeak_exe(), '--voices=en'], capture_output=True, text=True, timeout=20); res = []
    for ln in r.stdout.splitlines()[1:]:
        c = ln.split()
        if len(c) >= 4: res.append(dict(name=c[3], lang=c[1]))
    return res


def _espeak_speak(voice, rate, text, out): _run([_espeak_exe(), '-v', voice or 'en-gb', '-s', str(rate), '-w', out, '--', text])


def _piper_exe(): return shutil.which('piper')


def _piper_voices():                                                               # piper needs a model file: any *.onnx in $STRATA360_PIPER_VOICES (or ./models/piper)
    d = os.environ.get('STRATA360_PIPER_VOICES') or os.path.join(os.path.dirname(os.path.abspath(config.__file__)), '..', '..', '..', 'models', 'piper')
    return [dict(name=os.path.basename(f)[:-5], lang='en', path=f) for f in sorted(glob.glob(os.path.join(d, '*.onnx')))]


def _piper_speak(voice, rate, text, out):
    m = next((v['path'] for v in _piper_voices() if v['name'] == voice), None)
    if not m: raise RuntimeError('no piper voice model found')
    r = subprocess.run([_piper_exe(), '-m', m, '-f', out, '--length_scale', str(round(165.0 / rate, 3))], input=text, capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stderr[-300:])


ENGINES = {   # id -> (label, available?, voices, speak); the first available one in this order is the default
    'piper': ('Piper (neural, any platform)', lambda: bool(_piper_exe()) and bool(_piper_voices()), _piper_voices, _piper_speak),
    'say': ('macOS voices', lambda: sys.platform == 'darwin' and bool(shutil.which('say')), _say_voices, _say_speak),
    'sapi': ('Windows voices (SAPI)', lambda: sys.platform == 'win32' and bool(shutil.which('powershell') or shutil.which('pwsh')), _sapi_voices, _sapi_speak),
    'espeak': ('eSpeak NG', lambda: bool(_espeak_exe()), _espeak_voices, _espeak_speak),
}


def available_engines():
    res = []
    for k, (label, ok, vs, _) in ENGINES.items():
        try:
            if ok(): res.append(dict(id=k, label=label, voices=vs()))
        except (OSError, subprocess.SubprocessError, RuntimeError): pass
    return res


def pick(state):
    """(engine id, voice) to use: the saved ones if still available, else the first available engine and its first (preferring en_GB) voice."""
    av = available_engines()
    if not av: raise RuntimeError('no speech engine found: macOS has `say`; on Windows PowerShell with System.Speech is used; on Linux install espeak-ng (or piper with a voice model)')
    e = next((x for x in av if x['id'] == state.get('engine')), av[0]); names = [v['name'] for v in e['voices']]
    v = state.get('voice') if state.get('voice') in names else next((v['name'] for v in e['voices'] if v['lang'] == 'en_GB'), names[0] if names else None)
    return e['id'], v


def script_lines(folder):
    """(file name, [{seg, text, film_start_s, seconds}]) of the newest script; lines with no words are left out."""
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


def _spoken(text): return re.sub(r'\s+', ' ', text.replace('—', ', ').replace('…', '...')).strip()


def synth_path(folder, seg, text, engine, voice, rate):
    h = hashlib.sha1(f'{engine}|{voice}|{rate}|{text}'.encode()).hexdigest()[:10]
    return os.path.join(base(folder), 'synth', f'{int(seg):03d}-{h}.wav')


def synth_line(folder, seg, text, engine, voice, rate):
    p = synth_path(folder, seg, text, engine, voice, rate)
    if os.path.exists(p): return p
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + '.raw.wav' if engine != 'say' else p + '.aiff'
    ENGINES[engine][3](voice, rate, _spoken(text), tmp)
    _run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-af', _TRIM, '-ar', str(SR), '-ac', '1', p + '.part.wav']); os.replace(p + '.part.wav', p); os.remove(tmp)
    return p


def recorded_path(folder, seg): return os.path.join(base(folder), 'recorded', f'{int(seg):03d}.wav')


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
    """Speak every line (reusing unchanged ones), place them on the timeline and mix `voiceover.wav`. Returns the timings document."""
    st = load_state(folder)
    if engine: st['engine'] = engine
    if voice: st['voice'] = voice
    if rate: st['rate'] = int(rate)
    st['engine'], st['voice'] = pick(st); script, lines = script_lines(folder)
    if not lines: raise RuntimeError('there is no script yet: write one first')
    lines.sort(key=lambda l: l['film_start_s']); total = film_length(folder) or max(l['film_start_s'] + l['seconds'] for l in lines)
    wins = sorted({round(l['film_start_s'], 3) for l in lines}); out = []
    for i, l in enumerate(lines):
        sp = synth_line(folder, l['seg'], l['text'], st['engine'], st['voice'], st['rate']); rp = recorded_path(folder, l['seg']); has_rec = os.path.exists(rp)
        src = source_for(st, l['seg'], has_rec); path = rp if src == 'recorded' else sp
        nxt = lines[i + 1]['film_start_s'] if i + 1 < len(lines) else total
        start = l['film_start_s'] + LEAD_S; avail = max(0.3, min(nxt - GAP_S, total) - start); d = duration(path); tempo = 1.0; fit = 'ok'
        if d > avail:
            if src == 'synth' and d / avail <= MAX_TEMPO: tempo = round(d / avail + 0.005, 3); fit = 'sped'
            elif src == 'synth': tempo = MAX_TEMPO; fit = 'over'
            else: fit = 'over'
        played = d / tempo
        out.append(dict(seg=l['seg'], text=l['text'], source=src, has_recording=has_rec, recorded=has_rec, path=os.path.relpath(path, base(folder)), film_start_s=round(start, 3), window_s=l['seconds'], room_s=round(avail, 3),
                        natural_s=round(d, 3), played_s=round(min(played, avail) if fit == 'over' else played, 3), overrun_s=round(max(0.0, played - avail), 3), tempo=tempo, fit=fit,
                        synth_s=round(duration(sp), 3)))
        if progress: progress(i + 1, len(lines))
    _mix(folder, out, total)
    words = sum(len(o['text'].split()) for o in out); syn = sum(o['synth_s'] for o in out)
    doc = dict(script=script, engine=st['engine'], voice=st['voice'], rate=st['rate'], film_length_s=round(total, 3), lines=out, measured_wpm=round(words / syn * 60, 1) if syn else None,
               over=[o['seg'] for o in out if o['fit'] == 'over'], sped=[o['seg'] for o in out if o['fit'] == 'sped'])
    save_state(folder, st); json.dump(doc, open(os.path.join(base(folder), 'timings.json'), 'w'), indent=1); return doc


def _mix(folder, out, total):
    inputs = []; chains = []
    for i, o in enumerate(out):
        p = os.path.join(base(folder), o['path']); inputs += ['-i', p]; f = []
        if o['tempo'] != 1.0: f.append(f"atempo={o['tempo']}")
        if o['fit'] == 'over': f.append(f"atrim=0:{o['played_s']}"); f.append(f"afade=t=out:st={max(0.0, o['played_s'] - 0.08):.3f}:d=0.08")
        f.append(f"adelay={int(round(o['film_start_s'] * 1000))}:all=1"); chains.append(f"[{i}:a]" + ','.join(f) + f'[a{i}]')
    mix = ''.join(f'[a{i}]' for i in range(len(out))) + f'amix=inputs={len(out)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f},alimiter=limit=0.95[m]'
    p = os.path.join(base(folder), 'voiceover.wav')
    _run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', ';'.join(chains + [mix]), '-map', '[m]', '-ar', str(SR), '-ac', '1', p + '.part.wav']); os.replace(p + '.part.wav', p)


def load_timings(folder):
    try: return json.load(open(os.path.join(base(folder), 'timings.json')))
    except (OSError, ValueError): return None
