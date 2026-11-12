"""The voice-over spoken by strata-models (strata360.edit.voiceover, engine `strata-models`): offered only when the service runs and serves `speak`,
the eval's chosen voice by default (keyed on the model that serves the role, so a new choice is spoken again), the Kokoro voices by name, with a fake client."""

import sys
import types

import pytest

from strata360.edit import voiceover as V


def fake_client(calls, tmp_path, running=True, model="chatterbox-runner"):
    m = types.ModuleType("strata_models_client")

    class Unavailable(RuntimeError):
        pass

    class JobFailed(RuntimeError):
        pass

    m.Unavailable, m.JobFailed = Unavailable, JobFailed
    m.available = lambda: running
    m.role_model = lambda role: model if role == "speak" else None

    def speak(text, app, model=None, **params):
        calls.append((text, app, model, params))
        p = tmp_path / f"out{len(calls)}.wav"
        p.write_bytes(b"RIFF")
        return dict(path=str(p), duration_s=1.0)

    m.speak = speak
    return m


@pytest.fixture
def svc(monkeypatch, tmp_path):
    calls = []
    monkeypatch.delenv("STRATA360_MODELS", raising=False)
    V._SM.clear()
    monkeypatch.setitem(sys.modules, "strata_models_client", fake_client(calls, tmp_path))
    yield calls
    V._SM.clear()


def test_offered_when_the_service_serves_speak(svc, monkeypatch, tmp_path):
    assert (
        V._sm_available()
        and [v["name"] for v in V._sm_voices()][:2] == ["chosen", "bm_lewis"]
        and "chatterbox-runner" in V._sm_voices()[0]["label"]
    )
    monkeypatch.setenv("STRATA360_MODELS", "local")
    assert not V._sm_available()
    monkeypatch.delenv("STRATA360_MODELS")
    V._SM.clear()
    monkeypatch.setitem(sys.modules, "strata_models_client", fake_client([], tmp_path, model=None))
    assert not V._sm_available()  # an older service: no speak role
    monkeypatch.setitem(sys.modules, "strata_models_client", fake_client([], tmp_path, running=False))
    assert not V._sm_available()
    monkeypatch.setitem(sys.modules, "strata_models_client", None)
    assert not V._sm_available()


def test_speaks_the_chosen_voice_or_a_kokoro_voice(svc, tmp_path):
    out = tmp_path / "line.wav"
    V._sm_speak("chosen", 150, "Two hundred kilometres behind me.", str(out))
    assert out.read_bytes() == b"RIFF"
    assert svc[-1] == ("Two hundred kilometres behind me.", "strata-360", None, dict(wpm=150.0))
    V._sm_speak("bm_george", 165, "Faster.", str(out))
    assert svc[-1][2] == "kokoro-v1" and svc[-1][3] == dict(voice="bm_george", wpm=165.0)


def test_a_new_choice_is_spoken_again(svc, monkeypatch, tmp_path):
    a = V.synth_path("/p", 1, "hello", "strata-models", "chosen", 150)
    V._SM.clear()
    monkeypatch.setitem(sys.modules, "strata_models_client", fake_client([], tmp_path, model="qwen3-tts-design"))
    assert V.synth_path("/p", 1, "hello", "strata-models", "chosen", 150) != a
    assert V.voice_id("kokoro", "bm_lewis") == "bm_lewis" and V.voice_id("strata-models", "bm_lewis") == "bm_lewis"


def test_a_new_choice_rebuilds_the_track(svc, monkeypatch, tmp_path):
    st = dict(engine="strata-models", voice="chosen", rate=150, use={})
    a = V.signature(str(tmp_path), "s", st, 10.0)
    V._SM.clear()
    monkeypatch.setitem(sys.modules, "strata_models_client", fake_client([], tmp_path, model="qwen3-tts-design"))
    assert V.signature(str(tmp_path), "s", st, 10.0) != a
