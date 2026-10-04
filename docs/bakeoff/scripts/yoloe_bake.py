import sys, glob, json, time
from ultralytics import YOLOE
root, out, wt = sys.argv[1], sys.argv[2], sys.argv[3]
m = YOLOE(wt); files = sorted(glob.glob(root + '/*/*.jpg')); res = []; t0 = time.time()
for k, fn in enumerate(files):
    r = m.predict(fn, imgsz=1024, conf=0.25, device='mps', verbose=False)[0]
    for j in range(len(r.boxes)): res.append(dict(file='/'.join(fn.split('/')[-2:]), label=m.names[int(r.boxes.cls[j])], score=round(float(r.boxes.conf[j]), 2), box=[round(float(z)) for z in r.boxes.xyxy[j]]))
    if k % 80 == 0: print(k, len(files), round(time.time() - t0), flush=True)
json.dump(res, open(out, 'w')); print('done', len(res), 'hits', round(time.time() - t0), 's')
