"""The llama.cpp route of the local vision model (analysis/vlm.py), used where MLX is not installed."""
import io, json, os, sys
import pytest
from strata360.analysis import vlm


def test_the_backend_follows_the_environment_then_whether_mlx_is_installed(monkeypatch):
    monkeypatch.setenv('STRATA_VLM_BACKEND', 'llama'); assert vlm.use_llama()
    monkeypatch.setenv('STRATA_VLM_BACKEND', 'mlx'); assert not vlm.use_llama()
    monkeypatch.delenv('STRATA_VLM_BACKEND'); monkeypatch.setattr(vlm.importlib.util, 'find_spec', lambda n: None); assert vlm.use_llama()
    monkeypatch.setattr(vlm.importlib.util, 'find_spec', lambda n: object()); assert not vlm.use_llama()


def test_the_vision_scripts_fall_back_to_this_interpreter_without_a_vision_environment(monkeypatch, tmp_path):
    monkeypatch.delenv('STRATA_VISION_PYTHON', raising=False); monkeypatch.setattr(vlm, 'ROOT', str(tmp_path)); assert vlm.vision_python() == sys.executable
    fake = tmp_path / 'py'; fake.write_text(''); monkeypatch.setenv('STRATA_VISION_PYTHON', str(fake)); assert vlm.vision_python() == str(fake)


def test_the_model_label_names_the_build_so_it_is_not_mistaken_for_the_mac_one():
    assert vlm.label('x/Qwen3.5-9B-Q4_K_M.gguf') == 'unsloth/Qwen3.5-9B-GGUF:Q4_K_M' and vlm.label('x/Qwen3.5-9B-Q8_0.gguf').endswith(':Q8_0')


def test_model_files_come_from_the_environment(monkeypatch, tmp_path):
    (tmp_path / 'm.gguf').write_text(''); (tmp_path / 'mmproj-F16.gguf').write_text(''); monkeypatch.setenv('STRATA_VLM_GGUF', str(tmp_path / 'm.gguf'))
    assert vlm.model_files() == (str(tmp_path / 'm.gguf'), str(tmp_path / 'mmproj-F16.gguf'))


def test_a_question_goes_to_the_server_with_the_picture_and_no_thinking(monkeypatch, tmp_path):
    img = tmp_path / 'a.jpg'; img.write_bytes(b'jpegbytes'); seen = {}

    def urlopen(req, timeout=None):
        seen['body'] = json.loads(req.data); return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content='{"score": 5}'))])).encode())
    monkeypatch.setattr(vlm.urllib.request, 'urlopen', urlopen); s = vlm.Server.__new__(vlm.Server); s.port = 1234
    assert s.ask('rate it', str(img), 50) == '{"score": 5}'
    b = seen['body']; assert b['temperature'] == 0.0 and b['max_tokens'] == 50 and b['chat_template_kwargs'] == dict(enable_thinking=False)
    parts = b['messages'][0]['content']; assert parts[0]['image_url']['url'].startswith('data:image/jpeg;base64,') and parts[1]['text'] == 'rate it'


def test_the_text_model_defaults_to_the_moe_when_it_is_there_else_the_picture_model(monkeypatch, tmp_path):
    monkeypatch.delenv('STRATA_LLM_GGUF', raising=False); monkeypatch.setattr(vlm, 'ROOT', str(tmp_path)); monkeypatch.setattr(vlm, 'model_files', lambda: ('pic.gguf', 'proj.gguf'))
    assert vlm.llm_files() == ('pic.gguf', None)
    moe = tmp_path / 'models' / 'qwen36-35b-a3b'; moe.mkdir(parents=True); (moe / 'Qwen3.6-35B-A3B-Q4_K_M.gguf').write_text('')
    assert vlm.llm_files() == (str(moe / 'Qwen3.6-35B-A3B-Q4_K_M.gguf'), None)
    monkeypatch.setenv('STRATA_LLM_GGUF', 'x.gguf'); assert vlm.llm_files() == ('x.gguf', None)
    assert vlm.label('m/Qwen3.6-35B-A3B-Q4_K_M.gguf') == 'ggml-org/Qwen3.6-35B-A3B-GGUF:Q4_K_M'


def test_a_chat_goes_to_the_server_without_thinking(monkeypatch):
    seen = {}

    def urlopen(req, timeout=None):
        seen['body'] = json.loads(req.data); return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content='hi'))])).encode())
    monkeypatch.setattr(vlm.urllib.request, 'urlopen', urlopen); s = vlm.Server.__new__(vlm.Server); s.port = 1
    assert s.chat([dict(role='user', content='x')], 20, 0.7) == 'hi' and seen['body']['chat_template_kwargs'] == dict(enable_thinking=False) and seen['body']['temperature'] == 0.7 and 'repeat_penalty' not in seen['body']
