"""Composing the film from its shots and transitions. Independent of where the pictures come from: a SOURCE gives the frames of one planned window, the composer lays the windows end to end and
blends the transitions (edit/transitions.py). The preview uses the clips' proxies as the source; the final render uses the original lens video.

A source provides  frames(k, a0, a1, yaw_extra=None)  -> iterator of images (numpy, any integer dtype), for frames a0 .. a1-1 of window k, counted from the start of the window (a0 < 0 or
a1 > window length asks for the footage next to the window: the shot's 'handles'; the source holds the first/last frame where the clip ends). yaw_extra, if given, is an array (radians) added to the
camera's yaw frame by frame: the whip uses it to pan away and in.

The film keeps its length: a transition centred on a cut takes half of its frames from each side of the cut; the window frames it covers are the ones shown inside the blend."""
import numpy as np, cv2


def layout(segs, fps):
    """(first frame, frame count) of every window by cumulative rounding (so the film's total is exact), and the half-length in frames of the transition into each window."""
    ends = [int(round((g['film_start_s'] + g['dur_s']) * fps)) for g in segs]; starts = [0] + ends[:-1]; n = [e - s for s, e in zip(starts, ends)]; half = [0] * len(segs)
    for k in range(1, len(segs)):
        tr = segs[k].get('transition') or {}
        if tr.get('type', 'cut') != 'cut': half[k] = max(0, min(int(round(tr['dur_s'] * fps / 2)), (min(n[k - 1], n[k]) - 2) // 2))
    return starts, n, half


def _smooth(u): return u * u * (3 - 2 * u)


def blend(kind, a, b, i, total):
    """Frame i (0 .. total-1) of a dissolve or a dip to black between pictures a (outgoing) and b (incoming)."""
    u = (i + 0.5) / total
    if kind == 'dissolve': w = _smooth(u); return cv2.addWeighted(a, 1 - w, b, w, 0)
    if u < 0.5: return (a.astype(np.float32) * (1 - _smooth(u * 2))).astype(a.dtype)                 # dip: down to black, then up
    return (b.astype(np.float32) * _smooth(u * 2 - 1)).astype(b.dtype)


def motion_blur(img, amount):
    """Horizontal blur of `amount` (0..1) of the frame width/25: the whip's streak."""
    k = 1 + 2 * int(amount * img.shape[1] / 25)
    return img if k <= 1 else cv2.blur(img, (k, 1))


WHIP_RAD = 1.6


def compose(segs, source, fps, emit, progress=None):
    """Emit every frame of the film, in order: emit(image). segs: plan segments (film_start_s, dur_s, transition); returns the number of frames."""
    starts, n, half = layout(segs, fps); total = sum(n); done = 0
    for k in range(len(segs)):
        hin = half[k]; hout = half[k + 1] if k + 1 < len(segs) else 0
        for img in source.frames(k, hin, n[k] - hout): emit(img); done += 1
        if hout:
            kind = segs[k + 1]['transition']['type']; s = 1.0 if (hash(segs[k + 1]['id']) % 2) else -1.0
            if kind == 'whip':
                ramp = (np.arange(1, hout + 1) / hout) ** 2
                for i, img in enumerate(source.frames(k, n[k] - hout, n[k], yaw_extra=s * WHIP_RAD * ramp)): emit(motion_blur(img, ramp[i])); done += 1
                for i, img in enumerate(source.frames(k + 1, 0, hout, yaw_extra=-s * WHIP_RAD * ramp[::-1])): emit(motion_blur(img, ramp[::-1][i])); done += 1
            else:
                for i, (a, b) in enumerate(zip(source.frames(k, n[k] - hout, n[k] + hout), source.frames(k + 1, -hout, hout))): emit(blend(kind, a, b, i, 2 * hout)); done += 1
        if progress: progress(done, total)
    return done
