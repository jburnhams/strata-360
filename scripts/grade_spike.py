"""Experiment (A4): the exposure match on real windows, as stills from the clips' proxies.

  python scripts/grade_spike.py FOLDER OUT.jpg [FIRST [COUNT]]      (consecutive windows of the saved plan from window FIRST; default the four with the biggest gain swings)

One column per window: top the picture as it is, bottom with the grade, labelled with the window's id, the gain at its first frame and its base gain."""
import sys
import cv2, numpy as np
from strata360.edit import framing as FR, project as PJ
from strata360.render import grade as GR, preview as PV


def main():
    folder, out = sys.argv[1], sys.argv[2]; plan = PJ.load(folder)['plan']; segs = plan['segments']; fr = FR.resolve(folder, plan); gains = GR.plan_gains(folder, segs, fr)
    if len(sys.argv) > 3: first = int(sys.argv[3]); idx = list(range(first, first + (int(sys.argv[4]) if len(sys.argv) > 4 else 4)))
    else:
        sw = sorted((k for k, s in enumerate(segs) if s['id'] in gains), key=lambda k: -abs(gains[segs[k]['id']](0.0))); idx = sorted(sw[:4])
    W, H = 480, 270; cols = []
    for k in idx:
        g = segs[k]; gn = gains.get(g['id'])
        for graded in (False, True):
            src = PV.PreviewSource(folder, [g], {g['id']: fr[g['id']]}, W, H, 3072, gains={g['id']: gn} if graded and gn else None); img = np.ascontiguousarray(next(iter(src.frames(0, 25, 26))))
            txt = f"{g['id'][-12:]} {'graded' if graded else 'plain'}" + (f" {gn(1.0):+.2f}st" if graded and gn else ''); cv2.putText(img, txt, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA); cv2.putText(img, txt, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cols.append(img)
    top, bot = np.hstack(cols[0::2]), np.hstack(cols[1::2]); cv2.imwrite(out, np.vstack([top, bot]), [cv2.IMWRITE_JPEG_QUALITY, 88]); print(out, [segs[k]['id'] for k in idx])


if __name__ == '__main__':
    main()
