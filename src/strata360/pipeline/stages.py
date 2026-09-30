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
    needs_track: bool = False  # uses the race GPS track: waits until one is set, and is redone when the track or the clip-to-track time alignment changes


def stage(name, version, keys=(), deps=(), outputs=(), default=True, note='', needs_track=False):
    def deco(fn):
        STAGES[name] = Stage(name, version, fn, tuple(keys), tuple(deps), tuple(outputs), default, note, needs_track); ORDER.append(name); return fn
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


@stage('audio', 1, outputs=('audio.json',), deps=('ingest',), note='levels, loudness, clipping, wind/speech/crowd/ambience labels (README 5.10)')
def audio(ctx):
    from strata360.audio import dsp
    an = dsp.analyse_array(dsp.load_audio(ctx.clip.osv))
    ctx.write('audio.json', ctx.stamped(dict(source=os.path.basename(ctx.clip.osv), **an)))


@stage('transcribe', 1, keys=('languages', 'whisper_model'), outputs=('transcript.json',), deps=('ingest',),
       note='multilingual transcript, per-segment language, English translation, hallucination flags (README 5.11)')
def transcribe(ctx):
    from strata360.audio import dsp, speech
    m, tm = _whisper(ctx.cfg['whisper_model'])
    x = dsp.load_audio(ctx.clip.osv, 1)[:, 0]; x16 = dsp.ffmpeg_filter(x, dsp.SR, 'anull', out_sr=16000)[:, 0]     # raw audio: enhancement lowers word accuracy (progress.md)
    segs = speech.transcribe_multilingual(x16, m, tm, ctx.cfg['languages'])
    ctx.write('transcript.json', ctx.stamped(dict(source=os.path.basename(ctx.clip.osv), model=ctx.cfg['whisper_model'], translate_model='opus-mt',
                                                   denoise='none', languages=ctx.cfg['languages'], segments=segs)))


@stage('align', 1, keys=('align_languages',), outputs=('alignment.json',), deps=('transcribe',),
       note='accurate word start/end and safe cut points (README 5.11); whisper word times are not used for edits')
def align(ctx):
    from strata360.audio.align import align_transcript
    ctx.write('alignment.json', ctx.stamped(align_transcript(ctx.clip.osv, ctx.read('transcript.json'), ctx.cfg['align_languages'])))


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


@stage('thumb', 1, outputs=('thumb_quick.jpg',), deps=('motion',), note='a quick thumbnail (steadiest moment, looking ahead) so the clip list has pictures early')
def thumb(ctx):
    from strata360.analysis.thumbs import quick
    quick(ctx.clip.osv, str(ctx.dir))


@stage('preview', 1, outputs=('preview.mp4', 'preview.json'), deps=('ingest',),
       note='browser preview for the player: upright equirect 2048x1024, 25 fps, H.264 with audio (slow: several times real time)')
def preview(ctx):
    from strata360.render.proxy import make_preview
    make_preview(ctx.clip.osv, ctx.path('preview.mp4'))


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


@stage('people', 2, keys=('people_every_frames',), outputs=('people.json', 'faces.npy', 'faces_thumbs.npy'), deps=('ingest',), default=False,
       note='persons and faces on body-frame views (YOLO11 pose + InsightFace), deduplicated across views (slow: minutes per clip; needs .venv-vision and models/)')
def people(ctx):
    import numpy as np
    from strata360.analysis.people import analyse
    doc, emb, th = analyse(ctx.clip.osv, str(ctx.dir), ctx.cfg['people_every_frames'])
    ctx.write('people.json', ctx.stamped(doc)); np.save(ctx.path('faces.npy'), emb); np.save(ctx.path('faces_thumbs.npy'), th)


@stage('identity', 1, keys=('profile',), outputs=('identity.json',), deps=('people',),
       note='which detected person is the wearer (face profile from `who`), who else is in shot; needs profiles/<profile>.npz')
def identity(ctx):
    import numpy as np, os
    from strata360.analysis import identity as I
    path = os.path.join('profiles', ctx.cfg.get('profile', 'me') + '.npz')
    if not os.path.exists(path): raise RuntimeError(f'no wearer profile {path}: run ./strata360 who RACE --me N (or --auto) first')
    ctx.write('identity.json', ctx.stamped(I.analyse_clip(ctx.read('people.json'), np.load(ctx.path('faces.npy')), I.load_profile(path))))


@stage('scenes', 2, keys=('scenes_every_s',), outputs=('scenes.json',), deps=('ingest',), default=False,
       note='what is in shot (setting, people, light, weather, how scenic/lively, lens problems, tags) from a local VLM on front and rear views every few seconds (slow: minutes per clip)')
def scenes(ctx):
    from strata360.analysis.scenes import analyse
    ctx.write('scenes.json', ctx.stamped(analyse(ctx.clip.osv, str(ctx.dir), ctx.cfg['scenes_every_s'])))


@stage('speakers', 1, outputs=('speakers.json', 'speakers.npy'), deps=('transcribe',),
       note='speaker embedding and level of every speech segment; labelled wearer/other once the wearer voice is known (`strata360 voice`)')
def speakers(ctx):
    import numpy as np, os
    from strata360.analysis import voices
    doc, emb = voices.analyse(ctx.clip.osv, ctx.read('transcript.json'), str(ctx.dir))
    prof = os.path.join('profiles', ctx.cfg.get('profile', 'me') + '_voice.npz')
    if os.path.exists(prof) and len(emb):
        lab, sim = voices.label(emb, prof)
        for s, l, m in zip(doc['segments'], lab, sim): s['label'] = l; s['sim'] = m
    ctx.write('speakers.json', ctx.stamped(doc)); np.save(ctx.path('speakers.npy'), emb)


@stage('candidates', 2, outputs=('candidates.json',), deps=('motion', 'exposure', 'audio', 'transcribe', 'align', 'speakers', 'identity', 'scenes'),
       note='the usable moments of the clip with features, quality, energy and speech cut points: what the optimiser and the GUI choose from (no video decoding)')
def candidates(ctx):
    from strata360.analysis.candidates import build
    ctx.write('candidates.json', ctx.stamped(build(str(ctx.dir))))


@stage('thumb_best', 1, outputs=('thumb.jpg',), deps=('candidates', 'identity', 'scenes'), note='the better thumbnail: best candidate, most attractive moment, the wearer when clearly in view')
def thumb_best(ctx):
    from strata360.analysis.thumbs import best
    best(ctx.clip.osv, str(ctx.dir))


@stage('proxy', 1, keys=('proxy',), outputs=('proxy.mp4', 'proxy.json'), deps=('ingest',), default=False,
       note='the canonical upright equirect analysis proxy (slow: about 3.5x real time; large): opt-in')
def proxy(ctx):
    from strata360.render.proxy import make_proxy
    p = ctx.cfg['proxy']
    make_proxy(ctx.clip.osv, ctx.path('proxy.mp4'), p['size'], p['every_frames'], p['bitrate'])
