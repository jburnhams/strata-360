"""Which sound a window of the film uses: the voice only where the script plays the runner's lines."""
import os
import pytest
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


def lines(*spec): return [dict(id=f'0001.0{i}', t0=a, t1=b, mark=m) for i, (a, b, m) in enumerate(spec)]


def test_words_marked_never_are_silenced_inside_the_window_with_a_little_padding(project, monkeypatch):
    from strata360.edit import script_pack as SP
    project.add_clip(CLIP_ID); monkeypatch.setattr(SP, 'transcript_lines', lambda cdir, label: lines((12.0, 13.0, 'never'), (14.0, 15.0, 'must'), (30.0, 31.0, 'never'), (9.0, 10.5, 'never')))
    spans = PV.never_spans(project.folder, CLIP_ID, 10.0, 5.0)
    assert spans == [pytest.approx((1.96, 3.04)), pytest.approx((0.0, 0.54))]                                         # in transcript order; the one that starts before the window is cut at its start
    assert PV.never_spans(project.folder, CLIP_ID, 40.0, 5.0) == []


def test_the_mute_filter_silences_each_span_and_is_empty_without_any():
    assert PV.mute_filter([]) == '' and PV.mute_filter([(1.0, 2.5)]) == ",volume=enable='between(t,1.000,2.500)':volume=0"
    assert PV.mute_filter([(0.0, 1.0), (3.0, 4.0)]).count('volume=0') == 2


def test_narration_and_b_roll_windows_have_no_speech_to_silence():
    assert PV.role_has_speech('clip') and PV.role_has_speech(None) and not PV.role_has_speech('vo') and not PV.role_has_speech('broll')
