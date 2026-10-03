"""photos.py: photos taken during the race, placed by their time stamp and their position."""
import datetime as dt, io, os
import numpy as np
import pytest
from PIL import Image

from strata360 import photos as PH

T0 = dt.datetime(2026, 2, 20, 13, 0, 0, tzinfo=dt.timezone.utc).timestamp()          # 14:00 in Brussels


def jpeg(local='2026:02:20 14:12:17', offset=None, gps=None, gps_time=None, size=(40, 30)):
    """A small JPEG with the EXIF given: the camera's local time, its UTC offset, a GPS position (lat, lon) and a GPS time stamp (datetime, UTC)."""
    ex = Image.Exif()
    if local: sub = ex.get_ifd(0x8769); sub[0x9003] = local
    if local and offset: ex.get_ifd(0x8769)[0x9011] = offset
    if gps or gps_time:
        g = ex.get_ifd(0x8825)
        if gps:
            la, lo = gps; g[1] = 'N' if la >= 0 else 'S'; g[2] = (abs(int(la)), int(abs(la) % 1 * 60), abs(la) % 1 * 3600 % 60); g[3] = 'E' if lo >= 0 else 'W'; g[4] = (abs(int(lo)), int(abs(lo) % 1 * 60), abs(lo) % 1 * 3600 % 60)
        if gps_time: g[29] = gps_time.strftime('%Y:%m:%d'); g[7] = (float(gps_time.hour), float(gps_time.minute), float(gps_time.second))
    b = io.BytesIO(); Image.new('RGB', size, (10, 200, 30)).save(b, 'JPEG', exif=ex); return b.getvalue() + b'\0' * 200


def run_track(n=3600, lat0=50.0, lon0=5.0):                                       # 3 m/s north for an hour from T0
    t = T0 + np.arange(n, dtype=float); nan = np.full(n, np.nan); return dict(t=t, lat=lat0 + 3.0 * np.arange(n) / 110540.0, lon=np.full(n, lon0), alt=nan, speed=nan, hr=nan, cadence=nan, dist=nan, temp=nan, power=nan)


class TestTime:
    def test_the_gps_clock_is_the_most_exact_then_the_camera_clock_with_its_offset_then_the_race_time_zone(self, tmp_path):
        rd = str(tmp_path)
        g = PH.add(rd, 'a.jpg', jpeg(local='2026:02:20 14:12:17', offset='+01:00', gps=(50.1, 5.1), gps_time=dt.datetime(2026, 2, 20, 13, 12, 20, tzinfo=dt.timezone.utc)))
        assert g['time_source'] == 'gps clock' and g['taken_utc'] == dt.datetime(2026, 2, 20, 13, 12, 20, tzinfo=dt.timezone.utc).timestamp() and g['gps'] == dict(lat=pytest.approx(50.1, abs=1e-4), lon=pytest.approx(5.1, abs=1e-4))
        o = PH.add(rd, 'b.jpg', jpeg(offset='+01:00')); assert o['time_source'] == 'camera clock + offset' and o['taken_utc'] == dt.datetime(2026, 2, 20, 13, 12, 17, tzinfo=dt.timezone.utc).timestamp() and o['gps'] is None
        a = PH.add(rd, 'c.jpg', jpeg(), 'Europe/Brussels'); assert a['time_source'] == 'camera clock, assumed Europe/Brussels' and a['taken_utc'] == o['taken_utc']
        u = PH.add(rd, 'd.jpg', jpeg(), 'UTC'); assert u['taken_utc'] == o['taken_utc'] + 3600 and [p['id'] for p in PH.load(rd)['photos']] == ['p1', 'p2', 'p3', 'p4']

    def test_what_cannot_be_used_is_refused_with_a_message_and_not_kept(self, tmp_path):
        rd = str(tmp_path)
        with pytest.raises(ValueError, match='no time stamp'): PH.add(rd, 'a.jpg', jpeg(local=None))
        with pytest.raises(ValueError, match='not an image'): PH.add(rd, 'b.jpg', b'x' * 500)
        with pytest.raises(ValueError, match='a photo, please'): PH.add(rd, 'c.txt', b'x' * 500)
        with pytest.raises(ValueError, match='empty or too large'): PH.add(rd, 'd.jpg', b'x')
        assert PH.load(rd)['photos'] == [] and sorted(n for n in os.listdir(os.path.join(rd, 'photos')) if not n.endswith('.bad')) == []

    def test_a_position_of_zero_zero_is_a_camera_with_no_fix(self, tmp_path):
        assert PH.add(str(tmp_path), 'a.jpg', jpeg(gps=(0.0, 0.0)))['gps'] is None


