"""Name the thing in each crop with the local vision model (the same Qwen3.5 as the scenes stage), run inside `.venv-vision`.

  python -m strata360.analysis.objects_vlm CROPS_DIR OUT_JSON [--model PATH]

Output {"model": ..., "seconds": s, "labels": {file: "short noun phrase" or "unclear"}} for every *.jpg of CROPS_DIR. A crop takes a few seconds."""
import argparse, glob, json, os, re, time

from strata360.analysis.scenes_vlm import default_model, model_label, reencoded, RETRIES

PROMPT = ('This is a close-up crop of something seen while running outdoors. What is the main object or thing in the centre of the image? '
          'Answer with a specific noun phrase of 1 to 4 words (for example "wooden platform", "chicken", "stone bridge", "hedge", "street light"). If you cannot tell, answer "unclear".')


def clean(text):
    return re.sub(r'\s+', ' ', re.sub(r'[`"\n]', ' ', str(text))).strip().rstrip('.')[:80]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('images'); ap.add_argument('out'); ap.add_argument('--model'); a = ap.parse_args()
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    path = os.path.abspath(a.model or default_model()); model, proc = load(path); cfg = load_config(path); t0 = time.time()
    try: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1, enable_thinking=False)
    except TypeError: prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1)
    extra = dict(repetition_penalty=1.05) if 'qwen3' in path.lower() else {}
    ask = lambda p: clean((lambda r: r.text if hasattr(r, 'text') else str(r))(generate(model, proc, prompt, image=[p], max_tokens=24, temperature=0.0, verbose=False, **extra)))
    out = {}
    for fn in sorted(glob.glob(os.path.join(a.images, '*.jpg'))):
        txt = ask(fn)
        for q, s in RETRIES:                                                                  # a row of "!" for one exact picture: ask again re-encoded
            if txt and not set(txt) <= {'!', ' '}: break
            tmp = reencoded(fn, q, s); txt = ask(tmp); os.remove(tmp)
        out[os.path.basename(fn)] = txt or 'unclear'
    json.dump(dict(schema=1, model=model_label(path), seconds=round(time.time() - t0, 1), labels=out), open(a.out, 'w')); print(f'{len(out)} crops in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
