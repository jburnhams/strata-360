"""analysis/scenes_vlm.py: the parts that need no model: the name given to a model, and the choice of the default one."""
from strata360.analysis import scenes_vlm as M


def test_a_model_keeps_its_name_when_the_cache_folder_is_rebuilt(tmp_path):
    assert M.model_label('/Users/x/.cache/huggingface/hub/models--mlx-community--Qwen3.5-9B-4bit/snapshots/8b2b98c0') == 'mlx-community/Qwen3.5-9B-4bit'
    assert M.model_label(str(tmp_path / 'models' / 'qwen25vl3b-4bit')) == 'qwen25vl3b-4bit'


def test_the_default_model_is_the_env_override_when_it_exists_and_the_call_exits_with_a_hint_when_nothing_is_installed(tmp_path, monkeypatch):
    import pytest
    mine = tmp_path / 'mine'; mine.mkdir(); monkeypatch.setenv('STRATA_VLM_MODEL', str(mine)); assert M.default_model() == str(mine)
    monkeypatch.delenv('STRATA_VLM_MODEL'); monkeypatch.setattr(M.os.path, 'isdir', lambda p: False); monkeypatch.setattr(M.glob, 'glob', lambda p: [])
    with pytest.raises(SystemExit) as e: M.default_model()
    assert 'qwen35-9b-4bit' in str(e.value)
