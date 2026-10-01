# Task: add thorough backend unit tests to strata-360 (one PR, then stop)

You are a coding agent new to this repo. Find a coherent slice of **under-tested Python code**, cover it with thorough, best-practice unit tests, and extend and refactor the shared test helpers as you go. Open **one PR**, drive CI to green, then stop. This prompt is run many times: each run continues from the state the last one left, so choose work from the *current* coverage ledger and leave it up to date.

## 0. Orient yourself (read before writing anything)

1. Read `AGENTS.md` and `CLAUDE.md` at the repo root. They are authoritative. Web code (`web/`) is out of scope for this task.
2. Read **`tests/README.md`** in full: how to run things, the fixtures, the conventions and a per-module coverage ledger. Then read `tests/conftest.py`, `tests/unit/conftest.py`, `tests/utils/fakes.py`, `tests/utils/projects.py`, and the worked examples it lists: `tests/unit/test_server_api.py`, `test_llm_remote.py`, `test_track.py`, `test_fixtures.py`. Copy their style.
3. Layout: application code is in `src/strata360/` (`server/app.py` FastAPI; `pipeline/`, `edit/`, `analysis/`, `audio/`, `gps/`, `osv/`, `render/`, `cli.py`, `oslib.py`, `hw.py`). Unit tests are in `tests/unit/`, fast, hermetic (no ffmpeg, models, footage, network or real home folder; enforced by the autouse fixtures in `tests/conftest.py`). Integration tests (`tests/integration/`) need ffmpeg and are out of scope except to avoid breaking them.
4. Setup and commands, from the repo root: `pip install -r requirements-test.txt`, then
   - `pytest tests/unit --cov --cov-report=term-missing --cov-report=xml` (coverage gate: `fail_under` in `pyproject.toml`)
   - `pytest tests/unit -n auto` (parallel), `pytest tests/unit -p randomly --randomly-seed=N` (reproduce an order)
   - `ruff check src tests`
   - `diff-cover coverage.xml --compare-branch origin/main` (coverage of just your changed lines)
5. **GitHub Actions is the source of truth.** `unit.yml` runs the unit suite with coverage, ruff, and the web checks across Python 3.11–3.13 on Linux, macOS, and Windows (Windows is non-blocking). `integration.yml` runs the ffmpeg suites. The PR is done only when CI is green on the head commit. Code must be cross-platform: build paths with `os.path`, don't assume symlinks work (skip with a reason if they can't be created), and read AGENTS.md on `oslib.py`/`hw.py` before touching anything process- or hardware-related.

## 1. Choose the slice (data-driven, so reruns don't collide)

