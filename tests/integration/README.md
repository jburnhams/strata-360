# Integration tests

Shared commands, layout, fixtures and file-ownership rules are in [`tests/README.md`](../README.md); read that first. This file is owned by integration-test work: update it freely. Unit notes and the gated coverage ledger live in [`tests/unit/README.md`](../unit/README.md).

## Fixtures and conventions

Run real ffmpeg/ffprobe on tiny synthetic clips (`tests/utils/synthetic_osv.py`: a 60-frame, 128 px two-lens HEVC OSV with the DJI data tracks, built in ~0.2 s). No footage, no models, no network. In CI they run in parallel (`-n auto`); locally `pytest tests/integration -n auto` takes about 40 s (serial: about 2 min, mostly `test_edit.py`).

| Fixture (`tests/integration/conftest.py`) | What it gives you |
| --- | --- |
| `cli` | `cli('run', folder, '--stages', 'ingest')` -> `Result(stdout, stderr, code, out)`, **in-process** (fast, and counted by coverage). Raises with the output on a non-zero exit unless `check=False`. |
| `cli_subprocess` | The same through a real `python -m strata360` process: for the entry-point smoke test and anything that must not share this process's state. Slower (each call re-imports numpy/cv2). |
| `library` | `library(n=2, name='trip')` -> a footage folder of `n` distinct clips (own file name and header time, 60 s apart) plus a hidden file and a `notes.txt` that must be ignored. |
| `processed` | A private, writable copy of a 2-clip project that has been through ingest, audio and exposure (the model-free stages). The original is built **once per session** (`processed_template`, ~6 s); a copy is instant, with absolute paths rewritten. Prefer this to running stages in every test. |
| `served` | `(client, folder)`: the HTTP API (`make_client`) over `processed`. |
| `fake_engine` | A speech engine that "speaks" a tone, 0.1 s per word (no TTS model): the `edit.voiceover` module with `ENGINES` replaced (restored by `monkeypatch`). |

Helpers in `tests/utils/library.py`: `make_library`, `copy_project`, `ffprobe`, `make_tone` (a sine WAV), `duration`.

Conventions on top of the ones above:
- **Decide whether it belongs here.** A test that needs ffmpeg, a real file layout, several modules together, or the CLI/HTTP boundary is an integration test. Pure logic on synthetic arrays belongs in `unit/` (and counts toward coverage), even if it is slow to run.
- **Share expensive state, never mutate it.** Build once per session (or module) in a fixture, copy per test (see `processed`). Don't re-run a pipeline stage in each test to get its output; only run the stage in the test that is *about* running it.
- Use `cli` in-process by default; assert on files the stage wrote (JSON facts, ffprobe of media), not just on printed text.
- Fake only what needs a model or a network (the speech engine, `fake_urlopen`); everything else is real.
- Keep each test under ~10 s and the whole suite parallel-safe (no fixed ports, no shared paths, no reliance on the working directory).
- Anything that would need a downloaded model is not an integration test here; it is a manual check (README section 0) or marked `slow`.

## Coverage ledger (integration suite, informational)

Not gated. Numbers come from `pytest tests/integration -n auto --cov --cov-fail-under=0 --cov-report=term-missing`. Record, for each module the integration tests exercise: integration coverage next to the unit number, and what is covered or still missing. Modules not listed have no integration tests of their own.

| Module | Integration cover | Tests | Notes / what remains |
| --- | --- | --- | --- |
| `pipeline/runner.py` | n/a | `test_runner.py` | worker concurrency, claim, cache signatures, clear |
| `pipeline/stages.py`, `pipeline/ingest.py` | n/a | `test_pipeline.py` | the model-free stages on the synthetic clip |
| `server/app.py` | n/a | `test_server.py`, `test_project_api.py` | endpoints over real project files |
| `edit/voiceover.py`, `edit/vo_fit.py` | n/a | `test_voiceover.py` | `respeak`/`fit_project` with the fake speech engine |
| `edit/music.py` | n/a | `test_music.py` | |
| `edit/optimise.py` | n/a | `test_edit.py` | slow pure computation (see Known issues) |
| `cli.py`, `render/*`, `audio/*` | n/a | | todo: fill in the first numbers from a fresh coverage run |

## Known issues

- `test_edit.py` (the optimiser on synthetic candidates, ~100 s) needs no ffmpeg: it is slow pure computation. Candidate to move to `tests/unit/` with smaller inputs (a job for the unit run), or to mark `slow`.
- A `RuntimeWarning: overflow encountered in divide` from `render/photo.py:64` appears when the synthetic clip goes through exposure (a division by a zero scale on the synthetic lens). Possible product bug; not hidden here.
- Old files here still assign module globals directly (`R.mem_available_gb = lambda...`, `L.time.sleep = ...`); convert them to `monkeypatch` when you touch them.
