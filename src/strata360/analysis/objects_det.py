"""Box detection with YOLOE for the `objects` stage, run inside `.venv-vision`.

  python -m strata360.analysis.objects_det IMAGES_DIR OUT_JSON --words WORDS_JSON [--weights DIR]

Two models over every *.jpg of IMAGES_DIR: the text model (yoloe-26s-seg) with the given words, which names what it finds, and the prompt-free model (yoloe-26s-seg-pf), whose boxes are the candidates the words did not
cover. Output {"files": {name: {"named": [[label, conf, [x0, y0, x1, y1]]], "pf": [...]}}, "seconds": s}. The weights are in $STRATA_YOLOE_DIR, `models/yoloe` of the repository (any folder above this file) or --weights; the text
model needs the CLIP text encoder (the `clip` and `ftfy` packages, found through $PYTHONPATH; STRATA_VISION_EXTRA is added to it by the stage) and `mobileclip2_b.ts` next to the weights."""
import argparse, glob, json, os, time

TEXT, PF = 'yoloe-26s-seg.pt', 'yoloe-26s-seg-pf.pt'


def weights_dir(given=None):
    if given: return os.path.abspath(given)
    env = os.environ.get('STRATA_YOLOE_DIR')
    if env and os.path.isdir(env): return env
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        p = os.path.join(d, 'models', 'yoloe')
        if os.path.isdir(p): return p
        if os.path.dirname(d) == d: raise SystemExit('no YOLOE weights: put yoloe-26s-seg.pt, yoloe-26s-seg-pf.pt and mobileclip2_b.ts in models/yoloe (or set STRATA_YOLOE_DIR)')
        d = os.path.dirname(d)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('images'); ap.add_argument('out'); ap.add_argument('--words', required=True); ap.add_argument('--weights'); ap.add_argument('--imgsz', type=int, default=1024); a = ap.parse_args()
    wd = weights_dir(a.weights); words = json.load(open(a.words)); os.chdir(wd)                 # the text encoder is looked up in the working folder
    import torch
    from ultralytics import YOLOE
    dev = 'mps' if torch.backends.mps.is_available() else 0 if torch.cuda.is_available() else 'cpu'
    tx = YOLOE(os.path.join(wd, TEXT)); tx.set_classes(words, tx.get_text_pe(words)); pf = YOLOE(os.path.join(wd, PF)); t0 = time.time(); out = {}
    def preds(model, fn, conf):
        r = model.predict(fn, imgsz=a.imgsz, conf=conf, iou=0.5, agnostic_nms=True, device=dev, verbose=False)[0]
        return [[model.names[int(r.boxes.cls[j])], round(float(r.boxes.conf[j]), 3), [round(float(z), 1) for z in r.boxes.xyxy[j]]] for j in range(len(r.boxes))]
    for fn in sorted(glob.glob(os.path.join(os.path.abspath(a.images), '*.jpg'))):
        out[os.path.basename(fn)] = dict(named=preds(tx, fn, 0.10), pf=preds(pf, fn, 0.30))
    json.dump(dict(schema=1, words=len(words), seconds=round(time.time() - t0, 1), files=out), open(a.out, 'w')); print(f'{len(out)} images in {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
