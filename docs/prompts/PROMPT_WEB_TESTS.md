# Task: add thorough front-end tests to strata-360 (one PR, then stop)

You are a coding agent new to this repo. Find a coherent slice of **untested front-end code**, cover it with thorough, best-practice tests, and extend and refactor the shared test helpers as you go. Open **one PR**, drive CI to green, then stop. This prompt is run many times: each run continues from the state the last one left, so choose work from the *current* coverage ledger and leave it up to date.

## 0. Orient yourself (read before writing anything)

1. Read `AGENTS.md` and `CLAUDE.md` at the repo root. They are authoritative. Python code is out of scope: don't touch `src/strata360/`, the Python `tests/`, `pyproject.toml` or the workflows. **This task runs in parallel with the backend unit-test and integration-test tasks on other branches**, which never touch `web/`; keep your changes inside `web/` (plus `package.json`/`package-lock.json` only if a new dev dependency is unavoidable) so nothing collides. Your notes and ledger live only in `web/tests/README.md`; don't edit `tests/README.md` or the other READMEs.
2. Read **`web/tests/README.md`** in full. It documents the conventions, the shared helpers and a per-file coverage ledger. Then read everything in `web/tests/utils/` and the worked examples it lists:
   - `integration/FolderBrowser.test.tsx`: request and response states, navigation, accessibility.
   - `integration/NoteBox.test.tsx`: debounced saves with fake timers, and request assertions.
   - `integration/App.test.tsx`: mocking a child component with `vi.mock`.
   - `unit/api.test.ts`: the API client's contract.
   Copy their style.
3. Stack: React 19, TypeScript, Vite 7, vitest 4, Testing Library, `@testing-library/user-event`, **msw v3**, `vitest-axe`, `fast-check`. Source is in `web/src/` (`api.ts`, `usePoll.ts`, `aim.ts`, `App.tsx`, `components/*.tsx`). The app calls a FastAPI backend through the typed client in `web/src/api.ts`, using same-origin relative `/api/...` URLs.
4. Test projects: `unit` runs in node (`tests/unit/**`, setup `utils/setup-node.ts`). `integration` runs in jsdom (`tests/integration/**`, setup `utils/setup.ts`). Commands, from `web/`: `npm ci`, `npm run test:unit`, `npm run test:integration`, `npm run test:coverage:gate` (unit + integration together, what CI gates on; floors in `web/coverage-floor.json`), `npm run test:coverage:all` (no gate), `npm run test:coverage` (unit only, informational), `npm run typecheck` (tests are typechecked too), `npm run build`.
5. **GitHub Actions is the source of truth.** `unit.yml` runs the web typecheck, unit coverage (informational), the coverage gate over all projects, and the build. `integration.yml` runs `npm run test:integration`. Run what you can locally, but the PR is done only when CI is green on the head commit.

## 1. Choose the slice (data-driven, so reruns don't collide)

1. Open the **"Coverage status"** table in `web/tests/README.md`. Cross-check it against a fresh `npm run test:coverage:all` (or the latest CI log). The ledger is a summary, so the report wins on conflict.
2. Check what's in flight: `git log --oneline -20`, `git branch -a`, and the open PRs (GitHub MCP tools). Don't pick files another branch or PR already covers. If an earlier run's PR for the same slice is still open, continue on it instead of starting over.
3. Pick **one cohesive slice**, about 3–6 related source files or 300–600 lines of source, from the files marked `todo`/`partial`, ranked by:
   - logic density (parsing, time/position math, state machines, polling, error handling) over presentational markup;
   - interaction with the backend through `api.ts`;
   - bug-prone flows (dialogs, edit/redo, players, timelines).

   Examples of coherent slices: `aim.ts` + `Timeline` + `Moments`; `Workspace` + `ProjectProgress` + `Health`; `ScriptPanel` + `VoiceoverPanel` + `RedoDialog`; `TranscriptPanel` + `Phrase`; `api.ts` endpoint wrappers (URL builders, uploads, deletes). Test your logic, not hls.js or browser media internals.
4. State the chosen slice and why at the top of the PR description.
5. **Stop condition:** if every file is `done` (≥90% lines, or a justified gap noted in the ledger), change nothing and say so. Don't invent work.

## 2. Reuse and extend the shared helpers (don't bypass them)

Only the endpoints the example slice needed have default handlers and factories so far.

- When your slice hits an endpoint or payload type that is missing, **add it**:
  - a default happy-path handler in `utils/handlers.ts` (one per endpoint);
  - a typed factory in `utils/factories.ts` (one per interface in `src/api.ts`, `Partial<T>` overrides, valid and boring defaults).
