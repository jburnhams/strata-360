"""One frame of the final film as a still picture, made by the same pipeline as the film (render/final.py): the plan's windows and glides, the camera paths, the two-lens renderer, the exposure match, the map overlay and the transitions.

Which frame: film time `t` (seconds, e.g. the preview player's position) times the film's frame rate (`final.resolve_fps`, the footage's own unless set) gives frame n; `locate` finds the film piece (a plain stretch of one window, or a transition) that holds it.
The piece is rendered from a few frames before n (`WARM`, the seam between the lenses settles over a few frames, as in the film) and the frame n is kept. A transition piece is rendered from its start (the two halves are mixed frame by frame).

  <project>/final/stills/<key>_f<frame>.png      8-bit PNG (the film's 16-bit working values rounded to 8); <key> as for the film at that size, so a changed plan, voice-over or overlay gives a new still

The film's own file is not needed: nothing here reads a finished piece."""
import argparse, datetime as dt, json, os, sys

import cv2
import numpy as np

from strata360.pipeline import config, guard
from strata360.render import final as FN, grade as GR
from strata360.render.film import pieces, render_piece

WARM = 4                                                  # frames rendered before the wanted one inside a plain stretch
SIZES = ('1920x1080', '2560x1440', '3840x2160')


class _Done(Exception):
    """Raised from `emit` to stop a piece once the wanted frame has been made."""


def locate(ps, n):
    """The piece holding film frame n and the frame's place in it: (piece, index in the piece). n is held to the film (0 .. length - 1)."""
    total = sum(p['frames'] for p in ps); n = max(0, min(int(n), total - 1)); start = 0
    for p in ps:
        if n < start + p['frames']: return p, n - start
        start += p['frames']
    raise ValueError('the film has no frames')


def still_dir(folder): return os.path.join(config.race_dir(folder), 'final', 'stills')


def still_name(key, n): return f'{key}_f{n:06d}.png'


def moment_count(length_s):
    """How many moments an automatic series takes: 4 for a film of 2 minutes or less, rising evenly to 10 at 30 minutes and more."""
    return int(min(10, max(4, round(4 + (length_s / 60.0 - 2.0) * 6.0 / 28.0))))


def _tightness(fov):
    return 'unknown' if fov is None else 'tight' if fov < 62 else 'medium' if fov < 80 else 'wide'


def pick_moments(plan, framing, n=None):
    """A series of differing moments through the film for stills: [{t, id, clip, label, why}], in film order.
    The film is cut into `n` (`moment_count` of its length, unless given) equal stretches of time, so the series spreads over the whole film, and in each the shot is taken that adds most that is new to what has been chosen so far: a clip not used yet, a
    tightness (tight under 62 degrees at its narrowest, medium, wide) not used yet, generated or footage; ties go to the shot nearest the middle of the stretch. The moment is the middle of the part of the shot inside the stretch (away from its transitions)."""
    from strata360.render import camera as cam
    segs = [g for g in plan['segments'] if g['dur_s'] > 0]
    if not segs: return []
    length = max(g['film_start_s'] + g['dur_s'] for g in segs); n = n or moment_count(length); edges = [length * i / n for i in range(n + 1)]; out = []; clips, tight, kinds = set(), set(), set()
    def fov_of(g):
        try: return float(min(cam.CameraPath.from_dict(framing[g['id']]).fov))
        except (KeyError, ValueError, TypeError, IndexError): return None
    for i in range(n):
        lo, hi = edges[i], edges[i + 1]; mid = (lo + hi) / 2; best = None
        for g in segs:
            a, b = g['film_start_s'], g['film_start_s'] + g['dur_s']
            if b <= lo or a >= hi: continue
            oa, ob = max(lo, a), min(hi, b); t = (oa + ob) / 2                                                                         # the middle of the part of the shot that is in the stretch (the shot's own middle when it is all inside)
            fov = fov_of(g); kind = 'generated' if g.get('synthetic') else 'footage'
            new = (g.get('clip') not in clips) + (_tightness(fov) not in tight) + (kind not in kinds); score = new - abs(t - mid) / max(hi - lo, 1e-6) * 0.5
            if best is None or score > best[0]: best = (score, g, t, fov, kind, new)
        if best is None: continue
        _, g, t, fov, kind, new = best; clips.add(g.get('clip')); tight.add(_tightness(fov)); kinds.add(kind)
        out.append(dict(t=round(t, 2), id=g['id'], clip=g.get('clip'), label=f"{kind}, {_tightness(fov)}" + (f' ({fov:.0f}\u00b0)' if fov is not None else ''), why=f"clip {str(g.get('clip'))[-9:]}" + (', new to the series' if new else ', nearest the middle of its stretch')))
    return out


