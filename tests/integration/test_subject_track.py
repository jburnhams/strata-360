"""The between-detections tracker follows a moving textured patch through a real (synthetic) video, and blends the forward and backward tracks through both detections (analysis/subject_track.py)."""
import numpy as np, cv2
from strata360.analysis import subject_track as ST

W, H = 960, 480


def scene(n, path):
    """n gray equirect-shaped frames: a textured background and a textured patch at path(k) = (x, y) pixels."""
    rng = np.random.default_rng(3); bg = (rng.random((H, W)) * 120 + 40).astype(np.uint8); bg = cv2.GaussianBlur(bg, (0, 0), 1.5); patch = (rng.random((60, 30)) * 255).astype(np.uint8); out = []
    for k in range(n):
        f = bg.copy(); x, y = path(k); x0, y0 = int(round(x)) - 15, int(round(y)) - 30
        xs = np.arange(x0, x0 + 30) % W; f[y0:y0 + 60, xs[:, None].T[0]] = patch; out.append(f)
    return out


def test_it_follows_a_patch_between_two_detections_and_passes_through_both():
    path = lambda k: (480 + 12 * np.sin(k * 0.5), 240 + 6 * np.cos(k * 0.35)); frames = scene(26, path)                                    # a patch that bobs about a few degrees
    anchors = [(0, *ST.to_deg(*path(0), W, H), 60.0), (25, *ST.to_deg(*path(25), W, H), 60.0)]; yaw, pitch = ST.track_positions(frames, anchors)
    truth = np.array([ST.to_deg(*path(k), W, H) for k in range(26)])
    assert np.nanmax(np.abs(yaw - truth[:, 0])) < 1.5 and np.nanmax(np.abs(pitch - truth[:, 1])) < 1.5                       # within a degree and a half of the real path at every frame
    assert abs(yaw[0] - truth[0, 0]) < 1e-6 and abs(yaw[25] - truth[25, 0]) < 1e-6                                            # exactly the detections at the detections


def test_it_works_across_the_wrap_around_edge_of_the_picture():
    path = lambda k: (W - 8 + 1.2 * k, 250); frames = scene(21, path)                                                          # the patch crosses the right edge into the left
    anchors = [(0, *ST.to_deg(*path(0), W, H), 60.0), (20, *ST.to_deg(path(20)[0] % W, path(20)[1], W, H), 60.0)]; yaw, pitch = ST.track_positions(frames, anchors)
    truth = np.array([ST.to_deg(path(k)[0] % W, path(k)[1], W, H)[0] for k in range(21)]); err = ((yaw - truth + 180) % 360) - 180
    assert np.nanmax(np.abs(err)) < 2.0


def test_the_blend_and_the_geometry():
    fwd = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]); bwd = np.array([[2.0, 0.0], [1.5, 0.0], [0.5, 0.0]])             # from the second detection backwards
    b = ST.blend(fwd, bwd); assert b[0].tolist() == [0.0, 0.0] and b[-1].tolist() == [2.0, 0.0] and b[1][0] == 1.25
    x, y = ST.to_px(0.0, 0.0, 3840, 1920); assert (x, y) == (1920.0, 960.0); assert ST.to_deg(1920.0, 960.0, 3840, 1920) == (0.0, 0.0)
