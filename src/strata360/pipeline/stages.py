"""Pipeline stages. Each stage: a name, a version (bump it when the code changes results), the config keys it depends on, its dependencies
and its output files. The runner (runner.py) skips a stage when its cache key is unchanged, so re-running is cheap and changing a setting
re-runs only what it affects."""
import functools, json, os, time
from dataclasses import dataclass, field
from typing import Callable

STAGES = {}
ORDER = []


@dataclass
class Stage:
    name: str
    version: int
    fn: Callable
    keys: tuple = ()          # config keys this stage's result depends on
    deps: tuple = ()          # stages whose outputs it reads
    outputs: tuple = ()
    default: bool = True      # part of the default `run`
    note: str = ''
    soft_deps: tuple = ()      # stages whose output is used when present and waited for before a NEW item starts (they do not enter the key: finished results stay valid)
    retries: int = 2           # how many times a failed item is tried again (waiting longer each time; see pipeline/retry.py) before it counts as failed
    needs_track: bool = False  # uses the race GPS track: waits until one is set, and is redone when the track or the clip-to-track time alignment changes


def stage(name, version, keys=(), deps=(), outputs=(), default=True, note='', needs_track=False, soft_deps=(), retries=2):
    def deco(fn):
        STAGES[name] = Stage(name, version, fn, tuple(keys), tuple(deps), tuple(outputs), default, note, tuple(soft_deps), retries, needs_track); ORDER.append(name); return fn
    return deco


class Ctx:
    """What a stage sees for one clip."""
    def __init__(self, clip, cfg, clip_dir, log):
        self.clip, self.cfg, self.dir, self.log = clip, cfg, clip_dir, log
    def path(self, name): return os.path.join(self.dir, name)
    def read(self, name): return json.load(open(self.path(name)))
    def write(self, name, obj):
        tmp = self.path(name) + '.tmp'
        with open(tmp, 'w') as f: json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path(name))                       # atomic: a crash never leaves a half-written artefact
    @property
    def clip_json(self): return self.read('clip.json')
    def stamped(self, obj):
        from strata360.pipeline.ingest import stamp
        return stamp(self.clip_json, obj)


@functools.lru_cache(maxsize=2)
def _whisper(model): 
    from strata360.audio import speech
    return speech.load_models(model)


@stage('ingest', 1, keys=('camera_clock',), outputs=('clip.json',), note='clip facts and the definitive UTC time (README 5.1)')
def ingest(ctx):
    from strata360.pipeline.ingest import ingest_clip
    ctx.write('clip.json', ingest_clip(ctx.clip, ctx.cfg))


def audio_src(ctx):
    """The clip's sound as stored by the audio_extract stage (lossless, so the stages that read it need not open the big video file), else the video file itself: the same samples."""
    p = ctx.path('audio_original.flac')
    return p if os.path.exists(p) else ctx.clip.osv


@stage('audio_extract', 1, outputs=('audio_original.flac',), deps=('ingest',), note='the clip\'s sound saved on its own, lossless: the original audio every later step and the player use')
def audio_extract(ctx):
    import subprocess
    out = ctx.path('audio_original.flac')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', ctx.clip.osv, '-vn', '-map', '0:a:0', '-c:a', 'flac', '-compression_level', '5', out + '.part.flac'], check=True); os.replace(out + '.part.flac', out)


@stage('audio_clean', 1, outputs=('audio_clean.flac',), deps=('audio_extract',), note='the sound cleaned for listening and for the film (DeepFilterNet3, capped so the crowd and the place stay); the recogniser keeps using the original')
def audio_clean(ctx):
    from strata360.audio import dsp
    y = dsp.clean_for_playback(dsp.load_audio(ctx.path('audio_original.flac'), 1)[:, 0]); out = ctx.path('audio_clean.flac'); dsp.write_flac(out + '.part.flac', y); os.replace(out + '.part.flac', out)


@stage('audio_events', 1, outputs=('audio_events.json',), deps=('audio_extract',), note='what the sound is, second by second (sound-event classifier, 527 AudioSet classes grouped into speech, shouting, cheering, crowd, breathing, footsteps, wind, handling noise, nature, water, vehicles, music, bells, beeps) with a suggested role and level for the film')
def audio_events(ctx):
    from strata360.analysis import sound_events as SE
    ctx.write('audio_events.json', ctx.stamped(SE.classify(ctx.path('audio_original.flac'))))


@stage('audio', 1, outputs=('audio.json',), deps=('ingest',), soft_deps=('audio_extract',), note='levels, loudness, clipping, wind/speech/crowd/ambience labels (README 5.10)')
def audio(ctx):
    from strata360.audio import dsp
    an = dsp.analyse_array(dsp.load_audio(audio_src(ctx)))
    ctx.write('audio.json', ctx.stamped(dict(source=os.path.basename(ctx.clip.osv), **an)))


