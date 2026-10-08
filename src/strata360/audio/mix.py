"""The film's sound (implementation plan A3), shared by the preview, the rough mix and the final film.

  build_audio(folder, plan, out, total_s, music_gain=0.5, bg_gain=None, loudness=None) -> report     a stereo 48 kHz WAV at `out`

What is in it, in order of the signal path:
  * each WINDOW's own sound: the clip's cleaned voice only over the lines the script plays (role `clip`, `voice_span`), the speech-free background (`audio_background.flac`) everywhere else; narration and b-roll windows have only the background; the level
    comes from the sound classifier (`audio_events`, analysis/sound_events.window_mix); words marked NEVER USE are silenced. A voice is centred; stereo sources stay stereo.
  * every JOIN is a crossfade, never a dip: a transition centred on a cut crossfades over the transition's own length (equal power), a plain cut over 30 ms (equal power, or straight when the two windows are one continuous stretch of one clip). The windows are
    read a little beyond their ends for it, so the film keeps its length.
  * the VOICE-OVER track as it is, centred.
  * the MUSIC (stereo, from its first downbeat, delayed when the cuts start it later), turned down by an exact gain curve (audio/duck.py): under the voice-over lines (12 dB, already down 80 ms before each line starts) and under the runner's own speech
    windows (8 dB), fading out over its last 2.5 s.
  * a limiter, and with `loudness` (LUFS) a two-pass loudness normalisation to that target (true peak at most -1 dBTP); the report carries what was measured.
`music_gain` is the music's level; `bg_gain`, when given, is the level of the clips' own background sound in narration and b-roll windows (the rough mix plays it quietly)."""
import json, os, subprocess, tempfile

import numpy as np

from strata360.audio import duck
from strata360.pipeline import config

SR = 48000
CUT_XFADE_S = 0.03          # a plain cut crossfades over this long
VO_DUCK_DB, VO_ATTACK_S, VO_RELEASE_S = 12.0, 0.08, 0.5
CLIP_DUCK_DB, CLIP_ATTACK_S, CLIP_RELEASE_S = 8.0, 0.25, 0.25          # under the runner's own speech (the old rule: to 0.4 with a quarter-second ramp each side)
MUSIC_FADE_S = 2.5
LOUDNESS_TP = -1.0


def proxy_of(folder, clip):
    from strata360.render import preview as PV
    return PV.proxy_of(folder, clip)


