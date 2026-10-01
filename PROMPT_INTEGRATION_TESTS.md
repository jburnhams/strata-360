# Task: add thorough integration tests to strata-360 (one PR, then stop)

You are a coding agent new to this repo. Find a coherent slice of **pipeline, CLI, server or media behaviour that has no integration test**, cover it with thorough, best-practice tests on tiny synthetic clips, and extend and refactor the shared fixtures as you go. Open **one PR**, drive CI to green, then stop. This prompt is run many times: each run continues from the state the last one left, so choose work from the *current* ledger and leave it up to date.

## 0. Orient yourself (read before writing anything)

1. Read `AGENTS.md` and `CLAUDE.md` at the repo root. They are authoritative. The web app (`web/`) is out of scope.
2. Read **`tests/README.md`** in full: especially "Integration tests", the fixtures table, the conventions and the ledger. Then read `tests/conftest.py`, `tests/integration/conftest.py`, `tests/utils/library.py`, `tests/utils/synthetic_osv.py` (what the synthetic clip is and how it's built), and the worked examples: `tests/integration/test_pipeline.py`, `test_project_api.py`, `test_voiceover.py`. Copy their style.
3. What integration means here: a test that needs real **ffmpeg/ffprobe**, a real on-disk project layout, several modules together, or the CLI/HTTP boundary. Pure logic on synthetic arrays is a *unit* test (see `PROMPT_BACKEND_UNIT_TESTS.md`); put it in `tests/unit/`, where it counts toward coverage. Nothing may need a downloaded model, a GPU, real footage (`videos/` is gitignored and never required), or the network.
4. Setup: `pip install -r requirements-test.txt`, and ffmpeg/ffprobe with libx265 on PATH (`ffmpeg -hide_banner -encoders | grep libx265`). Commands from the repo root: `pytest tests/integration -n auto` (about 40 s), `pytest tests/integration/test_x.py -k name`, `pytest tests/integration -p randomly --randomly-seed=N` (reproduce an order), `pytest tests/integration --durations=15`, `ruff check src tests`. If ffmpeg isn't available in your environment, write the tests anyway and let CI run them, but say so in the PR.
5. **GitHub Actions is the source of truth.** `integration.yml` runs this suite on Linux, macOS and Windows (Windows non-blocking), plus the web integration tests, and weekly. `unit.yml` runs lint and the unit suite. The PR is done only when CI is green on the head commit. Code must be cross-platform: build paths with `os.path`/`pathlib`, never assume symlinks or POSIX permissions (skip with a reason), never hard-code `videotoolbox` (read the `hw.py`/`oslib.py` notes in AGENTS.md); CI VMs have no video hardware (`STRATA_HWACCEL`/`STRATA_ENCODER=software` are set by the workflow).

## 1. Choose the slice (data-driven, so reruns don't collide)

1. Open the ledger in `tests/README.md` and cross-check it against a fresh coverage run of the integration suite: `pytest tests/integration -n auto --cov --cov-fail-under=0 --cov-report=term-missing` (informational only: coverage gating is unit-only), or the latest CI log. Look for modules that unit tests can't reach but integration can: `cli.py` commands, `pipeline/runner.py` (workers, claims, retries, clear), `pipeline/stages.py`, `pipeline/ingest.py`, `osv/*` (mp4/telemetry/meta/calibration parsing on the synthetic file), `audio/dsp.py` and `audio/speech.py` (the ffmpeg-based parts), `render/proxy.py`, `render/preview.py`, `render/final.py`, `render/flat.py` (small renders), `edit/music.py` and the film audio mix, `server/app.py` endpoints that need real media (thumb, preview, film/final job control, uploads of music/track).
2. Check what's in flight: `git log --oneline -20`, `git branch -a`, open PRs (GitHub MCP tools). Don't pick what another branch or PR covers. If an earlier run's PR for the same slice is still open, continue on it.
3. Pick **one cohesive slice**: aim for 15–30 tests across 1–3 files. Prefer behaviour users depend on (resumable jobs, cached/stale handling, error reporting), things that broke before (see `git log --grep fix`), and boundaries (bad/truncated/missing input files, empty library, unsupported extension, a clip with no audio, dropped frames at the start/end, two clips with overlapping times).
4. State the chosen slice and why at the top of the PR description.
5. **Stop condition:** if the ledger shows nothing valuable left that can be tested without models or hardware, change nothing and say so. Don't invent work.

## 2. Reuse and extend the shared fixtures (don't bypass them)

- Use `cli` (in-process) for commands, `library(n)` for footage, `processed` for "stages already ran" (copying it is instant), `served` for the HTTP API over it, `fake_engine` for speech, `fake_urlopen`/`fake_popen`/`fake_run`/`no_sleep` from the shared conftest for the outside world. **Never** re-run a pipeline stage in a test just to obtain its output. Only run it in the test that is *about* running it.
- If you need a different shared state, add a fixture instead of building it inside tests: another session-scoped template next to `processed_template` (e.g. a project that has also gone through `motion` and `candidates`, a clip with no audio, a clip whose header is corrupt: add parameters to `build_osv`/`make_library` or a small wrapper in `tests/utils/`), always copied per test, never mutated in place. Add helpers (a `corrupt_file`, `make_video`, `read_wav`...) to `tests/utils/library.py` or a new `tests/utils/<topic>.py`. Anything two test files share moves into `tests/utils/` or a conftest.
- When you touch an older file (`test_server.py`, `test_music.py`, `test_edit.py`), convert it to the house style: pytest functions/classes with plain `assert`, fixtures instead of `tempfile.mkdtemp()`, `sys.path` hacks, `__main__` runners and module-global assignments (`monkeypatch` instead). Preserve every assertion's meaning. If a test needs no ffmpeg and is pure logic, move it to `tests/unit/` instead and say so. Don't convert files outside your slice.
- Add a test dependency only for a clear reason, put it in `requirements-test.txt`, and say why in the PR.

## 3. How to write the tests

- Assert on **artifacts**, not just printed text: the JSON a stage wrote (exact fields and values), `ffprobe` of rendered media (duration within tolerance, codec, size, stream count), the HTTP response and the files an endpoint created, exit codes and the error message on failure (`cli(..., check=False)`).
- Cover for each behaviour: happy path; idempotent re-run (nothing redone); a changed input or config invalidating exactly what it should (cache/stale keys); missing and malformed inputs (truncated OSV, zero-byte file, wrong extension, unreadable folder); partial failure (one clip bad, the others still processed, the failure reported, `--fail-fast`); cancellation and resume where applicable; concurrency (two workers on one project: claims, no double work: `runner.workers`, `claim`); the security boundary for server paths and uploads.
- Keep each test under ~10 s; share expensive state through fixtures; no `time.sleep` (poll with a deadline helper if you must wait for a job, never a bare sleep); no fixed ports (use `TestClient`); no dependence on the working directory or on test order. The suite must pass alone, in random order (`pytest-randomly` runs by default), and in parallel (`-n auto`).
- Tolerances for media: durations ±0.05–0.1 s, never exact float equality; don't assert on encoder-specific bytes or sizes.
- Don't change `src/` behaviour in a test-only PR. Allowed: a tiny testability change (a parameter with a default), called out in the PR. A bug found: write the test for the *correct* behaviour with `@pytest.mark.xfail(strict=True, reason='...')` and list it under "Findings". Never skip, delete or weaken an existing test.

## 4. Update the ledger

In `tests/README.md`, update the coverage/ledger notes for every module your tests exercise, record new fixtures and gotchas under "Integration tests", and move anything you found slow or mislabelled into "Known issues" (or fix it if it's in your slice). Put the integration-suite coverage you measured next to the unit numbers for the modules you touched, labelled informational.

## 5. Verify locally

`ruff check src tests`; `pytest tests/integration -n auto` and again serially with a few `--randomly-seed` values (the first run's seed is in the header); `pytest tests/unit -q` if you touched shared conftest or fixtures; `--durations=15` to check nothing you added is slow (>10 s: share state or shrink the clip). Mutation spot-check: break the source (flip a condition) for 2–3 representative tests, confirm they fail, then revert. Re-read your diff adversarially for tests that would still pass if the code were broken.

## 6. Branch, PR, and drive CI to green

- Use the branch name the environment gives you (otherwise `test/integration-<slice>` off the latest default branch). Make small logical commits (fixtures/helpers -> tests -> ledger). Push with `git push -u origin <branch>`.
- Open **one PR** (follow its PR template if the repo has one) as soon as the first meaningful commit is pushed; keep it a draft until CI is green if you can.
- Loop until CI is green on the latest head commit:
  1. Read results with the GitHub MCP tools (`actions_list`, `actions_get`, `get_job_logs`); the `--durations=10` output in the integration job shows what's slow.
  2. If red, reproduce, root-cause, push a minimal fix, repeat. macOS/Windows-only failures are usually path separators, line endings, file locking/open files on Windows, timing, or an ffmpeg build difference: fix the test (or skip with a precise reason only when the platform genuinely can't do it).
  3. If a failure is clearly not yours (the web jobs, Windows which is non-blocking, an infrastructure error), say so in one PR comment with the evidence and re-run at most once. Never mask a flake, skip tests to get green, or push an empty commit to retrigger CI.
- The PR description must include: the slice and why (and what's left); tests added and files converted; new fixtures/helpers; suite duration before -> after (from the CI log) and the slowest new tests; "Findings" (bugs as xfails, slow or mislabelled tests, product warnings, any `src/` change).
- Finish by stating the CI status on the head commit, the PR link, and what remains. Don't merge. Don't start a second slice. If review comments or CI events arrive on your PR, handle them as part of this same PR.
