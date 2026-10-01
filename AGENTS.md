# Repository Guidelines

- Python application code lives in `src/strata360/`; the React web app lives in `web/src/` and builds into `src/strata360/server/static/`.
- Python tests live under `tests/`, grouped by type:
  - `tests/unit/`: fast, isolated tests of pure logic (synthetic data, fakes). No ffmpeg, models or real footage.
  - `tests/integration/`: slower tests that run ffmpeg/ffprobe, the CLI, the server, or the full optimiser. They build a tiny synthetic OSV with `tests/utils/synthetic_osv.py` (the `synthetic_osv` fixture); real footage (`videos/`) is gitignored and never required.
  - `tests/utils/`: shared helpers. `tests/conftest.py` holds shared fixtures and restores patched globals after each test.
- Web tests live in `web/tests/{unit,integration,utils}` (vitest; unit runs in node, integration in jsdom).
- Commands (Python, from the repo root; `pip install -r requirements-test.txt` is enough for the suites):
  - `pytest tests/unit --cov` runs the unit suite with coverage.
  - `pytest tests/integration` runs the integration suite (needs ffmpeg with libx265).
  - `ruff check src tests` lints for syntax errors and undefined names.
- Commands (web, from `web/`): `npm run test:unit`, `npm run test:integration`, `npm run test:coverage`, `npm run typecheck`, `npm run build`.
- Code coverage is calculated from the unit suites only (Python `fail_under` in `pyproject.toml`, which only ratchets up).
- New tests use pytest style (`def test_...` with `assert`; use the `monkeypatch`/`tmp_path` fixtures instead of patching globals by hand).
- Cross-platform: ffmpeg hardware options (decode acceleration, encoders, GPU) come from `src/strata360/hw.py`, which picks VideoToolbox on macOS, NVENC on Windows when present, and software otherwise; never hard-code `videotoolbox` elsewhere. `STRATA_HWACCEL` and `STRATA_ENCODER=software` override it.
- OS differences other than video hardware (file locks, process liveness and termination, priority, free memory, how to start the CLI) live in `src/strata360/oslib.py`; do not import `fcntl` or call `os.kill(pid, 0)` elsewhere (on Windows that kills the process).
- GitHub Actions: `unit.yml` (Python 3.11 to 3.13 on Linux, plus macOS, plus Windows (non-blocking for now), unit tests with coverage, lint, web typecheck, unit tests and build) and `integration.yml` (synthetic-clip integration tests on Linux, macOS and Windows (non-blocking for now), plus web integration tests; also weekly). Model-dependent checks (transcription, alignment, exposure on real footage) are run by hand: see README section 0.
