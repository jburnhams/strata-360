# Python tests

pytest 8, pytest-cov, **hypothesis**, **pytest-randomly**, **pytest-timeout**, pytest-xdist, diff-cover (`pip install -r requirements-test.txt`). The web tests are in `web/tests` (see `web/tests/README.md`).

```
pytest tests/unit --cov                    # unit suite + coverage (what CI gates on: fail_under in pyproject.toml, only ratchets up)
pytest tests/unit -n auto                  # in parallel
pytest tests/unit -p randomly --randomly-seed=N   # reproduce a failure from a CI run (the seed is in the header of every run)
pytest tests/unit/test_x.py -k name        # one test
pytest tests/integration                   # needs ffmpeg with libx265 (slow: builds a synthetic clip)
ruff check src tests
diff-cover coverage.xml --compare-branch origin/main    # after `--cov-report=xml`: coverage of just the lines your change touches
```

## Layout

- `unit/`: fast, no ffmpeg or models.
- `integration/`: real ffmpeg/ffprobe, the CLI, the pipeline, the HTTP API over real project files, the optimiser. Not part of the coverage gate. See "Integration tests" below.
- Both suites are hermetic (autouse in `conftest.py`): `~` and `STRATA_RACES` point into a tmp dir outside `tmp_path`, API-key variables are removed, and any outbound (non-loopback) connection fails the test.
- `utils/`: helpers importable by name in any test (`from fakes import ...`, `from projects import ...`; `tests/utils` is on `pythonpath`).
- `conftest.py`: shared fixtures (below) and `restore_globals`, a safety net for old tests that assign module globals directly. Don't rely on it in new tests.
- One test file per module (`edit/script.py` -> `unit/test_script.py`; add to the existing file if there is one).

## Fixtures (use these; extend them when something is missing)

| Fixture | What it gives you |
| --- | --- |
| `tmp_path`, `monkeypatch` | pytest built-ins. Use instead of `tempfile.mkdtemp()` and direct assignment such as `module.fn = lambda ...` (these leak into other tests). |
| `fake_urlopen` | Scripts `urllib.request.urlopen`: `fake_urlopen.reply({...}, http_error(429, {...}))`; assert on `fake_urlopen.calls` (`url`, `method`, `headers` lower-cased, `body` parsed from JSON). An unexpected request fails the test. |
| `fake_popen` | `subprocess.Popen` replaced: nothing starts. `fake_popen.instances[i].cmd` / `.kw`. |
| `fake_run` | `subprocess.run` / `check_output` replaced: `.calls`, `.returns['ffprobe'] = b'...'`, `.code = 1`. |
| `no_sleep` | `time.sleep` returns at once; `no_sleep.delays` lists the requested delays. |
| `make_project`, `project` | On-disk project (`<footage>/strata360/...`): `make_project('trip', config=True, clips=[...])`, `project.add_clip(id, motion={...})`, `.write_json`, `.read_json`, `.path(...)`. `project` is ready-made with race.json and one clip. (`utils/projects.py`) |
| `make_client`, `client` | FastAPI `TestClient` over `server.app.create_app` with roots in `tmp_path`, an isolated server state file and job tables, and workers faked (`fake_popen`). `make_client(roots=[...], token='x')` for other setups. |
| `synthetic_osv` | (integration) one tiny real OSV clip built with ffmpeg once per session; skips the test when ffmpeg/libx265 is missing. |

## Conventions

- pytest style: `def test_...` / small classes to group, plain `assert`, `pytest.raises(..., match=...)`, `@pytest.mark.parametrize`. No `sys.path` hacks, no `if __name__ == '__main__'` runners, no `assert False` inside `try`. (Older test files still have them; convert a file when you touch it, as `test_llm_remote.py` shows.)
- Test behaviour through the public function or HTTP endpoint, with specific assertions (exact values, not `is not None`). Cover the happy path, empty/missing input, malformed input, boundaries, and each error branch (`coverage --cov-report=term-missing` shows what's unreached).
- Property tests (hypothesis) for numeric, parsing and interpolation code where an invariant is easy to state (bounds, monotonic, round-trip, idempotent). Keep them cheap: the `unit` profile (50 examples, no deadline) is loaded in `unit/conftest.py`.
- A test must pass in any order and alone (pytest-randomly shuffles every run) and must not touch the real home folder, repo files such as `secrets.env`, the network or ffmpeg.
- No `time.sleep` in tests: use `no_sleep`, or inject the clock. Mark anything needing ffmpeg/models as integration (put it in `tests/integration`).
- Never "fix" the code to make a test pass in a test-only change. A bug found while testing: write the test for the correct behaviour with `@pytest.mark.xfail(strict=True, reason='...')`, and list it in the PR.
- `unit/test_fixtures.py` tests the doubles themselves: extend it when you extend a double.
- Worked examples to copy: `unit/test_server_api.py` (TestClient, fixtures, parametrize), `unit/test_llm_remote.py` (an old script-style file converted: fake HTTP, key files, tiers), `unit/test_track.py` (numeric code with hypothesis and tmp files).

## Integration tests

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

## Coverage ledger (unit suite, line+branch; update the rows you change)

Numbers from `pytest tests/unit --cov`. `done` = >= 90%. Modules not listed are 0% and `todo`. Dependencies that need models, ffmpeg or a GPU are noted: test their pure parts, and leave the rest to the integration suite.

| Module | Cover | Status / notes |
| --- | --- | --- |
| `server/app.py` | 34% | partial: auth, browse, last, open, notes, log, clips done; the rest of the endpoints todo (transcript, script, voiceover, film, final, music, track, edit, clock, who, state/clear/stop) |
| `gps/track.py` | 52% | partial: `at`, `to_gpx`, cache done; `load_fit`/`load_gpx` need fitdecode/gpxpy (add to requirements-test.txt to test them) |
| `edit/llm_remote.py` | 81% | partial: Vertex/Gemini/Claude request shape, retries and tiers done |
| `edit/chrono.py`, `transcript_edits.py`, `analysis/follow.py`, `render/parallax.py` | >= 94% | done |
| `analysis/candidates.py`, `edit/project.py`, `gps/anchors.py`, `render/seam.py`, `pipeline/clips.py`, `pipeline/config.py`, `pipeline/resources.py` | 81-91% | partial |
| `gps/clock.py`, `gps/context.py`, `gps/overview.py` | 100% | done |
| `osv/*` | >= 90% | done |
| `audio/dsp.py`, `audio/wordtimes.py`, `audio/speech.py`, `edit/voiceover.py`, `pipeline/ingest.py`, `cli.py` | 0-10% | todo: mostly pure numpy/parsing: good candidates |
| `pipeline/runner.py` | 84% | done (integration tests for worker concurrency, claim, cache signatures, clear) |
| everything else | see `--cov-report=term-missing` | todo |

## Known issues in the existing suite

- `integration/test_edit.py` (the optimiser on synthetic candidates, ~100 s) needs no ffmpeg: it is slow pure computation. Candidate to move to `unit/` with smaller inputs, or to mark `slow`.
- A `RuntimeWarning: overflow encountered in divide` from `render/photo.py:64` appears when the synthetic clip goes through exposure (a division by a zero scale on the synthetic lens). Possible product bug; not hidden here.
- Several old files assign module globals directly (`R.mem_available_gb = lambda...`, `L.time.sleep = ...`); `restore_globals` papers over a few of them. Convert them to `monkeypatch` when you touch them.
- `test_workers.py` starts real processes and sleeps (about 5 s).
