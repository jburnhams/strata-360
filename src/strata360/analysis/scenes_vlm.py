"""Scene description with a local vision-language model (Qwen3.5-9B, 4-bit, mlx-vlm; the older Qwen2.5-VL 3B when that is all there is), run inside `.venv-vision`.

  python -m strata360.analysis.scenes_vlm IMAGES_DIR OUT_JSON [--model PATH] [--prompt log|scenery]

The model is, in order: --model, $STRATA_VLM_MODEL, models/qwen35-9b-4bit, the mlx-community/Qwen3.5-9B-4bit build in the Hugging Face cache (Apache 2.0), models/qwen25vl3b-4bit.

Two prompts: `log` (the general description: setting, light, weather, lens problems, tags ...) and `scenery` (the landscape only, people ignored: a 1 to 10 score and a 1 to 5 clarity).

One JSON answer per image (files named s{frame}_v{view}.jpg). The model is loaded once per call (about 10 s); an image takes a few seconds."""
import argparse, glob, json, os, re, time

def model_label(path):
    """A name for the model that stays the same when the cache folder is rebuilt: "mlx-community/Qwen3.5-9B-4bit" for a Hugging Face snapshot, else the folder's name."""
    p = os.path.abspath(path).replace(os.sep, '/')
    if '/models--' in p: return p.split('/models--', 1)[1].split('/', 1)[0].replace('--', '/')
    return os.path.basename(p)


def default_model():
    here = os.path.dirname(os.path.abspath(__file__)); root = os.path.abspath(os.path.join(here, '..', '..', '..')); env = os.environ.get('STRATA_VLM_MODEL')
    if env and os.path.isdir(env): return env
    for p in (os.path.join(root, 'models', 'qwen35-9b-4bit'), *sorted(glob.glob(os.path.expanduser('~/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/*'))), os.path.join(root, 'models', 'qwen25vl3b-4bit')):
        if os.path.isdir(p): return p
    raise SystemExit('no vision model: put Qwen3.5-9B in models/qwen35-9b-4bit (mlx-community/Qwen3.5-9B-4bit) or Qwen2.5-VL 3B in models/qwen25vl3b-4bit')


PROMPT = ("You are logging footage from a 360 camera worn by an ultramarathon runner, for a video editor. Look at the image and answer with ONE JSON object and nothing else, keys: "
          "\"setting\" (one of: forest, trail, road, town, field, mountain, river, building, indoor, aid_station, start_finish, night_scene, other), "
          "\"description\" (one short sentence), \"people\" (integer estimate of visible people), \"crowd\" (none|few|many), \"lighting\" (bright|overcast|dusk|dark|headlamp), "
          "\"weather\" (clear|cloud|rain|fog|snow|unknown), \"water\" (a river, stream, lake, sea or waterfall clearly in view: none|river|stream|lake|sea|waterfall|puddle), \"ground_snow\" (true if snow lies on the ground, else false), \"scenic\" (number 0 to 1: how visually attractive as a shot), "
          "\"energy\" (number 0 to 1: how lively), \"lens_problems\" (about the camera lens itself, not the weather: none|droplets (water or smears on the lens)|blocked (a finger or object covers it)|glare (flare or a bright reflection on the lens); fog, mist, rain and cloud in the scenery are NOT lens problems, answer none for them), \"tags\" (list of up to 5 short lowercase nouns).")

SCENERY = ("You are choosing scenery shots for a film of an ultramarathon, from a 360 camera worn by the runner. Rate the SCENERY in this view, 1 to 10, as a shot for the film. "
           "IGNORE any people, including the runner who wears the camera and their pole: people neither add to nor take away from the score; judge only the landscape, light, depth, composition and how clear the picture is. "
           "1-2: nothing worth showing (black, blocked, lens glare, blank wall, thick featureless fog). 3-4: dull or ugly (car park, bland road, cluttered, hazy). "
           "5-6: ordinary but fine (plain trail or forest). 7-8: attractive (good light, depth, an interesting composition). 9-10: stunning (dramatic landscape, golden light). "
           "Use the whole scale; most views are 3 to 7. Answer with ONE JSON object and nothing else: {\"score\": number, \"clarity\": number 1 to 5 (5 = sharp and clear, 1 = foggy, wet lens or blurred), \"reason\": \"short\"}.")
PROMPTS = dict(log=PROMPT, scenery=SCENERY)


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except ValueError:
        try: return json.loads(re.sub(r',\s*}', '}', m.group(0)))
        except ValueError: return None


RETRIES = ((85, 1.0), (90, 0.94))     # JPEG quality and scale of the second and third try at a picture that got no answer


def reencoded(path, quality, scale):
    import cv2
    im = cv2.imread(path)
    if scale != 1.0: im = cv2.resize(im, (int(im.shape[1] * scale), int(im.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    tmp = path + '.retry.jpg'; cv2.imwrite(tmp, im, [cv2.IMWRITE_JPEG_QUALITY, quality]); return tmp


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('images'); ap.add_argument('out'); ap.add_argument('--model')
    ap.add_argument('--max-tokens', type=int); ap.add_argument('--prompt', choices=sorted(PROMPTS), default='log'); a = ap.parse_args(); max_tokens = a.max_tokens or (140 if a.prompt == 'scenery' else 260)
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    model_path = os.path.abspath(a.model or default_model()); model, proc = load(model_path); cfg = load_config(model_path); t0 = time.time(); out = []
    try: prompt = apply_chat_template(proc, cfg, PROMPTS[a.prompt], num_images=1, enable_thinking=False)               # Qwen3.5 thinks first unless told not to
    except TypeError: prompt = apply_chat_template(proc, cfg, PROMPTS[a.prompt], num_images=1)
    extra = dict(repetition_penalty=1.05) if 'qwen3' in os.path.basename(model_path).lower() or 'qwen3.5' in model_path.lower() else {}
    ask = lambda path: (lambda r: r.text if hasattr(r, 'text') else str(r))(generate(model, proc, prompt, image=[path], max_tokens=max_tokens, temperature=0.0, verbose=False, **extra))
    for fn in sorted(glob.glob(os.path.join(a.images, 's*_v*.jpg'))):
        m = re.search(r's(\d+)_v(\d+)\.jpg', fn); k, v = int(m.group(1)), int(m.group(2))
        txt = ask(fn); ans = parse(txt)
        for quality, scale in RETRIES:                                                         # the model sometimes answers one exact picture with a row of "!" (every time the same); the same picture re-encoded or a little smaller does not
            if ans: break
            tmp = reencoded(fn, quality, scale); txt = ask(tmp); ans = parse(txt); os.remove(tmp)
        out.append(dict(frame=k, view=v, answer=ans, raw=None if ans else txt[:300]))
    json.dump(dict(schema=1, model=model_label(model_path), seconds=round(time.time() - t0, 1), items=out), open(a.out, 'w'))
    print(f'{len(out)} images in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
