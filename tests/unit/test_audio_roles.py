"""Which sound a window of the film uses: the voice only where the script plays the runner's lines."""
import os
from strata360.render import preview as PV
from projects import CLIP_ID


def test_dialogue_windows_use_the_cleaned_voice_and_narration_and_b_roll_use_only_the_background(project):
    d = project.add_clip(CLIP_ID)
    for n in ('audio_clean.flac', 'audio_original.flac'): open(os.path.join(d, n), 'wb').write(b'x')
    f = project.folder
    assert PV.audio_of(f, CLIP_ID, 'clip').endswith('audio_clean.flac')
    assert PV.audio_of(f, CLIP_ID, 'vo') is None and PV.audio_of(f, CLIP_ID, 'broll') is None                       # no background track yet: no sound of its own, never the voice
    open(os.path.join(d, 'audio_background.flac'), 'wb').write(b'x')
    assert PV.audio_of(f, CLIP_ID, 'vo').endswith('audio_background.flac') and PV.audio_of(f, CLIP_ID, 'broll').endswith('audio_background.flac')


def test_windows_of_a_beat_planner_plan_keep_the_old_rule(project):
    d = project.add_clip(CLIP_ID); open(os.path.join(d, 'audio_clean.flac'), 'wb').write(b'x')
    assert PV.audio_of(project.folder, CLIP_ID).endswith('audio_clean.flac') and PV.audio_of(project.folder, CLIP_ID, None).endswith('audio_clean.flac')