1. Open the **coverage ledger** in `tests/README.md` and cross-check it against a fresh `pytest tests/unit --cov --cov-report=term-missing` (or the latest CI log). The report wins on conflict.
2. Check what's in flight: `git log --oneline -20`, `git branch -a`, and the open PRs (GitHub MCP tools). Don't pick modules another branch or PR already covers. If an earlier run's PR for the same slice is still open, continue on it.
3. Pick **one cohesive slice**, about 2–5 related modules or 300–600 statements of missing coverage, ranked by:
   - logic density that can be tested without heavy dependencies (numpy/scipy math, parsing, state machines, config and path handling, retry/backoff, HTTP endpoints);
   - pure or near-pure code at 0–50% (`audio/dsp.py`, `audio/wordtimes.py`, `gps/clock.py`, `gps/context.py`, `gps/overview.py`, `osv/*`, `edit/voiceover.py`, `pipeline/ingest.py`, `pipeline/stages.py`, `edit/optimise.py`, `cli.py`, the rest of `server/app.py`'s endpoints);
   - bug-prone areas (concurrency, file locks, time and clock handling, input validation, security checks on paths).

   Test the pure parts of modules that need torch, whisper, ffmpeg, or a GPU, and fake the rest at the boundary (`fake_run`, `fake_popen`, `monkeypatch` on the single function that loads a model). Don't import heavyweight libraries that aren't in `requirements-test.txt`: if a module needs one at import time, import it lazily in the test or skip with `pytest.importorskip`.
4. State the chosen slice and why at the top of the PR description.
5. **Stop condition:** if every module is `done` (>= 90%, or a justified gap in the ledger), change nothing and say so. Don't invent work.

## 2. Reuse and extend the shared helpers (don't bypass them)

- Use the fixtures in `tests/README.md` instead of `tempfile.mkdtemp()`, hand-rolled `urlopen`/`Popen` fakes, or assigning to module globals. If a helper is missing, add it: a new double in `tests/utils/fakes.py` (with a fixture in `tests/conftest.py`, and a test in `tests/unit/test_fixtures.py`), a new builder in `tests/utils/projects.py` (e.g. `add_transcript`, a synthetic track, a `.wav` writer), or a new `tests/utils/<topic>.py` for something like numpy signal/track generators. Anything two test files share moves into `tests/utils/`.
- Add a new test dependency only for a clear reason (candidates: `fitdecode`/`gpxpy` if you test FIT/GPX loading, `freezegun`/`time-machine` if clock injection isn't enough), put it in `requirements-test.txt`, and say why in the PR.
- When you touch an older test file, convert it to the house style (see `test_llm_remote.py`): pytest functions/classes with plain `assert`, `monkeypatch`/`tmp_path`, no `sys.path` hacks, no `__main__` runner, no `assert False` in `try`, no module-global assignments. Preserve every assertion's meaning. Don't convert files outside your slice.
- Use `pytest-randomly` as a bug-finder: run your slice and the whole suite under several seeds (`--randomly-seed=1..5`) and with `-n 4`. A failure that depends on order is a leaked global: fix its cause (usually a direct assignment in an old test) with `monkeypatch`, and mention it in the PR.

## 3. How to write the tests

- Test behaviour through the public function (or HTTP endpoint via `client`), asserting exact values. Cover for each unit: the happy path, empty/missing input, malformed input (bad JSON, truncated files, NaNs), boundaries (zero, one, many; exact limits), each error branch, and idempotence/repeat calls. Use `--cov-report=term-missing` to find unreached lines, but don't write a test purely to touch a line without asserting something meaningful.
- `@pytest.mark.parametrize` for tables of cases; classes to group related tests; descriptive names that read as a sentence (`test_a_symlink_out_of_the_roots_is_not_followed`).
- **hypothesis** for numeric/parsing/interpolation code where an invariant is easy to state (bounds, monotonic, round-trip, idempotent, never raises on any input). Keep strategies bounded and fast.
- Assert side effects on the filesystem via `tmp_path`/`Project`; assert outgoing HTTP via `fake_urlopen.calls` and subprocess command lines via `fake_run`/`fake_popen`. Tests must pass alone, in any order, and in parallel, and must never touch the real home folder, repo files (e.g. `secrets.env`), the network, or real `time.sleep`.
- Don't change `src/` behaviour in a test-only PR. Allowed: tiny testability changes (a parameter with a default, extracting a pure function), called out in the PR. For a bug you find, write the test for the *correct* behaviour with `@pytest.mark.xfail(strict=True, reason='...')`, and list it under "Findings". Never skip, delete, or weaken an existing test, and never lower `fail_under`.

## 4. Update the ledger and the ratchet

- In `tests/README.md`, update the coverage ledger rows for every module you touched (percent from CI or the coverage report, `done`/`partial`/`todo`, notes on what remains), and keep the fixtures table and conventions current (new helpers, new gotchas).
- After CI is green and the total coverage is known, raise `fail_under` in `pyproject.toml` to the floor of the new total, rounded down (it only ratchets up). Do this in your last commit.
- Aim for >= 90% (line + branch) on the modules in your slice. Justify any gap in the ledger.

## 5. Verify locally

`pip install -r requirements-test.txt`, `ruff check src tests`, `pytest tests/unit --cov --cov-report=term-missing --cov-report=xml`, the suite under three random seeds and with `-n 4`, `diff-cover coverage.xml --compare-branch origin/main` (changed lines should be well covered), and `pytest tests/integration -x` if you touched shared fixtures or `tests/conftest.py` (needs ffmpeg with libx265; skip if unavailable and rely on CI). Mutation spot-check: break the source (flip a condition) for 2–3 representative tests, confirm they fail, then revert. Re-read your diff adversarially for tests that would still pass if the code were broken.

## 6. Branch, PR, and drive CI to green

- Use the branch name the environment gives you (otherwise `test/backend-coverage-<slice>` off the latest default branch). Make small logical commits (helpers -> tests per module -> ledger/ratchet). Push with `git push -u origin <branch>`.
- Open **one PR** (follow its PR template if the repo has one) as soon as the first meaningful commit is pushed; keep it a draft until CI is green if you can.
- Loop until CI is green on the latest head commit:
  1. Read results with the GitHub MCP tools (`actions_list`, `actions_get`, `get_job_logs`).
  2. If red, reproduce, root-cause, push a minimal fix, repeat. macOS- or Windows-only failures are usually path, line-ending, or symlink/permission assumptions: fix them in the test.
  3. If a failure is clearly not yours (the web jobs, Windows which is non-blocking, an infrastructure error), say so in one PR comment with the evidence and re-run at most once. Never mask a flake, skip tests, or push an empty commit to retrigger CI.
- The PR description must include: the slice and why (and what's left); coverage before -> after per module and overall (from CI); new dependencies/fixtures/helpers and which older tests were converted; "Findings" (bugs as xfails, order-dependence fixes, risky or untestable areas, any `src/` change).
- Finish by stating the CI status on the head commit, the PR link, and what remains. Don't merge. Don't start a second slice. If review comments or CI events arrive on your PR, handle them as part of this same PR.
