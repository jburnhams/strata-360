import sys, os, json, glob, subprocess, collections
from strata360.analysis import vocab as V
S = os.path.dirname(os.path.abspath(__file__)); D = "/Volumes/Expansion/2026-02-19 - Legends/strata360/clips"; v = V.load()
ask = V.ask_with_runner
# 2. simplify the odd labels of the three clips scanned today
objs = json.load(open(S + '/adapt/objects.json')); labels = [it['label'] for c in objs.values() for it in c]
can = V.canonicalise(labels, ask, v); json.dump(can, open(S + '/vocab_demo_canon2.json', 'w'), indent=1)
reg = {l: (None if V.kind_of_label(l, v) == 'stop' else V.normalise_label(l, v)) for l in set(labels)}
print('\nlabels', len(set(labels)), '| distinct simple words by the plain rules', len({w for w in reg.values() if w}), '| by the model', len({w for w in can.values() if w}), '| skipped by the model', sum(1 for w in can.values() if w is None))
for l in list(dict.fromkeys(labels))[:40]: print(f'  {l!r:34} rules: {reg[l]!r:16} model: {can[l]!r}')
# 3. the book the scan would have made, with the model's simple words, and a review of the suggestions
book = V.StatsBook()
for clip, items in objs.items():
    for it in items:
        if it['kind'] == 'animal': book.record_named(it['yoloe'], it['label'], v)
        else:
            book.record_leftover(it['label'], clip, v, word=can.get(it['label']))
sug = book.suggestions(v); print('\nsuggestions after simplifying:', [(w, book.suggest[w]['count'], len(book.suggest[w]['clips'])) for w in sug])
props = V.review(book, ask, v); print('model accepts:', [(p['word'], p['categories']) for p in props]); json.dump(dict(suggestions=sug, accepted=props), open(S + '/vocab_demo_review2.json', 'w'), indent=1); print('done')
