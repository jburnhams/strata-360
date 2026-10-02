"""Experiment (K6, three views of you): the same moment of a clip as mid, close and far, side by side, from the clip's proxy through the preview's own projection, so the look of the new shots can be judged.

  python scripts/views_spike.py FOLDER OUT_DIR CLIP_NUMBER[:T,T,...] ...      (clip numbers such as 0018; times in seconds, default: three moments where you are found)

Writes OUT_DIR/views_<clip>.jpg: one row per moment, columns mid (selfie_hold) | close (selfie_close) | far (selfie_far), each labelled with its field of view and what the framing was aimed at."""
import json, os, sys
import cv2, numpy as np
from strata360.edit import framing as FR, techniques as TQ
from strata360.pipeline import config
from strata360.render import preview as PV

COLS = ('selfie_hold', 'selfie_close', 'selfie_far')


def main():
    folder, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True); lib = TQ.load(); rd = config.race_dir(folder)
    for arg in sys.argv[3:]:
        num, _, ts = arg.partition(':'); clip = next(c for c in sorted(os.listdir(os.path.join(rd, 'clips'))) if f'_{num}_' in c); data = FR.clip_data(folder, clip)
        found = [s['t'] for s in data['you']]; times = [float(x) for x in ts.split(',')] if ts else [found[int(len(found) * f)] for f in (0.2, 0.5, 0.8)] if len(found) >= 3 else found
        W, H = 640, 360; rows = []
        for t in times:
            tiles = []
            for tech in COLS:
                g = dict(id=f'{clip}@{t:.2f}', clip=clip, clip_start_s=max(t - 1.0, 0.0), dur_s=2.0, technique=tech, variant_seed=3); path = FR.resolve_segment(g, lib, data)
                src = PV.PreviewSource(folder, [g], {g['id']: path}, W, H, 3072); img = next(iter(src.frames(0, 25, 26))); img = np.ascontiguousarray(img)
                fov = path['keyframes'][0]['fov']; cv2.putText(img, f"{tech.replace('selfie_', '')}  fov {fov:g}  t={t:.0f}s  {path['subject']}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(img, f"{tech.replace('selfie_', '')}  fov {fov:g}  t={t:.0f}s  {path['subject']}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA); tiles.append(img)
            rows.append(np.hstack(tiles))
        p = os.path.join(out, f'views_{num}.jpg'); cv2.imwrite(p, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88]); print(p)


if __name__ == '__main__':
    main()
