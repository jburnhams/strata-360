"""Generated sections of the built music (Milestone G3, docs/ai-music.md 4.6): new bars in the uploaded track's style where the score asks for them, made locally with ACE-Step 1.5 in its own environment, each take kept under <race dir>/music_gen/<key>/ so nothing is made twice.

How a section is made follows the fidelity (score.plan): at 0.75 and above it is a **repaint in context**, the recipe judged best by ear on Legends (progress.md, 6 and 7 Oct): the built track's own bars around the section (CONTEXT_BARS each side) go in as the source, only the section's bars are repainted, with the genre caption and the original as reference audio. Below that it is a **cover** of the section's own bars at the reference strength, and at 0 text alone. The caption always names the genre: one that only said "the same band" gave jazz.

  caption(style, level) -> the text for a section
  spec(section, ...) -> what one take depends on, with its key
  params(spec, src, ref) -> ACE-Step GenerationParams fields
  Generator(rd, backend, sr)(specs, seeds) -> [samples of each section at sr, or None]   the takes, cached
  available() -> ACE-Step is installed
  acestep(jobs, log) -> runs acestep_runner.py with ACE-Step's interpreter (STRATA_ACESTEP_ROOT, default ~/Code/ace-step-1.5; STRATA_ACESTEP_PYTHON; STRATA_ACESTEP_MODEL)
A backend is any callable(jobs, log) -> {jobs: [{out, ok, error, seconds, peak_gb}]} that writes each job's `out`; the unit tests pass a fake."""
import hashlib, json, os, subprocess, tempfile
import numpy as np
from strata360 import oslib
from strata360.edit import stems as ST

CONTEXT_BARS = 8                       # the built track's own bars each side of a repainted section
REF_S = 30.0                           # seconds of the original's instrumental given as reference audio
MODEL = 'acestep-v15-turbo'; STEPS = 8; BACKEND = 'acestep-1.5'
LEVEL_WORDS = ((0.3, 'sparse, stripped back, quiet'), (0.55, 'steady groove, medium energy'), (0.8, 'driving, building energy'), (9.0, 'full band, peak energy'))


def caption(style, level):
    words = next(w for top, w in LEVEL_WORDS if level < top); return f'{style.strip().rstrip(",")}, {words}, instrumental, no vocals'


def mode(section):
    s = section.get('strength') or 0.0; return 'repaint' if section.get('repaint') else 'cover' if s > 0 else 'text'


def spec(section, bar_s, bpm, key_name, style, context_bars, beats_per_bar=4):
    """What one take of a score section depends on: the section (its key covers bars, level, source and strength), how it is made, the caption and, for a repaint, which of the track's bars surround it (context_bars: the source bar of every film bar in the context). The key names its folder of takes."""
    d = dict(first=section['first'], end=section['end'], level=section['level'], strength=section.get('strength') or 0.0, mode=mode(section), bar_s=round(bar_s, 4), bpm=bpm, beats_per_bar=beats_per_bar, keyscale=key_name, caption=caption(style, section['level']), section_key=section.get('key'))
    body = dict(d, context=list(context_bars), backend=BACKEND, model=os.environ.get('STRATA_ACESTEP_MODEL', MODEL), steps=STEPS); d['key'] = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]; return d


def params(s, src, ref, src_len_s, r0=None, r1=None):
    """ACE-Step GenerationParams for a spec. src: the audio to repaint or cover (a file), ref: the original's instrumental as reference (a file, or None), r0..r1 the repainted seconds inside src."""
    p = dict(caption=s['caption'], bpm=int(round(s['bpm'])), keyscale=s['keyscale'], timesignature=str(s['beats_per_bar']), duration=round(src_len_s, 3))
    if s['mode'] == 'repaint':
        p.update(task_type='repaint', src_audio=src, repainting_start=round(r0, 3), repainting_end=round(r1, 3), chunk_mask_mode='explicit', repaint_wav_crossfade_sec=0.5, repaint_latent_crossfade_frames=20, repaint_mode='conservative' if s['strength'] >= 0.6 else 'balanced', repaint_strength=s['strength'])
    elif s['mode'] == 'cover': p.update(task_type='cover', src_audio=src, chunk_mask_mode='auto', audio_cover_strength=s['strength'], cover_noise_strength=round(max(0.0, s['strength'] - 0.2), 2))
    else: p.update(task_type='text2music')
    if ref and s['strength'] > 0: p['reference_audio'] = ref
    return p


def where():
    """(ACE-Step's folder, its interpreter)."""
    root = os.path.expanduser(os.environ.get('STRATA_ACESTEP_ROOT') or '~/Code/ace-step-1.5'); return root, os.environ.get('STRATA_ACESTEP_PYTHON') or oslib.venv_python(os.path.join(root, '.venv'))