@stage('transcribe', 1, keys=('languages', 'whisper_model'), outputs=('transcript.json',), deps=('ingest',), soft_deps=('audio_extract',),
       note='multilingual transcript, per-segment language, English translation, hallucination flags (README 5.11)')
def transcribe(ctx):
    from strata360.audio import dsp, speech
    m, tm = _whisper(ctx.cfg['whisper_model'])
    x = dsp.load_audio(audio_src(ctx), 1)[:, 0]; x16 = dsp.ffmpeg_filter(x, dsp.SR, 'anull', out_sr=16000)[:, 0]     # raw audio: enhancement lowers word accuracy (progress.md)
    segs = speech.transcribe_multilingual(x16, m, tm, ctx.cfg['languages'])
    ctx.write('transcript.json', ctx.stamped(dict(source=os.path.basename(ctx.clip.osv), model=ctx.cfg['whisper_model'], translate_model='opus-mt',
                                                   denoise='none', languages=ctx.cfg['languages'], segments=segs)))


@stage('align', 1, keys=('align_languages',), outputs=('alignment.json',), deps=('transcribe',), soft_deps=('audio_extract',),
       note='accurate word start/end and safe cut points (README 5.11); whisper word times are not used for edits')
def align(ctx):
    from strata360.audio.align import align_transcript
    ctx.write('alignment.json', ctx.stamped(align_transcript(audio_src(ctx), ctx.read('transcript.json'), ctx.cfg['align_languages'])))


@stage('transcript_check', 1, keys=('transcript_check',), outputs=('transcript_check.json',), deps=('transcribe', 'audio_clean'), default=False, retries=100,
       note='checks the transcript against the cleaned audio with Gemini (speech-only excerpts of 30-60 s, several checks each, only fixes they agree on are kept) and stores them as corrections. Paid API calls: opt-in, every reply is cached on disk')
def transcript_check(ctx):
    from strata360.analysis import transcript_fix as TF
    c = ctx.cfg.get('transcript_check') or {}
    if c.get('mode') == 'transcribe':                                                                      # the transcription model alone
        from strata360.analysis import transcribe35 as T35
        ctx.write('transcript_check.json', ctx.stamped(T35.apply_clip(ctx.cfg['library'], ctx.clip.id, log=ctx.log))); return
    if c.get('pool'): kw = dict(pool=c['pool'], **{k: c[k] for k in ('min_calls', 'max_calls', 'accept', 'min_votes', 'patience', 'pair', 'transcriber') if k in c})       # the adaptive ensemble
    else: kw = dict(runs=int(c.get('runs', 3)), min_votes=int(c.get('min_votes', 2)), provider=c.get('provider'), model=c.get('model'))      # the fixed vote
    ctx.write('transcript_check.json', ctx.stamped(TF.check_clip(ctx.cfg['library'], ctx.clip.id, thinking=c.get('thinking', 'low'), log=ctx.log, **kw)))


@stage('exposure', 1, keys=('exposure_every_frames',), outputs=('exposure.json',), deps=('ingest',),
       note='brightness statistics every N frames for a later auto-gain (README 5.9)')
def exposure(ctx):
    from strata360.analysis.exposure import analyse
    ctx.write('exposure.json', ctx.stamped(analyse(ctx.clip.osv, ctx.cfg['exposure_every_frames'])))


@stage('motion', 2, outputs=('motion.json',), deps=('ingest',),
       note='heading, turn rate, shake (steadiness), stationary time, running cadence from telemetry alone (fast)')
def motion(ctx):
    from strata360.analysis.motion import analyse
    ctx.write('motion.json', ctx.stamped(analyse(ctx.clip.osv)))


@stage('proxy', 6, keys=('proxy',), outputs=('proxy.mp4', 'proxy.json'), deps=('ingest',),
       note='the clip rendered once as an upright, stabilised equirect (3840x1920, 25 fps, H.264 with audio, about 16 Mbps): the detectors, the scene model, thumbnails AND the browser player all use this one file instead of the lens files (slow: about 10x real time)')
def proxy(ctx):
    from strata360.render.proxy import make_proxy
    p = ctx.cfg['proxy']
    make_proxy(ctx.clip.osv, ctx.path('proxy.mp4'), p['size'], p['every_frames'], p['bitrate'], p.get('encoder', 'h264'))


@stage('thumb', 1, outputs=('thumb_quick.jpg',), deps=('motion',), soft_deps=('proxy',), note='a quick thumbnail (steadiest moment, looking ahead) so the clip list has pictures early')
def thumb(ctx):
    from strata360.analysis.thumbs import quick
    quick(ctx.clip.osv, str(ctx.dir))


