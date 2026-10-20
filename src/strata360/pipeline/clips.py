"""Clip discovery and identity. A clip is one camera recording: for the DJI Osmo 360 an .OSV file with an optional .LRF proxy; for an Insta360 (X3 and the like) a pair of .insv files, one a lens
(`..._00_NNN.insv` the rear lens, which carries the metadata and is the clip's primary file, `..._10_NNN.insv` the front lens) with an optional `LRV_..._11_NNN.lrv` proxy (osv/insta360.py).
The camera is told from the files, so a folder can hold either. Unsupported files are reported, not silently ignored."""
import hashlib, os, re
from strata360.osv.mp4 import cut_short
from dataclasses import dataclass, field

SUPPORTED = {'.osv'}                      # camera recordings this pipeline can process (an .insv pair is recognised by `_pairs`)
KNOWN_OTHER = {'.insv': 'Insta360 lens file without its partner', '.mp4': 'flat video (an export, not a camera original)', '.lrf': 'proxy (paired automatically)', '.lrv': 'proxy (paired automatically)',
               '.thm': 'thumbnail', '.jpg': 'photo', '.dng': 'photo', '.insp': 'Insta360 photo', '.gpx': 'GPS track (give it to the race as its track; footage folders are not searched for one)',
               '.fit': 'GPS track (give it to the race as its track; footage folders are not searched for one)', '.insproj': 'Insta360 Studio project', '.wav': 'audio recording'}
NO_INDEX = "recording cut short (no MP4 index; the battery or card probably ran out): repair it in the camera maker's app (Insta360 Studio, DJI Studio) to use it"
_INSV = re.compile(r'^(?P<kind>VID|PRO)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<lens>\d{2})_(?P<n>\d{3})$', re.I)


@dataclass
class Clip:
    id: str
    osv: str
    lrf: str = None
    size: int = 0
    fingerprint: str = ''
    filename_time: str = None             # timestamp encoded in the file name (DJI: CAM_YYYYMMDDHHMMSS_NNNN_D; Insta360: VID_YYYYMMDD_HHMMSS_00_NNN), as written

    def to_dict(self): return dict(id=self.id, osv=self.osv, lrf=self.lrf, size_bytes=self.size, fingerprint=self.fingerprint, filename_time=self.filename_time)


def fingerprint(path, block=1 << 20):
    """Cheap content identity: size plus the first and last MiB. Enough to tell clips apart and to notice a changed file."""
    size = os.path.getsize(path); h = hashlib.sha1(str(size).encode())
    with open(path, 'rb') as f:
        h.update(f.read(block)); f.seek(max(size - block, 0)); h.update(f.read(block))
    return h.hexdigest()[:12]


def parse_filename_time(stem):
    m = re.match(r'CAM_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_\d+_\w', stem)
    if m: return f'{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}'
    m = _INSV.match(stem)
    return f'{m["date"][:4]}-{m["date"][4:6]}-{m["date"][6:]}T{m["time"][:2]}:{m["time"][2:4]}:{m["time"][4:]}' if m else None


def _pairs(insv, lrv):
    """Insta360 recordings from the .insv files found: ([Clip], [(path, reason)]). A recording is the rear-lens file (_00_) with the front-lens file (_10_) of the same number; a lone file is reported."""
    by = {}
    for p in insv:
        m = _INSV.match(os.path.splitext(os.path.basename(p))[0])
        if m: by.setdefault((os.path.dirname(p), m['kind'].upper(), m['date'], m['time'], m['n']), {})[m['lens']] = p
        else: by.setdefault(('?', p), {})['??'] = p
    clips, odd = [], []
    for key, lens in sorted(by.items()):
        if '00' in lens and '10' in lens and (cut_short(lens['00']) or cut_short(lens['10'])):
            odd += [(p, NO_INDEX) for p in lens.values()]
        elif '00' in lens and '10' in lens:
            d, kind, date, time_, n = key; stem = f'{kind}_{date}_{time_}_{n}'; rear, front = lens['00'], lens['10']
            clips.append(Clip(id=stem, osv=rear, lrf=lrv.get(f'LRV_{date}_{time_}_11_{n}'), size=os.path.getsize(rear) + os.path.getsize(front),
                              fingerprint=hashlib.sha1((fingerprint(rear) + fingerprint(front)).encode()).hexdigest()[:12], filename_time=parse_filename_time(f'{kind}_{date}_{time_}_00_{n}')))
        else:
            for l, p in lens.items(): odd.append((p, 'Insta360 lens file without its partner (needs both _00_ and _10_)' if l in ('00', '10') else 'Insta360 file with an unknown name'))
    return clips, odd


def discover(library):
    """(clips, unsupported): clips sorted by id; unsupported = [(path, reason)] for files that are not camera recordings we handle."""
    clips, other, lrf, insv = [], [], {}, []
    for root, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if d != 'strata360']                  # our own results folder is not footage
        for fn in sorted(files):
            p = os.path.join(root, fn); ext = os.path.splitext(fn)[1].lower()
            if fn.startswith('.'): continue                            # macOS resource forks and hidden files
            if ext in ('.lrf', '.lrv'): lrf[os.path.splitext(fn)[0]] = p
            elif ext == '.insv': insv.append(p)
            elif ext in SUPPORTED: clips.append(p)
            elif ext in KNOWN_OTHER or True: other.append((p, KNOWN_OTHER.get(ext, 'unknown file type')))
    out = []
    for p in sorted(clips):
        if cut_short(p): other.append((p, NO_INDEX)); continue
        stem = os.path.splitext(os.path.basename(p))[0]
        out.append(Clip(id=stem, osv=p, lrf=lrf.get(stem), size=os.path.getsize(p), fingerprint=fingerprint(p), filename_time=parse_filename_time(stem)))
    pc, odd = _pairs(insv, lrf); out += pc; other += odd; out.sort(key=lambda c: c.id)
    ids = [c.id for c in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes: raise RuntimeError(f'duplicate clip names in {library}: {sorted(dupes)} (two cards with the same numbering?): give each card its own sub-folder and race')
    return out, [(p, r) for p, r in other if os.path.splitext(p)[1].lower() not in ('.lrf', '.lrv')]
