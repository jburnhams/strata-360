"""Experiment (K3): the scenery camera and the free view on real footage, as stills from the clip's proxy.

  python scripts/scenery_spike.py FOLDER OUT_DIR CLIP_NUMBER[:T,T,...] ...      (windows of 8 s starting at those clip times; default: three spread across the clip)

One row per window: the scenery camera at 0, 4 and 8 s, then the free view in the middle of the window, each labelled with its yaw; written to OUT_DIR/scenery_<clip>.jpg."""
import os, sys
import cv2, numpy as np
from strata360.edit import framing as FR, techniques as TQ
from strata360.pipeline import config
from strata360.render import preview as PV


def main():
    folder, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True); lib = TQ.load(); rd = config.race_dir(folder)
    for arg in sys.argv[3:]:
        num, _, ts = arg.partition(':'); clip = next(c for c in sorted(os.listdir(os.path.join(rd, 'clips'))) if f'_{num}_' in c); data = FR.clip_data(folder, clip); n = len(data['views']['grid']['tex']) / data['views']['grid']['hz']
        starts = [float(x) for x in ts.split(',')] if ts else [max(n * f - 4, 0.0) for f in (0.2, 0.5, 0.8)]; W, H = 640, 360; rows = []
        for t in starts:
            tiles = []
            for tech, offs in (('scenery', (0.0, 4.0, 8.0)), ('free_view', (4.0,))):
                g = dict(id=f'{clip}@{t:.2f}', clip=clip, clip_start_s=t, dur_s=8.0, technique=tech, variant_seed=7); path = FR.resolve_segment(g, lib, data); src = PV.PreviewSource(folder, [g], {g['id']: path}, W, H, 3072)
                for o in offs:
                    img = np.ascontiguousarray(next(iter(src.frames(0, int(o * 25), int(o * 25) + 1)))); y = np.interp(o, [k['t'] for k in path['keyframes']], [k['yaw'] for k in path['keyframes']]); label = f"{tech} t={t + o:.0f}s yaw {y:.0f}"
                    cv2.putText(img, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA); cv2.putText(img, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA); tiles.append(img)
            rows.append(np.hstack(tiles))
        p = os.path.join(out, f'scenery_{num}.jpg'); cv2.imwrite(p, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88]); print(p)


if __name__ == '__main__':
    main()
