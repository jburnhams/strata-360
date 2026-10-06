import os
import shutil
import numpy as np
import pytest

from strata360.osv import calib, meta, mp4, pbdump, telemetry

def test_pbdump_first_packet_reads_start_of_file(synthetic_osv):
    pk = pbdump.first_packet(synthetic_osv, 3)
    assert isinstance(pk, bytes)
    assert len(pk) > 0

def test_meta_header_extracts_device_info(synthetic_osv):
    h = meta.header(synthetic_osv, djmd_stream=3)
    assert h['device'] == 'Osmo 360'
    assert h['firmware'] == '1.0.0'
    assert h['serial'] == 'SYN0001'
    assert h['colour_mode'] == 'normal'
    assert h['calibration_slots'] > 0

def test_telemetry_read_frames_parses_timestamps_quats_and_accel(synthetic_osv):
    frames = telemetry.read_frames(synthetic_osv)
    assert 'ts_us' in frames
    assert 'quat' in frames
    assert 'acc' in frames
    assert len(frames['ts_us']) > 0
    assert frames['ts_us'].dtype == np.int64
    assert frames['quat'].shape == (len(frames['ts_us']), 4)
    assert frames['acc'].shape == (len(frames['ts_us']), 3)

def test_telemetry_has_dropped_frames(synthetic_osv):
    # The synthetic osv has dropped frames configured by drop=(30, 31)
    assert telemetry.has_dropped_frames(synthetic_osv)

def test_telemetry_video_pts(synthetic_osv):
    pts = telemetry.video_pts(synthetic_osv, stream=0)
    assert len(pts) > 0
    assert np.all(np.diff(pts) >= 0) # Sorted

def test_telemetry_read_exposure(synthetic_osv):
    exp = telemetry.read_exposure(synthetic_osv)
    assert 'djmd3' in exp
    assert 'djmd4' in exp
    assert 'iso' in exp['djmd3']
    assert 'shutter_den' in exp['djmd3']
    assert 'ct' in exp['djmd3']
    assert len(exp['djmd3']['iso']) > 0

def test_calib_Lens_can_project(synthetic_osv):
    slots = calib.read_slots(synthetic_osv)
    assert 1 in slots # Slot 1 is populated in synthetic osv
    lens = calib.Lens(slots[1])
    # Project a body-frame direction
    d_body = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    u, v, th = lens.project(d_body)
    assert len(u) == 2
    assert len(v) == 2
    assert len(th) == 2
    rim = lens.rim_radius()
    assert rim > 0
    th_edge, r_edge = lens.edge_theta()
    assert len(th_edge) > 0

def test_meta_frame_gaps(synthetic_osv):
    pts = telemetry.video_pts(synthetic_osv, stream=0)
    gaps, nominal = meta.frame_gaps(pts)
    # the synthetic osv has drop=(30,31)
    assert len(gaps) > 0
    # nominal should be ~0.02 (1/50 fps)
    assert pytest.approx(nominal, 0.01) == 0.02

def test_pbdump_show_function():
    from strata360.osv.pbdump import show
    # Construct a simple valid protobuf message for `show` to parse
    # field 1: string "test"
    # field 1 = 1 << 3 | 2 (length delimited) = 10 (0x0A), length = 4
    # field 2: varint 42
    # field 2 = 2 << 3 | 0 (varint) = 16 (0x10)
    # field 3: float 3.14
    # field 3 = 3 << 3 | 5 (32-bit) = 29 (0x1D)
    import struct
    b = bytes([0x0A, 4]) + b'test' + bytes([0x10, 42]) + bytes([0x1D]) + struct.pack('<f', 3.14)

    lines = show(b)
    assert any("1: 'test'" in line for line in lines)
    assert any("2: 42" in line for line in lines)
    assert any("3: f32" in line for line in lines)

    # Test nested message
    inner = bytes([0x10, 42]) # 2: 42
    b2 = bytes([0x0A, len(inner)]) + inner
    lines2 = show(b2)
    assert any("msg" in line for line in lines2)
    assert any("2: 42" in line for line in lines2)

    # Test f64 (w=1)
    # field 4: f64 2.71
    b3 = bytes([4 << 3 | 1]) + struct.pack('<d', 2.71)
    lines3 = show(b3)
    assert any("4: f64" in line for line in lines3)

def test_pbdump_errors():
    from strata360.osv.pbdump import parse
    with pytest.raises(ValueError, match="eof"):
        parse(bytes([0x80])) # Truncated varint
    with pytest.raises(ValueError, match="field"):
        parse(bytes([0x00])) # Field 0 is invalid
    with pytest.raises(ValueError, match="trunc"):
        parse(bytes([0x1D, 0x00, 0x00])) # Truncated 32-bit (needs 4 bytes)
    with pytest.raises(ValueError, match="trunc"):
        parse(bytes([0x0A, 10, 0x01])) # Truncated length delimited (claims 10 bytes, only 1 provided)


