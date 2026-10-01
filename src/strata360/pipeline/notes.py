"""User notes: one for the whole folder (the race: what it was, who was there, the story) and one per clip (what happened, names, places, how it felt).

Stored as `<project>/notes.json` = {"folder": "text", "clips": {"CAM_..._0004_D": "text"}, "updated": {...}}. They are plain text, edited in the GUI, and are fed (with the transcript
and the per-clip data) to the voice-over script writer (`edit/script.py`).

Beside each note is a "voice-over MUST INCLUDE" field, one piece of narration per line: `vo_must` = {"folder": "text", "folder_ordered": true, "clips": {"CAM_..._0004_D": "text"}}. Each line of a clip's field must be spoken inside that clip's run
of the film; each line of the folder's field must be spoken somewhere (in the order written when `folder_ordered`, else in any order). They become pins for the script writer (edit/script_pins.py)."""
import datetime as dt, json, os
from strata360.pipeline import config


def _path(folder):
    return os.path.join(config.race_dir(folder), 'notes.json')


def load(folder):
    p = _path(folder)
    if os.path.exists(p):
        try: d = json.load(open(p))
        except ValueError: d = {}
    else: d = {}
    d.setdefault('folder', ''); d.setdefault('clips', {}); d.setdefault('updated', {}); vo = d.setdefault('vo_must', {}); vo.setdefault('folder', ''); vo.setdefault('folder_ordered', True); vo.setdefault('clips', {}); return d


def save(folder, text, clip=None):
    """Set the folder note (clip=None) or one clip's note; an empty text removes a clip's note. Returns the notes."""
    d = load(folder); now = dt.datetime.now().isoformat(timespec='seconds'); text = str(text)[:20000]
    if clip is None: d['folder'] = text; d['updated']['folder'] = now
    elif text.strip(): d['clips'][clip] = text; d['updated'][clip] = now
    else: d['clips'].pop(clip, None); d['updated'].pop(clip, None)
    os.makedirs(config.race_dir(folder), exist_ok=True); p = _path(folder)
    json.dump(d, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p); return d


def save_vo(folder, text, clip=None, ordered=None):
    """Set the folder's voice-over MUST INCLUDE text (clip=None; `ordered` says whether its lines keep the order written) or one clip's; an empty clip text removes it. Returns the notes."""
    d = load(folder); text = str(text)[:20000]; vo = d['vo_must']
    if clip is None:
        vo['folder'] = text
        if ordered is not None: vo['folder_ordered'] = bool(ordered)
    elif text.strip(): vo['clips'][clip] = text
    else: vo['clips'].pop(clip, None)
    os.makedirs(config.race_dir(folder), exist_ok=True); p = _path(folder)
    json.dump(d, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p); return d
