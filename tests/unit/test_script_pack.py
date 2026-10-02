"""edit/script_pack.py: clip labels (camera clips by number, generated clips by name) and how a generated clip appears in the writer's context."""
import pytest
from strata360.edit import script_pack as SP, synthetic as SY


@pytest.mark.parametrize('x,want', [(23, '0023'), ('23', '0023'), ('0023', '0023'), (' g03 ', 'G03'), ('G03', 'G03'), (None, ''), ('', '')])
def test_labels_pad_numbers_and_upper_case_names(x, want): assert SP.norm_label(x) == want


def test_only_rendered_generated_clips_enter_the_pack_with_their_race_facts(tmp_path, monkeypatch):
    gap = dict(id='G02', t0=1_771_754_000.0, t1=1_771_754_000.0 + 5400); a = SY.make(gap, seconds=8.0); b = SY.make(dict(gap, id='G03'), seconds=8.0)
    monkeypatch.setattr(SY, 'load', lambda folder: dict(clips=[dict(a, status='ready', file='synthetic/G02.mp4'), dict(b, status='planned')]))
    out = SP.synthetic_clips('x', None, 'UTC'); assert [c['label'] for c in out] == ['G02'] and out[0]['synthetic'] and out[0]['duration_s'] == 8.0 and out[0]['lines'] == [] and out[0]['race_s'] == 5400.0


def test_the_prompt_text_says_there_is_no_footage_and_no_words():
    c = dict(label='G02', clip='G02', duration_s=8.0, usable_s=8.0, usable=[], synthetic=True, race_s=5400.0, speedup=675.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0, start_utc='2026-02-22T10:00:00Z')
    text = SP.render(dict(race={}, clips=[c])); assert '=== CLIP G02: 8.0 s long' in text and 'NO FOOTAGE' in text and '1.5 h of the race in 8.0 s' in text and 'the runner says nothing' in text