def frame_for(plan, t, fps):
    """The film frame at time t seconds, held to the film."""
    ends = [int(round((g['film_start_s'] + g['dur_s']) * fps)) for g in plan['segments']]; return max(0, min(int(round(float(t) * fps)), (ends[-1] if ends else 1) - 1))


def to_png_array(img):
    """BGR 8-bit from the renderer's RGB picture (uint16 code values over the full range, or already 8-bit)."""
    a = np.asarray(img)
    if a.dtype != np.uint8: a = np.clip((a.astype(np.uint32) + 128) >> 8, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(a[..., ::-1])


def progress_path(out): return out + '.progress.json'
def meta_path(out): return out + '.json'


def write_meta(out, meta):
    tmp = meta_path(out) + '.part'; json.dump(meta, open(tmp, 'w'), indent=1); os.replace(tmp, meta_path(out))


def read_meta(out):
    """The metadata kept beside a still (when, how and from what it was made), or None for one made before they were kept."""
    try: return json.load(open(meta_path(out)))
    except (OSError, ValueError): return None


def shot_fov(framing, g):
    """The narrowest field of view (degrees) on a shot's camera path, or None."""
    from strata360.render import camera as cam
    try: return round(float(min(cam.CameraPath.from_dict(framing[g['id']]).fov)), 1)
    except (KeyError, ValueError, TypeError, IndexError): return None


def render_still(folder, plan, framing, t, size=(3840, 2160), fps=50.0, out=None, upscale='off', pg=None, min_zoom=None):
    """Render the film's frame at time `t` at `size`; returns the path of the PNG (an existing one for the same plan, size, frame and upscaling is returned at once). `upscale`: a mode of edit/upscale.py (off, 1080p, 1440p, full): enlarge the shot with the local model if it needs it, as the film does.
    What it is doing and how long each step takes goes to `pg` (render/progress.py; default a file beside the picture, which the page shows)."""
    from strata360.edit import pans as PN, upscale as UP
    from strata360.render.progress import Progress
    W, H = size; key = FN.final_key(plan, [W, H], fps, '100M', folder, upscale, min_zoom); n0 = frame_for(plan, t, fps)
    out = out or os.path.join(still_dir(folder), still_name(key, n0))
    if os.path.exists(out): return out
    pg = pg or Progress(progress_path(out)); got = []
    try:
        with pg.stage('prepare', 'glides, exposure match, overlay'):
            plan = dict(plan, segments=PN.apply_pans(plan['segments'], framing, scorer=PN.looker(folder))[0]); segs = plan['segments']; ps = pieces(segs, fps); piece, j = locate(ps, n0)
            from strata360.overlay import for_project
            src = FN.FinalSource(folder, segs, framing, W, H, fps, overlay=for_project(folder, (W, H)), gains=GR.gains_for(folder, segs, framing), upscale=upscale, up_min_zoom=min_zoom, progress=pg)
            piece_kind = piece['kind']; shots = [piece['k']] + ([piece['k'] + 1] if piece['kind'] != 'plain' else []); factors = [src.shot_factor(segs[k]) for k in shots]
            pg.note(f"frame {n0} of the film: {piece['kind']} piece, shot{'s' if len(shots) > 1 else ''} " + ', '.join(segs[k]['id'] for k in shots))
        with guard.heavy('final still', 4.0):
            if max(factors) > 1:
                with pg.stage('load model', UP.MODEL): UP.load()
            if piece['kind'] == 'plain':                                                                                           # the stretch from a few frames before the wanted one
                first = max(0, j - WARM); piece = dict(piece, a0=piece['a0'] + first, a1=piece['a0'] + j + 1, frames=j - first + 1); j = j - first; src.last_only = True                    # the warm-up frames are thrown away: no enlarging, grading or overlay for them
            def emit(img):
                got.append(img); pg.detail(f'frame {len(got)} of {j + 1}')
                if len(got) > j: raise _Done()
            with pg.stage('render', f'frame 0 of {j + 1}'):
                try: render_piece(piece, segs, src, emit)
                except _Done: pass
        if len(got) <= j: raise RuntimeError(f'the film has no frame {n0}')
        with pg.stage('write', os.path.basename(out)):
            os.makedirs(os.path.dirname(out), exist_ok=True); tmp = out + '.part.png'; cv2.imwrite(tmp, to_png_array(got[j])); os.replace(tmp, out)
        pg.finish(); doc = pg.doc()
        write_meta(out, dict(schema=1, name=os.path.basename(out), key=key, t=round(float(t), 3), frame=n0, fps=fps, size=[W, H], upscale=UP.normalize(upscale), model=UP.MODEL if UP.normalize(upscale) != 'off' else None, piece=piece_kind,
                             shots=[dict(id=segs[k]['id'], clip=segs[k].get('clip'), fov=shot_fov(framing, segs[k]), factor=src.shot_factor(segs[k]), note=src.why.get(segs[k]['id'], '')) for k in shots],
                             rendered=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), seconds=round(doc['updated'] - doc['started'], 1), stages={x['name']: x['seconds'] for x in doc['stages']}, timings={k: v['seconds'] for k, v in doc['timings'].items()}))
        return out
    except BaseException as e:
        if pg.state == 'running': pg.fail(e)
        raise


