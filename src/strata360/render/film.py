"""Composing the film from its shots and transitions. Independent of where the pictures come from: a SOURCE gives the frames of one planned window, the composer lays the windows end to end and
blends the transitions (edit/transitions.py). The preview uses the clips' proxies as the source; the final render uses the original lens video.

A source provides  frames(k, a0, a1, yaw_extra=None, pose_extra=None)  -> iterator of images (numpy, any integer dtype), for frames a0 .. a1-1 of window k, counted from the start of the window (a0 < 0 or
a1 > window length asks for the footage next to the window: the shot's 'handles'; the source holds the first/last frame where the clip ends). yaw_extra, if given, is an array (radians) added to the
camera's yaw frame by frame: the whip uses it to pan away and in. pose_extra, if given, is an (n, 3) array of degrees added to the camera's yaw, pitch and field of view frame by frame: the pan transition glides with it.

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


def pieces(segs, fps):
    """The film as independent pieces in order: plain stretches of one window and transition regions between two windows. Each is {id, kind, k, frames}; rendering pieces separately is what makes a long
    render resumable (a finished piece is kept), and concatenating them gives the film."""
    starts, n, half = layout(segs, fps); out = []
    for k in range(len(segs)):
        hin = half[k]; hout = half[k + 1] if k + 1 < len(segs) else 0
        if n[k] - hout - hin > 0: out.append(dict(id=f'p{len(out):04d}', kind='plain', k=k, a0=hin, a1=n[k] - hout, frames=n[k] - hout - hin))
        if hout: out.append(dict(id=f'p{len(out):04d}', kind=segs[k + 1]['transition']['type'], k=k, hout=hout, n=n[k], frames=2 * hout, fps=fps))
    assert sum(p['frames'] for p in out) == sum(n)
    return out


def pan_extras(tr, n, hout, fps):
    """(first, second): the (hout, 3) yaw, pitch and field-of-view offsets (degrees) for the last `hout` frames of the first window and the first `hout` frames of the second, that make the camera glide from the first shot's pose to the second's through the cut (edit/pans.py):
    at progress u over the whole transition the camera is the first shot's pose (held at its last pose past its end) plus smoothstep(u) of the way to the second's (held at its first pose before its start)."""
    from strata360.edit import pans as PN
    first = np.zeros((hout, 3)); second = np.zeros((hout, 3)); A_end = PN.pose_at(tr['a_kf'], tr['a_dur']); B_start = PN.pose_at(tr['b_kf'], 0.0)
    for j in range(2 * hout):
        s = PN.smooth((j + 0.5) / (2 * hout))
        if j < hout: A = PN.pose_at(tr['a_kf'], (n - hout + j) / fps); first[j] = (s * float(PN.wrap(B_start[0] - A[0])), s * (B_start[1] - A[1]), s * (B_start[2] - A[2]))
        else: B = PN.pose_at(tr['b_kf'], (j - hout) / fps); second[j - hout] = ((1 - s) * float(PN.wrap(A_end[0] - B[0])), (1 - s) * (A_end[1] - B[1]), (1 - s) * (A_end[2] - B[2]))
    return first, second


def render_piece(piece, segs, source, emit):
    """Emit the frames of one piece."""
    k = piece['k']
    if piece['kind'] == 'plain':
        for img in source.frames(k, piece['a0'], piece['a1']): emit(img)
        return
    hout = piece['hout']; n = piece['n']; kind = piece['kind']; s = 1.0 if (sum(map(ord, segs[k + 1]['id'])) % 2) else -1.0
    if kind == 'pan':                                                                                     # the footage of a hard cut here, with the camera gliding from the first shot's pose to the second's through it
        first, second = pan_extras(segs[k + 1]['transition'], n, hout, piece['fps'])
        for img in source.frames(k, n - hout, n, pose_extra=first): emit(img)
        for img in source.frames(k + 1, 0, hout, pose_extra=second): emit(img)
        return
    if kind == 'whip':
        ramp = (np.arange(1, hout + 1) / hout) ** 2
        for i, img in enumerate(source.frames(k, n - hout, n, yaw_extra=s * WHIP_RAD * ramp)): emit(motion_blur(img, ramp[i]))
        for i, img in enumerate(source.frames(k + 1, 0, hout, yaw_extra=-s * WHIP_RAD * ramp[::-1])): emit(motion_blur(img, ramp[::-1][i]))
    else:
        for i, (a, b) in enumerate(zip(source.frames(k, n - hout, n + hout), source.frames(k + 1, -hout, hout))): emit(blend(kind, a, b, i, 2 * hout))


def compose(segs, source, fps, emit, progress=None):
    """Emit every frame of the film, in order: emit(image). segs: plan segments (film_start_s, dur_s, transition); returns the number of frames."""
    ps = pieces(segs, fps); total = sum(p['frames'] for p in ps); done = 0
    for p in ps:
        render_piece(p, segs, source, emit); done += p['frames']
        if progress: progress(done, total)
    return done
