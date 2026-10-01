# Unit tests

Fast, hermetic tests of pure logic (synthetic data, fakes). Shared commands, layout, fixtures and file-ownership rules are in [`tests/README.md`](../README.md); read that first. This file is owned by unit-test work: update it freely. Integration notes live in [`tests/integration/README.md`](../integration/README.md).

## Conventions (unit suite, on top of the shared ones in `tests/README.md`)

- Cover the happy path, empty/missing input, malformed input, boundaries, and each error branch (`coverage --cov-report=term-missing` shows what's unreached).
- Property tests (hypothesis) for numeric, parsing and interpolation code where an invariant is easy to state (bounds, monotonic, round-trip, idempotent). Keep them cheap: the `unit` profile (50 examples, no deadline) is loaded in `unit/conftest.py`.
- No ffmpeg, models, or network: anything needing them is an integration test (`tests/integration`).
- Worked examples to copy: `test_server_api.py` (TestClient, fixtures, parametrize), `test_llm_remote.py` (an old script-style file converted: fake HTTP, key files, tiers), `test_track.py` (numeric code with hypothesis and tmp files).

## Coverage ledger (line+branch; update the rows you change)

Numbers from `pytest tests/unit --cov`. `done` = >= 90%. Modules not listed are 0% and `todo`. Dependencies that need models, ffmpeg or a GPU are noted: test their pure parts, and leave the rest to the integration suite.

| Module | Cover | Status / notes |
| --- | --- | --- |
| `server/app.py` | 34% | partial: auth, browse, last, open, notes, log, clips done; the rest of the endpoints todo (transcript, script, voiceover, film, final, music, track, edit, clock, who, state/clear/stop) |
| `gps/track.py` | 52% | partial: `at`, `to_gpx`, cache done; `load_fit`/`load_gpx` need fitdecode/gpxpy (add to requirements-test.txt to test them) |
| `edit/llm_remote.py` | 81% | partial: Vertex/Gemini/Claude request shape, retries and tiers done |
| `edit/chrono.py`, `transcript_edits.py`, `analysis/follow.py`, `render/parallax.py` | >= 94% | done |
| `analysis/candidates.py`, `edit/project.py`, `gps/anchors.py`, `render/seam.py`, `pipeline/clips.py`, `pipeline/config.py`, `pipeline/resources.py` | 81-91% | partial |
| `gps/clock.py`, `gps/context.py`, `gps/overview.py` | 100% | done |
| `overlay/*` | 98-100% | done: fake tile service (`utils/overlay_fakes.py`), synthetic tracks; never the network |
| `analysis/thumbs.py` | 46% | partial: the overlay thumbnail done; choosing the moment (`quick`, `best`) needs video |
| `pipeline/ingest.py` | 98% | done |
| `audio/speech.py` | 86% | partial: 101-112 (CLI) todo |
| `audio/wordtimes.py` | 96% | done: pure math and logic covered |
| `audio/dsp.py` | 53% | partial: signal metrics and basic functions done; heavy ffmpeg filters todo |
| `edit/voiceover.py`, `cli.py` | 0-10% | todo: mostly pure numpy/parsing: good candidates |
| `osv/*` | >= 91% | done |
| `pipeline/runner.py` | 84% | done (integration tests for worker concurrency, claim, cache signatures, clear) |
| `pipeline/coverage.py` | 100% | done: stage states, blocked decisions, CLI, API (`unit/test_coverage.py`) |
| `edit/blocks.py` | 99% | done: allocation, dropping, dialogue padding, automatic length, overrides (`unit/test_blocks.py`) |
| `edit/script.py` | 88% | partial: the per-block writer done (`unit/test_script_blocks.py`, scripted model); the beat-window writer and `segment_facts` todo |
| `edit/vo_measure.py` | 93% | done: speech extent, status checks, single and multi-line recordings, `vo.json` reuse (`unit/test_vo_measure.py`, scripted aligner; the real aligner is a manual check) |
| `edit/vo_fit.py` | 92% | done: block sizing, speed fallback, music placement, problems (`unit/test_vo_fit.py`); `respeak`/`fit_project` in `integration/test_voiceover.py` |
| everything else | see `--cov-report=term-missing` | todo |

## Known issues in the existing suite

- Several old files assign module globals directly (`R.mem_available_gb = lambda...`, `L.time.sleep = ...`); `restore_globals` papers over a few of them. Convert them to `monkeypatch` when you touch them.
- `test_workers.py` starts real processes and sleeps (about 5 s).
- Integration-side issues (slow `test_edit.py`, the exposure overflow warning) are listed in `tests/integration/README.md`.
