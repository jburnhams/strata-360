"""Run in .venv-vision: the objects in still photos (YOLO11, the 80 everyday classes: bicycle, car, dog, bottle, backpack, bench, boat, sign ...).

  python -m strata360.analysis.photo_objects IMAGES_DIR OUT_JSON [--models models/] [--conf 0.35]

For every `p<index>.jpg`: [{label, conf, box [x0, y0, x1, y1]}] in pixels of that image, people left out (the people stage has them, with faces and a better model for them). The segmentation checkpoint is used for its boxes; the masks are not kept.
Output {"images": {index: {"w", "h", "objects": [...]}}}. Not used for the clips."""
import argparse, glob, json, os, re, time

import cv2


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('dir'); ap.add_argument('out_json'); ap.add_argument('--models', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models')); ap.add_argument('--conf', type=float, default=0.35); ap.add_argument('--imgsz', type=int, default=1280)
    a = ap.parse_args(); M = os.path.abspath(a.models)
    import torch; from ultralytics import YOLO
    from strata360 import hw; dev = hw.gpu_device(); torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', '2')))
    yolo = YOLO(f'{M}/yolo11s-seg.pt'); predict = hw.gpu_throttled(yolo.predict, dev) if dev != 'cpu' else yolo.predict; names = yolo.names; out = {}; t0 = time.time()
    for fn in sorted(glob.glob(os.path.join(a.dir, 'p*.jpg'))):
        k = int(re.search(r'p(\d+)\.jpg', fn).group(1)); img = cv2.imread(fn); h, w = img.shape[:2]; res = predict(img, imgsz=a.imgsz, conf=a.conf, device=dev, verbose=False, retina_masks=False)[0]; objs = []
        for j in range(len(res.boxes)):
            label = names[int(res.boxes.cls[j])]
            if label == 'person': continue
            objs.append(dict(label=label, conf=round(float(res.boxes.conf[j]), 3), box=[round(float(z), 1) for z in res.boxes.xyxy[j].cpu().numpy()]))
        out[k] = dict(w=w, h=h, objects=sorted(objs, key=lambda o: -o['conf']))
    json.dump(dict(seconds=round(time.time() - t0, 1), images=out), open(a.out_json, 'w')); print(f'{len(out)} photos, {sum(len(v["objects"]) for v in out.values())} objects, {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