- Per-test variations use `mockGet`, `mockPost`, `mockError`, `mockNetworkError`, `mockPending` and `recordRequests` from `utils/api.ts`. `recordRequests` is how you assert the request the client sent (method, query, JSON body).
- Never inline a one-off `http.get(...)` in a test file, and never stub `fetch` by hand.
- If a helper isn't enough, extend it (a request matcher, a `renderWithX` wrapper, an hls.js fake in `utils/media.ts`). Anything two test files share moves into `utils/`. When you touch an older test, move it onto the helpers.
- A new dev dependency needs a clear reason and a line in the PR. Candidates: `@faker-js/faker` (seeded) for bulk data. Property tests with `fast-check` suit pure math in `aim.ts` and `Phrase`, where invariants are easy to state (monotonic, clamped, round-trips).
- Already-solved gotchas:
  - msw v3's option is `onUnhandledFrame`, not `onUnhandledRequest`.
  - `/api` relative URLs work in jsdom, and `setup-node.ts` makes them work in node.
  - Use `vi.useFakeTimers({ shouldAdvanceTime: true })` with user-event for debounces and polling.
  - Use `vi.mock` for child components when the test is about the parent.
  - jsdom lacks media playback, `ResizeObserver` and `scrollIntoView`; use `stubMedia()` and `stubBrowserApis()` from `utils/media.ts`.

## 3. How to write the tests

- **Behaviour, not implementation.** Query by role, label or text (`getByRole`, `findByText`). No class-name queries, no big snapshots. Add a `data-testid` only if there's no alternative, and mention it in the PR.
- One concept per `it`, named as a sentence. Arrange, act, assert.
- Cover, for each unit: happy path, loading state, empty state, server error (4xx/5xx with `{ detail }`), dropped connection, edge values (null/undefined optionals, empty lists, boundaries), and keyboard/mouse interaction.
- Assert the **outgoing requests** (method, URL, query, JSON body) with `recordRequests`.
- Accessibility: one `expect(await axe(container)).toHaveNoViolations()` per component where it's cheap. If it flags a violation in existing app code, don't fix the app here. Add a `it.todo`/`it.fails` and report it under "Findings".
- Deterministic and independent: no sleeps (`findBy*`, `vi.waitFor`, fake timers), no shared mutable state, no real network. msw errors on any request without a handler, so a forgotten endpoint fails loudly.
- Placement: pure/no-DOM → `tests/unit/<name>.test.ts`; renders React or needs jsdom → `tests/integration/<Name>.test.tsx`. One test file per source file.
- **Don't change `web/src` behaviour.** Allowed: a tiny testability change (export a pure function, add an accessible label), called out in the PR. When you find a real bug, document it with `it.todo`/`it.fails` plus a comment, list it under "Findings", and don't fix it in this PR. Never skip, `.only` or delete a test, and never lower a threshold to get green.

## 4. Update the ledger (this is what makes reruns work)

- In `web/tests/README.md`, update the "Coverage status" row of every file you touched (line %, `done`/`partial`/`todo`, notes) and add rows for new files. Take the numbers from `npm run test:coverage:all` or the CI log, not an estimate.
- Keep the README's helper table and conventions current. If you added a helper or learned a gotcha, write it down there.
- Aim for ≥90% lines and ≥85% branches on files in your slice. Justify any gap in the ledger.
- **Ratchet:** you are the only task that edits `web/coverage-floor.json`. After CI is green, raise each floor (lines, statements, functions, branches) to the integer floor of the new totals from the gate step's report, in your last commit. Floors only go up: never lower one to get green, and never add a threshold anywhere else.

## 5. Verify locally (if node is available)

From `web/`: `npm ci`, `npm run typecheck`, `npm run test:unit`, `npm run test:integration`, `npm run test:coverage:all`, `npm run build`. Run the integration suite 3 times to catch flakiness. Mutation spot-check: break the source (flip a condition) for 2–3 representative tests, confirm they fail, then revert. Re-read your diff adversarially for tests that would still pass if the component were broken. If you can't run node locally, push early and use CI as your runner.

## 6. Branch, PR, and drive CI to green

- Use the branch name the environment gives you (otherwise `test/frontend-coverage-<slice>` off the latest default branch). Make small logical commits (helpers → tests per file → docs/ledger). Push with `git push -u origin <branch>`.
- Open **one PR** (follow its PR template if the repo has one) as soon as the first meaningful commit is pushed. The PR triggers `unit.yml` and `integration.yml`. Keep it a draft until CI is green if you can.
- Loop until the **web** jobs of "Unit tests" and "Integration tests" are green on the latest head commit:
  1. Read the results with the GitHub MCP tools (`actions_list`, `actions_get`, `get_job_logs`).
  2. If red, reproduce, root-cause, push a minimal fix, repeat.
  3. If a failure is clearly not yours (a Python job, or an infrastructure error naming something your diff doesn't touch), say so in one PR comment with the evidence and re-run at most once. Never mask a flake. Never skip tests or push an empty commit to retrigger CI.
  4. CI-only failures to anticipate: `package-lock.json` out of sync (commit a lockfile generated with Node 26), timing-sensitive tests on slower runners (use `findBy*`/fake timers), and type errors in test files (tests are typechecked).
- The PR description must include:
  - the slice and why, and what's left for next runs;
  - coverage before → after for each target file, taken from CI;
  - new dev dependencies and why, and the helpers/handlers/factories added or extended, plus which older tests were refactored onto them;
  - **Findings**: bugs, a11y violations, untestable areas, and any `web/src` changes (should be minimal).
- Finish by stating plainly the CI status on the head commit, the PR link, and what remains. Don't merge the PR. Don't start a second slice. If review comments or CI events arrive on your PR, handle them as part of this same PR.
