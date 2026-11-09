"""Whisper through strata-models, the service that owns the GPU on omarchy: the same faster-whisper models, loaded once for every app, run in one
queue, on the GPU even where this app is set to the CPU (STRATA_GPU=0 was for the old 2 GB card).

`whisper_model(name)` returns an object with the two methods the speech and lyrics code call on a faster_whisper.WhisperModel (`transcribe`,
`detect_language`), with the same return shapes (segments with .start .end .text .avg_logprob .no_speech_prob .words; info with .language
.language_probability .duration), so the code around it does not change. It is used when the service answers and knows the model; otherwise, or
with STRATA360_MODELS=local, the model is loaded here as before. Audio given as an array (a speech chunk after denoising) is written to a
16 kHz WAV in a temporary file for the service to read; a path is sent as it is."""

import contextlib
import os
import tempfile
import types
import wave

import numpy as np

APP = "strata-360"
# faster-whisper name -> (role, strata-models model). The role decides only which queue entry it is; the model is named explicitly.
MODELS = {
    "large-v3": ("transcribe", "whisper-large-v3"),
    "large-v3-turbo": ("transcribe", "whisper-large-v3-turbo"),
    "small": ("transcribe-fast", "whisper-small"),
}
PASS = (
    "language",
    "task",
    "word_timestamps",
    "vad_filter",
    "beam_size",
    "condition_on_previous_text",
    "initial_prompt",
    "temperature",
)


def _client():
    try:
        import strata_models_client as sm
    except ImportError:
        return None
    return sm


def use_service(name):
    """Whether `name` runs on strata-models: the service is running, knows the model, and STRATA360_MODELS is not 'local'."""
    if os.environ.get("STRATA360_MODELS", "").lower() == "local" or name not in MODELS:
        return False
    sm = _client()
    return bool(sm and sm.available())


@contextlib.contextmanager
def _as_path(audio):
    if isinstance(audio, (str, os.PathLike)):
        yield os.path.abspath(audio)
        return
    x = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    fd, path = tempfile.mkstemp(
        suffix=".wav", prefix="s360-whisper-", dir="/dev/shm" if os.path.isdir("/dev/shm") else None
    )
    os.close(fd)
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def _segment(d):
    words = [
        types.SimpleNamespace(start=w["start"], end=w["end"], word=w["word"], probability=w["probability"])
        for w in d.get("words") or []
    ]
    return types.SimpleNamespace(
        start=d["start"],
        end=d["end"],
        text=d["text"],
        avg_logprob=d["avg_logprob"],
        no_speech_prob=d["no_speech_prob"],
        words=words or None,
    )


class ServiceWhisper:
    """A faster_whisper.WhisperModel stand-in whose work is done by strata-models."""

    def __init__(self, name, client=None):
        self.name = name
        self.role, self.model = MODELS[name]
        self.sm = client or _client()

    def _run(self, params):
        return self.sm.run(self.role, params, app=APP, model=self.model)

    def detect_language(self, audio):
        """(language, probability, [(code, probability), ...]) as faster-whisper gives it."""
        with _as_path(audio) as p:
            r = self._run(dict(path=p, detect_language_only=True))
        return r["language"], r["language_probability"], sorted(r["all_language_probs"].items(), key=lambda kv: -kv[1])

    def transcribe(self, audio, **kw):
        """(segments, info) as faster-whisper gives them; `clip_timestamps` is passed as the service's `clip`. Other options are refused, so a call
        that relies on one never silently runs without it."""
        unknown = set(kw) - set(PASS) - {"clip_timestamps"}
        if unknown:
            raise TypeError(f"strata-models whisper does not take {sorted(unknown)}")
        params = {k: v for k, v in kw.items() if k in PASS}
        if kw.get("clip_timestamps") is not None:
            params["clip"] = list(kw["clip_timestamps"])[:2]
        with _as_path(audio) as p:
            r = self._run(dict(path=p, **params))
        info = types.SimpleNamespace(
            language=r["language"], language_probability=r["language_probability"], duration=r["duration"]
        )
        return [_segment(s) for s in r["segments"]], info


def whisper_model(name, device=None, compute_type=None):
    """The model to transcribe with: strata-models when it can (use_service), else faster-whisper loaded here on `device` / `compute_type`."""
    if use_service(name):
        return ServiceWhisper(name)
    from faster_whisper import WhisperModel

    from strata360 import hw

    return WhisperModel(name, device=device or hw.whisper_args()[0], compute_type=compute_type or hw.whisper_args()[1])
