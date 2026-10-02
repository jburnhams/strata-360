"""edit/script_pack.py: clip labels (camera clips by number, generated clips by name) and how a generated clip appears in the writer's context."""
import pytest
from strata360.edit import script_pack as SP, synthetic as SY


@pytest.mark.parametrize('x,want', [(23, '0023'), ('23', '0023'), ('0023', '0023'), (' g03 ', 'G03'), ('G03', 'G03'), (None, ''), ('', '')])
def test_labels_pad_numbers_and_upper_case_names(x, want): assert SP.norm_label(x) == want


GAP = dict(id='G02', t0=1_771_754_000.0, t1=1_771_754_000.0 + 5400, duration_s=5400.0, local_start='Sat 21 Feb 16:15', local_end='Sun 22 Feb 09:04', km_start=233.5, km_end=307.1, distance_km=73.6, ascent_m=2078, daylight='night->night', moving_share=0.88)


def test_every_gap_is_a_pack_clip_with_the_choices_for_filling_it_and_the_state_of_any_clip_planned(monkeypatch):
    from strata360.gps import gaps as GP, context as X
    monkeypatch.setattr(GP, 'load_spans', lambda f: []); monkeypatch.setattr(GP, 'find_gaps', lambda spans, tr, min_s, tz: [GAP, dict(GAP, id='G03', t0=GAP['t1'] + 3600, t1=GAP['t1'] + 7200, duration_s=3600.0)])
    monkeypatch.setattr(X, 'context_at', lambda tr, a, b, tz: dict(covered=True, distance_km=250.0, elapsed_h=20.0, local_date='Sat 21 Feb', local_time='19:00')); monkeypatch.setattr(X, 'describe', lambda ctx: 'night, km 250')
    planned = SY.make(GAP, seconds=8.0, kind='flyover', approved=False); monkeypatch.setattr(SY, 'load', lambda folder: dict(clips=[dict(planned, status='planned')]))
    out = SP.gap_clips('x', object(), 'UTC'); assert [c['label'] for c in out] == ['G02', 'G03'] and all(c['synthetic'] and c['lines'] == [] and c['usable_s'] == SP.MAX_GAP_S for c in out)
    a, b = out; assert a['duration_s'] == 8.0 and a['race_s'] == 5400.0 and [o['kind'] for o in a['options']] == ['map', 'flyover'] and 'approval' in a['options'][1]['note'] and a['planned'] == dict(kind='flyover', seconds=8.0, status='planned', approved=False)
    assert b['planned'] is None and b['duration_s'] == SY.default_seconds(3600.0) and a['km'] == 250.0 and SP.gap_clips('x', None, 'UTC') == []


def test_the_prompt_text_describes_each_gap_and_the_music_with_its_sung_stretches():
    c = dict(label='G02', clip='G02', duration_s=8.0, usable_s=45.0, usable=[], synthetic=True, race_s=5400.0, speedup=675.0, scene={}, note='', lines=[], speech_s=0.0, speech_words=0, start_utc='2026-02-22T10:00:00Z', gap={k: GAP[k] for k in ('local_start', 'local_end', 'km_start', 'km_end', 'ascent_m', 'daylight', 'moving_share')},
             options=[dict(kind='map', default_seconds=8.0), dict(kind='flyover', default_seconds=8.0, note='x')], planned=dict(kind='flyover', seconds=8.0, status='planned', approved=False))
    music = dict(length_s=245.0, bpm=97.0, bar_s=2.47, sections=[dict(t0=0.0, t1=10.0, energy=0.0), dict(t0=10.0, t1=20.0, energy=0.36)], lyrics=dict(language='en', vocal_spans=[[20.0, 50.0], [54.0, 92.0]], phrases=[dict(t0=21.0, t1=24.0, text='a line', doubtful=False), dict(t0=60.0, t1=63.0, text='another', doubtful=True)]))
    text = SP.render(dict(race={}, clips=[c], music=music)); assert '=== CLIP G02: 8.0 s long' in text and 'NO FOOTAGE: a gap of 1.5 h' in text and 'km 233.5 to 307.1, +2078 m, night->night' in text and 'Already planned: flyover, 8.0 s (planned)' in text and 'the runner says nothing' in text
    assert 'THE MUSIC (times are FILM seconds' in text and 'length 245 s, 97 bpm' in text and '0-10 s 0.00; 10-20 s 0.36' in text and 'Sung (en): 20-50 s, 54-92 s' in text and '[21 s] a line' in text and '[60 s] another (doubtful)' in text
    assert 'instrumental' in SP.render(dict(race={}, clips=[], music=dict(music, lyrics=dict(instrumental=True)))) and 'THE MUSIC' not in SP.render(dict(race={}, clips=[], music=None))
