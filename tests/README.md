# Python tests

pytest 8, pytest-cov, **hypothesis**, **pytest-randomly**, **pytest-timeout**, pytest-xdist, diff-cover (`pip install -r requirements-test.txt`). The web tests are in `web/tests` (see `web/tests/README.md`).

This file holds only what **both** Python suites share, and it is rarely edited. Each suite keeps its own notes and ledger so that parallel work on them does not collide:

| Suite | Notes, fixtures and ledger |
| --- | --- |
| Unit (`tests/unit/`) | [`tests/unit/README.md`](unit/README.md): conventions, coverage ledger, known issues |
| Integration (`tests/integration/`) | [`tests/integration/README.md`](integration/README.md): fixtures, conventions, ledger, known issues |
| Web (`web/tests/`) | [`web/tests/README.md`](../web/tests/README.md) |

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
- `integration/`: real ffmpeg/ffprobe, the CLI, the pipeline, the HTTP API over real project files, the optimiser. Not part of the coverage gate.
- Both suites are hermetic (autouse in `conftest.py`): `~` and `STRATA_RACES` point into a tmp dir outside `tmp_path`, API-key variables are removed, and any outbound (non-loopback) connection fails the test.
- `utils/`: helpers importable by name in any test (`from fakes import ...`, `from projects import ...`; `tests/utils` is on `pythonpath`).
- `conftest.py`: shared fixtures (below) and `restore_globals`, a safety net for old tests that assign module globals directly. Don't rely on it in new tests.
- One test file per module (`edit/script.py` -> `unit/test_script.py`; add to the existing file if there is one).

## Who owns which files (so parallel branches don't conflict)

Unit-test work and integration-test work may run at the same time on separate branches. Keep to these rules:

| Area | Unit work | Integration work |
| --- | --- | --- |
| Tests | `tests/unit/**` | `tests/integration/**` |
| Fixtures | `tests/conftest.py`, `tests/unit/conftest.py` | `tests/integration/conftest.py` only |
| Helpers | `tests/utils/fakes.py`, `projects.py`, `overlay_fakes.py`, `pbdump_fakes.py`, new `tests/utils/<topic>.py` | `tests/utils/library.py`, `synthetic_osv.py`, new `tests/utils/integration_<topic>.py` |
| Notes and ledger | `tests/unit/README.md` | `tests/integration/README.md` |
| Coverage gate | `fail_under` in `pyproject.toml` (the only writer) | none: integration coverage is informational |

- Don't edit a file the other column owns. If you truly need a shared fixture or helper changed, add your own variant in a file you own (an `integration_*.py` helper, a fixture in `tests/integration/conftest.py`) and note the duplication in your README. Never rewrite `tests/conftest.py` or an existing helper's behaviour from integration work.
- Don't edit `tests/README.md` (this file), `AGENTS.md`, `CLAUDE.md`, `requirements-test.txt` or `.github/workflows/*` unless the task cannot be done without it; say why in the PR.
- Module ownership, so both don't pick the same slice: integration work takes `cli.py`, `pipeline/runner.py`, `pipeline/stages.py`, `render/*`, `edit/music.py`, the film audio mix, and the `server/app.py` endpoints that need real media (thumb, preview, film/final job control, uploads). Unit work takes everything else, including the pure parts of those modules that need no ffmpeg (argument parsing, config and path logic, helpers) and the other `server/app.py` endpoints. When a module is on both sides, unit work covers pure functions and integration work covers real-media behaviour. Check the other suite's README ledger first.
- Pure logic found in integration work is not moved to `tests/unit/` by that run: list it under "Known issues" in `tests/integration/README.md` as a candidate for the unit run.

## Fixtures (use these; extend them when something is missing)

| Fixture | What it gives you |
| --- | --- |
| `tmp_path`, `monkeypatch` | pytest built-ins. Use instead of `tempfile.mkdtemp()` and direct assignment such as `module.fn = lambda ...` (these leak into other tests). |
| `overlay_fakes` (utils) | `race_track(...)` (a straight run as track arrays), `TileServer()` (a tile service in memory: pass as `Tiles(fetch=...)`; `.urls`, `.fail`), `T0`. |
| `fake_urlopen` | Scripts `urllib.request.urlopen`: `fake_urlopen.reply({...}, http_error(429, {...}))`; assert on `fake_urlopen.calls` (`url`, `method`, `headers` lower-cased, `body` parsed from JSON). An unexpected request fails the test. |
| `fake_popen` | `subprocess.Popen` replaced: nothing starts. `fake_popen.instances[i].cmd` / `.kw`. |
| `fake_run` | `subprocess.run` / `check_output` replaced: `.calls`, `.returns['ffprobe'] = b'...'`, `.code = 1`. |
| `no_sleep` | `time.sleep` returns at once; `no_sleep.delays` lists the requested delays. |
| `make_project`, `project` | On-disk project (`<footage>/strata360/...`): `make_project('trip', config=True, clips=[...])`, `project.add_clip(id, motion={...})`, `.write_json`, `.read_json`, `.path(...)`. `project` is ready-made with race.json and one clip. (`utils/projects.py`) |
| `make_client`, `client` | FastAPI `TestClient` over `server.app.create_app` with roots in `tmp_path`, an isolated server state file and job tables, and workers faked (`fake_popen`). `make_client(roots=[...], token='x')` for other setups. |
| `synthetic_osv` | (integration) one tiny real OSV clip built with ffmpeg once per session; skips the test when ffmpeg/libx265 is missing. |

## Shared conventions (both suites)

- pytest style: `def test_...` / small classes to group, plain `assert`, `pytest.raises(..., match=...)`, `@pytest.mark.parametrize`. No `sys.path` hacks, no `if __name__ == '__main__'` runners, no `assert False` inside `try`. (Older test files still have them; convert a file when you touch it, as `test_llm_remote.py` shows.)
- Test behaviour through the public function, CLI or HTTP endpoint, with specific assertions (exact values, not `is not None`).
- A test must pass in any order, alone and in parallel (pytest-randomly shuffles every run) and must not touch the real home folder, repo files such as `secrets.env`, or the network.
- No `time.sleep` in tests: use `no_sleep`, or inject the clock.
- Never "fix" the code to make a test pass in a test-only change. A bug found while testing: write the test for the correct behaviour with `@pytest.mark.xfail(strict=True, reason='...')`, and list it in the PR.
- `unit/test_fixtures.py` tests the doubles in `tests/utils/fakes.py`: extend it when you extend a double.
