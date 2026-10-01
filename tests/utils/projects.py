"""Builders for on-disk projects (`<footage>/strata360/...`) so tests don't repeat the folder layout. Use through the `make_project` / `project` fixtures."""
import json, os
from dataclasses import dataclass
from pathlib import Path

CLIP_ID = 'CAM_20260221120007_0019_D'


@dataclass
class Project:
    folder: str                      # the footage folder (what the GUI and `config.race_dir` call the project)
    race_dir: str                    # <folder>/strata360
    def clip_dir(self, clip_id=CLIP_ID): return os.path.join(self.race_dir, 'clips', clip_id)
    def path(self, *parts): return os.path.join(self.race_dir, *parts)
    def write_json(self, rel, obj):
        p = self.path(rel); os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(obj, open(p, 'w')); return p
    def read_json(self, rel): return json.load(open(self.path(rel)))
    def add_clip(self, clip_id=CLIP_ID, start_utc='2026-02-21T12:00:07+00:00', source_frames=300, fps=30.0, **files):
        """clip.json plus any extra per-clip files: `add_clip(motion={'summary': {'steady': .8}}, candidates={...})` writes motion.json, candidates.json."""
        d = self.clip_dir(clip_id); os.makedirs(d, exist_ok=True)
        json.dump(dict(clip_id=clip_id, time=dict(start_utc=start_utc), video=dict(source_frames=source_frames, nominal_fps=fps)), open(os.path.join(d, 'clip.json'), 'w'))
        for name, obj in files.items(): json.dump(obj, open(os.path.join(d, name + '.json'), 'w'))
        return d


def make_project(base, name='trip', *, config=None, footage=('CAM_20260221120007_0019_D.OSV',), clips=()):
    """A project folder under `base` (a tmp_path): footage placeholder files (so the folder counts as having camera files), race.json when `config` is given
    (a dict, or True for the defaults' minimum), and one clip dir per id in `clips`."""
    folder = Path(base, name).resolve(); folder.mkdir(parents=True, exist_ok=True)
    for f in footage: (folder / f).write_bytes(b'x')
    p = Project(str(folder), str(folder / 'strata360'))
    if config is not None:
        p.write_json('race.json', {} if config is True else config)
    for c in clips: p.add_clip(c)
    return p
