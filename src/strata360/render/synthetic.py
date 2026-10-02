"""Frames of a generated clip (edit/synthetic.py, overlay/mapclip.py) for the film: a plain picture video, not a lens recording, so there is no camera and no overlay (the map clip has its own overlay baked in,
at the clip's own speed-up: the race clock on it already runs fast, so no time map is needed here).

frames(path, start_s, a0, a1, fps, W, H, order='rgb', dtype=uint8) -> iterator of pictures for frames a0 .. a1-1 of the window, which shows the video from `start_s`. Before the start of the video
the first frame is held, after its end the last (the transition handles, as for lens footage); the video is scaled to W x H and its frames are picked at the film's rate."""
import subprocess

import numpy as np

from strata360.pipeline import guard


def frames(path, start_s, a0, a1, fps, W, H, order='rgb', dtype=np.uint8):
    m = a1 - a0
    if m <= 0: return
    t_from = start_s + a0 / fps; lead = int(round(max(-t_from, 0.0) * fps)); n = W * H * 3
    dec = guard.popen(['ffmpeg', '-v', 'error', '-ss', f'{max(t_from, 0.0):.3f}', '-i', path, '-t', f'{m / fps + 0.2:.3f}', '-an', '-vf', f'scale={W}:{H}:flags=bilinear,fps={fps:g}', '-pix_fmt', f'{order}24', '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    fr = None
    try:
        for i in range(m):
            if i >= lead or fr is None:
                buf = dec.stdout.read(n)
                if len(buf) == n: fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
                elif fr is None: fr = np.zeros((H, W, 3), np.uint8)                          # past the end the last frame is held
            yield fr if dtype == np.uint8 else fr.astype(dtype) * 257
    finally:
        dec.stdout.close(); dec.terminate(); dec.wait()
