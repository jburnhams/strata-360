"""How a clip's video is opened, whatever camera made it.

The pipeline calls a clip's primary file its `osv` (the name is from the first supported camera). For a DJI .OSV both lens streams are in that one file (stream 1 = front, stream 0 = rear). For an Insta360 .insv pair
(osv/insta360.py) each lens is its own file and its own single stream. `lens_input` gives the ffmpeg input and map options for one lens either way, so a decoder is written once.
"""
from strata360.osv import insta360


def is_insta360(osv): return insta360.is_insv(osv)


def lens_input(osv, stream):
    """ffmpeg input options that select the video of one lens: stream 1 = front (master), stream 0 = rear."""
    if insta360.is_insv(osv): return ['-i', insta360.lens_file(osv, stream), '-map', '0:v:0']
    return ['-i', osv, '-map', f'0:v:{stream}']


def lens_path(osv, stream):
    """The file that holds one lens's video."""
    return insta360.lens_file(osv, stream) if insta360.is_insv(osv) else osv


def full_frame_filter(osv, native=False):
    """ffmpeg filters (a list, maybe empty) that bring a lens picture to the renderers' lens size, 3840 x 3840, in the range the readers expect: BT.709 limited range for `native` (p010, converted on the GPU), else whatever the
    rgb48 conversion makes of it. DJI lenses already are 3840 x 3840 (10-bit HEVC, limited range); an Insta360 lens is 2880 x 2880, 8-bit, full range."""
    if not insta360.is_insv(osv): return []
    s = 'scale=3840:3840:flags=bicubic'
    return [s + ':in_range=full:out_range=limited:in_color_matrix=bt709:out_color_matrix=bt709' if native else s]