class TestWhere:
    def entry(self, **kw): return dict(id='p1', taken_utc=T0 + 600, gps=None, **kw)

    def test_the_run_position_is_found_by_the_time(self):
        p = PH.run_position(run_track(), T0 + 600); assert p['elapsed_s'] == 600 and 1.79 < p['km'] <= 1.82 and abs(p['lat'] - (50.0 + 1800 / 110540.0)) < 1e-5
        assert PH.run_position(run_track(), T0 - 60) is not None and PH.run_position(run_track(), T0 - 600) is None and PH.run_position(run_track(), T0 + 3600 + 600) is None     # a little before or after is still the first or last point

    def test_a_photo_without_gps_is_placed_on_the_run(self):
        r = PH.located(self.entry(), run_track()); assert r['loc']['source'] == 'run track' and r['apart_m'] is None and r['flag'] is None and r['track']['km'] > 1.7

    def test_the_photos_own_position_comes_first_and_is_flagged_when_far_from_the_run(self):
        near = PH.located(dict(self.entry(), gps=dict(lat=50.0 + 1800 / 110540.0 + 0.0005, lon=5.0)), run_track()); assert near['loc']['source'] == 'photo gps' and 40 < near['apart_m'] < 70 and near['flag'] is None
        far = PH.located(dict(self.entry(), gps=dict(lat=50.1, lon=5.1)), run_track()); assert far['loc']['source'] == 'photo gps' and far['apart_m'] > 5000 and 'km apart' in far['flag'] and 'clock' in far['flag']

    def test_a_photo_outside_the_run_is_flagged_and_keeps_its_own_position(self):
        out = PH.located(dict(self.entry(), taken_utc=T0 + 90000), run_track()); assert out['loc'] is None and out['flag'] == 'taken outside the time of the run'
        own = PH.located(dict(self.entry(), taken_utc=T0 + 90000, gps=dict(lat=50.2, lon=5.2)), run_track()); assert own['loc']['source'] == 'photo gps' and own['flag'] == 'taken outside the time of the run'
        assert PH.located(self.entry(), None)['flag'] == 'no race track to place it on'

    def test_the_clip_or_gap_the_time_falls_in(self):
        clips = [dict(id='CAM_1', start_utc='2026-02-20T13:00:00Z', duration_s=120.0), dict(id='CAM_2', start_utc='2026-02-20T14:00:00Z', duration_s=60.0)]; gaps = [dict(id='G01', t0=T0 + 120, t1=T0 + 3600)]
        assert PH.assign(T0 + 60, clips, gaps) == dict(kind='clip', id='CAM_1') and PH.assign(T0 + 600, clips, gaps) == dict(kind='gap', id='G01') and PH.assign(T0 + 7200, clips, gaps) is None


