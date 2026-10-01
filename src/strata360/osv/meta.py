"""Clip-level facts from an OSV: device identity, colour mode, calibration presence (from the first djmd packet), and frame timing."""
import struct
import numpy as np
from strata360.osv.pbdump import parse, first_packet
from strata360.osv.calib import read_slots

COLOUR_MODES = {0: 'normal', 9: 'hlg', 19: 'dlogm'}      # StreamMeta.4 (README 2.1; codes from OpenOSV's FORMAT.md)


def header(osv, djmd_stream=3):
    """Device, colour mode and calibration facts. Fields that cannot be decoded are None, never guessed."""
    pk = first_packet(osv, djmd_stream); top = {f: v for f, w, v in parse(pk) if w == 2}
    out = dict(device=None, firmware=None, serial=None, proto=None, colour_mode='unknown', colour_mode_raw=None, calibration_slots=0)
    if 1 in top:                                                        # header message: field 1 holds the device block
        outer = {f: v for f, w, v in parse(top[1]) if w == 2}
        h = {f: v for f, w, v in parse(outer[1])} if 1 in outer else {}
        dec = lambda b: b.decode('ascii', 'replace') if isinstance(b, (bytes, bytearray)) else None
        out.update(proto=dec(h.get(1)), device=dec(h.get(10)), firmware=dec(h.get(6)), serial=dec(h.get(5)))
    if 2 in top:                                                        # StreamMeta
        sm = parse(top[2])
        for f, w, v in sm:
            if f == 4:                                                  # colour mode: absent/empty message = default 0 = Normal
                raw = 0
                if w == 0: raw = v
                elif w == 2 and len(v):
                    inner = parse(v); raw = next((iv for _, iw, iv in inner if iw == 0), 0)
                out['colour_mode_raw'] = int(raw); out['colour_mode'] = COLOUR_MODES.get(int(raw), f'unknown({raw})')
                break
        else: out['colour_mode'] = 'normal'; out['colour_mode_raw'] = 0
    try:
        sl = read_slots(osv, djmd_stream); out['calibration_slots'] = sum(1 for d in sl.values() if d.get(1, 0) != 0)
    except Exception: pass
    return out


def frame_gaps(pts):
    """Dropped-frame gaps from source frame timestamps: [(frame_index, t_s, missing_frames)] and the nominal frame interval."""
    pts = np.asarray(pts); dt = np.diff(pts); nominal = float(np.median(dt))
    gaps = [(int(i), round(float(pts[i]), 4), int(round(dt[i] / nominal)) - 1) for i in np.where(dt > 1.5 * nominal)[0]]
    return gaps, nominal
