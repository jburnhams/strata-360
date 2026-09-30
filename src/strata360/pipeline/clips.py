"""Clip discovery and identity. A clip is one camera recording (for the DJI Osmo 360: an .OSV file with an optional .LRF proxy).

Other cameras plug in here later (Insta360 .insv pairs need their own adapter); unsupported files are reported, not silently ignored."""
import hashlib, os, re
from dataclasses import dataclass, field

SUPPORTED = {'.osv'}                      # camera recordings this pipeline can process
KNOWN_OTHER = {'.insv': 'Insta360 (adapter not written yet)', '.mp4': 'flat video (an export, not a camera original)', '.lrf': 'proxy (paired automatically)',
               '.thm': 'thumbnail', '.jpg': 'photo', '.dng': 'photo', '.insp': 'Insta360 photo'}


@dataclass
class Clip:
    id: str
    osv: str
    lrf: str = None
    size: int = 0
    fingerprint: str = ''
    filename_time: str = None             # timestamp encoded in the file name (DJI: CAM_YYYYMMDDHHMMSS_NNNN_D), as written

    def to_dict(self): return dict(id=self.id, osv=self.osv, lrf=self.lrf, size_bytes=self.size, fingerprint=self.fingerprint, filename_time=self.filename_time)


def fingerprint(path, block=1 << 20):
    """Cheap content identity: size plus the first and last MiB. Enough to tell clips apart and to notice a changed file."""
    size = os.path.getsize(path); h = hashlib.sha1(str(size).encode())
    with open(path, 'rb') as f:
        h.update(f.read(block)); f.seek(max(size - block, 0)); h.update(f.read(block))
    return h.hexdigest()[:12]


def parse_filename_time(stem):
    m = re.match(r'CAM_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_\d+_\w', stem)
    return f'{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}' if m else None


def discover(library):
    """(clips, unsupported): clips sorted by id; unsupported = [(path, reason)] for files that are not camera recordings we handle."""
    clips, other, lrf = [], [], {}
    for root, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if d != 'strata360']                  # our own results folder is not footage
        for fn in sorted(files):
            p = os.path.join(root, fn); ext = os.path.splitext(fn)[1].lower()
            if fn.startswith('.'): continue                            # macOS resource forks and hidden files
            if ext == '.lrf': lrf[os.path.splitext(fn)[0]] = p
            elif ext in SUPPORTED: clips.append(p)
            elif ext in KNOWN_OTHER or True: other.append((p, KNOWN_OTHER.get(ext, 'unknown file type')))
    out = []
    for p in sorted(clips):
        stem = os.path.splitext(os.path.basename(p))[0]
        out.append(Clip(id=stem, osv=p, lrf=lrf.get(stem), size=os.path.getsize(p), fingerprint=fingerprint(p), filename_time=parse_filename_time(stem)))
    ids = [c.id for c in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes: raise RuntimeError(f'duplicate clip names in {library}: {sorted(dupes)} (two cards with the same numbering?): give each card its own sub-folder and race')
    return out, [(p, r) for p, r in other if os.path.splitext(p)[1].lower() != '.lrf']
