## Milestone A: the film is deliverable (critical path)

### A1. Finish the Legends batch on current stage versions (S, mostly machine time)
- Run every default stage to completion at its current version (proxy v6 for all 25 clips; scenes, speakers, candidates, thumb_best).
- Add `strata360 coverage FOLDER [--json]` (overview 15.3): per clip, which section 15.1 artefacts exist and which decisions they unblock. Show it in the Overview's progress panel.
- **Built (1 Oct):** `strata360 coverage FOLDER [--json]`, `/api/coverage` and a "Data missing" line in the progress panel (`pipeline/coverage.py`, `tests/unit/test_coverage.py`). **Still to do:** the batch run on Legends. **Started 1 Oct (evening):** one low-priority worker (`strata360 open`); it waits whenever the machine is busy. Left: exposure (3 clips), proxy, candidates, thumb_best, thumb_overlay.
- **Done when:** `progress` reports `complete` for Legends; `coverage` lists nothing missing for default stages.
