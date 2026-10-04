"""Run in .venv-vision: a local Qwen answering a list of text prompts (for analysis/vocab.py: matching scene labels to categories, reviewing suggested words, simplifying labels).

  python -m strata360.analysis.vocab_llm PROMPTS_JSON ANSWERS_JSON [--model PATH]

PROMPTS_JSON is a list of strings; ANSWERS_JSON a list of the model's answers in the same order. The default model is the one scenes_vlm uses (see its text: Qwen3.5-9B 4-bit MLX, Apache 2.0). Greedy decoding, short answers."""
import argparse, glob, json, os, time


def default_model():
    from strata360.analysis.scenes_vlm import default_model as shared
    return shared()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('prompts'); ap.add_argument('answers'); ap.add_argument('--model'); ap.add_argument('--max-tokens', type=int, default=200); a = ap.parse_args()
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    mp = os.path.abspath(a.model or default_model()); model, proc = load(mp); cfg = load_config(mp); out = []; t0 = time.time()
    for text in json.load(open(a.prompts)):
        try: p = apply_chat_template(proc, cfg, text, num_images=0, enable_thinking=False)
        except TypeError: p = apply_chat_template(proc, cfg, text, num_images=0)
        r = generate(model, proc, p, max_tokens=a.max_tokens, temperature=0.0, repetition_penalty=1.05, verbose=False); out.append((r.text if hasattr(r, 'text') else str(r)).strip())
    json.dump(out, open(a.answers, 'w')); print(f'{len(out)} answers in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
