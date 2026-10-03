"""Run in .venv-vision: people and faces in still photos.

  python -m strata360.analysis.photo_detect IMAGES_DIR OUT_JSON OUT_NPY [--models models/]

For every `p<index>.jpg`: the persons (YOLO11 pose: box, confidence, nose / eyes / ears) and the faces (InsightFace buffalo_l: box, detection score, HEAD POSE [pitch, yaw, roll] from the 3D landmarks, and a 512-d ArcFace embedding written to OUT_NPY, referenced by `emb`).
Output {"images": {index: {"w", "h", "people": [...], "faces": [...]}}}."""
import argparse, glob, json, os, re, time

import numpy as np, cv2


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('dir'); ap.add_argument('out_json'); ap.add_argument('out_npy'); ap.add_argument('--models', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models'))
    ap.add_argument('--conf', type=float, default=0.3); ap.add_argument('--imgsz', type=int, default=1280)
    a = ap.parse_args(); M = os.path.abspath(a.models)
    import torch; from ultralytics import YOLO; from insightface.app import FaceAnalysis
    from strata360 import hw; dev = hw.gpu_device(); torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', '2')))
    yolo = YOLO(f'{M}/yolo11s-pose.pt'); predict = hw.gpu_throttled(yolo.predict, dev) if dev != 'cpu' else yolo.predict
    fa = FaceAnalysis(name='buffalo_l', root=f'{M}/insightface', allowed_modules=['detection', 'recognition', 'landmark_3d_68'], providers=['CPUExecutionProvider']); fa.prepare(ctx_id=-1, det_size=(640, 640))
    out = {}; embs = []; t0 = time.time()
    for fn in sorted(glob.glob(os.path.join(a.dir, 'p*.jpg'))):
        k = int(re.search(r'p(\d+)\.jpg', fn).group(1)); img = cv2.imread(fn); h, w = img.shape[:2]
        res = predict(img, imgsz=a.imgsz, conf=a.conf, classes=[0], device=dev, verbose=False)[0]; people = []; faces = []
        for j in range(len(res.boxes)):
            kp = res.keypoints.data[j].cpu().numpy()
            people.append(dict(box=[round(float(z), 1) for z in res.boxes.xyxy[j].cpu().numpy()], conf=round(float(res.boxes.conf[j]), 3), kp=[[round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 2)] for p in kp[:5]]))
        for f in fa.get(img):
            emb = None
            if getattr(f, 'normed_embedding', None) is not None: embs.append(f.normed_embedding.astype(np.float16)); emb = len(embs) - 1
            faces.append(dict(box=[round(float(z), 1) for z in f.bbox], score=round(float(f.det_score), 3), pose=[round(float(z), 1) for z in f.pose] if getattr(f, 'pose', None) is not None else None, emb=emb))
        out[k] = dict(w=w, h=h, people=people, faces=faces)
    np.save(a.out_npy, np.array(embs, np.float16).reshape(-1, 512)); json.dump(dict(seconds=round(time.time() - t0, 1), images=out), open(a.out_json, 'w')); print(f'{len(out)} photos, {len(embs)} faces, {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
