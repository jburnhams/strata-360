import sys, glob, json, time, os, torch
sys.path.insert(0, os.path.dirname(__file__)); from terms import TERMS
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
name, root, out = sys.argv[1], sys.argv[2], sys.argv[3]; limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
MP = {'owl': 'google/owlv2-base-patch16-ensemble', 'gdino': 'IDEA-Research/grounding-dino-base', 'llmdet': 'iSEE-Laboratory/llmdet_base'}[name]
dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
P = AutoProcessor.from_pretrained(MP); m = AutoModelForZeroShotObjectDetection.from_pretrained(MP).eval().to(dev)
files = sorted(glob.glob(root + '/*/*.jpg')); files = files[:limit] if limit else files; res = []; t0 = time.time()
TH = 0.2 if name == 'owl' else 0.25
for k, fn in enumerate(files):
    img = Image.open(fn).convert('RGB'); w, h = img.size
    if name == 'owl': txt = [[f'a photo of a {t}' for t in TERMS]]
    elif name == 'gdino': txt = [' . '.join(TERMS) + ' .']
    else: txt = [TERMS]
    inp = P(images=img, text=txt, return_tensors='pt').to(dev)
    with torch.no_grad(): o = m(**inp)
    kw = dict(target_sizes=torch.tensor([[max(w, h)] * 2] if name == 'owl' else [[h, w]]))
    if name == 'owl': r = P.post_process_grounded_object_detection(o, threshold=TH, text_labels=txt, **kw)[0]
    elif name == 'gdino': r = P.post_process_grounded_object_detection(o, inp.input_ids, threshold=TH, text_threshold=TH, **kw)[0]
    else: r = P.post_process_grounded_object_detection(o, threshold=TH, text_labels=txt, **kw)[0]
    labs = r.get('text_labels') or r.get('labels')
    for sc, lb, bx in zip(r['scores'], labs, r['boxes']): res.append(dict(file='/'.join(fn.split('/')[-2:]), label=str(lb).replace('a photo of a ', ''), score=round(float(sc), 2), box=[round(float(z)) for z in bx]))
    if k % 40 == 0: print(k, len(files), round(time.time() - t0), flush=True)
json.dump(res, open(out, 'w')); print('done', len(res), 'hits', round(time.time() - t0), 's')
