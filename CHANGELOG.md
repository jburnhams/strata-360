# Changelog

Newest first, grouped by day. One entry per change, in the same commit or PR as the change.

## 2026-11-09

**Move the Python side to uv, ruff, pyright and the shared strata-python gate (branch `claude/project-thread-iw7199`)**
Jonathan asked for every Python project to use the same tooling as [python-app-template](https://github.com/jburnhams/python-app-template): uv, ruff with `ruff format`, pyright and ty, one `scripts/check` gate, and dependencies kept current. Behaviour of the program is unchanged.

- `pyproject.toml`, `uv.lock`: **new**. The light dependencies, a `dev` group (test tooling, ruff, pyright, ty, `mcp`, `numba`), git sources for `strata-python` and `strata-models-client`, tool configuration (ruff `E,F,I,B,UP,SIM,RUF,C4,PT,S,TID` with `pytest.importorskip` banned, pyright strict ratchet starting at `__init__.py`, ty). The heavy model stack stays in `requirements.txt`, `requirements-vision.txt` and `requirements-cv.txt` on purpose: torch is not locked because the right build depends on the card. On a GPU machine use `uv sync --locked --no-dev --inexact` and then the requirements files; an exact sync would remove torch. `requirements-test.txt`: **removed**.
- ruff: line length 120 and `ruff format` over `src`, `tests`, `scripts` and `format.py` (`docs/`, `spike/` and `web/` are excluded). Rules the existing code breaks are ignored with a reason in `pyproject.toml`; B023, F841, RUF071 and B005 can hide bugs and are the first to clean up.
- `src/strata360/render/preview.py`, `src/strata360/edit/blocks.py`: keep imports other modules and tests read as `preview.audio_of` and `blocks.MIN_SEG_S` (ruff's unused-import fix had removed them; the unit tests caught it).
- `src/strata360/__init__.py`, `src/strata360/edit/upscale.py`: annotations and `noqa` for the strict ratchet and for the `import torch` availability probe.
- `tests/unit`: `importorskip` of `mcp`, `numba`, `torch` and `spandrel` replaced by plain imports (they are in the dev group or installed by the torch-cpu action), so a missing dependency fails instead of skipping.
- `.github/workflows/unit.yml`, `integration.yml`: uv, current action versions, `strata-check --fast` once on Linux 3.13, CPU torch through `.github/actions/torch-cpu` (**new**); the ffmpeg and libx265 steps are unchanged. `upgrade-strata-python.yml`: **new**, weekly PR that moves the library pin after the gate. `.github/dependabot.yml`: **new**, daily, minor and patch grouped, no ignores (Actions, npm, uv, and pip for the kept requirements files).
- `scripts/check`: **new**. `README.md`, `AGENTS.md`, `tests/README.md`, `tests/unit/README.md`, `docs/`: commands for uv.
- Python coverage floor stays at 74 (74.41% on the unit suite). Locally in a sandbox without DNS or torch, `test_the_network_is_blocked_in_unit_tests` and `test_upscale::TestLoad` fail for the environment, not the code; CI installs torch.
- Not adopted here: strata-python's `oslib`, settings and server skeleton, and its pytest plugin (this app has its own isolation in `tests/conftest.py`).