def has_audio(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', p], capture_output=True, text=True); return bool(r.stdout.strip())


def channels(p):
    """The number of audio channels of a file (1 when it cannot be read)."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=channels', '-of', 'csv=p=0', p], capture_output=True, text=True)
    try: return int(r.stdout.strip().split()[0])
    except (ValueError, IndexError): return 1


def window_gain(folder, g):
    """Linear gain for a window's own sound: you speaking is full volume; otherwise what the sound classifier found decides (analysis/sound_events.window_mix); without it the old rule (1.0 speech, 0.25 else)."""
    from strata360.analysis import sound_events as SE
    try: doc = json.load(open(os.path.join(config.race_dir(folder), 'clips', g['clip'], 'audio_events.json')))
    except (OSError, ValueError): return 1.0 if g.get('speech') else 0.25
    return 10 ** (SE.window_mix(doc, g['clip_start_s'], g['clip_start_s'] + g['dur_s'], bool(g.get('speech')))['gain_db'] / 20.0)


MUTE_PAD_S = 0.04            # a never-say word is silenced from this long before it starts to this long after it ends


def never_spans(folder, clip, start_s, dur_s):
    """[(a, b)] seconds inside the window [start_s, start_s + dur_s) of a clip where the wearer says something marked NEVER USE (red words, analysis/transcript_marks.py), as times from the window's start,
    padded a little. The clip's own sound is silenced there whatever the script plays."""
    from strata360.edit import script_pack as SP
    cdir = os.path.join(config.race_dir(folder), 'clips', clip); out = []
    for l in SP.transcript_lines(cdir, SP.label_of(clip)):
        if l.get('mark') != 'never': continue
        a, b = l['t0'] - MUTE_PAD_S - start_s, l['t1'] + MUTE_PAD_S - start_s
        if b > 0 and a < dur_s: out.append((max(a, 0.0), min(b, dur_s)))
    return out


def role_has_speech(role): return role not in ('vo', 'broll')           # the speech-free background track has nothing to silence


def mute_filter(spans):
    """The ffmpeg filter that silences `spans` ([(a, b)] seconds), or '' for none."""
    return ''.join(f",volume=enable='between(t,{a:.3f},{b:.3f})':volume=0" for a, b in spans)


def audio_of(folder, clip, role=None):
    """The sound to use for a clip in the film: the cleaned audio, else the original, else the proxy's own sound; None if there is none. In a plan made from the script (windows have a `role`) the clip's voice is
    heard ONLY in dialogue windows (role 'clip', the lines the script plays); narration and b-roll windows use the speech-free background track (audio_background.flac) or, until that exists, no sound of their own."""
    d = os.path.join(config.race_dir(folder), 'clips', clip)
    if role in ('vo', 'broll'):
        b = os.path.join(d, 'audio_background.flac'); return b if os.path.exists(b) else None
    for n in ('audio_clean.flac', 'audio_original.flac'):
        if os.path.exists(os.path.join(d, n)): return os.path.join(d, n)
    p = proxy_of(folder, clip); return p if p and has_audio(p) else None




def film_starts(plan):
    """[(start_s, dur_s)] of every window on the film's clock (a plan without film_start_s is read as windows end to end)."""
    out = []; run = 0.0
    for g in plan['segments']:
        a = float(g['film_start_s']) if g.get('film_start_s') is not None else run; d = float(g['dur_s']); out.append((a, d)); run = a + d
    return out


def joins(plan):
    """For each cut k (between window k-1 and k): (half length in seconds of its crossfade, whether the two windows are one continuous stretch of one clip). A transition crossfades over its own length (at most what the shorter window can give); a plain cut over CUT_XFADE_S."""
    segs = plan['segments']; fs = film_starts(plan); out = [(0.0, False)]
    for k in range(1, len(segs)):
        tr = segs[k].get('transition') or {}; room = max((min(fs[k - 1][1], fs[k][1]) - 0.1) / 2.0, 0.0)
        a, b = segs[k - 1], segs[k]; same = bool(a.get('clip')) and a.get('clip') == b.get('clip') and not a.get('synthetic') and abs(float(b.get('clip_start_s') or 0.0) - (float(a.get('clip_start_s') or 0.0) + float(a['dur_s']))) <= 0.05
        h = min(float(tr['dur_s']) / 2.0, room) if tr.get('type', 'cut') != 'cut' and tr.get('dur_s') else min(CUT_XFADE_S / 2.0, room)
        out.append((h, same and tr.get('type', 'cut') == 'cut'))
    return out


def _to_stereo(p, speech):
    """The ffmpeg filter that makes a window's sound stereo: a voice (or any mono source) is centred by copying it to both sides, a stereo source stays stereo unless it carries the voice (then it is centred too)."""
    if speech or channels(p) == 1: return 'aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0'
    return 'aformat=channel_layouts=stereo'


def _window(folder, g, n, bg_gain):
    """The ffmpeg inputs, filter chains and output label of one window's sound over [clip_start, clip_start + dur) as stereo: (inputs, chains, label, n_next)."""
    p = audio_of(folder, g['clip'], g.get('role')); d = g['dur_s']; speech = role_has_speech(g.get('role')); gain = bg_gain if bg_gain is not None and not speech else window_gain(folder, g); span = g.get('voice_span')
    pad = f'apad=whole_dur={d:.3f},atrim=0:{d:.3f}'
    if p and span and g.get('role') == 'clip':                                                       # the clip's voice only over the lines the script wants; the rest of the window is the speech-free background (a window run on past the wanted words must not play the next sentence)
        a, b = max(float(span[0]), 0.0), min(float(span[1]), d); outside = [x for x in ((0.0, a), (b, d)) if x[1] - x[0] > 1e-3]; bgp = audio_of(folder, g['clip'], 'broll'); bg_level = bg_gain if bg_gain is not None else window_gain(folder, dict(g, speech=False))
        inputs = ['-ss', f"{g['clip_start_s']:.3f}", '-t', f'{d:.3f}', '-i', p]
        voice = f"[{n}:a]aresample={SR},aformat=channel_layouts=mono,volume={gain}{mute_filter(sorted(set(outside) | set(never_spans(folder, g['clip'], g['clip_start_s'], d))))},{pad},pan=stereo|c0=c0|c1=c0"
        if bgp and outside:
            inputs += ['-ss', f"{g['clip_start_s']:.3f}", '-t', f'{d:.3f}', '-i', bgp]
            return inputs, [voice + f"[v{n}];[{n + 1}:a]aresample={SR},{_to_stereo(bgp, False)},volume={bg_level}{mute_filter([(a, b)])},{pad}[b{n}];[v{n}][b{n}]amix=inputs=2:normalize=0:duration=longest[s{n}]"], f's{n}', n + 2
        return inputs, [voice + f'[s{n}]'], f's{n}', n + 1
    if p:
        mute = mute_filter(never_spans(folder, g['clip'], g['clip_start_s'], d)) if speech else ''
        return ['-ss', f"{g['clip_start_s']:.3f}", '-t', f'{d:.3f}', '-i', p], [f"[{n}:a]aresample={SR},{_to_stereo(p, speech)},volume={gain}{mute},{pad}[s{n}]"], f's{n}', n + 1
    return ['-f', 'lavfi', '-t', f'{d:.3f}', '-i', f'anullsrc=r={SR}:cl=stereo'], [f'[{n}:a]anull[s{n}]'], f's{n}', n + 1


def _decode(path, ss, t):
    """`path` as stereo float32 at SR, from `ss` for `t` seconds: (2, n) array."""
    cmd = ['ffmpeg', '-v', 'error', '-ss', f'{max(ss, 0.0):.4f}', '-t', f'{t:.3f}', '-i', path, '-vn', '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout; x = np.frombuffer(raw[: len(raw) // 8 * 8], np.float32); return x.reshape(-1, 2).T.copy()


def music_track(plan, folder, total_s, music_gain, vo_path):
    """The music as a stereo float array (2, n) for the whole film: placed, ducked and faded, or None when the plan has no music file."""
    mus = (plan.get('film') or {}).get('music'); mp = os.path.join(config.race_dir(folder), mus['file']) if mus else None
    if not (mp and os.path.exists(mp)): return None
    n = int(round(total_s * SR)); delay = float(mus.get('delay_s') or 0.0); x = _decode(mp, float(mus.get('offset_s') or 0.0), max(total_s - max(delay, 0.0), 0.0) + 0.1)
    out = np.zeros((2, n), np.float32); d0 = int(round(max(delay, 0.0) * SR)); m = max(min(x.shape[1], n - d0), 0); out[:, d0:d0 + m] = x[:, :m]
    env = np.ones(n, np.float32)
    spans = [(a, a + d) for (a, d), g in zip(film_starts(plan), plan['segments']) if g.get('role') == 'clip']
    if spans: env = duck.combine(env, duck.envelope(n, SR, spans, CLIP_DUCK_DB, CLIP_ATTACK_S, CLIP_RELEASE_S))
    if vo_path and os.path.exists(vo_path):
        v = _decode(vo_path, 0.0, total_s).mean(axis=0); vs = duck.speech_spans(v, SR)
        if vs: env = duck.combine(env, duck.envelope(n, SR, vs, VO_DUCK_DB, VO_ATTACK_S, VO_RELEASE_S))
    fade = np.ones(n, np.float32); k = int(min(MUSIC_FADE_S, total_s) * SR)
    if k > 0: fade[n - k:] = np.linspace(1.0, 0.0, k, dtype=np.float32)
    return out * (music_gain * env * fade)


def _loudnorm(src, out, target, report):
    """Two-pass loudness normalisation of the WAV `src` to `target` LUFS with a true peak of at most LOUDNESS_TP; the measurements go into `report`."""
    flt = f'loudnorm=I={target}:TP={LOUDNESS_TP}:LRA=11:print_format=json'
    r = subprocess.run(['ffmpeg', '-v', 'info', '-nostats', '-i', src, '-af', flt, '-f', 'null', '-'], capture_output=True, text=True)
    try: m = json.loads(r.stderr[r.stderr.rindex('{'):r.stderr.rindex('}') + 1])
    except ValueError: m = None
    if not m or m.get('input_i') in (None, '-inf', 'inf') or float(m['input_i']) < -69:                                     # silence: nothing to normalise
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-ar', str(SR), out], check=True); report.update(target_lufs=target, measured=None, note='no measurable sound'); return
    flt2 = f"loudnorm=I={target}:TP={LOUDNESS_TP}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json"
    r2 = subprocess.run(['ffmpeg', '-v', 'info', '-nostats', '-y', '-i', src, '-af', flt2 + f',aresample={SR}', '-ar', str(SR), out], capture_output=True, text=True)
    if r2.returncode: raise RuntimeError('loudness: ' + r2.stderr[-300:])
    try: o = json.loads(r2.stderr[r2.stderr.rindex('{'):r2.stderr.rindex('}') + 1])
    except ValueError: o = {}
    report.update(target_lufs=target, true_peak_limit_dbtp=LOUDNESS_TP, measured=dict(input_lufs=float(m['input_i']), input_true_peak_dbtp=float(m['input_tp']), input_lra=float(m['input_lra'])),
                  output=dict(lufs=float(o['output_i']) if o.get('output_i') not in (None, '-inf') else None, true_peak_dbtp=float(o['output_tp']) if o.get('output_tp') not in (None, '-inf') else None, mode=o.get('normalization_type')))


def build_audio(folder, plan, out, total_s, music_gain=0.5, bg_gain=None, loudness=None):
    """Write the film's sound (see the module docstring) to the WAV `out`; returns a report dict (windows, music, voice-over, and with `loudness` the measured loudness before and after)."""
    segs = plan['segments']; fs = film_starts(plan); jn = joins(plan); inputs = []; chains = []; labels = []; n = 0
    for k, g in enumerate(segs):
        hin = jn[k][0] if k > 0 else 0.0; hout = jn[k + 1][0] if k + 1 < len(segs) else 0.0; cs = float(g['clip_start_s']); hin_eff = min(hin, max(cs, 0.0)) if not g.get('synthetic') else hin
        d = float(g['dur_s']) + hin_eff + hout; ext = dict(g, clip_start_s=cs - hin_eff, dur_s=d)
        if g.get('voice_span'): ext['voice_span'] = [float(g['voice_span'][0]) + hin_eff, float(g['voice_span'][1]) + hin_eff]
        ins, ch, lab, n = _window(folder, ext, n, bg_gain); inputs += ins; chains += ch
        fin = 2 * hin_eff; fout = 2 * hout; cin = 'tri' if jn[k][1] and k > 0 else 'qsin'; cout = 'tri' if k + 1 < len(segs) and jn[k + 1][1] else 'qsin'; f = []
        if fin > 1e-3: f.append(f'afade=t=in:st=0:d={fin:.4f}:curve={cin}')
        if fout > 1e-3: f.append(f'afade=t=out:st={d - fout:.4f}:d={fout:.4f}:curve={cout}')
        start_ms = max(fs[k][0] - hin_eff, 0.0) * 1000.0; f.append(f'adelay={start_ms:.1f}:all=1'); chains.append(f"[{lab}]{','.join(f)}[w{k}]"); labels.append(f'w{k}')
    vo = os.path.join(config.race_dir(folder), 'voiceover', 'voiceover.wav'); has_vo = os.path.exists(vo); tmp = tempfile.mkdtemp(prefix='mix-', dir=os.path.dirname(os.path.abspath(out)) or None); report = dict(windows=len(segs), voice_over=has_vo, music=False)
    try:
        mus = music_track(plan, folder, total_s, music_gain, vo if has_vo else None); k = n; mix = list(labels)
        if has_vo: inputs += ['-i', vo]; chains.append(f'[{k}:a]aresample={SR},aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0[vo]'); mix.append('vo'); k += 1
        if mus is not None:
            from scipy.io import wavfile
            mpath = os.path.join(tmp, 'music.wav'); wavfile.write(mpath, SR, np.ascontiguousarray(mus.T)); inputs += ['-i', mpath]; chains.append(f'[{k}:a]anull[mu]'); mix.append('mu'); k += 1; report['music'] = True
        chain = ';'.join(chains) + ';' + ''.join(f'[{x}]' for x in mix) + f'amix=inputs={len(mix)}:normalize=0:duration=longest,apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f},alimiter=limit=0.95[m]'
        pre = os.path.join(tmp, 'pre.wav') if loudness is not None else out
        r = subprocess.run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', chain, '-map', '[m]', '-ar', str(SR), '-ac', '2', pre], capture_output=True, text=True)
        if r.returncode: raise RuntimeError('audio: ' + r.stderr[-300:])
        if loudness is not None: _loudnorm(pre, out, float(loudness), report.setdefault('loudness', {}))
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)
    return report
