"""Boxes for snow and water on wide views with the local vision model (Qwen3.5), run inside `.venv-vision`.

  python -m strata360.analysis.regions_vlm VIEWS_DIR OUT_JSON [--model PATH]

VIEWS_DIR holds the pictures and `jobs.json`, {file: [kinds asked about]}. Output {"model", "seconds", "answers": {file: raw text}}; the text is read by regions.parse."""
import argparse, json, os, time

from strata360.analysis.scenes_vlm import default_model, model_label
from strata360.analysis.regions import question


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('images'); ap.add_argument('out'); ap.add_argument('--model'); a = ap.parse_args()
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    path = os.path.abspath(a.model or default_model()); model, proc = load(path); cfg = load_config(path); t0 = time.time(); jobs = json.load(open(os.path.join(a.images, 'jobs.json'))); out = {}
    extra = dict(repetition_penalty=1.05) if 'qwen3' in path.lower() else {}
    for fn, kinds in sorted(jobs.items()):
        q = question(kinds)
        try: prompt = apply_chat_template(proc, cfg, q, num_images=1, enable_thinking=False)
        except TypeError: prompt = apply_chat_template(proc, cfg, q, num_images=1)
        r = generate(model, proc, prompt, image=[os.path.join(a.images, fn)], max_tokens=400, temperature=0.0, verbose=False, **extra); out[fn] = (r.text if hasattr(r, 'text') else str(r)).strip()
    json.dump(dict(schema=1, model=model_label(path), seconds=round(time.time() - t0, 1), answers=out), open(a.out, 'w')); print(f'{len(out)} views in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
