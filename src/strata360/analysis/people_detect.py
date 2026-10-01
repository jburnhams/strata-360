"""People and face detector, run inside `.venv-vision` on the JPEG views written by `analysis.views` (subprocess: keeps its heavy dependencies out of the main env).

  python -m strata360.analysis.people_detect VIEWS_DIR OUT_JSON OUT_NPY [--models models/]

Per sampled frame and view: YOLO11 pose (persons, 17 keypoints) and InsightFace buffalo_l (faces, 512-d ArcFace embedding). Each person gets its direction in the
camera body frame (yaw from the front lens, pitch above the horizon) so later stages can follow people across views, and the face that lies inside its box.
Embeddings go to OUT_NPY (float16, one row per face, referenced by `emb`)."""
import argparse, glob, json, os, re, sys, time
import numpy as np, cv2

SCHEMA_VERSION = 1


def pixel_dir(view_yaw, x, y, px, fov):
    """Body-frame direction (yaw deg from the front lens, pitch deg above the horizon) of pixel (x, y) in a view."""
    from strata360.analysis.views import view_rays
    a = np.radians(view_yaw); f = np.array([np.sin(a), np.cos(a), 0.0]); r = np.array([np.cos(a), -np.sin(a), 0.0]); u = np.cross(r, f)
    t = np.tan(np.radians(fov) / 2); gx = ((x / px) * 2 - 1) * t; gy = -((y / px) * 2 - 1) * t
    d = f + gx * r + gy * u; d /= np.linalg.norm(d)
    return float(np.degrees(np.arctan2(d[0], d[1])) % 360.0), float(np.degrees(np.arcsin(np.clip(d[2], -1, 1))))


def thumb(img, box, size=96, margin=0.35):
    x0, y0, x1, y1 = box; w, h = x1 - x0, y1 - y0; c = max(w, h) * (1 + margin) / 2; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x0, x1, y0, y1 = int(cx - c), int(cx + c), int(cy - c), int(cy + c); pad = int(c) + 2
    big = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT); return cv2.resize(big[y0 + pad:y1 + pad, x0 + pad:x1 + pad], (size, size), interpolation=cv2.INTER_AREA)[:, :, ::-1]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('views'); ap.add_argument('out_json'); ap.add_argument('out_npy')
    ap.add_argument('--models', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models')); ap.add_argument('--fov', type=float, default=100.0)
    ap.add_argument('--conf', type=float, default=0.3); ap.add_argument('--imgsz', type=int, default=1024)
    a = ap.parse_args(); M = os.path.abspath(a.models)
    import torch; from ultralytics import YOLO; from insightface.app import FaceAnalysis
    from strata360 import hw; dev = hw.gpu_device()          # CPU by default: the GPU is what makes a desktop stutter
    torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', '2')))
    yolo = YOLO(f'{M}/yolo11s-pose.pt'); fa = FaceAnalysis(name='buffalo_l', root=f'{M}/insightface', allowed_modules=['detection', 'recognition'], providers=['CPUExecutionProvider'])
    fa.prepare(ctx_id=-1, det_size=(640, 640))
    files = sorted(glob.glob(os.path.join(a.views, 's*_v*.jpg'))); pat = re.compile(r's(\d+)_v(\d+)\.jpg'); dets, embs, thumbs = [], [], []; t0 = time.time()
    for fn in files:
        k, v = map(int, pat.search(fn).groups()); img = cv2.imread(fn); px = img.shape[0]
        res = yolo.predict(img, imgsz=a.imgsz, conf=a.conf, classes=[0], device=dev, verbose=False)[0]
        faces = fa.get(img)
        for fc in faces: fc._used = False
        for j in range(len(res.boxes)):
            x0, y0, x1, y1 = [float(z) for z in res.boxes.xyxy[j].cpu().numpy()]; kp = res.keypoints.data[j].cpu().numpy()             # (17, 3): x, y, conf
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; yaw, pitch = pixel_dir(v, cx, cy, px, a.fov)
            d = dict(frame=k, view=v, box=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)], conf=round(float(res.boxes.conf[j]), 3), yaw=round(yaw, 2), pitch=round(pitch, 2),
                     height_deg=round(float((y1 - y0) / px * a.fov), 1), kp=[[round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 2)] for p in kp[:5]], face=None)   # nose, eyes, ears
            best = None
            for fc in faces:
                fx, fy = (fc.bbox[0] + fc.bbox[2]) / 2, (fc.bbox[1] + fc.bbox[3]) / 2
                if x0 <= fx <= x1 and y0 <= fy <= y1 and fy < y0 + 0.5 * (y1 - y0) and not fc._used and (best is None or fc.det_score > best.det_score): best = fc
            if best is not None:
                best._used = True; embs.append(best.normed_embedding.astype(np.float16)); thumbs.append(thumb(img, best.bbox))
                d['face'] = dict(box=[round(float(z), 1) for z in best.bbox], score=round(float(best.det_score), 3), size_px=round(float(best.bbox[2] - best.bbox[0]), 1), emb=len(embs) - 1)
            dets.append(d)
        for fc in faces:                                                                            # faces YOLO missed (close-ups, cropped bodies)
            if fc._used or fc.det_score < 0.5: continue
            cx, cy = (fc.bbox[0] + fc.bbox[2]) / 2, (fc.bbox[1] + fc.bbox[3]) / 2; yaw, pitch = pixel_dir(v, cx, cy, px, a.fov); embs.append(fc.normed_embedding.astype(np.float16)); thumbs.append(thumb(img, fc.bbox))
            dets.append(dict(frame=k, view=v, box=None, conf=None, yaw=round(yaw, 2), pitch=round(pitch, 2), height_deg=None, kp=None,
                             face=dict(box=[round(float(z), 1) for z in fc.bbox], score=round(float(fc.det_score), 3), size_px=round(float(fc.bbox[2] - fc.bbox[0]), 1), emb=len(embs) - 1)))
    np.save(a.out_npy, np.array(embs, np.float16).reshape(-1, 512)); np.save(a.out_npy.replace('.npy', '_thumbs.npy'), np.array(thumbs, np.uint8).reshape(-1, 96, 96, 3))
    json.dump(dict(schema=SCHEMA_VERSION, models=dict(person='yolo11s-pose', face='insightface buffalo_l (ArcFace)'), view_fov=a.fov, n_images=len(files), seconds=round(time.time() - t0, 1), detections=dets), open(a.out_json, 'w'))
    print(f'{len(files)} views, {len(dets)} detections, {len(embs)} faces, {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
