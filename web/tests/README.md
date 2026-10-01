# Web tests

vitest 4, Testing Library, user-event, msw (backend mocks), vitest-axe, fast-check. Run from `web/`: `npm run test:unit`, `npm run test:integration`, `npm run test:coverage:gate` (unit + integration together, the number CI gates on: floors in `web/coverage-floor.json`), `npm run test:coverage:all` (same run, no gate), `npm run test:coverage` (unit only, informational: most tests here are jsdom integration tests), `npm run typecheck` (also checks the tests).

## Layout

- `unit/`: node environment, no DOM. Pure functions and `api.ts`. Setup: `utils/setup-node.ts`.
- `integration/`: jsdom. Components and hooks, rendered with Testing Library. Setup: `utils/setup.ts`.
- One test file per source file, same name (`components/NoteBox.tsx` -> `integration/NoteBox.test.tsx`).
- Worked examples to copy: `integration/FolderBrowser.test.tsx` (request/response states, navigation, a11y), `integration/NoteBox.test.tsx` (debounced saves with fake timers, request assertions), `integration/App.test.tsx` (mocking a child component), `unit/api.test.ts` (the client's contract).

## The shared helpers (`utils/`): use these, extend them, don't bypass them

| File | What it is |
| --- | --- |
| `server.ts`, `handlers.ts` | The one msw server and its default happy-path handlers. **Only the endpoints tests have needed so far are there.** An unmocked request fails the test (`onUnhandledFrame: 'error'`), so when you need an endpoint, add its default handler (and a factory) here, not inline in a test. |
| `factories.ts` | Typed payload builders, `makeBrowse({ can_create: true })`. One per interface in `src/api.ts`, added as needed. Defaults valid and boring. |
| `api.ts` | Per-test overrides: `mockGet`/`mockPost` (body or function of the request), `mockError(path, status, detail)`, `mockNetworkError`, `mockPending` (loading state), `recordRequests(path)` (assert method, query, JSON body that the client sent). |
| `render.tsx` | `setup(<C />)` returns `{ user, ...rtl }`; re-exports `screen`, `waitFor`, `within`, `act`. |
| `media.ts` | `stubMedia()` and `stubBrowserApis()` for what jsdom lacks (play/pause, ResizeObserver, scrollIntoView, ...). |
| `vitest.d.ts` | Types for `toHaveNoViolations`. |

Move anything two tests share into `utils/`. Refactor older tests onto the helpers when you touch them.

## Conventions

- Test what a user or caller sees: query by role/label/text; assert on outgoing requests with `recordRequests`. No class-name queries, no snapshots.
- One concept per `it`, named as a sentence. Cover happy path, loading, empty, server error (4xx/5xx), dropped connection, edge values, interaction.
- No arbitrary sleeps: `findBy*`, `vi.waitFor`, and fake timers (`vi.useFakeTimers({ shouldAdvanceTime: true })` with user-event) for debounces and polling.
- Mock a child component with `vi.mock` when the test is about the parent only (see `App.test.tsx`).
- msw v3: the option is `onUnhandledFrame`, not `onUnhandledRequest`. Handlers use relative `/api/...` paths; `setup-node.ts` makes that work in node.
- A bug found while testing: write `it.todo('...')` or `it.fails`, comment it as a finding, and don't change app behaviour in a test PR.

## Coverage status

Line coverage from `npm run test:coverage:all`. Update the rows you change. `done` means >= 90% lines (or a justified gap noted here).

| Source | Lines | Status |
| --- | --- | --- |
| `src/api.ts` | 33.82% | partial: client contract tested through the `call` helper; most endpoint wrappers (URL builders, uploads, deletes) todo |
| `src/App.tsx` | 77.77% | done (the effect's failure branch is the gap) |
| `src/components/ClockPanel.tsx` | 100% | done |
| `src/components/TrackPanel.tsx` | 88.46% | done (branches tested via interactions, some fallback cases left) |
| `src/components/WhoPanel.tsx` | 100% | done |
| `src/components/Workspace.tsx` | 100% | done |
| `src/components/FolderBrowser.tsx` | 100% | done |
| `src/components/NoteBox.tsx` | 100% | done |
| `src/components/Health.tsx` | 100% | done |
| `src/components/MusicPanel.tsx` | 100% | done |
| `src/components/ProjectProgress.tsx` | 100% | done |
| `src/components/RedoDialog.tsx` | 100% | done |
| `src/components/Phrase.tsx` | 100% | done (trivial branch misses) |
| `src/components/TranscriptPanel.tsx` | 96.55% | done (tooltips difficult to query) |
| `src/usePoll.ts` | 100% | done |
| `src/thumbOverlay.ts` | 100% | done (storage failures are swallowed by design) |
| every other file in `src/` | 0% | todo
| `src/components/Timeline.tsx` | 77.55% | partial (interactions and edge cases)
| `src/components/Moments.tsx` | 100% | done |

### Helpers Added

* `makeEditResponse`, `makePlanSegment` in `factories.ts` to mock Timeline data.
* `extraHandlers` in `handlers.ts` to support API calls specific to `Timeline` such as `/api/edit`, `/api/edit/propose` and `/api/edit/override`.
