"""Experiment: bigger detector sizes on the RTX 5070 Ti against the ones the stages use (YOLO11s-pose for `people` / `face_view`, YOLOE-26s-seg for `objects`).

  python scripts/win_exp/vision_models.py PROJECT_FOLDER CLIP OUT.json [--views N]

The views are the ones the people stage makes (stabilised front and rear views of the clip's proxy, every 50 source frames). For each size: seconds a picture, detections, and how well the stage's own size agrees with it
(share of the bigger model's detections that the small one also finds with IoU 0.5, and the reverse). Run from the repository root; weights are fetched by ultralytics into the working folder."""
import argparse, glob, json, os, sys, tempfile, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from strata360.analysis import views as V
from strata360.pipeline import config


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]); i = max(x1 - x0, 0) * max(y1 - y0, 0)
    return i / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i, 1e-9)


def agree(base, other):
    """(share of `other`'s boxes that `base` also has, share of `base`'s boxes that `other` also has), per image lists of boxes."""
    n_o = n_b = h_o = h_b = 0
    for bb, oo in zip(base, other):
        n_o += len(oo); n_b += len(bb); h_o += sum(any(iou(o, b) > 0.5 for b in bb) for o in oo); h_b += sum(any(iou(o, b) > 0.5 for o in oo) for b in bb)
    return round(h_o / max(n_o, 1), 3), round(h_b / max(n_b, 1), 3)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('clip'); ap.add_argument('out'); ap.add_argument('--views', type=int, default=40); a = ap.parse_args()
    import torch
    from ultralytics import YOLO, YOLOE
    cdir = glob.glob(os.path.join(a.folder, 'strata360', 'clips', a.clip))[0]; cj = json.load(open(os.path.join(cdir, 'clip.json'))); osv = config.source(cj['source_files']['osv'], cdir); res = {}
    with tempfile.TemporaryDirectory() as tmp:
        V.write_stab_views_proxy(os.path.join(cdir, 'proxy.mp4'), osv, tmp, every=50); files = sorted(glob.glob(os.path.join(tmp, '*.jpg')))[:a.views]; print(len(files), 'views', flush=True)
        os.makedirs('models/yolo_bench', exist_ok=True); os.chdir('models/yolo_bench')
        def run(model, kw):
            model.predict(files[0], verbose=False, device=0, **kw); torch.cuda.synchronize(); t = time.time(); boxes = []; extra = []
            for f in files:
                r = model.predict(f, verbose=False, device=0, **kw)[0]; boxes.append([list(map(float, b)) for b in r.boxes.xyxy.cpu().numpy()])
                extra.append(r.keypoints.conf.cpu().numpy().mean() if getattr(r, 'keypoints', None) is not None and r.keypoints.conf is not None and len(r.boxes) else None)
            torch.cuda.synchronize(); return boxes, (time.time() - t) / len(files), [e for e in extra if e is not None]
        pose = {}
        for size in ('s', 'm', 'l', 'x'):
            m = YOLO(f'yolo11{size}-pose.pt'); b, s, k = run(m, dict(imgsz=1024, conf=0.3, classes=[0])); pose[size] = b; res[f'pose_{size}'] = dict(seconds_per_view=round(s, 3), detections=sum(map(len, b)), mean_keypoint_conf=round(float(np.mean(k)), 3) if k else None); print('pose', size, res[f'pose_{size}'], flush=True)
        for size in ('m', 'l', 'x'): res[f'pose_{size}']['small_finds_share_of_bigger__bigger_finds_share_of_small'] = agree(pose['s'], pose[size])
        words = json.load(open(os.path.join(cdir, 'objects.json')))['words']; det = {}
        for size in ('s', 'm', 'l'):
            try:
                tx = YOLOE(f'yoloe-26{size}-seg.pt'); tx.set_classes(words, tx.get_text_pe(words)); pf = YOLOE(f'yoloe-26{size}-seg-pf.pt')
            except Exception as e: print('yoloe', size, 'not available', type(e).__name__); continue
            b1, s1, _ = run(tx, dict(imgsz=1024, conf=0.10, iou=0.5, agnostic_nms=True)); b2, s2, _ = run(pf, dict(imgsz=1024, conf=0.30, iou=0.5, agnostic_nms=True)); det[size] = (b1, b2)
            res[f'yoloe_{size}'] = dict(seconds_per_view=round(s1 + s2, 3), named=sum(map(len, b1)), prompt_free=sum(map(len, b2))); print('yoloe', size, res[f'yoloe_{size}'], flush=True)
        for size in det:
            if size != 's': res[f'yoloe_{size}']['small_finds_share_of_bigger__bigger_finds_share_of_small_(named)'] = agree(det['s'][0], det[size][0])
    json.dump(res, open(os.path.join('..', '..', a.out) if not os.path.isabs(a.out) else a.out, 'w'), indent=1); print(json.dumps(res, indent=1))


if __name__ == '__main__': main()
