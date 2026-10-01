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

- `unit/`: fast, hermetic, no ffmpeg or models. Hermetic is enforced by `unit/conftest.py` (autouse): `~` and `STRATA_RACES` point into a tmp dir, API-key variables are removed, and any outbound network connection fails the test.
- `integration/`: ffmpeg/ffprobe, the CLI, the full pipeline (uses the `synthetic_osv` fixture). Not part of the coverage gate.
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
| `synthetic_osv` | (integration) a tiny real OSV clip built with ffmpeg. |

## Conventions

- pytest style: `def test_...` / small classes to group, plain `assert`, `pytest.raises(..., match=...)`, `@pytest.mark.parametrize`. No `sys.path` hacks, no `if __name__ == '__main__'` runners, no `assert False` inside `try`. (Older test files still have them; convert a file when you touch it, as `test_llm_remote.py` shows.)
- Test behaviour through the public function or HTTP endpoint, with specific assertions (exact values, not `is not None`). Cover the happy path, empty/missing input, malformed input, boundaries, and each error branch (`coverage --cov-report=term-missing` shows what's unreached).
- Property tests (hypothesis) for numeric, parsing and interpolation code where an invariant is easy to state (bounds, monotonic, round-trip, idempotent). Keep them cheap: the `unit` profile (50 examples, no deadline) is loaded in `unit/conftest.py`.
- A test must pass in any order and alone (pytest-randomly shuffles every run) and must not touch the real home folder, repo files such as `secrets.env`, the network or ffmpeg.
- No `time.sleep` in tests: use `no_sleep`, or inject the clock. Mark anything needing ffmpeg/models as integration (put it in `tests/integration`).
- Never "fix" the code to make a test pass in a test-only change. A bug found while testing: write the test for the correct behaviour with `@pytest.mark.xfail(strict=True, reason='...')`, and list it in the PR.
- `unit/test_fixtures.py` tests the doubles themselves: extend it when you extend a double.
- Worked examples to copy: `unit/test_server_api.py` (TestClient, fixtures, parametrize), `unit/test_llm_remote.py` (an old script-style file converted: fake HTTP, key files, tiers), `unit/test_track.py` (numeric code with hypothesis and tmp files).

## Coverage ledger (unit suite, line+branch; update the rows you change)

Numbers from `pytest tests/unit --cov`. `done` = >= 90%. Modules not listed are 0% and `todo`. Dependencies that need models, ffmpeg or a GPU are noted: test their pure parts, and leave the rest to the integration suite.

| Module | Cover | Status / notes |
| --- | --- | --- |
| `server/app.py` | 34% | partial: auth, browse, last, open, notes, log, clips done; the rest of the endpoints todo (transcript, script, voiceover, film, final, music, track, edit, clock, who, state/clear/stop) |
| `gps/track.py` | 100% | done |
| `edit/llm_remote.py` | 81% | partial: Vertex/Gemini/Claude request shape, retries and tiers done |
| `edit/chrono.py`, `transcript_edits.py`, `analysis/follow.py`, `render/parallax.py` | >= 94% | done |
| `analysis/candidates.py`, `edit/project.py`, `gps/anchors.py`, `render/seam.py`, `pipeline/clips.py`, `pipeline/config.py`, `pipeline/resources.py` | 81-91% | partial |
| `audio/dsp.py`, `audio/wordtimes.py`, `audio/speech.py`, `osv/*`, `edit/voiceover.py`, `pipeline/ingest.py`, `cli.py` | 0-10% | todo: mostly pure numpy/parsing: good candidates |
| `gps/clock.py`, `gps/context.py`, `gps/overview.py` | 98-100% | done |
| everything else | see `--cov-report=term-missing` | todo |

## Known issues in the existing suite

- Several old files assign module globals directly (`R.mem_available_gb = lambda...`, `L.time.sleep = ...`); `restore_globals` papers over a few of them. Convert them to `monkeypatch` when you touch them.
- `test_workers.py` starts real processes and sleeps (about 5 s).
