import numpy as np
import pytest
import os
from strata360.gps import track

def test_load_gpx(tmp_path):
    gpx_content = """<?xml version="1.0"?>
    <gpx version="1.1" creator="strata360" xmlns="http://www.topografix.com/GPX/1/1">
      <trk>
        <trkseg>
          <trkpt lat="50.0" lon="4.0">
            <ele>100.0</ele>
            <time>2026-02-21T12:00:00Z</time>
          </trkpt>
          <trkpt lat="50.1" lon="4.1">
            <time>2026-02-21T12:00:10Z</time>
          </trkpt>
        </trkseg>
      </trk>
    </gpx>
    """
    gpx_file = tmp_path / "test.gpx"
    gpx_file.write_text(gpx_content)

    tr = track.load_gpx(str(gpx_file))

    assert len(tr['t']) == 2
    assert tr['lat'][0] == 50.0
    assert tr['lon'][0] == 4.0
    assert tr['alt'][0] == 100.0
    assert tr['lat'][1] == 50.1
    assert tr['lon'][1] == 4.1
    assert np.isnan(tr['alt'][1])
    assert np.isnan(tr['speed']).all()
    assert np.isnan(tr['hr']).all()

def test_at():
    t = np.array([1000.0, 1010.0, 1020.0])
    lat = np.array([50.0, 50.1, 50.2])
    lon = np.array([4.0, 4.1, 4.2])
    tr = dict(t=t, lat=lat, lon=lon)

    lat_interp, lon_interp = track.at(tr, 1010.0)
    assert lat_interp == 50.1
    assert lon_interp == 4.1

    lat_interp, lon_interp = track.at(tr, 1005.0)
    assert lat_interp == 50.05
    assert lon_interp == 4.05

def test_to_gpx(tmp_path):
    t = np.array([1771520000.0, 1771520010.0])
    lat = np.array([50.0, 50.1])
    lon = np.array([4.0, 4.1])
    alt = np.array([100.0, np.nan])

    tr = dict(t=t, lat=lat, lon=lon, alt=alt)
    out_file = tmp_path / "out.gpx"
    track.to_gpx(tr, str(out_file))

    content = out_file.read_text()
    assert "<gpx" in content
    assert 'lat="50.000000"' in content
    assert '<ele>100.0</ele>' in content
    assert 'lat="50.100000"' in content
    assert content.count('<ele>') == 1

def test_load_cache(tmp_path):
    gpx_content = """<?xml version="1.0"?>
    <gpx version="1.1" creator="strata360" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><trkseg><trkpt lat="50.0" lon="4.0"><time>2026-02-21T12:00:00Z</time></trkpt></trkseg></trk>
    </gpx>
    """
    gpx_file = tmp_path / "test2.gpx"
    gpx_file.write_text(gpx_content)

    tr1 = track.load(str(gpx_file))
    assert os.path.exists(str(gpx_file) + '.npz')
    assert tr1['lat'][0] == 50.0

    gpx_file.write_text("corrupted")
    tr2 = track.load(str(gpx_file))
    assert tr2['lat'][0] == 50.0

def test_load_fit_mocked(monkeypatch):
    class MockFitField:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class MockFitFrame:
        def __init__(self, frame_type, name, fields):
            self.frame_type = frame_type
            self.name = name
            self.fields = fields

    class MockFitReader:
        def __init__(self, path):
            self.path = path
        def __enter__(self):
            import fitdecode
            import datetime
            ts = datetime.datetime.fromtimestamp(1000, datetime.timezone.utc)
            self.frames = [
                MockFitFrame(fitdecode.FIT_FRAME_DATA, 'record', [
                    MockFitField('timestamp', ts),
                    MockFitField('position_lat', 50.0 / track.SEMI),
                    MockFitField('position_long', 4.0 / track.SEMI),
                    MockFitField('enhanced_altitude', 100.0),
                    MockFitField('enhanced_speed', 2.5),
                ])
            ]
            return self.frames
        def __exit__(self, *args):
            pass

    import fitdecode
    monkeypatch.setattr(fitdecode, 'FitReader', MockFitReader)

    tr = track.load_fit("fake.fit")
    assert len(tr['t']) == 1
    assert tr['lat'][0] == 50.0
    assert tr['lon'][0] == 4.0
    assert tr['alt'][0] == 100.0
    assert tr['speed'][0] == 2.5
    assert np.isnan(tr['hr'][0])

def test_load_fit_mocked_skips(monkeypatch):
    class MockFitField:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class MockFitFrame:
        def __init__(self, frame_type, name, fields):
            self.frame_type = frame_type
            self.name = name
            self.fields = fields

    class MockFitReader:
        def __init__(self, path):
            self.path = path
        def __enter__(self):
            import fitdecode
            import datetime
            ts = datetime.datetime.fromtimestamp(1000, datetime.timezone.utc)
            self.frames = [
                MockFitFrame(fitdecode.FIT_FRAME_HEADER, 'record', []),
                MockFitFrame(fitdecode.FIT_FRAME_DATA, 'event', []),
                MockFitFrame(fitdecode.FIT_FRAME_DATA, 'record', [MockFitField('position_lat', 50.0)]),
                MockFitFrame(fitdecode.FIT_FRAME_DATA, 'record', [MockFitField('timestamp', ts)]),
            ]
            return self.frames
        def __exit__(self, *args):
            pass

    import fitdecode
    monkeypatch.setattr(fitdecode, 'FitReader', MockFitReader)

    tr = track.load_fit("fake.fit")
    assert len(tr['t']) == 1
    assert np.isnan(tr['lat'][0])
    assert np.isnan(tr['lon'][0])
