"""edit/photo_motion.py write_video: the move over a photo as a real H.264 file (needs ffmpeg with libx264)."""
import shutil, subprocess

import numpy as np
import pytest

from strata360.edit import photo_motion as PM

pytestmark = pytest.mark.skipif(shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None, reason='needs ffmpeg')


def test_the_move_is_written_as_a_video_of_the_right_size_and_length(tmp_path):
    img = np.zeros((800, 1200, 3), np.uint8); img[:, 600:] = (40, 160, 90); img[300:400, 900:1000] = 255
    pl = PM.plan((1200, 800), 2.0, 'push_in', [dict(cx=0.78, cy=0.44, w=0.08, h=0.12, weight=1.0, label='you')], seed=1); out = str(tmp_path / 'move.mp4')
    assert PM.write_video(out, img, pl, (320, 180), fps=25) == 50
    info = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=codec_name,width,height,nb_read_frames', '-of', 'csv=p=0', out], capture_output=True, text=True).stdout.strip().split(',')
    assert info[:3] == ['h264', '320', '180'] and int(info[3]) == 50


def test_ffmpeg_failing_is_reported_not_swallowed(tmp_path):
    pl = PM.plan((1200, 800), 1.0, 'hold')
    with pytest.raises(RuntimeError, match='ffmpeg failed'): PM.write_video(str(tmp_path / 'no' / 'such' / 'dir' / 'x.mp4'), np.zeros((800, 1200, 3), np.uint8), pl, (320, 180))
