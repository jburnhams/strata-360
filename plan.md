1. **Goal:** Add thorough integration tests for the rough mix API endpoints in `src/strata360/server/app.py`. The endpoints to test are:
   - `GET /api/script2/mix` (`get_rough_mix`)
   - `POST /api/script2/mix` (`post_rough_mix`)
   - `DELETE /api/script2/mix` (`delete_rough_mix`)
   - `GET /api/script2/mix/audio` (`get_rough_mix_audio`)

2. **File:** I will create a new test file `tests/integration/test_roughmix_api.py`. It belongs to the integration task, covering `server/app.py` real media behaviour boundaries. Alternatively, I can add to `test_server.py` or `test_project_api.py`. Since `test_project_api.py` seems like a good fit, or just a new file. Wait, the ledger lists `test_project_api.py` and `test_server.py` for `server/app.py`. Let's create `tests/integration/test_roughmix_api.py` or add to `test_project_api.py`.
Wait, looking at `tests/integration/README.md`, `server/app.py` has tests in `test_server.py`, `test_project_api.py`. Adding `test_roughmix_api.py` is fine.

3. **What to test:**
   - Happy path: `GET /api/script2/mix` returns initial status. `POST` starts a job. `GET` returns building. The job finishes and creates a mix (I'll need to poll or mock the subprocess).
   - Missing plan: `POST` returns `started=False, reason='there is no film plan yet...'`.
   - Idempotency / concurrent: `POST` when already running returns `started=False, reason='the rough mix is already being made'`.
   - `GET .../audio`: Returns 404 before it's ready, returns `FileResponse` after.
   - `DELETE /api/script2/mix`: Resets the mix, `GET` returns `has_mix=False`. Cannot delete while running (HTTP 409).
   - Failure: `POST` fails, `GET` returns the error from `mix.log`.

4. **Shared fixtures:** `served`, `make_client`, `processed`, `fake_popen`.
   Wait, if we use `fake_popen`, the subprocess doesn't really run. I can use `fake_popen` and check `.cmd`, `.cwd`.
   Let's check how `test_project_api.py` does jobs. It mocks `fake_popen`. Wait, `make_client` already mocks workers with `fake_popen`. Let's see `tests/utils/fakes.py`.

5. **Update Ledger:** In `tests/integration/README.md`, update `server/app.py` entry to mention rough mix endpoints.

6. **Refactor & Verification:** Run `ruff check` and `pytest`.

7. **Pre-commit:** call `pre_commit_instructions` tool to make sure all pre-commit requirements are fulfilled.

8. **Submit.**