class TestFiles:
    def test_a_thumbnail_is_made_once_the_right_way_up_and_a_removed_photo_is_kept_aside(self, tmp_path):
        rd = str(tmp_path); e = PH.add(rd, 'big.jpg', jpeg(size=(1200, 800))); t = PH.thumb(rd, e['id'], 300)
        assert Image.open(t).size[0] == 300 and PH.thumb(rd, e['id'], 300) == t and PH.thumb(rd, 'p9') is None
        PH.remove(rd, e['id']); assert PH.load(rd)['photos'] == [] and os.listdir(os.path.join(rd, 'photos', 'removed')) and not os.path.exists(os.path.join(rd, e['file']))
        with pytest.raises(KeyError): PH.remove(rd, e['id'])

    @pytest.mark.parametrize('fmt,ext,mode', [('PNG', '.png', 'RGBA'), ('TIFF', '.tif', 'RGB'), ('WEBP', '.webp', 'RGB'), ('PNG', '.png', 'P'), ('PNG', '.png', 'I;16')])
    def test_other_formats_are_read_and_always_shown_as_jpeg(self, tmp_path, fmt, ext, mode):
        ex = Image.Exif(); ex[0x0132] = '2026:02:20 14:12:17'; ex.get_ifd(0x8769)[0x9003] = '2026:02:20 14:12:17'; b = io.BytesIO()
        im = Image.new(mode, (60, 40), 7000 if mode == 'I;16' else 0) if mode != 'P' else Image.new('RGB', (60, 40), (200, 10, 10)).convert('P')
        im.save(b, fmt, **(dict(tiffinfo={306: '2026:02:20 14:12:17'}) if fmt == 'TIFF' else dict(exif=ex))); rd = str(tmp_path); e = PH.add(rd, 'x' + ext, b.getvalue() + b'\0' * 200)
        assert e['time_source'].startswith('camera clock') and e['width'] == 60
        t = PH.thumb(rd, e['id'], 100); assert Image.open(t).format == 'JPEG' and Image.open(t).mode == 'RGB'
        big = PH.thumb(rd, e['id'], 3000); assert Image.open(big).format == 'JPEG' and Image.open(big).size == (60, 40)             # (never enlarged)

    def test_a_format_without_exif_is_refused_with_the_reason(self, tmp_path):
        b = io.BytesIO(); Image.new('RGB', (30, 30)).save(b, 'GIF')
        with pytest.raises(ValueError, match='no time stamp'): PH.add(str(tmp_path), 'a.gif', b.getvalue() + b'\0' * 200)

    def test_heic_is_converted_when_a_converter_exists_and_refused_loudly_when_not(self, tmp_path, monkeypatch):
        jpg = jpeg(offset='+01:00')
        def fake(path): out = os.path.splitext(path)[0] + '.converted.jpg'; open(out, 'wb').write(jpg); return out
        monkeypatch.setattr(PH, 'convert_heic', fake); e = PH.add(str(tmp_path), 'IMG_1.HEIC', b'heic' * 100)
        assert e['file'].endswith('.converted.jpg') and e['original'].endswith('.HEIC') and e['time_source'] == 'camera clock + offset'
        monkeypatch.setattr(PH, 'convert_heic', lambda path: None)
        with pytest.raises(ValueError, match='pillow-heif'): PH.add(str(tmp_path), 'IMG_2.heic', b'heic' * 100)


class TestMotionSettings:
    def test_defaults_are_not_stored_and_changes_are_checked(self, tmp_path):
        rd = str(tmp_path); e = PH.add(rd, 'a.jpg', jpeg()); assert PH.motion_of(e) == dict(style='auto', seconds=6.0, seed=0)
        assert PH.set_motion(rd, 'p1', style='pan', seconds=9) == dict(style='pan', seconds=9.0, seed=0) and PH.load(rd)['photos'][0]['motion'] == dict(style='pan', seconds=9.0, seed=0)
        assert PH.set_motion(rd, 'p1', seed=4)['style'] == 'pan'                                                                  # only what is sent changes
        PH.set_motion(rd, 'p1', style='auto', seconds=6, seed=0); assert 'motion' not in PH.load(rd)['photos'][0]
        for bad in (dict(style='spin'), dict(seconds=1), dict(seconds=99), dict(seconds='x'), dict(speed=3)):
            with pytest.raises(ValueError): PH.set_motion(rd, 'p1', **bad)
        with pytest.raises(KeyError): PH.set_motion(rd, 'p9', style='pan')

    def test_the_size_is_as_the_photo_is_shown(self, tmp_path):
        ex = Image.Exif(); ex[0x0112] = 6; ex.get_ifd(0x8769)[0x9003] = '2026:02:20 14:12:17'; b = io.BytesIO(); Image.new('RGB', (80, 40)).save(b, 'JPEG', exif=ex)       # turned a quarter: shown 40 x 80
        e = PH.add(str(tmp_path), 'a.jpg', b.getvalue() + b'\0' * 200); assert (e['width'], e['height']) == (40, 80)
