"""edit/credits.py: the credits a film needs, listed for its distribution (never drawn into the picture)."""
import os
from strata360.edit import credits as CR, project as PJ, synthetic as SY
from strata360.pipeline import config


def seg(clip): return dict(clip=clip, synthetic=f'/x/{clip}.mp4', dur_s=5.0)


def test_a_project_without_a_track_or_generated_clips_needs_no_credits(project):
    assert CR.needed(project.folder) == [] and 'No credits are needed' in CR.text(project.folder)


def test_the_overlays_maps_and_the_generated_clips_are_listed_once_each(project):
    open(os.path.join(project.race_dir, 'track.gpx'), 'w').write('<gpx/>')
    gap = dict(id='G01', t0=1_771_754_000.0, t1=1_771_754_000.0 + 3600)
    SY.save(project.folder, dict(clips=[SY.make(gap, seconds=6.0), SY.make(dict(gap, id='G02'), seconds=6.0, kind='flyover'), SY.make(dict(gap, id='G03'), seconds=6.0, style={'map': 'osm'})]))
    edit = PJ.load(project.folder); edit['plan'] = dict(segments=[seg('G01'), seg('G02'), seg('G03'), dict(clip='CAM', dur_s=3.0)]); PJ.save(project.folder, edit)
    rows = CR.needed(project.folder); texts = [t for _, t in rows]
    assert len(set(texts)) == len(texts)                                                                                       # each credit once, whatever uses it
    assert 'Maps © Thunderforest, data © OpenStreetMap contributors' in texts and any('Terrain' in t and 'Mapterhorn' in t for t in texts) and '© OpenStreetMap contributors' in texts
    assert any('flyover G02' in w for w, _ in rows) and any('2D map G03 (osm)' in w for w, _ in rows) and any('route map on the overlay' in w for w, _ in rows) and not any('G01' in w for w, _ in rows)      # G01 shares the overlay's credit


def test_credits_can_be_written_next_to_the_project(project):
    p = CR.write(project.folder); assert p == os.path.join(config.race_dir(project.folder), 'credits.txt') and open(p).read().startswith('No credits')