def available():
    """Whether ACE-Step is installed where acestep() looks for it."""
    return os.path.exists(where()[1])


def acestep(jobs, log=print):
    root, py = where()
    if not os.path.exists(py): raise RuntimeError(f'ACE-Step is not installed: no {py} (install ACE-Step 1.5 in {root} with `uv sync`, or set STRATA_ACESTEP_ROOT / STRATA_ACESTEP_PYTHON)')
    d = tempfile.mkdtemp(prefix='s360gen_'); jp, rp = os.path.join(d, 'jobs.json'), os.path.join(d, 'result.json')
    json.dump(dict(root=root, model=os.environ.get('STRATA_ACESTEP_MODEL', MODEL), steps=STEPS, jobs=jobs), open(jp, 'w'))
    runner = os.path.join(os.path.dirname(__file__), 'acestep_runner.py'); p = subprocess.Popen([py, runner, jp, rp], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    tail = []
    for line in p.stdout:
        line = line.rstrip(); tail = (tail + [line])[-20:]
        if line.startswith(('model loaded', 'take ')): log('ACE-Step: ' + line)
    if p.wait() or not os.path.exists(rp): raise RuntimeError('ACE-Step failed: ' + ' | '.join(l for l in tail if l)[-600:])
    return json.load(open(rp))


class Generator:
    """Makes the takes of generated sections, in batches (the model loads once per batch). Called as gen(items, seeds) with items [(spec, inputs)], inputs = dict(src (samples at sr), r0, r1 seconds inside src for a repaint, ref (samples at sr) or None); returns, per item, the take's samples at sr (for a repaint the whole context, on the same timeline as `src`, which music_fit judges and cuts) or None when the take failed. Each take is FLAC at <rd>/music_gen/<key>/take<seed>.flac with take<seed>.json beside it."""

    def __init__(self, rd, sr, backend=None, log=print, write=None, read=None):
        self.rd, self.sr, self.backend, self.log = rd, sr, backend or acestep, log; self.write = write or ST.ffmpeg_write; self.read = read or (lambda p: ST.ffmpeg_read(p, sr)); self.runs = []

    def dir(self, key): return os.path.join(self.rd, 'music_gen', key)
    def path(self, key, seed): return os.path.join(self.dir(key), f'take{int(seed)}.flac')

    def takes(self, key):
        """The takes kept for a key: [{seed, ...the fit report}] by seed."""
        d = self.dir(key); out = []
        if not os.path.isdir(d): return out
        for f in sorted(os.listdir(d)):
            if f.startswith('take') and f.endswith('.json'):
                try: out.append(json.load(open(os.path.join(d, f))))
                except (OSError, ValueError): pass
        return sorted(out, key=lambda t: t.get('seed', 0))

    def note(self, spec, seed, report):
        """Keep a take's fit verdict beside it (music_fit.repair calls this for every take)."""
        d = self.dir(spec['key']); os.makedirs(d, exist_ok=True); json.dump(dict(report, seed=int(seed)), open(os.path.join(d, f'take{int(seed)}.json'), 'w'))

    def __call__(self, items, seeds):
        jobs = []; todo = []
        for (s, inp), seed in zip(items, seeds):
            if os.path.exists(self.path(s['key'], seed)): continue
            d = self.dir(s['key']); os.makedirs(d, exist_ok=True); src = os.path.join(d, 'src.wav'); ref = os.path.join(d, 'ref.wav') if inp.get('ref') is not None else None
            self.write(src, inp['src'], self.sr)
            if ref: self.write(ref, inp['ref'], self.sr)
            json.dump({k: v for k, v in s.items()}, open(os.path.join(d, 'spec.json'), 'w'), indent=1)
            jobs.append(dict(out=self.path(s['key'], seed), seed=int(seed), params=params(s, src, ref, len(inp['src']) / self.sr, inp.get('r0'), inp.get('r1')))); todo.append(s['key'])
        if jobs:
            self.log(f'generating {len(jobs)} take{"s" if len(jobs) > 1 else ""} with {BACKEND}'); r = self.backend(jobs, self.log); self.runs.append(dict(load_s=r.get('load_s'), device=r.get('device'), jobs=r.get('jobs')))
            for j in r.get('jobs') or []:
                if not j.get('ok'): self.log(f"a take failed: {j.get('error')}")
        out = []
        for (s, inp), seed in zip(items, seeds):
            p = self.path(s['key'], seed)
            if not os.path.exists(p): out.append(None); continue
            x, _ = self.read(p); out.append(np.asarray(x, np.float32))
        return out
