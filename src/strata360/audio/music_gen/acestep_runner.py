"""Run inside ACE-Step 1.5's own environment (docs/ai-music.md 4.6, G3): every job of a batch with the model loaded once (loading takes about two minutes).

  python acestep_runner.py JOBS.json RESULT.json
JOBS.json: {root, model, steps, jobs: [{out, seed, params: GenerationParams fields}]}. Each take is written to its `out` (FLAC, the model's own rate). RESULT.json: {device, load_s, jobs: [{out, ok, error, seconds, peak_gb}]}.
Imports nothing from strata360: it runs with ACE-Step's interpreter and dependencies."""
import json, os, shutil, sys, tempfile, time


def device():
    import torch
    if os.environ.get('STRATA_GPU') == '0': return 'cpu'
    if torch.cuda.is_available(): return 'cuda'
    return 'mps' if torch.backends.mps.is_available() else 'cpu'


def peak_gb(dev):
    import torch
    if dev == 'cuda': return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
    if dev == 'mps' and hasattr(torch.mps, 'driver_allocated_memory'): return round(torch.mps.driver_allocated_memory() / 2 ** 30, 2)
    return None


def main(jobs_path, result_path):
    spec = json.load(open(jobs_path)); sys.path.insert(0, spec['root'])
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music
    dev = device(); t0 = time.time(); h = AceStepHandler(); h.initialize_service(project_root=spec['root'], config_path=spec['model'], device=dev); load_s = round(time.time() - t0, 1); print(f'model loaded on {dev} in {load_s} s', flush=True)
    out = []; tmp = tempfile.mkdtemp(prefix='s360ace_')
    for k, j in enumerate(spec['jobs']):
        p = dict(lyrics='[Instrumental]', instrumental=True, inference_steps=spec.get('steps', 8), thinking=False, use_cot_metas=False, use_cot_caption=False, use_cot_language=False); p.update(j['params'])
        t = time.time(); r = generate_music(h, None, GenerationParams(**p), GenerationConfig(batch_size=1, audio_format='flac', use_random_seed=False, seeds=[int(j['seed'])]), save_dir=tmp); dt = round(time.time() - t, 1)
        ok = bool(r.success and r.audios)
        if ok: os.makedirs(os.path.dirname(j['out']), exist_ok=True); shutil.move(r.audios[0]['path'], j['out'])
        out.append(dict(out=j['out'], ok=ok, error=None if ok else str(r.error)[:500], seconds=dt, peak_gb=peak_gb(dev))); print(f"take {k + 1} of {len(spec['jobs'])}: {'ok' if ok else 'failed'} in {dt} s", flush=True)
        json.dump(dict(device=dev, load_s=load_s, jobs=out), open(result_path, 'w'))
    json.dump(dict(device=dev, load_s=load_s, jobs=out), open(result_path, 'w'))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
