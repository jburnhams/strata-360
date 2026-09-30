"""Scene description with a local vision-language model (Qwen2.5-VL 3B, 4-bit, mlx-vlm), run inside `.venv-vision`.

  python -m strata360.analysis.scenes_vlm IMAGES_DIR OUT_JSON [--model models/qwen25vl3b-4bit]

One JSON answer per image (files named s{frame}_v{view}.jpg). The model is loaded once per call (about 10 s); an image takes a few seconds."""
import argparse, glob, json, os, re, time

PROMPT = ("You are logging footage from a 360 camera worn by an ultramarathon runner, for a video editor. Look at the image and answer with ONE JSON object and nothing else, keys: "
          "\"setting\" (one of: forest, trail, road, town, field, mountain, river, building, indoor, aid_station, start_finish, night_scene, other), "
          "\"description\" (one short sentence), \"people\" (integer estimate of visible people), \"crowd\" (none|few|many), \"lighting\" (bright|overcast|dusk|dark|headlamp), "
          "\"weather\" (clear|cloud|rain|fog|snow|unknown), \"activity\" (short), \"mood\" (short), \"scenic\" (number 0 to 1: how visually attractive as a shot), "
          "\"energy\" (number 0 to 1: how lively), \"lens_problems\" (none|droplets|fog|blocked|glare), \"tags\" (list of up to 5 short lowercase nouns).")


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except ValueError:
        try: return json.loads(re.sub(r',\s*}', '}', m.group(0)))
        except ValueError: return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('images'); ap.add_argument('out'); ap.add_argument('--model', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models', 'qwen25vl3b-4bit'))
    ap.add_argument('--max-tokens', type=int, default=260); a = ap.parse_args()
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    model_path = os.path.abspath(a.model); model, proc = load(model_path); cfg = load_config(model_path); t0 = time.time(); out = []
    prompt = apply_chat_template(proc, cfg, PROMPT, num_images=1)
    for fn in sorted(glob.glob(os.path.join(a.images, 's*_v*.jpg'))):
        m = re.search(r's(\d+)_v(\d+)\.jpg', fn); k, v = int(m.group(1)), int(m.group(2))
        r = generate(model, proc, prompt, image=[fn], max_tokens=a.max_tokens, temperature=0.0, verbose=False)
        txt = r.text if hasattr(r, 'text') else str(r); out.append(dict(frame=k, view=v, answer=parse(txt), raw=None if parse(txt) else txt[:300]))
    json.dump(dict(schema=1, model=os.path.basename(model_path), seconds=round(time.time() - t0, 1), items=out), open(a.out, 'w'))
    print(f'{len(out)} images in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