def test_pbdump_packed_f32_f64_bytes():
    from strata360.osv.pbdump import show
    import struct
    # packed f32 (length % 4 == 0, reasonable values)
    b_f32 = bytes([0x0A, 8]) + struct.pack('<ff', 1.0, 2.0)
    lines_f32 = show(b_f32)
    assert any("packed f32" in line for line in lines_f32)
    assert any("1" in line for line in lines_f32)
    assert any("2" in line for line in lines_f32)

    # packed f64 (length % 8 == 0, >= 16 bytes)
    b_f64 = bytes([0x0A, 16]) + struct.pack('<dd', 1.0, 2.0)
    lines_f64 = show(b_f64)
    assert any("packed f64" in line for line in lines_f64)

    # arbitrary bytes (unprintable, not packed float sizes)
    b_bytes = bytes([0x0A, 3]) + b'\x00\xFF\x00'
    lines_bytes = show(b_bytes)
    assert any("bytes(3)" in line for line in lines_bytes)

def test_telemetry_cache_behaviour(synthetic_osv, tmp_path, monkeypatch):
    monkeypatch.setenv('STRATA_CACHE', str(tmp_path))
    # Copy the fixture to a private place to safely mutate its metadata
    private_osv = str(tmp_path / 'mutable.osv')
    shutil.copy(synthetic_osv, private_osv)

    # Should create a cache file
    frames1 = telemetry.read_frames(private_osv)
    assert len(frames1['ts_us']) > 0

    # Ensure cache exists
    cache_dir = telemetry.cache_dir()
    assert len(os.listdir(cache_dir)) > 0

    # Modify file mtime to invalidate cache
    st = os.stat(private_osv)
    os.utime(private_osv, (st.st_atime, st.st_mtime + 10))

    frames2 = telemetry.read_frames(private_osv)
    assert len(frames2['ts_us']) > 0
    assert len(os.listdir(cache_dir)) > 1

def test_meta_header_missing_or_corrupt_data(monkeypatch):
    # Construct an empty/bare stream meta using byte serialization directly
    mock_pk = bytes([2 << 3 | 2, 2]) + bytes([1 << 3 | 2, 0]) # Field 2 is msg(2 bytes): Field 1 is msg(0)

    import strata360.osv.meta as meta_mod

    def mock_first_packet(path, idx): return mock_pk
    def mock_read_slots(path, idx): raise ValueError("no slots")

    monkeypatch.setattr(meta_mod, 'first_packet', mock_first_packet)
    monkeypatch.setattr(meta_mod, 'read_slots', mock_read_slots)

    h = meta_mod.header("fake_path")
    assert h['colour_mode'] == 'normal'
    assert h['calibration_slots'] == 0
    assert h['device'] is None

def test_meta_header_colour_modes(monkeypatch):
    # Test alternative colour modes via mock (code 9 = hlg, code 19 = dlogm)
    # 2: len, 4: varint (9)
    # 4 is w=0
    import strata360.osv.meta as meta_mod

    def mock_first_packet(path, idx):
        # We need a packet containing field 2 -> StreamMeta
        # Within StreamMeta, field 4 has the colour mode
        # StreamMeta is field 2: w=2
        # Inside, field 4 is varint: 4 << 3 | 0 = 32 (0x20)
        return bytes([0x12, 2, 0x20, 9])

    def mock_read_slots(path, idx): raise ValueError("no slots")

    monkeypatch.setattr(meta_mod, 'first_packet', mock_first_packet)
    monkeypatch.setattr(meta_mod, 'read_slots', mock_read_slots)

    h = meta_mod.header("fake_path")
    assert h['colour_mode'] == 'hlg'
    assert h['colour_mode_raw'] == 9


def test_telemetry_video_pts_ffprobe_fallback(synthetic_osv, monkeypatch):
    import strata360.osv.mp4 as mp4_mod

    def mock_video_sample_times(path): raise ValueError("Index unreadable")
    monkeypatch.setattr(mp4_mod, 'video_sample_times', mock_video_sample_times)

    # This should trigger the fallback to ffprobe
    pts = telemetry.video_pts(synthetic_osv, stream=0)
    assert len(pts) > 0
    assert np.all(np.diff(pts) >= 0)


def test_mp4_video_sample_times_invalid_path():
    with pytest.raises(FileNotFoundError):
        mp4.video_sample_times("non_existent_file.mp4")

