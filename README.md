# strata-360

Turns the short 360° clips shot during an ultramarathon (DJI Osmo 360 `.OSV` today) into one edited, reframed flat film, with a voice-over, music, and the race's GPS map overlay kept in time with the footage. Everything runs locally; a browser app on top drives the processing and the edit.

## Quick start

```bash
scripts/setup_env.sh --fetch-models      # once per machine: environment, pinned packages, models
./strata360 doctor                       # checks the environment and says how to fix anything missing
./strata360 serve --root ~/footage       # the web app: pick a footage folder, process it, edit, render
```

Command-line equivalents (`open`, `run`, `progress`, `script`, `voiceover`, `film`, `final`, ...) are in [overview section 0](docs/overview.md#0-quick-start-running-the-pipeline-on-a-new-race-collection). On Windows use `python -m strata360` instead of `./strata360`.

## Documentation

| Document | What it is |
|---|---|
| [docs/overview.md](docs/overview.md) | The design brief: goals, architecture, data contracts, each phase, the edit model and the GUI. Code comments cite its sections as "README N". |
| [docs/implementation-plan.md](docs/implementation-plan.md) | What to build next, in order, with acceptance tests. |
| [docs/progress.md](docs/progress.md) | The log of what was tried, measured and decided. |
| [docs/notes-and-script.md](docs/notes-and-script.md) | Notes, and how the voice-over script is written. |
| [docs/prompts/](docs/prompts/) | Prompts for writing backend unit, integration and web tests. |
| [AGENTS.md](AGENTS.md) | Repository conventions, commands and CI (for people and coding agents). |
| [tests/README.md](tests/README.md), [web/tests/README.md](web/tests/README.md) | How the Python and web tests are organised, fixtures and coverage ledgers. |

## Tests

```bash
pip install -r requirements-test.txt
pytest tests/unit --cov                  # fast unit suite with coverage
pytest tests/integration -n auto         # needs ffmpeg with libx265
cd web && npm run test:coverage          # web unit tests
```

Licence notices for ported work are in [NOTICE](NOTICE).
