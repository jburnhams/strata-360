"""Experiment: the local text models on the project's own text prompts (vocabulary category matching and word review, analysis/vocab.py).

  python scripts/win_exp/text_models.py PROMPTS.json OUT.json

PROMPTS.json: a list of prompt strings (captured by running vocab.categorise / vocab.review with a recording `ask`). Each model answers all of them (greedy, no thinking); reports seconds a prompt, answers that parse as the
requested JSON or list, and how often the models give the same answer."""
import json, os, re, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360.analysis import vlm

MODELS = {'qwen3.5-9b': 'models/qwen35-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf', 'qwen3.6-35b-a3b': 'models/qwen36-35b-a3b/Qwen3.6-35B-A3B-Q4_K_M.gguf'}


def parsed(t):
    m = re.search(r'\{.*\}', t, re.S)
    if m:
        try: return json.loads(m.group(0))
        except ValueError: return None
    m = re.search(r'\[.*\]', t, re.S)
    try: return json.loads(m.group(0)) if m else None
    except ValueError: return None


def main():
    prompts = json.load(open(sys.argv[1])); res = {}
    for name, path in MODELS.items():
        t0 = time.time()
        with vlm.Server(os.path.abspath(path), text=True) as s:
            load_s = time.time() - t0; t1 = time.time(); ans = [s.chat([dict(role='user', content=p)], 200).strip() for p in prompts]; sec = time.time() - t1
        res[name] = dict(load_s=round(load_s, 1), seconds_per_prompt=round(sec / len(prompts), 2), parsed=sum(parsed(a) is not None for a in ans), answers=ans); print(name, res[name]['seconds_per_prompt'], 's/prompt', res[name]['parsed'], 'of', len(prompts), 'parse', flush=True)
    a, b = (res[k]['answers'] for k in MODELS)
    def key(t):
        p = parsed(t)
        if isinstance(p, dict): return json.dumps({k: (sorted(v) if isinstance(v, list) else v) for k, v in p.items() if k in ('add', 'word', 'categories', 'pick', 'categories_picked')}, sort_keys=True)
        return json.dumps(sorted(p) if isinstance(p, list) else t.strip().lower())
    res['same_answer'] = sum(key(x) == key(y) for x, y in zip(a, b)); res['of'] = len(prompts); json.dump(res, open(sys.argv[2], 'w'), indent=1, ensure_ascii=False); print('same', res['same_answer'], 'of', len(prompts))


if __name__ == '__main__': main()
