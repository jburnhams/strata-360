"""Experiment (K, camera list): how scenery, free and person windows look when framed by the clip's camera list (edit/cameras.py) against the framing's own choice.

  python scripts/camera_list_spike.py FOLDER OUT.jpg [N]       (N windows from a 180 s beat plan of the whole race, default 6)

One block per window: top row the framing with the camera list (start, middle, end of the window), bottom row the same window framed without it (`cameras` emptied); each tile is labelled with the technique, the clip and the yaw."""
import sys
import cv2, numpy as np
from strata360.edit import chrono as CH, framing as FR, optimise as O, project as P, techniques as TQ
from strata360.render import preview as PV

W, H = 480, 270


def tiles(folder, g, path, label):
    src = PV.PreviewSource(folder, [g], {g['id']: path}, W, H, 3072); n = max(int(g['dur_s'] * 25) - 1, 1); out = []
    for o in (0, n // 2, n):
        img = np.ascontiguousarray(next(iter(src.frames(0, o, o + 1)))); y = np.interp(o / 25.0, [k['t'] for k in path['keyframes']], [k['yaw'] for k in path['keyframes']])
        txt = f"{label} {g['technique']} {g['clip'][-7:-2]} +{o / 25:.1f}s yaw {y:.0f}"
        cv2.putText(img, txt, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA); cv2.putText(img, txt, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA); out.append(img)
    return np.hstack(out)


def main():
    folder, out = sys.argv[1], sys.argv[2]; want = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    clips, _ = P.load_clips(folder); lib = TQ.with_cams(TQ.load(), folder); m = O.Music(bpm=97, beats=int(180 * 97 / 60) // 4 * 4, bar_beats=4, sections=[(0, 10 ** 6, 0.5)])
    plan = CH.plan(clips, lib, m, CH.Settings(seed=1)); cache = {}; rows = []; seen = {}
    for s in plan:
        if s.tech.id not in ('scenery', 'free_view', 'person_hold') or seen.get(s.tech.id, 0) >= (want + 2) // 3: continue
        cid = s.cand.clip; data = cache.setdefault(cid, FR.clip_data(folder, cid))
        g = dict(id=s.parts['wid'], clip=cid, clip_start_s=s.clip_start_s, dur_s=s.beats * m.beat_s, technique=s.tech.id, variant_seed=s.variant_seed, kind=getattr(s.cand, 'kind', None))
        with_list = FR.resolve_segment(g, lib, data); without = FR.resolve_segment(g, lib, dict(data, cameras=[]))
        rows += [tiles(folder, g, with_list, 'LIST'), tiles(folder, g, without, 'OLD ')]; seen[s.tech.id] = seen.get(s.tech.id, 0) + 1
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85]); print(out, len(rows) // 2, 'windows')


if __name__ == '__main__':
    main()