@stage('places', 2, keys=('places',), outputs=('places.json',), deps=('ingest',), needs_track=True,
       note='where the clip was: address and named places near its start, middle and end (OpenStreetMap web services; needs the race track; cached; sends those coordinates online)')
def places(ctx):
    import os
    from strata360.analysis.places import analyse
    from strata360.gps import track
    root = os.path.abspath(os.path.join(str(ctx.dir), '..', '..')); tp = next((os.path.join(root, n) for n in ('track.fit', 'track.gpx') if os.path.exists(os.path.join(root, n))), None) or ctx.cfg.get('gps')
    if not tp or not os.path.exists(tp): raise RuntimeError('no race track (track.fit / track.gpx in the project folder): add it in the app, then redo this stage')
    ctx.write('places.json', ctx.stamped(analyse(ctx.read('clip.json'), track.load(tp), os.path.join(root, 'cache', 'places'), ctx.cfg)))
    from strata360.analysis.places import rebuild_locations
    rebuild_locations(root)                                                        # the race-wide locations.json in the project folder


@stage('people', 2, keys=('people_every_frames',), outputs=('people.json', 'faces.npy', 'faces_thumbs.npy'), deps=('ingest',), soft_deps=('proxy',), default=False,
       note='persons and faces on body-frame views (YOLO11 pose + InsightFace), deduplicated across views (slow: minutes per clip; needs .venv-vision and models/)')
def people(ctx):
    import numpy as np
    from strata360.analysis.people import analyse
    doc, emb, th = analyse(ctx.clip.osv, str(ctx.dir), ctx.cfg['people_every_frames'])
    ctx.write('people.json', ctx.stamped(doc)); np.save(ctx.path('faces.npy'), emb); np.save(ctx.path('faces_thumbs.npy'), th)


@stage('identity', 2, keys=('profile',), outputs=('identity.json',), deps=('people',),
       note='which detected person is the wearer (face profile from `who`), who else is in shot; needs profiles/<profile>.npz')
def identity(ctx):
    import numpy as np, os
    from strata360.analysis import identity as I
    path = os.path.join('profiles', ctx.cfg.get('profile', 'me') + '.npz')
    if not os.path.exists(path): raise RuntimeError(f'no wearer profile {path}: run ./strata360 who RACE --me N (or --auto) first')
    ctx.write('identity.json', ctx.stamped(I.analyse_clip(ctx.read('people.json'), np.load(ctx.path('faces.npy')), I.load_profile(path))))


@stage('scenes', 2, keys=('scenes_every_s',), outputs=('scenes.json',), deps=('ingest',), soft_deps=('proxy',), default=False,
       note='what is in shot (setting, people, light, weather, how scenic/lively, lens problems, tags) from a local VLM on front and rear views every few seconds (slow: minutes per clip)')
def scenes(ctx):
    from strata360.analysis.scenes import analyse
    ctx.write('scenes.json', ctx.stamped(analyse(ctx.clip.osv, str(ctx.dir), ctx.cfg['scenes_every_s'])))


@stage('speakers', 1, outputs=('speakers.json', 'speakers.npy'), deps=('transcribe',), soft_deps=('audio_extract',),
       note='speaker embedding and level of every speech segment; labelled wearer/other once the wearer voice is known (`strata360 voice`)')
def speakers(ctx):
    import numpy as np, os
    from strata360.analysis import voices
    doc, emb = voices.analyse(audio_src(ctx), ctx.read('transcript.json'), str(ctx.dir))
    prof = os.path.join('profiles', ctx.cfg.get('profile', 'me') + '_voice.npz')
    if os.path.exists(prof) and len(emb):
        lab, sim = voices.label(emb, prof)
        for s, l, m in zip(doc['segments'], lab, sim): s['label'] = l; s['sim'] = m
    ctx.write('speakers.json', ctx.stamped(doc)); np.save(ctx.path('speakers.npy'), emb)


@stage('candidates', 3, outputs=('candidates.json',), deps=('motion', 'exposure', 'audio', 'transcribe', 'align', 'speakers', 'identity', 'scenes'),
       note='the usable spans of the clip (only shake, a blocked lens or bad exposure make footage unusable) and overlapping candidates on them: different ways to see the same footage, in priority order (no video decoding)')
def candidates(ctx):
    from strata360.analysis.candidates import build
    ctx.write('candidates.json', ctx.stamped(build(str(ctx.dir))))


@stage('thumb_best', 1, outputs=('thumb.jpg',), deps=('candidates', 'identity', 'scenes'), soft_deps=('proxy',), note='the better thumbnail: best candidate, most attractive moment, the wearer when clearly in view')
def thumb_best(ctx):
    from strata360.analysis.thumbs import best
    best(ctx.clip.osv, str(ctx.dir))