def main():
    from strata360.edit import framing as FR, project as PJ
    ap = argparse.ArgumentParser(); ap.add_argument('folder'); ap.add_argument('--t', type=float, required=True, action='append', help='film time in seconds (the preview player position); give it more than once to render several stills one after the other in this process'); ap.add_argument('--size', default='3840x2160', choices=SIZES)
    ap.add_argument('--fps', type=float, default=0.0, help="frames a second the film is made at; 0 (the default) is the footage's own rate"); ap.add_argument('--half-rate', action='store_true'); ap.add_argument('--out'); ap.add_argument('--upscale-min-zoom', type=float, default=None, help='enlarge a shot only if more than 0.5 s of it need at least this zoom (default: the film setting)'); ap.add_argument('--upscale', nargs='?', const='full', default='off', choices=['off', '1080p', '1440p', 'full'], help='enlarge the shot with the local model if it holds too few pixels, as the film does: to the output size, or to 1080p / 1440p and then resample'); a = ap.parse_args()
    from strata360 import oslib; oslib.lower_priority(19)
    plan = PJ.load(a.folder).get('plan')
    if not plan: sys.exit('no plan yet')
    W, H = map(int, a.size.split('x')); fr = FR.resolve(a.folder, plan, head=True); fps = FN.resolve_fps(a.folder, plan, a.fps, a.half_rate)
    failed = 0
    for t in a.t:                                                                                                      # one after the other: the model and the clips' data stay loaded between them
        try: print(render_still(a.folder, plan, fr, t, (W, H), fps, a.out if len(a.t) == 1 else None, upscale=a.upscale, min_zoom=a.upscale_min_zoom), flush=True)
        except Exception as e: failed += 1; print(f'still at {t:g} s failed: {e}', flush=True)                       # (its progress file says why; the next one still gets its turn)
    if failed: sys.exit(1)


if __name__ == '__main__': main()
