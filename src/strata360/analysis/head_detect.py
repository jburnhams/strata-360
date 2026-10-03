"""Run in .venv-vision: YOLO pose on a folder of crops (c00000.jpg ...), the first five keypoints (nose, eyes, ears) of every person found, and with `--pose` also every face (insightface: box, detection score and HEAD POSE [pitch, yaw, roll] degrees from its 3D landmarks, as the crop sees it). `python -m strata360.analysis.head_detect DIR OUT.json [--models DIR] [--conf 0.3] [--imgsz 960]`."""
import argparse, glob, json, os, time

import cv2


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('dir'); ap.add_argument('out_json'); ap.add_argument('--models', default=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'models')); ap.add_argument('--conf', type=float, default=0.1); ap.add_argument('--imgsz', type=int, default=960); ap.add_argument('--pose', action='store_true')
    a = ap.parse_args(); M = os.path.abspath(a.models)
    import torch; from ultralytics import YOLO
    from strata360 import hw; dev = hw.gpu_device(); torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', '2')))
    fa = None
    if a.pose:
        from insightface.app import FaceAnalysis; fa = FaceAnalysis(name='buffalo_l', root=f'{M}/insightface', allowed_modules=['detection', 'landmark_3d_68'], providers=['CPUExecutionProvider']); fa.prepare(ctx_id=-1, det_size=(640, 640))
    yolo = YOLO(f'{M}/yolo11s-pose.pt'); predict = hw.gpu_throttled(yolo.predict, dev) if dev != 'cpu' else yolo.predict; out = {}; t0 = time.time()
    for fn in sorted(glob.glob(os.path.join(a.dir, 'c*.jpg'))):
        k = int(os.path.basename(fn)[1:-4]); img = cv2.imread(fn); res = predict(img, imgsz=a.imgsz, conf=a.conf, classes=[0], device=dev, verbose=False)[0]; people = []; faces = []
        if fa is not None: faces = [dict(box=[round(float(z), 1) for z in f.bbox], score=round(float(f.det_score), 3), pose=[round(float(z), 1) for z in f.pose]) for f in fa.get(img) if getattr(f, 'pose', None) is not None]
        for j in range(len(res.boxes)):
            kp = res.keypoints.data[j].cpu().numpy()
            people.append(dict(box=[round(float(z), 1) for z in res.boxes.xyxy[j].cpu().numpy()], conf=round(float(res.boxes.conf[j]), 3), kp=[[round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 2)] for p in kp[:5]]))
        out[k] = dict(people=people, faces=faces) if a.pose else people
    json.dump(dict(seconds=round(time.time() - t0, 1), frames=out), open(a.out_json, 'w')); print(f'{len(out)} crops, {time.time() - t0:.1f} s')


if __name__ == '__main__':
    main()
