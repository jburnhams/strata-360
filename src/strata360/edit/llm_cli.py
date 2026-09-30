"""Run a local instruction-tuned LLM (mlx-lm, `.venv-vision`) on a chat prompt.

  python -m strata360.edit.llm_cli REQUEST_JSON OUT_JSON [--model models/qwen25-7b-instruct-4bit]

REQUEST_JSON: {"messages": [{"role": "system"|"user"|"assistant", "content": "..."}], "max_tokens": 1500, "temperature": 0.7, "json": true}
OUT_JSON: {"text": "...", "seconds": s, "tokens": n}. With "json": true the first {...} in the answer is also parsed into "parsed" (null when it does not parse)."""
import argparse, json, os, re, time


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('request'); ap.add_argument('out')
    ap.add_argument('--model', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models', 'qwen25-7b-instruct-4bit')); a = ap.parse_args()
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    req = json.load(open(a.request)); model, tok = load(os.path.abspath(a.model)); t0 = time.time()
    prompt = tok.apply_chat_template(req['messages'], add_generation_prompt=True, tokenize=False)
    text = generate(model, tok, prompt=prompt, max_tokens=int(req.get('max_tokens', 1500)), sampler=make_sampler(temp=float(req.get('temperature', 0.7)), top_p=0.95), verbose=False)
    out = dict(text=text, seconds=round(time.time() - t0, 1), tokens=len(tok.encode(text)))
    if req.get('json'):
        m = re.search(r'\{.*\}', text, re.S); out['parsed'] = None
        if m:
            try: out['parsed'] = json.loads(m.group(0))
            except ValueError:
                try: out['parsed'] = json.loads(re.sub(r',\s*([}\]])', r'\1', m.group(0)))
                except ValueError: pass
    json.dump(out, open(a.out, 'w'), indent=1); print(f"{out['tokens']} tokens in {out['seconds']} s")


if __name__ == '__main__':
    main()
