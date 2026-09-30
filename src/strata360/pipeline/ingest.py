"""Ingest: the facts about one clip, and its definitive UTC time (README 5.1).

`clip.json` is the ONLY place time is decided. Every other artefact stores clip-relative seconds and carries a header copy of
clip_id, start_utc and utc_hash so stale files are detected (see check_header)."""
import datetime as dt, hashlib, json, subprocess
import numpy as np
from strata360.osv.meta import header, frame_gaps
from strata360.osv.mp4 import video_sample_times

SCHEMA_VERSION = 1


def _probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size,format_name:format_tags:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,sample_rate,channels,channel_layout',
        '-of', 'json', path]))


def _parse_iso(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def utc_hash(clip_id, start_utc, end_utc):
    return hashlib.sha1(f'{clip_id}|{start_utc}|{end_utc}'.encode()).hexdigest()[:12]


def ingest_clip(clip, cfg):
    """Build the clip.json body. Nothing here is guessed: what cannot be determined is recorded as None with a note."""
    p = _probe(clip.osv); fmt = p['format']; tags = fmt.get('tags', {})
    vs = [s for s in p['streams'] if s['codec_type'] == 'video' and s.get('codec_name') == 'hevc']
    au = [s for s in p['streams'] if s['codec_type'] == 'audio']
    notes = []
    if len(vs) != 2: notes.append(f'expected two HEVC lens streams, found {len(vs)}')
    pts = video_sample_times(clip.osv); gaps, nominal = frame_gaps(pts)
    nominal_fps = round(1.0 / nominal, 3)
    duration = float(pts[-1] - pts[0]) + nominal
    hdr = header(clip.osv)
    # ---- time (README 6.1): container creation_time is treated as camera clock; the config says how the camera clock relates to UTC
    creation = _parse_iso(tags.get('creation_time'))
    fname = dt.datetime.fromisoformat(clip.filename_time).replace(tzinfo=dt.timezone.utc) if clip.filename_time else None
    clock = cfg['camera_clock']; offset = dt.timedelta(hours=float(clock.get('utc_offset_hours', 0.0)), seconds=float(clock.get('offset_seconds', 0.0)))     # camera clock minus UTC
    if clock.get('drift_s_per_day') and creation is not None:                                        # a clock that gains/loses steadily: offset grows linearly from a reference camera time
        ref = _parse_iso(clock.get('drift_ref_camera_time')) or creation; offset += dt.timedelta(seconds=float(clock['drift_s_per_day']) * (creation - ref).total_seconds() / 86400.0)
    if creation is not None: start, source = creation - offset, 'container_creation_time'
    elif fname is not None: start, source = fname - offset, 'filename'; notes.append('container has no creation_time; used the file name')
    else: start, source = None, 'none'; notes.append('no time source found')
    disagreement = abs((creation - fname).total_seconds()) if (creation and fname) else None
    status = 'definitive' if (start is not None and clock.get('verified') and (disagreement is None or disagreement <= 3.0)) else 'provisional'
    if disagreement is not None and disagreement > 3.0: notes.append(f'container time and file name disagree by {disagreement:.0f} s')
    if not clock.get('verified'): notes.append('camera clock not verified against the GPX or a known event (race.json camera_clock.verified)')
    end = start + dt.timedelta(seconds=duration) if start else None
    ts = lambda d: None if d is None else d.isoformat().replace('+00:00', 'Z')
    return dict(
        schema_version=SCHEMA_VERSION, clip_id=clip.id, fingerprint=clip.fingerprint, source_files=dict(osv=clip.osv, lrf=clip.lrf), size_bytes=clip.size,
        camera=dict(model=hdr['device'] or tags.get('encoder'), serial=hdr['serial'], firmware=hdr['firmware'], proto=hdr['proto']),
        video=dict(streams=len(vs), width=int(vs[0]['width']) if vs else None, height=int(vs[0]['height']) if vs else None, codec='hevc', pix_fmt=vs[0].get('pix_fmt') if vs else None,
                   nominal_fps=nominal_fps, source_frames=int(len(pts)), dropped_frames=int(sum(g[2] for g in gaps)), gaps=[dict(after_frame=g[0], t_s=g[1], missing=g[2]) for g in gaps]),
        audio=dict(present=bool(au), channels=int(au[0]['channels']) if au else None, sample_rate=int(au[0]['sample_rate']) if au else None, codec=au[0]['codec_name'] if au else None),
        colour_mode=hdr['colour_mode'], colour_mode_raw=hdr['colour_mode_raw'], calibration_slots=hdr['calibration_slots'], gps_in_metadata=False,
        duration_s=round(duration, 3),
        time=dict(start_utc=ts(start), end_utc=ts(end), utc_status=status, utc_source=source, utc_hash=utc_hash(clip.id, ts(start), ts(end)),
                  container_creation_time=ts(creation), filename_time=clip.filename_time, container_vs_filename_s=disagreement,
                  camera_clock_utc_offset_hours=float(clock.get('utc_offset_hours', 0.0)), camera_clock_offset_seconds=float(clock.get('offset_seconds', 0.0)), camera_clock_verified=bool(clock.get('verified'))),
        notes=notes)


def check_header(clip_json, artefact):
    """Downstream artefacts must carry the clip's clip_id and utc_hash; a mismatch means the artefact is stale (the time changed)."""
    if artefact.get('clip_id') != clip_json['clip_id'] or artefact.get('utc_hash') != clip_json['time']['utc_hash']:
        raise ValueError(f"stale artefact for {clip_json['clip_id']}: header {artefact.get('clip_id')}/{artefact.get('utc_hash')} != clip.json {clip_json['time']['utc_hash']}")


def stamp(clip_json, artefact):
    """Add the read-only time header to an artefact (times inside it stay clip-relative)."""
    artefact = dict(artefact); artefact['clip_id'] = clip_json['clip_id']; artefact['start_utc'] = clip_json['time']['start_utc']; artefact['utc_hash'] = clip_json['time']['utc_hash']
    return artefact


def restamp(clip_dir):
    """After the camera clock changed: update the time header (start_utc, utc_hash) of every stamped artefact in a clip folder. The data inside is clip-relative, so nothing is recomputed."""
    import glob, json, os
    cj = json.load(open(os.path.join(clip_dir, 'clip.json'))); n = 0
    for f in glob.glob(os.path.join(clip_dir, '*.json')):
        if os.path.basename(f) in ('clip.json', 'stages.json'): continue
        try: d = json.load(open(f))
        except ValueError: continue
        if isinstance(d, dict) and 'utc_hash' in d:
            d['start_utc'] = cj['time']['start_utc']; d['utc_hash'] = cj['time']['utc_hash']; json.dump(d, open(f + '.tmp', 'w')); os.replace(f + '.tmp', f); n += 1
    return n
