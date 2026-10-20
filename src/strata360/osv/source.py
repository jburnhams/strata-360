"""How a clip's video is opened, whatever camera made it.

The pipeline calls a clip's primary file its `osv` (the name is from the first supported camera). For a DJI .OSV both lens streams are in that one file (stream 1 = front, stream 0 = rear). For an Insta360 .insv pair
(osv/insta360.py) each lens is its own file and its own single stream. `lens_input` gives the ffmpeg input and map options for one lens either way, so a decoder is written once.
"""
import functools
from strata360.osv import insta360


def is_insta360(osv): return insta360.is_insv(osv)


def camera_id(device, osv):
    """A short name for the camera that made a clip, from its header's device string: 'dji_osmo_360' for the DJI, 'insta360_x3' for an Insta360 X3 (lower case, spaces to underscores)."""
    if not insta360.is_insv(osv): return 'dji_osmo_360'
    d = (device or '').strip().lower(); d = d[len('insta360'):].strip() if d.startswith('insta360') else d
    return 'insta360_' + ('_'.join(d.split()) or 'unknown')


def lens_input(osv, stream):
    """ffmpeg input options that select the video of one lens: stream 1 = front (master), stream 0 = rear."""
    if insta360.is_insv(osv): return ['-i', insta360.lens_file(osv, stream), '-map', '0:v:0']
    return ['-i', osv, '-map', f'0:v:{stream}']


def lens_path(osv, stream):
    """The file that holds one lens's video."""
    return insta360.lens_file(osv, stream) if insta360.is_insv(osv) else osv


@functools.lru_cache(maxsize=64)
def lens_size(osv):
    """Pixels along one side of a lens picture: the lens video's own width (3840 for a DJI Osmo 360, 2880 for an Insta360 X3). Every renderer and analyser works at this size (no resizing to fit)."""
    import json, subprocess
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width', '-of', 'json', lens_path(osv, 0)])
    return int(json.loads(out)['streams'][0]['width'])


def full_frame_filter(osv, native=False):
    """ffmpeg filters (a list, maybe empty) that bring a lens picture, at its own size, into the range the readers expect: BT.709 limited range for `native` (p010, converted on the GPU), else whatever the rgb48 conversion
    makes of it. DJI lenses are 10-bit HEVC, limited range already; an Insta360 lens is 8-bit, full range, so the native path converts it."""
    if not insta360.is_insv(osv) or not native: return []
    return ['scale=in_range=full:out_range=limited:in_color_matrix=bt709:out_color_matrix=bt709']