def test_mp4_video_sample_times_no_moov(tmp_path):
    # Create an mp4 file without a moov box
    p = tmp_path / "nomoov.mp4"
    import struct
    # write ftyp box
    p.write_bytes(struct.pack('>I4s', 8, b'ftyp'))
    with pytest.raises(ValueError, match="no moov box"):
        mp4.video_sample_times(str(p))

def test_mp4_video_sample_times_no_video_track(tmp_path):
    # Create an mp4 file with moov but no video track
    p = tmp_path / "novid.mp4"
    import struct
    def _box(typ, payload=b''): return struct.pack('>I4s', 8 + len(payload), typ) + payload

    # We need a moov box. Inside it we'll put a trak box without a mdia->hdlr that says 'vide'
    # Actually just a moov box with no trak box will raise 'no video track'
    moov = _box(b'moov', b'')
    p.write_bytes(moov)

    with pytest.raises(ValueError, match="no video track"):
        mp4.video_sample_times(str(p))

def test_mp4_video_sample_times_non_video_hdlr(tmp_path):
    # Create an mp4 file with moov, trak, mdia, hdlr but not 'vide'
    p = tmp_path / "audio.mp4"
    import struct
    def _box(typ, payload=b''): return struct.pack('>I4s', 8 + len(payload), typ) + payload

    # We want mdia->hdlr to not be vide, e.g. soun
    # The hdlr box structure requires type at offset 8 (so 12 bytes in payload? Wait, the code seeks to hdlr[0]+8 and reads 4 bytes to check if it's 'vide')
    # Let's make hdlr payload big enough: version/flags(4) + pre_defined(4) + handler_type(4)
    hdlr_payload = bytes([0,0,0,0]) + bytes([0,0,0,0]) + b'soun' + b'\0'*12
    hdlr = _box(b'hdlr', hdlr_payload)
    mdia = _box(b'mdia', hdlr)
    trak = _box(b'trak', mdia)
    moov = _box(b'moov', trak)
    p.write_bytes(moov)

    with pytest.raises(ValueError, match="no video track"):
        mp4.video_sample_times(str(p))

def test_mp4_video_sample_times_ctts_version_1(tmp_path):
    # Test ctts parsing with version 1 (which supports negative composition offsets)
    p = tmp_path / "ctts_v1.mp4"
    import struct
    def _box(typ, payload=b''): return struct.pack('>I4s', 8 + len(payload), typ) + payload
    def _full(typ, payload, ver=0, flags=0): return _box(typ, struct.pack('>I', ver << 24 | flags) + payload)

    hdlr = _full(b'hdlr', b'\0'*4 + b'vide' + b'\0'*12)
    mdhd = _full(b'mdhd', struct.pack('>IIII', 0,0,1000,0) + struct.pack('>HH', 0, 0), ver=1)

    # stts: 2 samples of duration 100
    stts = _full(b'stts', struct.pack('>I', 1) + struct.pack('>II', 2, 100))
    # ctts: version 1, 2 samples. Offset for sample 1 = 10, offset for sample 2 = -10 (which is 2**32 - 10)
    ctts = _full(b'ctts', struct.pack('>I', 2) + struct.pack('>II', 1, 10) + struct.pack('>II', 1, 2**32 - 10), ver=1)

    stbl = _box(b'stbl', stts + ctts)
    minf = _box(b'minf', stbl)
    mdia = _box(b'mdia', mdhd + hdlr + minf)
    trak = _box(b'trak', mdia)
    moov = _box(b'moov', trak)
    p.write_bytes(moov)

    # Timescale is 1000
    # Dts for sample 1 = 0, sample 2 = 100
    # Pts = Dts + offset = 0+10 = 10, 100-10 = 90
    # Expected returned pts = sorted(10/1000, 90/1000) = 0.01, 0.09

    # Let's adjust mdhd struct because timescale offset depends on version
    # mdhd body version 1: creation_time(8), modification_time(8), timescale(4), duration(8), pad(2), lang(2)
    mdhd_body = struct.pack('>QQIQ', 0, 0, 1000, 0) + struct.pack('>HH', 0, 0)
    mdhd = _full(b'mdhd', mdhd_body, ver=1)
    mdia = _box(b'mdia', mdhd + hdlr + minf)
    trak = _box(b'trak', mdia)
    moov = _box(b'moov', trak)
    p.write_bytes(moov)

    pts = mp4.video_sample_times(str(p))
    assert len(pts) == 2
    assert pytest.approx(pts[0]) == 0.01
    assert pytest.approx(pts[1]) == 0.09
