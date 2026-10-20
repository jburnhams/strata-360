"""osv/source.py: which camera made a clip, from its file and header."""
from strata360.osv import source


def test_camera_id_names_the_insta360_model_from_its_header():
    assert source.camera_id('Insta360 X3', 'race/VID_20240720_195607_00_001.insv') == 'insta360_x3'
    assert source.camera_id('Insta360 One RS', 'race/VID_20240720_195607_00_001.insv') == 'insta360_one_rs'


def test_camera_id_of_an_insta360_with_no_model_is_unknown_not_dji():
    assert source.camera_id(None, 'race/VID_20240720_195607_00_001.insv') == 'insta360_unknown'


def test_camera_id_of_an_osv_is_the_dji():
    assert source.camera_id('Osmo 360', 'race/CAM_20260219_0001.OSV') == 'dji_osmo_360'
    assert source.camera_id(None, 'race/CAM_20260219_0001.OSV') == 'dji_osmo_360'
