"""On-disk helpers for integration tests: libraries of synthetic OSVs, copying a finished project, and small ffmpeg media. All fast (a 60-frame clip builds in 0.2 s)."""
import json, os, shutil, subprocess
from pathlib import Path


def osv_name(i=0, start='20260221120007', gap_s=60):
    """CAM_<yyyymmddHHMMSS>_<seq>_D.OSV: clip `i` starts `gap_s` seconds after clip 0 (camera file names carry the start time)."""
    import datetime as dt
    t = dt.datetime.strptime(start, '%Y%m%d%H%M%S') + dt.timedelta(seconds=gap_s * i)
    return f'CAM_{t:%Y%m%d%H%M%S}_{19 + i:04d}_D.OSV'


def make_library(base, n=1, name='trip', junk=True, frames=60, drop=(30, 31), start='20260221120007', gap_s=60):
    """A footage folder `base/name` holding `n` distinct synthetic clips (each built in ~0.2 s; clip i starts `gap_s` seconds after clip 0, in its file name and its header), plus a
    hidden file and a text file that must be ignored. Needs ffmpeg with libx265 (use through a fixture that depends on `synthetic_osv`, which skips when it is missing)."""
    from synthetic_osv import build_osv
    import datetime as dt
    lib = Path(base, name); lib.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        t = dt.datetime.strptime(start, '%Y%m%d%H%M%S') + dt.timedelta(seconds=gap_s * i)
        build_osv(str(lib / osv_name(i, start, gap_s)), frames=frames, drop=drop, name_time=f'{t:%Y%m%d%H%M%S}')
    if junk: (lib / '.hidden').write_text('x'); (lib / 'notes.txt').write_text('not a clip')
    return str(lib)


def copy_project(src, dst):
    """Copy a footage folder with its finished `strata360/` results to `dst`, rewriting the absolute paths the results contain (race.json, catalog.json, clip.json) to the new place."""
    src, dst = str(src), str(dst); shutil.copytree(src, dst)
    for root, _, files in os.walk(os.path.join(dst, 'strata360')):
        for f in files:
            if f.endswith('.json'):
                p = os.path.join(root, f); s = open(p).read()
                if src in s: open(p, 'w').write(s.replace(src, dst))
    return dst


def ffprobe(path):
    """`ffprobe -show_format -show_streams` as a dict."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def make_tone(path, seconds=1.0, hz=440, rate=48000, channels=1):
    """A sine-wave WAV made with ffmpeg (a stand-in for speech, music or a recording)."""
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={hz}:duration={seconds}', '-ar', str(rate), '-ac', str(channels), str(path)], check=True)
    return str(path)


def duration(path): return float(ffprobe(path)['format']['duration'])
