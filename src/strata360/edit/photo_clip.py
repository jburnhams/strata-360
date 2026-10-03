"""A photo as a clip of the film (edit/synthetic.py kind `photo`): the pan and zoom (edit/photo_motion.py) rendered to a 4K video of exactly the length the plan gives it, which the film plays like any generated clip (picture only; the overlay goes on top, showing the race as it was when the photo was taken).

`sync(folder, specs)` makes synthetic.json and the videos match the plan's photo clips (`specs` are the plan's `synthetic` entries for labels such as P3): a clip whose photo, length and move are unchanged is left as it is; the others are made again."""
import os

from strata360 import photos as PH
from strata360.edit import photo_motion as PM, synthetic as SY
from strata360.pipeline import config


def is_photo_label(label): return str(label).upper().startswith('P') and str(label)[1:].isdigit()


def render(folder, entry, seconds, motion, path, log=print):
    """Write the move over the photo for `seconds` to `path` (3840x2160, 30 fps). The target is what the analysis found in the photo (`focals`), the style and seed the photo's own settings."""
    from strata360.analysis import photo_analysis as PA
    rd = config.race_dir(folder); src = os.path.join(rd, entry['file']); size = PH.oriented_size(src); img = PA.read_bgr(src, 4000)
    pl = PM.plan(size, seconds, motion['style'], PM.focals(PA.load_doc(rd, entry['id']), PA.read_bgr(src, 480)), motion['seed'], out_w=3840)
    os.makedirs(os.path.dirname(path), exist_ok=True); tmp = path + '.part.mp4'; w, h = (int(x) for x in SY.PHOTO_SIZE.split('x')); n = PM.write_video(tmp, img, pl, (w, h), fps=30.0, crf=17); os.replace(tmp, path)
    log(f"rendered the {pl['style']} move over {entry['id']} for {seconds:g} s ({n} frames)"); return pl


def sync(folder, specs, log=print):
    """Make the clips for the plan's photo entries; returns the clip documents made or kept. A photo the project no longer has is reported and skipped (the plan then shows a card for it)."""
    rd = config.race_dir(folder); photos = {p['id']: p for p in PH.load(rd)['photos']}; docs = {c['id']: c for c in SY.load(folder)['clips']}; out = []
    for sp in specs:
        if not is_photo_label(sp['clip']): continue
        e = photos.get(str(sp['clip']).lower())
        if e is None: log(f"{sp['clip']}: the photo is not in the project any more"); continue
        mo = PH.motion_of(e); sec = round(min(max(float(sp['seconds']), SY.MIN_SECONDS), 45.0), 2); c = SY.make_photo(e, sec, mo); old = docs.get(c['id']); path = os.path.join(rd, 'synthetic', c['id'] + '.mp4'); c['file'] = os.path.join('synthetic', c['id'] + '.mp4')
        if old and old.get('key') == c['key'] and os.path.exists(path): out.append(old); continue
        render(folder, e, sec, mo, path, log); c['status'] = 'ready'; out.append(SY.upsert(folder, c))
    return out
